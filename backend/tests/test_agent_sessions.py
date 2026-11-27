# -*- coding: utf-8 -*-
"""Tests for harness session continuity (`resume_session_id`), fallback on resume error, free_report skill, and `/agent/sessions` API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import agent as agent_api
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.harnesses import (
    AgyHarness,
    ClaudeCodeHarness,
    CodexHarness,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRegistry,
    HarnessRunRequest,
    HarnessStatus,
    OpenCodeHarness,
    SubprocessChunk,
)
from backend.app.harnesses.base import STUDIO_MCP_TOOL_NAMES
from backend.app.services.agent_orchestrator import AgentOrchestratorService
from backend.app.services.workspace_service import WorkspaceService


def _mock_runner(
    stdout_lines: Sequence[str],
    captured: dict[str, Any],
) -> Any:
    async def _runner(
        cmd: Sequence[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
        timeout_seconds: float | None = 300.0,
    ) -> AsyncIterator[SubprocessChunk]:
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["stdin"] = stdin_data.decode("utf-8") if stdin_data else ""
        for line in stdout_lines:
            yield SubprocessChunk(stream="stdout", line=line)
        yield SubprocessChunk(stream="exit", returncode=0)

    return _runner


def test_studio_mcp_tool_names_includes_three_db_tools() -> None:
    assert "list_db_tables" in STUDIO_MCP_TOOL_NAMES
    assert "describe_db_table" in STUDIO_MCP_TOOL_NAMES
    assert "preview_db_select" in STUDIO_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_all_four_harnesses_capture_session_id_and_pass_resume_flags(tmp_path: Path) -> None:
    # 1. AGY CLI -> --conversation <id> & DONE.metadata["session_id"]
    agy_cap: dict[str, Any] = {}
    agy = AgyHarness(
        runner=_mock_runner(
            [
                json.dumps({"event": "init", "conversation_id": "agy-conv-42"}),
                json.dumps(
                    {
                        "event": "result",
                        "result": {
                            "conversation_id": "agy-conv-42",
                            "status": "SUCCESS",
                            "response": "OK AGY",
                        },
                    }
                ),
            ],
            agy_cap,
        ),
        which_resolver=lambda name: "/bin/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
    )
    agy_events = await agy.run_to_completion(
        HarnessRunRequest(
            workspace_dir=tmp_path,
            phase="jrxml",
            prompt="Continue",
            gate_authorized=True,
            resume_session_id="agy-conv-prev",
        )
    )
    assert "--conversation" in agy_cap["cmd"]
    assert agy_cap["cmd"][agy_cap["cmd"].index("--conversation") + 1] == "agy-conv-prev"
    assert agy_events[-1].metadata["session_id"] == "agy-conv-42"

    # 2. Claude Code -> --resume <id> & DONE.metadata["session_id"]
    claude_cap: dict[str, Any] = {}
    claude = ClaudeCodeHarness(
        runner=_mock_runner(
            [
                json.dumps({"type": "system", "subtype": "init", "session_id": "claude-sid-9"}),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "result": "OK Claude",
                        "session_id": "claude-sid-9",
                    }
                ),
            ],
            claude_cap,
        ),
        which_resolver=lambda name: "/bin/claude" if name == "claude" else None,
    )
    claude_events = await claude.run_to_completion(
        HarnessRunRequest(
            workspace_dir=tmp_path,
            phase="jrxml",
            prompt="Continue",
            gate_authorized=True,
            resume_session_id="claude-sid-prev",
        )
    )
    assert "--resume" in claude_cap["cmd"]
    assert claude_cap["cmd"][claude_cap["cmd"].index("--resume") + 1] == "claude-sid-prev"
    assert claude_events[-1].metadata["session_id"] == "claude-sid-9"

    # 3. Codex -> `codex exec resume <id>` & DONE.metadata["session_id"]
    codex_cap: dict[str, Any] = {}
    codex = CodexHarness(
        runner=_mock_runner(
            [
                json.dumps({"type": "thread.started", "thread_id": "th_codex_77"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"id": "i1", "type": "agent_message", "text": "OK Codex"},
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ],
            codex_cap,
        ),
        which_resolver=lambda name: "/bin/codex" if name == "codex" else None,
    )
    codex_events = await codex.run_to_completion(
        HarnessRunRequest(
            workspace_dir=tmp_path,
            phase="jrxml",
            prompt="Continue",
            gate_authorized=True,
            resume_session_id="th_codex_prev",
        )
    )
    assert codex_cap["cmd"][:4] == ["/bin/codex", "exec", "resume", "th_codex_prev"]
    assert codex_events[-1].metadata["session_id"] == "th_codex_77"
    assert codex_events[-1].metadata["thread_id"] == "th_codex_77"

    # 4. OpenCode HTTP -> skips POST /session and posts directly to /session/<id>/message
    oc_paths: list[str] = []

    def _oc_handler(request: httpx.Request) -> httpx.Response:
        oc_paths.append(f"{request.method} {request.url.path}")
        if request.url.path == "/session/oc-sess-prev/message":
            return httpx.Response(
                200,
                json={"parts": [{"type": "text", "text": "OK OpenCode"}]},
            )
        return httpx.Response(404)

    opencode = OpenCodeHarness(
        server_url="http://127.0.0.1:4096",
        http_transport=httpx.MockTransport(_oc_handler),
        which_resolver=lambda _: None,
    )
    oc_events = await opencode.run_to_completion(
        HarnessRunRequest(
            workspace_dir=tmp_path,
            phase="jrxml",
            prompt="Continue",
            gate_authorized=True,
            resume_session_id="oc-sess-prev",
        )
    )
    assert oc_paths == ["POST /session/oc-sess-prev/message"]
    assert oc_events[-1].metadata["session_id"] == "oc-sess-prev"


class SessionTestingHarness:
    """Fake harness simulating session creation, resume, and stale-session failures."""

    kind = HarnessKind.CLAUDE
    display_name = "Fake Claude"

    def __init__(self, *, fail_resume_ids: set[str] | None = None) -> None:
        self.fail_resume_ids = set(fail_resume_ids or set())
        self.requests: list[HarnessRunRequest] = []
        self._counter = 0

    def check_status(self) -> HarnessStatus:
        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=True,
            executable_path="/fake/claude",
            sdk_available=False,
            version="1.0-test",
            auth_hint="",
            supports_vision=True,
            supports_mcp=True,
        )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        self.requests.append(request)
        if request.resume_session_id and request.resume_session_id in self.fail_resume_ids:
            yield HarnessEvent(
                type=EventType.ERROR,
                content="Session expired on harness",
                harness=self.kind,
            )
            return

        if request.resume_session_id:
            sid = request.resume_session_id
        else:
            self._counter += 1
            sid = f"fresh-sess-{self._counter}"

        yield HarnessEvent(
            type=EventType.TEXT_DELTA,
            content=f"Resposta na sessão {sid}",
            harness=self.kind,
        )
        yield HarnessEvent(
            type=EventType.DONE,
            harness=self.kind,
            metadata={"session_id": sid},
        )


@pytest.mark.asyncio
async def test_orchestrator_persists_resumes_falls_back_and_selects_free_report_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    store = SQLiteStore(db_path=data_dir / "studio.db")
    ws = WorkspaceService(store=store, data_dir=data_dir)
    fake_claude = SessionTestingHarness(fail_resume_ids={"stale-expired-999"})
    registry = HarnessRegistry([fake_claude])
    orch = AgentOrchestratorService(workspace_service=ws, harness_registry=registry)

    proj = ws.create_project(
        ProjectCreate(
            name="Relatório Livre Hospitalar",
            project_kind="free_report",
            entry_mode="blank_report",
            preferred_harness="claude",
        )
    )

    # Turn 1: no saved session -> saves fresh-sess-1 AND selects manutencao_relatorio skill
    events1 = [
        ev
        async for ev in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Ajustar query",
            harness_id="claude",
            explicit_gate_authorized=True,
        )
    ]
    assert fake_claude.requests[0].resume_session_id is None
    assert fake_claude.requests[0].extra_context["skill_name"] == "manutencao_relatorio"
    assert fake_claude.requests[0].system_prompt_override is not None
    assert "Manutenção e Criação de Relatórios Livres" in fake_claude.requests[0].system_prompt_override
    assert events1[-1].type == EventType.DONE
    assert events1[-1].metadata["session_id"] == "fresh-sess-1"

    saved = store.get_agent_session(proj.id, "jrxml", "claude")
    assert saved is not None
    assert saved["external_session_id"] == "fresh-sess-1"

    # Turn 2: automatically resumes fresh-sess-1
    events2 = [
        ev
        async for ev in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Agora ajuste o cabeçalho",
            harness_id="claude",
            explicit_gate_authorized=True,
        )
    ]
    assert fake_claude.requests[1].resume_session_id == "fresh-sess-1"
    assert events2[-1].metadata["session_id"] == "fresh-sess-1"

    # Turn 3: stale session fails -> automatic fallback to fresh session (fresh-sess-2)
    store.upsert_agent_session(proj.id, "jrxml", "claude", "stale-expired-999")
    events3 = [
        ev
        async for ev in orch.stream_turn(
            proj.id,
            phase="jrxml",
            prompt="Continuar após expiração",
            harness_id="claude",
            explicit_gate_authorized=True,
        )
    ]
    # Attempt 1 tried stale-expired-999, attempt 2 ran fresh with None
    assert fake_claude.requests[2].resume_session_id == "stale-expired-999"
    assert fake_claude.requests[3].resume_session_id is None
    assert not any(ev.type == EventType.ERROR for ev in events3)
    assert events3[-1].type == EventType.DONE
    assert events3[-1].metadata["session_id"] == "fresh-sess-2"
    assert events3[-1].metadata.get("session_fallback") is True
    assert store.get_agent_session(proj.id, "jrxml", "claude")["external_session_id"] == "fresh-sess-2"


def test_agent_sessions_rest_api_list_and_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    store = SQLiteStore(db_path=data_dir / "studio.db")
    ws = WorkspaceService(store=store, data_dir=data_dir)
    orch = AgentOrchestratorService(
        workspace_service=ws,
        harness_registry=HarnessRegistry([SessionTestingHarness()]),
    )
    proj = ws.create_project(ProjectCreate(name="Sessões API", entry_mode="pdf"))
    store.upsert_agent_session(proj.id, "jrxml", "claude", "sess-jrxml-1")
    store.upsert_agent_session(proj.id, "extraction", "agy", "sess-ext-2")

    app = FastAPI()
    app.state.agent_orchestrator = orch
    app.include_router(agent_api.router)
    client = TestClient(app)

    r_list = client.get(f"/api/projects/{proj.id}/agent/sessions")
    assert r_list.status_code == 200
    items = r_list.json()
    assert len(items) == 2

    # Status also includes sessions
    r_status = client.get(f"/api/projects/{proj.id}/agent/status")
    assert r_status.status_code == 200
    assert len(r_status.json()["sessions"]) == 2

    # Delete specific (phase, harness_id)
    r_del = client.delete(
        f"/api/projects/{proj.id}/agent/session?phase=jrxml&harness_id=claude"
    )
    assert r_del.status_code == 200
    assert r_del.json()["deleted"] == 1

    remaining = client.get(f"/api/projects/{proj.id}/agent/sessions").json()
    assert len(remaining) == 1
    assert remaining[0]["external_session_id"] == "sess-ext-2"
