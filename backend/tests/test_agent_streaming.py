# -*- coding: utf-8 -*-
"""Testes completos do AgentOrchestratorService e da API de Streaming SSE/WebSocket."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import agent as agent_api
from backend.app.db.schemas import ChatMessageCreate, ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.harnesses import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRegistry,
    HarnessRunRequest,
    HarnessStatus,
)
from backend.app.services.agent_orchestrator import (
    AgentOrchestratorService,
    is_gate_confirmation_message,
)
from backend.app.services.workspace_service import WorkspaceService

# -----------------------------------------------------------------------------
# Fixtures de Dados Clínicos e JRXML Válidos
# -----------------------------------------------------------------------------


def _valid_clinical_json(title: str = "Ficha de Admissão Clínica") -> dict[str, Any]:
    return {
        "template": {
            "nome": title,
            "descricao": "Ficha extraída pelo agente de IA em Gate 2",
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "posicao_assinatura": "RODAPE",
        },
        "perguntas": [
            {
                "nome": "Sinais Vitais",
                "titulo": False,
                "respostas": [
                    {"label": "Pressão Arterial", "tipo_campo": "TEXTO"},
                    {"label": "Febre", "tipo_campo": "BOOLEANO", "observacao": True},
                ],
            }
        ],
    }


VALID_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              name="ficha_admissao_clinica"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
    <parameter name="id" class="java.lang.Long"/>
    <parameter name="caminho_relatorio" class="java.lang.String"/>
    <detail>
        <band height="48">
            <staticText>
                <reportElement x="0" y="0" width="200" height="16"/>
                <text><![CDATA[SINAIS VITAIS]]></text>
            </staticText>
        </band>
    </detail>
</jasperReport>
"""


# -----------------------------------------------------------------------------
# Fake Harness Assíncrono para Testes Determinísticos
# -----------------------------------------------------------------------------


class FakeAsyncHarness:
    """Harness fake assíncrono que registra requisições e emite eventos normalizados."""

    def __init__(
        self,
        kind: HarnessKind = HarnessKind.AGY,
        display_name: str = "Fake AGY Harness",
        *,
        on_run: Callable[[HarnessRunRequest], None] | None = None,
        emit_gate_request_on_gate1: bool = True,
        step_delay: float = 0.0,
        chunks_count: int = 2,
    ) -> None:
        self.kind = kind
        self.display_name = display_name
        self.on_run = on_run
        self.emit_gate_request_on_gate1 = emit_gate_request_on_gate1
        self.step_delay = step_delay
        self.chunks_count = chunks_count
        self.recorded_requests: list[HarnessRunRequest] = []
        self.started_event = asyncio.Event()

    def check_status(self) -> HarnessStatus:
        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=True,
            executable_path="/fake/bin/agy",
            sdk_available=True,
            version="1.0.0-test",
            auth_hint="Fake test harness pronto",
            supports_vision=True,
            supports_mcp=True,
        )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        self.recorded_requests.append(request)
        self.started_event.set()

        yield HarnessEvent(
            type=EventType.THOUGHT_DELTA,
            content="Analisando estrutura do workspace e histórico da fase...",
            harness=self.kind,
        )

        if self.step_delay > 0:
            await asyncio.sleep(self.step_delay)

        yield HarnessEvent(
            type=EventType.TOOL_CALL,
            tool_name="inspect_clinical_pdf",
            tool_call_id="call-1",
            tool_args={"pdf_path": str(request.workspace_dir / "uploads" / "source.pdf")},
            harness=self.kind,
        )

        if self.on_run is not None:
            self.on_run(request)

        yield HarnessEvent(
            type=EventType.TOOL_RESULT,
            tool_name="inspect_clinical_pdf",
            tool_call_id="call-1",
            tool_output={"pages": 1, "orientation": "RETRATO"},
            content="PDF inspecionado com sucesso.",
            harness=self.kind,
        )

        for idx in range(self.chunks_count):
            if self.step_delay > 0:
                await asyncio.sleep(self.step_delay)
            yield HarnessEvent(
                type=EventType.TEXT_DELTA,
                content=f"Parte {idx + 1} da resposta para '{request.prompt}'. ",
                harness=self.kind,
            )

        if not request.gate_authorized and self.emit_gate_request_on_gate1:
            yield HarnessEvent(
                type=EventType.GATE_REQUEST,
                content="Mapeamento concluído. Envie 'Autorizado' para gerar o arquivo final.",
                harness=self.kind,
                metadata={"phase": request.phase, "gate_authorized": False},
            )

        yield HarnessEvent(
            type=EventType.DONE,
            harness=self.kind,
            metadata={"phase": request.phase, "gate_authorized": request.gate_authorized},
        )


def _parse_sse_payload(raw_text: str) -> list[dict[str, Any]]:
    """Converte corpo `text/event-stream` em lista ordenada de dicionários `{event, data}`."""
    events: list[dict[str, Any]] = []
    blocks = [block.strip() for block in raw_text.replace("\r\n", "\n").split("\n\n") if block.strip()]
    for block in blocks:
        event_name = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            parsed_data = json.loads("\n".join(data_lines))
            events.append({"event": event_name, "data": parsed_data})
    return events


def _build_mini_app(
    tmp_path: Path,
    harness: FakeAsyncHarness,
    *,
    extra_harnesses: list[FakeAsyncHarness] | None = None,
) -> tuple[FastAPI, WorkspaceService, AgentOrchestratorService]:
    data_dir = tmp_path / "studio_data"
    db_path = data_dir / "studio.db"
    store = SQLiteStore(db_path=db_path)
    store.init_db()
    workspace_service = WorkspaceService(store=store, data_dir=data_dir)
    registry = HarnessRegistry(harnesses=[harness, *(extra_harnesses or [])])
    orchestrator = AgentOrchestratorService(
        workspace_service=workspace_service,
        harness_registry=registry,
    )

    app = FastAPI()
    app.state.workspace_service = workspace_service
    app.state.harness_registry = registry
    app.state.agent_orchestrator = orchestrator
    app.include_router(agent_api.router)
    return app, workspace_service, orchestrator


# -----------------------------------------------------------------------------
# 1. Testes Unitários de Detecção de Confirmação de Gate 2
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Autorizado", True),
        ("Aprovado!", True),
        ("Sim, pode gerar o JSON agora", True),
        ("Ok, autorizado. Pode seguir com a geração.", True),
        ("Pode prosseguir e salvar o arquivo", True),
        ("Não autorizado ainda", False),
        ("Ainda não aprovado, precisa ajustar a pergunta 2", False),
        ("Não pode gerar ainda", False),
        ("Analise o PDF e verifique se o campo autorizado existe?", False),
        ("Mapear seções da ficha de triagem", False),
    ],
)
def test_gate_confirmation_message_detection(text: str, expected: bool) -> None:
    assert is_gate_confirmation_message(text) is expected


# -----------------------------------------------------------------------------
# 2. GET /agent/status + Feedbacks Visuais Pendentes
# -----------------------------------------------------------------------------


def test_agent_status_and_pending_visual_feedback_count(tmp_path: Path) -> None:
    fake_harness = FakeAsyncHarness()
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(
        ProjectCreate(name="Ficha de Triagem", preferred_harness="agy")
    )

    # Adiciona 2 anotações visuais vindas do Jasper Studio na fase jrxml
    for idx in range(2):
        workspace_service.add_chat_message(
            project.id,
            ChatMessageCreate(
                phase="jrxml",
                role="user",
                content=f"Ajustar espaçamento da área #{idx + 1}",
                metadata={
                    "type": "visual_region_feedback",
                    "page": 1,
                    "scenario": "full",
                    "pdf_rect": {"x0": 20, "y0": 220, "x1": 240, "y1": 260, "width": 220, "height": 40},
                    "detail_coords": {"x": 0, "y": 38, "width": 220, "height": 40},
                },
            ),
        )

    with TestClient(app) as client:
        resp = client.get(f"/api/projects/{project.id}/agent/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project_id"] == project.id
        assert body["active_run"] is False
        assert body["preferred_harness"] == "agy"
        assert len(body["harnesses"]) == 1
        assert body["harnesses"][0]["id"] == "agy"
        assert body["harnesses"][0]["installed"] is True
        assert {g["gate_name"] for g in body["gates"]} == {
            "gate1_json",
            "gate2_sql_insert",
            "gate3_jrxml",
        }
        assert body["pending_visual_feedback_count"] == 2

        # Após resposta do assistente na fase jrxml, contador volta a 0
        workspace_service.add_chat_message(
            project.id,
            ChatMessageCreate(
                phase="jrxml",
                role="assistant",
                content="Ajustes aplicados.",
                metadata={"harness": "agy"},
            ),
        )
        resp_after = client.get(f"/api/projects/{project.id}/agent/status")
        assert resp_after.status_code == 200
        assert resp_after.json()["pending_visual_feedback_count"] == 0


# -----------------------------------------------------------------------------
# 3. POST /agent/stream (SSE) em Gate 1 — Sem Sync + Persistência Completa
# -----------------------------------------------------------------------------


def test_sse_stream_gate1_blocks_artifact_sync_and_persists_chat(tmp_path: Path) -> None:
    def _write_json_even_in_gate1(req: HarnessRunRequest) -> None:
        # Mesmo que um harness desobediente tente escrever .json em Gate 1, o orquestrador bloqueia sync
        (req.workspace_dir / "ficha_clinica.json").write_text(
            json.dumps(_valid_clinical_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    fake_harness = FakeAsyncHarness(on_run=_write_json_even_in_gate1)
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(
        ProjectCreate(name="Ficha de Anamnese", preferred_harness="agy")
    )

    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{project.id}/agent/stream",
            json={
                "phase": "extraction",
                "prompt": "Analise o PDF da ficha e liste as perguntas.",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"

        events = _parse_sse_payload(resp.text)
        event_types = [e["event"] for e in events]
        assert event_types == [
            "thought_delta",
            "tool_call",
            "tool_result",
            "text_delta",
            "text_delta",
            "gate_request",
            "done",
        ]
        assert not any(
            e["data"].get("tool_name") == "workspace_sync" for e in events
        )

    # Nenhum artefato JSON foi importado no banco durante Gate 1
    assert workspace_service.list_revisions(project.id) == []

    # Verifica contexto rico enviado ao harness
    assert len(fake_harness.recorded_requests) == 1
    run_req = fake_harness.recorded_requests[0]
    assert run_req.gate_authorized is False
    assert run_req.phase == "extraction"
    assert run_req.extra_context["project"]["id"] == project.id
    assert len(run_req.extra_context["available_tools"]) >= 4

    # Verifica persistência no histórico de chat (user + assistant com thoughts e tool_calls)
    messages = workspace_service.list_chat_messages(project.id, phase="extraction")
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Analise o PDF da ficha e liste as perguntas."

    assistant_msg = messages[1]
    assert assistant_msg.role == "assistant"
    assert "Parte 1" in assistant_msg.content
    assert "Parte 2" in assistant_msg.content
    assert assistant_msg.metadata["harness"] == "agy"
    assert "Analisando estrutura" in assistant_msg.metadata["thoughts"]
    assert assistant_msg.metadata["gate_requested"] is True
    assert assistant_msg.metadata["synced_artifacts"] == []
    assert len(assistant_msg.metadata["tool_calls"]) == 1
    assert assistant_msg.metadata["tool_calls"][0]["tool_name"] == "inspect_clinical_pdf"
    assert assistant_msg.metadata["tool_calls"][0]["tool_output"] == {
        "pages": 1,
        "orientation": "RETRATO",
    }


def test_sse_stream_gate1_synthesizes_gate_request_when_harness_omits_it(tmp_path: Path) -> None:
    fake_harness = FakeAsyncHarness(emit_gate_request_on_gate1=False)
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(ProjectCreate(name="Ficha Gate Fallback"))

    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{project.id}/agent/stream",
            json={"phase": "extraction", "prompt": "Inspecionar ficha"},
        )
        assert resp.status_code == 200
        events = _parse_sse_payload(resp.text)
        types = [e["event"] for e in events]
        assert "gate_request" in types
        assert types.index("gate_request") < types.index("done")


# -----------------------------------------------------------------------------
# 4. POST /agent/authorize-gate + Gate 2 Sync (JSON + Auto SQL e JRXML + Preview PNGs)
# -----------------------------------------------------------------------------


def test_authorize_gate_and_gate2_extraction_syncs_json_and_regenerates_sql(tmp_path: Path) -> None:
    def _write_clinical_json(req: HarnessRunRequest) -> None:
        if req.gate_authorized:
            (req.workspace_dir / "ficha_clinica.json").write_text(
                json.dumps(_valid_clinical_json("Ficha Admissão Gate 2"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    fake_harness = FakeAsyncHarness(on_run=_write_clinical_json)
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(ProjectCreate(name="Ficha Admissão"))

    with TestClient(app) as client:
        # 1) Aprova explicitamente gate1_json via endpoint dedicado
        auth_resp = client.post(
            f"/api/projects/{project.id}/agent/authorize-gate",
            json={"phase": "extraction", "notes": "Mapeamento validado pela enfermagem"},
        )
        assert auth_resp.status_code == 200
        auth_data = auth_resp.json()
        assert auth_data["ok"] is True
        assert auth_data["gate"]["gate_name"] == "gate1_json"
        assert auth_data["gate"]["status"] == "approved"
        assert auth_data["message"]["phase"] == "extraction"

        # 2) Dispara turno Gate 2 (mesmo sem enviar gate_authorized=True, lê gate approved no SQLite)
        stream_resp = client.post(
            f"/api/projects/{project.id}/agent/stream",
            json={"phase": "extraction", "prompt": "Pode prosseguir com a geração"},
        )
        assert stream_resp.status_code == 200
        events = _parse_sse_payload(stream_resp.text)
        event_types = [e["event"] for e in events]

        # Encontra evento workspace_sync ANTES do DONE
        sync_indices = [
            idx
            for idx, ev in enumerate(events)
            if ev["event"] == "tool_result" and ev["data"].get("tool_name") == "workspace_sync"
        ]
        assert len(sync_indices) == 1
        done_idx = event_types.index("done")
        assert sync_indices[0] < done_idx

        sync_meta = events[sync_indices[0]]["data"]["metadata"]
        assert sync_meta["artifact_synced"] is True
        assert sync_meta["artifact_type"] == "json"
        assert sync_meta["version_num"] == 1
        assert sync_meta["sql_insert_version"] == 1
        assert sync_meta["sql_select_version"] == 1

    # Confirma revisões persistidas no WorkspaceService (JSON por "agent" + INSERT/SELECT automáticos)
    json_rev = workspace_service.get_latest_artifact(project.id, "json")
    assert json_rev.version_num == 1
    assert json_rev.created_by == "agent"
    assert "FICHA ADMISSÃO GATE 2" in json_rev.content

    sql_ins = workspace_service.get_latest_artifact(project.id, "sql_insert")
    sql_sel = workspace_service.get_latest_artifact(project.id, "sql_select")
    assert sql_ins.version_num == 1
    assert sql_sel.version_num == 1
    assert "template_ficha_clinica" in sql_ins.content.lower()
    assert "$P{id}" in sql_sel.content


def test_gate2_jrxml_sync_and_preview_png_and_visual_feedback_context(tmp_path: Path) -> None:
    def _write_jrxml(req: HarnessRunRequest) -> None:
        if req.gate_authorized:
            (req.workspace_dir / "ficha_layout.jrxml").write_text(VALID_JRXML, encoding="utf-8")

    fake_harness = FakeAsyncHarness(on_run=_write_jrxml)
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(ProjectCreate(name="Ficha Layout JRXML"))
    ws_dir = Path(project.workspace_dir)

    # Cria PNGs de preview recentes em exports/pages_full/*.png
    pages_dir = ws_dir / "exports" / "pages_full"
    pages_dir.mkdir(parents=True, exist_ok=True)
    png1 = pages_dir / "page_001.png"
    png1.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")
    (ws_dir / "exports" / "latest_preview.json").write_text(
        json.dumps({"scenario": "full", "page_count": 1}),
        encoding="utf-8",
    )

    # Registra feedback visual do Jasper Studio no chat da fase jrxml
    workspace_service.add_chat_message(
        project.id,
        ChatMessageCreate(
            phase="jrxml",
            role="user",
            content="Deslocar checkbox 4px para a direita",
            metadata={
                "type": "visual_region_feedback",
                "page": 1,
                "scenario": "full",
                "pdf_rect": {"x0": 40, "y0": 210, "x1": 160, "y1": 240, "width": 120, "height": 30},
                "detail_coords": {"x": 20, "y": 28, "width": 120, "height": 30},
            },
        ),
    )

    with TestClient(app) as client:
        # Envia frase "Autorizado" diretamente — deve aprovar gate3_jrxml automaticamente e rodar Gate 2
        stream_resp = client.post(
            f"/api/projects/{project.id}/agent/stream",
            json={"phase": "jrxml", "prompt": "Autorizado, pode gerar o JRXML"},
        )
        assert stream_resp.status_code == 200
        events = _parse_sse_payload(stream_resp.text)
        sync_events = [
            ev
            for ev in events
            if ev["event"] == "tool_result" and ev["data"].get("tool_name") == "workspace_sync"
        ]
        assert len(sync_events) == 1
        assert sync_events[0]["data"]["metadata"]["artifact_type"] == "jrxml"
        assert sync_events[0]["data"]["metadata"]["version_num"] == 1

    # Confirma gate3_jrxml promovido para approved
    gates_map = {g.gate_name: g.status for g in workspace_service.list_gates(project.id)}
    assert gates_map["gate3_jrxml"] == "approved"

    # Confirma que PNGs de preview e feedback visual chegaram no HarnessRunRequest
    assert len(fake_harness.recorded_requests) == 1
    req = fake_harness.recorded_requests[0]
    assert req.gate_authorized is True
    assert png1.resolve() in req.image_paths
    assert len(req.extra_context.get("visual_region_feedbacks", [])) == 1

    # Confirma revisão JRXML gravada no WorkspaceService
    jrxml_rev = workspace_service.get_latest_artifact(project.id, "jrxml")
    assert jrxml_rev.version_num == 1
    assert jrxml_rev.created_by == "agent"
    assert "<jasperReport" in jrxml_rev.content


# -----------------------------------------------------------------------------
# 5. WebSocket /agent/ws (send_message, authorize_gate, cancel, 404)
# -----------------------------------------------------------------------------


def test_websocket_send_message_authorize_gate_and_sync(tmp_path: Path) -> None:
    def _write_json_in_gate2(req: HarnessRunRequest) -> None:
        if req.gate_authorized:
            (req.workspace_dir / "ws_ficha.json").write_text(
                json.dumps(_valid_clinical_json("Ficha WebSocket"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    fake_harness = FakeAsyncHarness(on_run=_write_json_in_gate2)
    app, workspace_service, _ = _build_mini_app(tmp_path, fake_harness)
    project = workspace_service.create_project(ProjectCreate(name="Ficha WS"))

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/projects/{project.id}/agent/ws") as ws:
            # 1) Turno em Gate 1 via WebSocket
            ws.send_json(
                {
                    "type": "send_message",
                    "phase": "extraction",
                    "prompt": "Analise a ficha via WebSocket",
                }
            )
            gate1_events: list[dict[str, Any]] = []
            while True:
                ev = ws.receive_json()
                gate1_events.append(ev)
                if ev["type"] == "done":
                    break

            assert [e["type"] for e in gate1_events] == [
                "thought_delta",
                "tool_call",
                "tool_result",
                "text_delta",
                "text_delta",
                "gate_request",
                "done",
            ]

            # 2) Autoriza Gate via WebSocket
            ws.send_json(
                {
                    "type": "authorize_gate",
                    "phase": "extraction",
                    "notes": "Aprovado no WS",
                }
            )
            auth_ack = ws.receive_json()
            assert auth_ack["type"] == "gate_authorized"
            assert auth_ack["ok"] is True
            assert auth_ack["gate"]["gate_name"] == "gate1_json"
            assert auth_ack["gate"]["status"] == "approved"

            # 3) Turno em Gate 2 via WebSocket -> sincroniza JSON antes do done
            ws.send_json(
                {
                    "type": "send_message",
                    "phase": "extraction",
                    "prompt": "Gerar agora",
                    "gate_authorized": True,
                }
            )
            gate2_events: list[dict[str, Any]] = []
            while True:
                ev = ws.receive_json()
                gate2_events.append(ev)
                if ev["type"] == "done":
                    break

            sync_ev = [e for e in gate2_events if e.get("tool_name") == "workspace_sync"]
            assert len(sync_ev) == 1
            assert sync_ev[0]["metadata"]["artifact_synced"] is True
            assert sync_ev[0]["metadata"]["version_num"] == 1

            # 4) Cancelamento quando ocioso
            ws.send_json({"type": "cancel"})
            cancel_ack = ws.receive_json()
            assert cancel_ack == {"type": "cancelled", "ok": True, "cancelled": False}


def test_websocket_nonexistent_project_returns_error_and_closes(tmp_path: Path) -> None:
    fake_harness = FakeAsyncHarness()
    app, _, _ = _build_mini_app(tmp_path, fake_harness)

    with TestClient(app) as client:
        with client.websocket_connect("/api/projects/nao-existe-999/agent/ws") as ws:
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["metadata"]["status_code"] == 404


# -----------------------------------------------------------------------------
# 6. Cancelamento Ativo (POST /agent/cancel) e Erros 404 / 400
# -----------------------------------------------------------------------------


def test_cancel_active_run_and_error_status_codes(tmp_path: Path) -> None:
    slow_harness = FakeAsyncHarness(step_delay=0.35, chunks_count=10)
    app, workspace_service, orchestrator = _build_mini_app(tmp_path, slow_harness)
    project = workspace_service.create_project(ProjectCreate(name="Ficha Cancelamento"))

    async def _run_cancel_scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as aclient:
            # Idle cancel -> cancelled=False
            idle_cancel = await aclient.post(f"/api/projects/{project.id}/agent/cancel")
            assert idle_cancel.status_code == 200
            assert idle_cancel.json() == {"ok": True, "cancelled": False}

            received_chunks: list[str] = []

            async def _consume_sse() -> None:
                async with aclient.stream(
                    "POST",
                    f"/api/projects/{project.id}/agent/stream",
                    json={"phase": "extraction", "prompt": "Execução longa para cancelamento"},
                ) as response:
                    assert response.status_code == 200
                    async for chunk in response.aiter_text():
                        received_chunks.append(chunk)

            stream_task = asyncio.create_task(_consume_sse())

            # Aguarda o harness realmente iniciar e registrar o run ativo
            await asyncio.wait_for(slow_harness.started_event.wait(), timeout=2.0)

            status_during = await aclient.get(f"/api/projects/{project.id}/agent/status")
            assert status_during.status_code == 200
            assert status_during.json()["active_run"] is True

            cancel_resp = await aclient.post(f"/api/projects/{project.id}/agent/cancel")
            assert cancel_resp.status_code == 200
            assert cancel_resp.json() == {"ok": True, "cancelled": True}

            await asyncio.wait_for(stream_task, timeout=3.0)

            parsed = _parse_sse_payload("".join(received_chunks))
            assert any(
                e["event"] == "error" and e["data"].get("metadata", {}).get("cancelled") is True
                for e in parsed
            )
            assert parsed[-1]["event"] == "done"
            assert parsed[-1]["data"]["metadata"]["cancelled"] is True

            status_after = await aclient.get(f"/api/projects/{project.id}/agent/status")
            assert status_after.json()["active_run"] is False

    asyncio.run(_run_cancel_scenario())

    # Verifica erros 404 (projeto inexistente) e 400 (harness desconhecido)
    with TestClient(app) as client:
        assert client.get("/api/projects/inexistente-404/agent/status").status_code == 404
        assert (
            client.post(
                "/api/projects/inexistente-404/agent/stream",
                json={"phase": "extraction", "prompt": "Oi"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/projects/inexistente-404/agent/authorize-gate",
                json={"phase": "extraction"},
            ).status_code
            == 404
        )
        assert client.post("/api/projects/inexistente-404/agent/cancel").status_code == 404

        unknown_harness_resp = client.post(
            f"/api/projects/{project.id}/agent/stream",
            json={
                "phase": "extraction",
                "prompt": "Usar harness inválido",
                "harness_id": "harness_desconhecido_xyz",
            },
        )
        assert unknown_harness_resp.status_code == 400
        assert "harness_desconhecido_xyz" in unknown_harness_resp.json()["detail"]

    # Verifica que dependency_overrides funciona com get_agent_orchestrator
    override_called = False

    def _override_orch() -> AgentOrchestratorService:
        nonlocal override_called
        override_called = True
        return orchestrator

    app.dependency_overrides[agent_api.get_agent_orchestrator] = _override_orch
    try:
        with TestClient(app) as client:
            r = client.get(f"/api/projects/{project.id}/agent/status")
            assert r.status_code == 200
            assert override_called is True
    finally:
        app.dependency_overrides.clear()
