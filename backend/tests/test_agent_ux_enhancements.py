# -*- coding: utf-8 -*-
"""Testes unitários e de integração para UX de Agentes: modelos, effort, pool persistente AGY, source_pdf_pages, resolução de anotações e prompt delta."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

import pymupdf as fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import agent as agent_api
from backend.app.api import harnesses_and_tools as tools_api
from backend.app.api import jasper_preview as preview_api
from backend.app.db.schemas import ChatMessageCreate, ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.harnesses import (
    VALID_EFFORT_LEVELS,
    AgyHarness,
    AgyPersistentSessionPool,
    ClaudeCodeHarness,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRegistry,
    HarnessRunRequest,
    HarnessStatus,
    SubprocessChunk,
    compose_phase_system_prompt,
)
from backend.app.main import create_app
from backend.app.services.agent_orchestrator import AgentOrchestratorService
from backend.app.services.workspace_service import WorkspaceService

VALID_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              name="ficha_ux_test"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
    <parameter name="id" class="java.lang.Long"/>
    <parameter name="caminho_relatorio" class="java.lang.String"/>
    <detail>
        <band height="48">
            <staticText>
                <reportElement x="0" y="0" width="220" height="16"/>
                <text><![CDATA[ANAMNESE CLÍNICA]]></text>
            </staticText>
        </band>
    </detail>
</jasperReport>
"""


def _make_sample_pdf_bytes(text: str = "Ficha Clinica Original Salutem") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 80), text, fontsize=14)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _parse_sse(raw_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in raw_text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev_name = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            events.append({"event": ev_name, "data": json.loads("\n".join(data_lines))})
    return events


class _FakePipeWriter:
    def __init__(self, on_write: Callable[[bytes], None]) -> None:
        self._on_write = on_write
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.writes.append(data)
        self._on_write(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakePipeReader:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def feed_line(self, text: str) -> None:
        self._queue.put_nowait((text + "\n").encode("utf-8"))

    def feed_eof(self) -> None:
        self._queue.put_nowait(b"")

    async def readline(self) -> bytes:
        return await self._queue.get()


class _FakeAsyncProcess:
    """Fake `asyncio.subprocess.Process` para testar ciclo de vida do pool persistente AGY."""

    def __init__(
        self,
        cmd: Sequence[str],
        *,
        on_turn_input: Callable[[_FakeAsyncProcess, dict[str, Any]], None],
    ) -> None:
        self.cmd = list(cmd)
        self.returncode: int | None = None
        self.killed = False
        self.turns_received: list[dict[str, Any]] = []
        self.stdout = _FakePipeReader()
        self.stderr = _FakePipeReader()
        self._on_turn_input = on_turn_input
        self.stdin = _FakePipeWriter(self._handle_stdin)

    def _handle_stdin(self, raw: bytes) -> None:
        text = raw.decode("utf-8").strip()
        if not text:
            return
        payload = json.loads(text)
        self.turns_received.append(payload)
        self._on_turn_input(self, payload)

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


# -----------------------------------------------------------------------------
# 1. Model Discovery, Caching, Endpoint `/api/harnesses/{id}/models` e `--effort`
# -----------------------------------------------------------------------------


def test_agy_list_models_parses_caches_and_falls_back_gracefully() -> None:
    calls: list[list[str]] = []

    def _fake_models_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=(
                "gemini-4-neon-high\tGemini 4 Neon (High)\n"
                "claude-sonnet-5-5-medium\tClaude Sonnet 5.5 (Medium)\n"
                "Fetching available models...\n"
                "\n"
            ),
            stderr="Fetching available models...\n",
        )

    agy = AgyHarness(
        which_resolver=lambda name: "/fake/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
        models_runner=_fake_models_runner,
        models_cache_ttl=300.0,
    )

    first = agy.list_models()
    second = agy.list_models()
    assert len(calls) == 1  # 5-min cache hit!
    assert first == [
        {"id": "gemini-4-neon-high", "label": "Gemini 4 Neon (High)"},
        {"id": "claude-sonnet-5-5-medium", "label": "Claude Sonnet 5.5 (Medium)"},
    ]
    assert second == first

    # Missing executable -> graceful empty fallback
    agy_missing = AgyHarness(
        which_resolver=lambda _: None,
        sdk_spec_finder=lambda _: None,
        local_appdata_dir="/nonexistent-dir",
    )
    assert agy_missing.list_models() == []

    # Subprocess error -> graceful empty fallback
    def _failing_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise OSError("binary failed")

    agy_err = AgyHarness(
        which_resolver=lambda name: "/fake/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
        models_runner=_failing_runner,
    )
    assert agy_err.list_models() == []


def test_harnesses_models_endpoint_agy_non_agy_and_404() -> None:
    agy = AgyHarness(
        which_resolver=lambda name: "/fake/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
        models_runner=lambda cmd: subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="gemini-4-neon-high\tGemini 4 Neon (High)\n",
            stderr="",
        ),
    )
    claude = ClaudeCodeHarness(which_resolver=lambda _: None)
    registry = HarnessRegistry([agy, claude])

    app = FastAPI()
    app.state.harness_registry = registry
    app.include_router(tools_api.router)

    with TestClient(app) as client:
        r_agy = client.get("/api/harnesses/agy/models")
        assert r_agy.status_code == 200
        body = r_agy.json()
        assert body["harness_id"] == "agy"
        assert body["supports_effort"] is True
        assert body["effort_levels"] == list(VALID_EFFORT_LEVELS)
        assert body["models"] == [{"id": "gemini-4-neon-high", "label": "Gemini 4 Neon (High)"}]

        r_claude = client.get("/api/harnesses/claude/models")
        assert r_claude.status_code == 200
        c_body = r_claude.json()
        assert c_body["harness_id"] == "claude"
        assert c_body["models"] == []
        assert c_body["supports_effort"] is False

        r_404 = client.get("/api/harnesses/unknown_xyz/models")
        assert r_404.status_code == 404


@pytest.mark.asyncio
async def test_agy_effort_flag_and_resolved_model_capture_and_persistence(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    async def _runner(
        cmd: Sequence[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
        timeout_seconds: float | None = 300.0,
    ) -> AsyncIterator[SubprocessChunk]:
        captured["cmd"] = list(cmd)
        yield SubprocessChunk(
            stream="stdout",
            line=json.dumps(
                {
                    "event": "init",
                    "conversation_id": "conv-m1",
                    "init": {"model": "gemini-4-neon-xhigh"},
                }
            ),
        )
        yield SubprocessChunk(
            stream="stdout",
            line=json.dumps(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "conv-m1",
                        "status": "SUCCESS",
                        "response": "Resposta gerada com sucesso.",
                        "model": "gemini-4-neon-xhigh",
                    },
                }
            ),
        )
        yield SubprocessChunk(stream="exit", returncode=0)

    agy = AgyHarness(
        runner=_runner,
        which_resolver=lambda name: "/fake/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
    )

    store = SQLiteStore(db_path=tmp_path / "studio.db")
    ws = WorkspaceService(store=store, data_dir=tmp_path / "data")
    orch = AgentOrchestratorService(workspace_service=ws, harness_registry=HarnessRegistry([agy]))
    proj = ws.create_project(ProjectCreate(name="Ficha Effort Model", preferred_harness="agy"))

    app = FastAPI()
    app.state.workspace_service = ws
    app.state.agent_orchestrator = orch
    app.include_router(agent_api.router)

    # SSE stream com effort e sem model explícito -> resolve model vindo do evento AGY!
    with TestClient(app) as client:
        resp = client.post(
            f"/api/projects/{proj.id}/agent/stream",
            json={
                "phase": "extraction",
                "prompt": "Analise a ficha",
                "effort": "xhigh",
            },
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        done_ev = [e for e in events if e["event"] == "done"][-1]
        assert done_ev["data"]["metadata"]["resolved_model"] == "gemini-4-neon-xhigh"
        assert done_ev["data"]["metadata"]["model"] == "gemini-4-neon-xhigh"
        assert done_ev["data"]["metadata"]["effort"] == "xhigh"

        # Invalid effort rejected by validation (422)
        bad_resp = client.post(
            f"/api/projects/{proj.id}/agent/stream",
            json={"phase": "extraction", "prompt": "Oi", "effort": "ultra-invalid"},
        )
        assert bad_resp.status_code == 422

    assert "--effort" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--effort") + 1] == "xhigh"

    # Assistant message persisted with resolved model in SQLite
    messages = ws.list_chat_messages(proj.id, phase="extraction")
    assistant_msgs = [m for m in messages if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].metadata["model"] == "gemini-4-neon-xhigh"
    assert assistant_msgs[0].metadata["effort"] == "xhigh"


# -----------------------------------------------------------------------------
# 2. Persistent Warm AGY Session Pool Lifecycle, Warmup & Reset/Shutdown
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agy_persistent_session_pool_warmup_multiturn_ttl_respawn_and_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_PERSISTENT_SESSION", "1")
    fake_now = [1000.0]
    spawned: list[_FakeAsyncProcess] = []
    fail_next_turn = [False]

    def _on_turn(proc: _FakeAsyncProcess, payload: dict[str, Any]) -> None:
        turn_idx = len(proc.turns_received)
        if fail_next_turn[0]:
            fail_next_turn[0] = False
            proc.returncode = 1
            proc.stderr.feed_line("Simulated crash")
            proc.stdout.feed_eof()
            proc.stderr.feed_eof()
            return
        if turn_idx == 1:
            proc.stdout.feed_line(
                json.dumps({"event": "init", "conversation_id": "warm-conv-1", "model": "gemini-4-neon-high"})
            )
        proc.stdout.feed_line(
            json.dumps(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "warm-conv-1",
                        "status": "SUCCESS",
                        "response": f"Turn {turn_idx} ok",
                        "model": "gemini-4-neon-high",
                    },
                }
            )
        )

    async def _fake_factory(*cmd: str, **kwargs: Any) -> _FakeAsyncProcess:
        proc = _FakeAsyncProcess(cmd, on_turn_input=_on_turn)
        spawned.append(proc)
        return proc

    pool = AgyPersistentSessionPool(
        idle_ttl_seconds=600.0,
        process_factory=_fake_factory,
        clock=lambda: fake_now[0],
    )
    agy = AgyHarness(
        which_resolver=lambda name: "/fake/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
        session_pool=pool,
    )

    store = SQLiteStore(db_path=tmp_path / "studio.db")
    ws = WorkspaceService(store=store, data_dir=tmp_path / "data")
    orch = AgentOrchestratorService(workspace_service=ws, harness_registry=HarnessRegistry([agy]))
    proj = ws.create_project(ProjectCreate(name="Warm Pool Test", preferred_harness="agy"))

    # 1) Pre-warmup spawns 1 warm process
    warm_res = await orch.warmup_agent(
        proj.id,
        phase="jrxml",
        harness_id="agy",
        model="gemini-4-neon-high",
        effort="medium",
    )
    assert warm_res["ok"] is True
    assert warm_res["warmed"] is True
    assert warm_res["already_warm"] is False
    assert len(spawned) == 1
    assert "--effort" in spawned[0].cmd
    assert "--model" in spawned[0].cmd

    # Second warmup reuses same warm process
    warm_res2 = await orch.warmup_agent(
        proj.id,
        phase="jrxml",
        harness_id="agy",
        model="gemini-4-neon-high",
        effort="medium",
    )
    assert warm_res2["already_warm"] is True
    assert len(spawned) == 1

    # 2) Turn 1 reuses pre-warmed process (no extra spawn!) and keeps stdin open
    ev1 = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Primeira análise",
            harness_id="agy",
            model="gemini-4-neon-high",
            effort="medium",
        )
    ]
    assert len(spawned) == 1
    assert spawned[0].stdin.closed is False
    assert ev1[-1].metadata["mode"] == "cli_persistent"
    assert ev1[-1].metadata["session_id"] == "warm-conv-1"
    turn1_content = spawned[0].turns_received[0]["message"]["content"]
    assert "gerador-layout-jrxml-salutem-v3" in turn1_content  # Full SKILL on turn 1

    # 3) Turn 2 reuses SAME persistent process and sends SLIM delta prompt (no 30KB SKILL.md!)
    ev2 = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Ajuste fino na linha 2",
            harness_id="agy",
            model="gemini-4-neon-high",
            effort="medium",
        )
    ]
    assert len(spawned) == 1
    assert len(spawned[0].turns_received) == 2
    assert spawned[0].stdin.closed is False
    turn2_content = spawned[0].turns_received[1]["message"]["content"]
    assert "Continuação (JRXML)" in turn2_content
    assert "gerador-layout-jrxml-salutem-v3" not in turn2_content
    assert "recent_chat" not in turn2_content
    assert "available_tools" not in turn2_content
    assert len(turn2_content) < len(turn1_content) // 2
    assert ev2[-1].type == EventType.DONE

    # 4) Reset session closes the warm process
    closed = await orch.close_warm_sessions(proj.id, harness_id="agy")
    assert closed == 1
    assert spawned[0].killed is True
    assert pool.active_count() == 0

    # 5) Respawn after TTL expiry
    await orch.warmup_agent(proj.id, phase="jrxml", harness_id="agy")
    assert len(spawned) == 2
    fake_now[0] += 601.0
    evicted = await pool.evict_expired()
    assert evicted == 1
    assert spawned[1].killed is True

    # 6) Respawn cleanly after unexpected EOF / crash (testing both direct crash error AND next-turn respawn)
    orch.reset_session(proj.id)
    await orch.warmup_agent(proj.id, phase="jrxml", harness_id="agy")
    assert len(spawned) == 3
    fail_next_turn[0] = True
    ev_crash = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Turno que falha",
            harness_id="agy",
        )
    ]
    assert any(e.type == EventType.ERROR for e in ev_crash)
    assert spawned[2].returncode == 1
    assert spawned[2].stdin.closed is True
    assert pool.active_count() == 0

    # Next turn after crash automatically spawns a fresh warm process and succeeds
    ev_recovered = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Turno recuperado",
            harness_id="agy",
        )
    ]
    assert len(spawned) == 4
    assert not any(e.type == EventType.ERROR for e in ev_recovered)
    assert ev_recovered[-1].type == EventType.DONE
    assert pool.active_count() == 1

    # Clean shutdown_all terminates remaining sessions
    shut = await pool.shutdown_all()
    assert shut == 1
    assert pool.active_count() == 0


def test_agent_warmup_and_delete_session_rest_endpoints(tmp_path: Path) -> None:
    store = SQLiteStore(db_path=tmp_path / "studio.db")
    ws = WorkspaceService(store=store, data_dir=tmp_path / "data")
    claude = ClaudeCodeHarness(which_resolver=lambda _: None)
    orch = AgentOrchestratorService(workspace_service=ws, harness_registry=HarnessRegistry([claude]))
    proj = ws.create_project(ProjectCreate(name="Warmup Endpoint Test", preferred_harness="claude"))
    store.upsert_agent_session(proj.id, "jrxml", "claude", "sid-123")

    app = FastAPI()
    app.state.workspace_service = ws
    app.state.agent_orchestrator = orch
    app.include_router(agent_api.router)

    with TestClient(app) as client:
        r_warm = client.post(
            f"/api/projects/{proj.id}/agent/warmup",
            json={"phase": "jrxml", "harness": "claude", "effort": "high"},
        )
        assert r_warm.status_code == 200
        assert r_warm.json()["ok"] is True
        assert r_warm.json()["warmed"] is False

        r_del = client.delete(f"/api/projects/{proj.id}/agent/session?phase=jrxml&harness_id=claude")
        assert r_del.status_code == 200
        assert r_del.json()["deleted"] == 1
        assert r_del.json()["closed_warm_sessions"] == 0


# -----------------------------------------------------------------------------
# 3. Auto-attach source_pdf_pages + Visual Feedback Resolve + Auto-Resolve + Fidelity Prompt
# -----------------------------------------------------------------------------


class _RecordingHarness:
    kind = HarnessKind.AGY
    display_name = "Recording AGY"

    def __init__(self, *, write_jrxml: bool = False) -> None:
        self.write_jrxml = write_jrxml
        self.requests: list[HarnessRunRequest] = []

    def check_status(self) -> HarnessStatus:
        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=True,
            executable_path="/fake/agy",
            sdk_available=False,
            version="1.0-test",
        )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        self.requests.append(request)
        if self.write_jrxml and request.gate_authorized:
            (request.workspace_dir / "ficha_ux_test.jrxml").write_text(VALID_JRXML, encoding="utf-8")
        yield HarnessEvent(type=EventType.TEXT_DELTA, content="OK", harness=self.kind)
        yield HarnessEvent(
            type=EventType.DONE,
            harness=self.kind,
            metadata={"session_id": "rec-sess-1", "resolved_model": "gemini-4-neon-high"},
        )


@pytest.mark.asyncio
async def test_source_pdf_pages_cached_attached_first_and_feedback_resolve_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteStore(db_path=tmp_path / "studio.db")
    ws = WorkspaceService(store=store, data_dir=tmp_path / "data")
    harness = _RecordingHarness(write_jrxml=True)
    orch = AgentOrchestratorService(workspace_service=ws, harness_registry=HarnessRegistry([harness]))

    proj = ws.create_project(
        ProjectCreate(name="Ficha Visual Fidelity", entry_mode="pdf", preferred_harness="agy"),
        pdf_bytes=_make_sample_pdf_bytes(),
    )
    ws_dir = Path(proj.workspace_dir)

    # Preview PNG existente
    preview_dir = ws_dir / "exports" / "pages_full"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_png = preview_dir / "preview_full_page_1.png"
    preview_png.write_bytes(b"\x89PNG\r\n\x1a\npreview")
    (ws_dir / "exports" / "latest_preview.json").write_text(
        json.dumps({"scenario": "full", "page_count": 1}), encoding="utf-8"
    )

    # Dois recortes de feedback visual: um será resolvido manualmente antes do turno, outro fica pendente
    fb_dir = ws_dir / "exports" / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    crop1 = fb_dir / "crop1.png"
    crop2 = fb_dir / "crop2.png"
    crop1.write_bytes(b"\x89PNG\r\n\x1a\ncrop1")
    crop2.write_bytes(b"\x89PNG\r\n\x1a\ncrop2")

    msg1 = ws.add_chat_message(
        proj.id,
        ChatMessageCreate(
            phase="jrxml",
            role="user",
            content="Feedback antigo já resolvido",
            metadata={"type": "visual_region_feedback", "page": 1, "crop_png_path": str(crop1)},
        ),
    )
    msg2 = ws.add_chat_message(
        proj.id,
        ChatMessageCreate(
            phase="jrxml",
            role="user",
            content="Feedback pendente ativo",
            metadata={"type": "visual_region_feedback", "page": 1, "crop_png_path": str(crop2)},
        ),
    )

    # Testa endpoint POST /jasper/feedback/resolve (seletivo para msg1)
    app = FastAPI()
    app.state.workspace_service = ws
    app.include_router(preview_api.router)
    with TestClient(app) as client:
        r_res = client.post(
            f"/api/projects/{proj.id}/jasper/feedback/resolve",
            json={"message_ids": [msg1.id]},
        )
        assert r_res.status_code == 200
        assert r_res.json()["resolved_count"] == 1
        assert r_res.json()["resolved_message_ids"] == [msg1.id]

    # Conta chamadas a render_pdf_to_pngs para verificar cache em exports/source_pages/
    render_calls = [0]
    from backend.app.services import agent_orchestrator as orch_mod

    orig_render = orch_mod.render_pdf_to_pngs

    def _counting_render(*args: Any, **kwargs: Any) -> list[Path]:
        render_calls[0] += 1
        return orig_render(*args, **kwargs)

    monkeypatch.setattr(orch_mod, "render_pdf_to_pngs", _counting_render)

    # Turn 1 (Gate 2 autorizado): deve renderizar source.pdf, anexar source_pages PRIMEIRO,
    # incluir apenas msg2/crop2 (NÃO msg1/crop1), sincronizar JRXML v1 e auto-resolver msg2!
    events1 = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Autorizado, corrija o layout conforme feedback",
            harness_id="agy",
            explicit_gate_authorized=True,
        )
    ]
    assert render_calls[0] == 1
    req1 = harness.requests[0]
    source_pages = req1.extra_context.get("source_pdf_pages", [])
    assert len(source_pages) == 1
    assert "source_pages" in source_pages[0]
    # source_pdf_pages vem PRIMEIRO em image_paths, antes de preview_png e crop2
    assert str(req1.image_paths[0]) == str(Path(source_pages[0]).resolve())
    assert preview_png.resolve() in req1.image_paths
    assert crop2.resolve() in req1.image_paths
    assert crop1.resolve() not in req1.image_paths
    assert len(req1.extra_context["visual_region_feedbacks"]) == 1
    assert req1.extra_context["visual_region_feedbacks"][0]["id"] == msg2.id

    # Verifica auto-resolve de msg2 com resolved_by_jrxml_version == 1
    sync_ev = [e for e in events1 if e.tool_name == "workspace_sync"]
    assert len(sync_ev) == 1
    assert sync_ev[0].metadata["resolved_feedback_ids"] == [msg2.id]
    all_msgs = {m.id: m for m in ws.list_chat_messages(proj.id, phase="jrxml")}
    assert all_msgs[msg2.id].metadata["resolved"] is True
    assert all_msgs[msg2.id].metadata["resolved_by_jrxml_version"] == 1

    # Turn 2 (resumed): source_pages vem do cache (render_calls continua 1!),
    # prompt é delta enxuto (sem recent_chat/available_tools), e nenhum feedback antigo entra!
    harness.write_jrxml = False
    _ = [
        e
        async for e in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Confirme o alinhamento do rodapé",
            harness_id="agy",
            explicit_gate_authorized=True,
        )
    ]
    assert render_calls[0] == 1  # Cache hit!
    req2 = harness.requests[1]
    assert req2.resume_session_id == "rec-sess-1"
    assert req2.extra_context.get("continuation") is True
    assert "recent_chat" not in req2.extra_context
    assert "available_tools" not in req2.extra_context
    assert "visual_region_feedbacks" not in req2.extra_context
    assert crop2.resolve() not in req2.image_paths
    assert req2.system_prompt_override is not None
    assert "Continuação (JRXML)" in req2.system_prompt_override
    assert "gerador-layout-jrxml-salutem-v3" not in req2.system_prompt_override

    # Resolve-all (sem message_ids) resolve múltiplos novos feedbacks
    m3 = ws.add_chat_message(
        proj.id,
        ChatMessageCreate(
            phase="jrxml",
            role="user",
            content="Novo ajuste A",
            metadata={"type": "visual_region_feedback", "page": 1},
        ),
    )
    m4 = ws.add_chat_message(
        proj.id,
        ChatMessageCreate(
            phase="jrxml",
            role="user",
            content="Novo ajuste B",
            metadata={"type": "visual_region_feedback", "page": 1},
        ),
    )
    with TestClient(app) as client:
        r_all = client.post(f"/api/projects/{proj.id}/jasper/feedback/resolve", json={})
        assert r_all.status_code == 200
        assert r_all.json()["resolved_count"] == 2
        assert set(r_all.json()["resolved_message_ids"]) == {m3.id, m4.id}


def test_jrxml_gate2_system_prompt_enforces_visual_fidelity_and_verification(tmp_path: Path) -> None:
    prompt = compose_phase_system_prompt(
        phase="jrxml",
        gate_authorized=True,
        workspace_dir=tmp_path,
    )
    assert "source_pdf_pages" in prompt
    assert "FIDELIDADE VISUAL ESTRITA AO PDF ORIGINAL" in prompt
    assert "validate_and_compile_jrxml" in prompt
    assert "render_preview_images" in prompt


def test_main_app_lifespan_calls_agy_pool_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown_called = [0]

    class _DummyPool:
        async def shutdown_all(self) -> int:
            shutdown_called[0] += 1
            return 0

    from backend.app import main as main_mod

    monkeypatch.setattr(main_mod, "get_agy_session_pool", lambda: _DummyPool())
    store = SQLiteStore(db_path=tmp_path / "studio.db")
    app = create_app(store=store, frontend_dist_dir=tmp_path / "no_dist")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
    assert shutdown_called[0] == 1
