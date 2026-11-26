# -*- coding: utf-8 -*-
"""Testes unitários dos 4 Harnesses (AGY, OpenCode, Claude Code, Codex), Registry e Prompt 2-Gate."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.harnesses import (
    AgentHarness,
    AgyHarness,
    ClaudeCodeHarness,
    CodexHarness,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRegistry,
    HarnessRunRequest,
    OpenCodeHarness,
    SubprocessChunk,
    SubprocessRunner,
    compose_phase_system_prompt,
    default_subprocess_runner,
)


def make_mock_runner(
    stdout_lines: Sequence[str] = (),
    stderr_lines: Sequence[str] = (),
    returncode: int = 0,
    captured: dict[str, Any] | None = None,
) -> SubprocessRunner:
    """Cria um `SubprocessRunner` determinístico em memória para testes unitários."""

    async def _runner(
        cmd: Sequence[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
        timeout_seconds: float | None = 300.0,
    ) -> AsyncIterator[SubprocessChunk]:
        if captured is not None:
            captured["cmd"] = list(cmd)
            captured["cwd"] = cwd
            captured["env"] = env
            captured["stdin"] = stdin_data.decode("utf-8") if stdin_data else ""
            captured["timeout"] = timeout_seconds

        for line in stdout_lines:
            yield SubprocessChunk(stream="stdout", line=line)
        for err in stderr_lines:
            yield SubprocessChunk(stream="stderr", line=err)
        yield SubprocessChunk(stream="exit", returncode=returncode)

    return _runner


# ---------------------------------------------------------------------------
# 1. Tipos, Serialização SSE e Composição de System Prompt 2-Gate
# ---------------------------------------------------------------------------


def test_harness_event_sse_serialization() -> None:
    ev = HarnessEvent(
        type=EventType.TEXT_DELTA,
        content="Analisando seção 1...",
        harness=HarnessKind.AGY,
    )
    sse = ev.to_sse()
    assert sse.startswith("event: text_delta\ndata: ")
    assert sse.endswith("\n\n")
    payload = json.loads(sse.splitlines()[1].removeprefix("data: "))
    assert payload["type"] == "text_delta"
    assert payload["content"] == "Analisando seção 1..."
    assert payload["harness"] == "agy"


def test_compose_phase_system_prompt_extraction_2_gates(tmp_path: Path) -> None:
    prompt_gate1 = compose_phase_system_prompt(
        phase="extraction",
        skill_markdown=None,
        gate_authorized=False,
        workspace_dir=tmp_path,
    )
    assert "GATE 1" in prompt_gate1
    assert "`False`" in prompt_gate1
    assert "PROIBIDO GERAR ARQUIVOS FINAIS" in prompt_gate1
    assert "extrator-ficha-clinica-salutem" in prompt_gate1
    assert str(tmp_path.resolve()) in prompt_gate1

    prompt_gate2 = compose_phase_system_prompt(
        phase="extraction",
        skill_markdown=None,
        gate_authorized=True,
        workspace_dir=tmp_path,
    )
    assert "GATE 2" in prompt_gate2
    assert "`True`" in prompt_gate2
    assert "GRAVAÇÃO DIRETA EM ARQUIVO NO WORKSPACE" in prompt_gate2
    assert '"template"' in prompt_gate2


def test_compose_phase_system_prompt_jrxml_2_gates(tmp_path: Path) -> None:
    prompt_gate1 = compose_phase_system_prompt(
        phase="jrxml",
        skill_markdown=None,
        gate_authorized=False,
        workspace_dir=tmp_path,
    )
    assert "GATE 1" in prompt_gate1
    assert "PAUSA OBRIGATÓRIA ANTES DO CÓDIGO" in prompt_gate1
    assert "pdf_y - 182" in prompt_gate1
    assert "gerador-layout-jrxml-salutem-v3" in prompt_gate1

    prompt_gate2 = compose_phase_system_prompt(
        phase="jrxml",
        skill_markdown=None,
        gate_authorized=True,
        workspace_dir=tmp_path,
    )
    assert "GATE 2" in prompt_gate2
    assert 'isBlankWhenNull="true"' in prompt_gate2
    assert "PROIBIDO POLUIR O CHAT COM XML LONGO" in prompt_gate2


def test_compose_phase_system_prompt_invalid_phase() -> None:
    with pytest.raises(ValueError, match="Fase inválida"):
        compose_phase_system_prompt("sql_invalid", None, False, ".")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Executor Real Assíncrono (`default_subprocess_runner`) e Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_subprocess_runner_streams_stdout_stderr_and_exit(tmp_path: Path) -> None:
    script = (
        "import sys; "
        "sys.stdout.write('linha-1\\n'); sys.stdout.flush(); "
        "sys.stderr.write('aviso-stderr\\n'); sys.stderr.flush(); "
        "data = sys.stdin.read().strip(); "
        "sys.stdout.write(f'eco:{data}\\n'); sys.stdout.flush()"
    )
    chunks: list[SubprocessChunk] = []
    async for ch in default_subprocess_runner(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdin_data=b"salutem",
        timeout_seconds=10.0,
    ):
        chunks.append(ch)

    stdout_lines = [c.line for c in chunks if c.stream == "stdout"]
    stderr_lines = [c.line for c in chunks if c.stream == "stderr"]
    exits = [c.returncode for c in chunks if c.stream == "exit"]

    assert stdout_lines == ["linha-1", "eco:salutem"]
    assert stderr_lines == ["aviso-stderr"]
    assert exits == [0]


@pytest.mark.asyncio
async def test_default_subprocess_runner_enforces_timeout_and_kills_process(
    tmp_path: Path,
) -> None:
    with pytest.raises(TimeoutError):
        async for _ in default_subprocess_runner(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
            timeout_seconds=0.15,
        ):
            pass


# ---------------------------------------------------------------------------
# 3. HarnessRegistry — Descoberta e Ordem de Prioridade dos 4 Harnesses
# ---------------------------------------------------------------------------


def test_harness_registry_registers_all_four_harnesses_and_resolves_priority() -> None:
    agy_uninstalled = AgyHarness(
        which_resolver=lambda _: None,
        sdk_spec_finder=lambda _: None,
        local_appdata_dir="/nonexistent",
    )
    opencode_uninstalled = OpenCodeHarness(
        server_url="",
        which_resolver=lambda _: None,
    )
    claude_installed = ClaudeCodeHarness(
        which_resolver=lambda name: "/usr/local/bin/claude" if name == "claude" else None
    )
    codex_installed = CodexHarness(
        which_resolver=lambda name: "/usr/local/bin/codex" if name == "codex" else None
    )

    registry = HarnessRegistry(
        [agy_uninstalled, opencode_uninstalled, claude_installed, codex_installed]
    )

    assert registry.list_ids() == [
        HarnessKind.AGY,
        HarnessKind.OPENCODE,
        HarnessKind.CLAUDE,
        HarnessKind.CODEX,
    ]

    statuses = registry.list_statuses()
    assert len(statuses) == 4
    assert [s.id for s in statuses] == [
        HarnessKind.AGY,
        HarnessKind.OPENCODE,
        HarnessKind.CLAUDE,
        HarnessKind.CODEX,
    ]
    assert statuses[0].installed is False
    assert statuses[1].installed is False
    assert statuses[2].installed is True
    assert statuses[3].installed is True

    for kind in HarnessKind:
        adapter = registry.get(kind.value)
        assert isinstance(adapter, AgentHarness)

    default = registry.get_default_available()
    assert default is claude_installed

    with pytest.raises(KeyError, match="Harness desconhecido"):
        registry.get("cursor-nonexistent")


# ---------------------------------------------------------------------------
# 4. AgyHarness — Modo SDK (`google.antigravity`) e Fallback CLI (`agy`)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agy_harness_streams_sdk_thoughts_tools_and_tokens(tmp_path: Path) -> None:
    captured_sdk: dict[str, Any] = {}

    @dataclass
    class FakeCapabilitiesConfig:
        enable_write: bool = True

    @dataclass
    class FakeLocalAgentConfig:
        system_instructions: str = ""
        capabilities: Any = None
        model: str | None = None

    class FakeResponse:
        def __init__(self) -> None:
            self._tokens = ["Resumo ", "da ficha clínica."]

        def __aiter__(self) -> AsyncIterator[str]:
            return self._iter_tokens()

        async def _iter_tokens(self) -> AsyncIterator[str]:
            for tok in self._tokens:
                yield tok

        @property
        async def thoughts(self) -> AsyncIterator[str]:
            yield "Inspecionando metadados do PDF..."

        @property
        async def tool_calls(self) -> AsyncIterator[Any]:
            yield SimpleNamespace(
                id="call-agy-1",
                name="inspect_clinical_pdf",
                args={"pdf_path": "ficha.pdf"},
            )

    class FakeAgent:
        def __init__(self, config: FakeLocalAgentConfig) -> None:
            captured_sdk["config"] = config

        async def __aenter__(self) -> FakeAgent:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        async def chat(self, prompt: str) -> FakeResponse:
            captured_sdk["prompt"] = prompt
            return FakeResponse()

    fake_module = SimpleNamespace(
        __version__="2.1.0",
        Agent=FakeAgent,
        LocalAgentConfig=FakeLocalAgentConfig,
        CapabilitiesConfig=FakeCapabilitiesConfig,
    )

    harness = AgyHarness(
        which_resolver=lambda _: None,
        sdk_spec_finder=lambda name: object() if name == "google.antigravity" else None,
        sdk_importer=lambda _: fake_module,
        local_appdata_dir=tmp_path / "empty_appdata",
    )

    status = harness.check_status()
    assert status.installed is True
    assert status.sdk_available is True
    assert status.version == "2.1.0"

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="extraction",
        prompt="Analise a ficha de triagem.",
        gate_authorized=False,
        model="gemini-2.5-pro",
    )
    events = await harness.run_to_completion(req)
    event_types = [e.type for e in events]

    assert EventType.THOUGHT_DELTA in event_types
    assert EventType.TOOL_CALL in event_types
    assert EventType.TEXT_DELTA in event_types
    assert event_types[-2] == EventType.GATE_REQUEST
    assert event_types[-1] == EventType.DONE
    assert events[-1].metadata["mode"] == "sdk"

    text_joined = "".join(e.content for e in events if e.type == EventType.TEXT_DELTA)
    assert text_joined == "Resumo da ficha clínica."
    assert captured_sdk["config"].model == "gemini-2.5-pro"
    assert "GATE 1" in captured_sdk["config"].system_instructions


@pytest.mark.asyncio
async def test_agy_harness_cli_fallback_via_localappdata(tmp_path: Path) -> None:
    fake_bin = tmp_path / "agy" / "bin" / "agy.exe"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_bytes(b"MZ")

    captured: dict[str, Any] = {}
    runner = make_mock_runner(
        stdout_lines=[
            json.dumps({"type": "thought", "content": "Validando tags XSD..."}),
            json.dumps({"type": "text", "content": "Arquivo ficha.jrxml gravado com sucesso."}),
        ],
        captured=captured,
    )

    harness = AgyHarness(
        runner=runner,
        which_resolver=lambda _: None,
        sdk_spec_finder=lambda _: None,
        local_appdata_dir=tmp_path,
    )

    status = harness.check_status()
    assert status.installed is True
    assert status.sdk_available is False
    assert status.executable_path == str(fake_bin)

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="jrxml",
        prompt="Gere o JRXML final autorizado.",
        gate_authorized=True,
    )
    events = await harness.run_to_completion(req)

    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TEXT_DELTA,
        EventType.DONE,
    ]
    assert events[-1].metadata["mode"] == "cli"
    assert EventType.GATE_REQUEST not in [e.type for e in events]
    assert "--input-format" in captured["cmd"]
    assert "stream-json" in captured["cmd"]
    assert "--mode" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--mode") + 1] == "accept-edits"
    stdin_obj = json.loads(captured["stdin"].strip())
    assert stdin_obj["event"] == "user"
    assert "GATE 2" in stdin_obj["message"]["content"]


@pytest.mark.asyncio
async def test_agy_harness_parses_official_stream_json_events_and_modes(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    runner = make_mock_runner(
        stdout_lines=[
            json.dumps(
                {
                    "event": "init",
                    "conversation_id": "conv-agy-123",
                    "init": {"cwd": str(tmp_path), "tools": ["view_file"]},
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "conv-agy-123",
                        "step_index": 1,
                        "state": "ACTIVE",
                        "step_type": "thinking",
                        "text_delta": "Analisando geometria...",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "conv-agy-123",
                        "step_index": 2,
                        "state": "DONE",
                        "step_type": "tool",
                        "tool_name": "extract_pdf_geometry",
                        "tool_info": {
                            "name": "extract_pdf_geometry",
                            "parameters": {"project_id": "p1"},
                            "output": '{"page_count": 1}',
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "conv-agy-123",
                        "step_index": 3,
                        "state": "ACTIVE",
                        "step_type": "agent_response",
                        "text_delta": "Mapeamento ",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "step_update",
                    "step_update": {
                        "conversation_id": "conv-agy-123",
                        "step_index": 3,
                        "state": "DONE",
                        "step_type": "agent_response",
                        "text_delta": "concluído.",
                    },
                }
            ),
            json.dumps(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "conv-agy-123",
                        "status": "SUCCESS",
                        "response": "Mapeamento concluído.",
                        "usage": {"total_tokens": 512},
                    },
                }
            ),
        ],
        captured=captured,
    )

    harness = AgyHarness(
        runner=runner,
        which_resolver=lambda name: "/usr/local/bin/agy" if name == "agy" else None,
        sdk_spec_finder=lambda _: None,
    )

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="extraction",
        prompt="Analise o PDF da ficha.",
        gate_authorized=False,
        model="gemini-3.6-pro",
        timeout_seconds=120.0,
    )
    events = await harness.run_to_completion(req)

    assert captured["cmd"][captured["cmd"].index("--mode") + 1] == "plan"
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "gemini-3.6-pro"
    assert captured["cmd"][captured["cmd"].index("--print-timeout") + 1] == "120s"
    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TEXT_DELTA,
        EventType.TEXT_DELTA,
        EventType.GATE_REQUEST,
        EventType.DONE,
    ]
    assert "".join(e.content for e in events if e.type == EventType.TEXT_DELTA) == "Mapeamento concluído."
    assert events[-1].metadata["conversation_id"] == "conv-agy-123"
    assert events[-1].metadata["usage"]["total_tokens"] == 512


# ---------------------------------------------------------------------------
# 5. OpenCodeHarness — HTTP/SSE (`opencode serve`) e CLI (`opencode run --format json`)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_harness_http_sse_streaming(tmp_path: Path) -> None:
    sse_lines = [
        'event: message.part.updated\ndata: {"type":"message.part.updated","properties":{"part":{"type":"reasoning"},"delta":"Mapeando perguntas..."}}',
        "",
        'event: message.part.updated\ndata: {"type":"message.part.updated","properties":{"part":{"id":"p1","callID":"oc-tool-1","type":"tool","tool":"inspect_clinical_pdf","state":{"status":"completed","input":{"pdf_path":"a.pdf"},"output":{"page_count":1}}}}}',
        "",
        'event: message.part.delta\ndata: {"type":"message.part.delta","properties":{"field":"text","delta":"Foram encontradas 8 perguntas."}}',
        "",
    ]
    sse_body = ("\n".join(sse_lines) + "\n\n").encode("utf-8")

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-opencode-42"})
        if request.url.path == "/session/sess-opencode-42/message" and request.method == "POST":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=sse_body,
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_mock_handler)
    harness = OpenCodeHarness(
        server_url="http://127.0.0.1:4096",
        http_transport=transport,
        which_resolver=lambda _: None,
    )

    status = harness.check_status()
    assert status.installed is True
    assert status.sdk_available is True

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="extraction",
        prompt="Inspecione o PDF.",
        gate_authorized=False,
        model="anthropic/claude-sonnet-4-5",
    )
    events = await harness.run_to_completion(req)

    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TEXT_DELTA,
        EventType.GATE_REQUEST,
        EventType.DONE,
    ]
    assert events[1].tool_name == "inspect_clinical_pdf"
    assert events[2].tool_output == {"page_count": 1}
    assert events[-1].metadata == {"mode": "http", "session_id": "sess-opencode-42"}


@pytest.mark.asyncio
async def test_opencode_harness_cli_json_mode(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    img_file = tmp_path / "page_1.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    runner = make_mock_runner(
        stdout_lines=[
            json.dumps({"type": "reasoning", "part": {"text": "Verificando BOOLEANO_RADIO..."}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "tool": "write",
                        "callID": "call-oc-9",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "ficha_clinica.json"},
                            "output": "gravado",
                        },
                    },
                }
            ),
            json.dumps({"type": "text", "part": {"text": "JSON salvo em ficha_clinica.json."}}),
        ],
        captured=captured,
    )

    harness = OpenCodeHarness(
        server_url="",
        runner=runner,
        which_resolver=lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    )

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="extraction",
        prompt="Grave o JSON autorizado.",
        gate_authorized=True,
        model="openai/gpt-5",
        image_paths=[img_file],
    )
    events = await harness.run_to_completion(req)

    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TEXT_DELTA,
        EventType.DONE,
    ]
    assert captured["cmd"][:4] == ["/usr/bin/opencode", "run", "--format", "json"]
    assert "--model" in captured["cmd"]
    assert "--file" in captured["cmd"]


# ---------------------------------------------------------------------------
# 6. ClaudeCodeHarness — Stream NDJSON (`claude -p --output-format stream-json --verbose`)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_code_harness_parses_ndjson_stream(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    ndjson_lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "claude-sess-7"}),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "Calculando área útil 623px..."},
                        {
                            "type": "tool_use",
                            "id": "toolu_01",
                            "name": "inspect_clinical_pdf",
                            "input": {"pdf_path": "ficha.pdf"},
                        },
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_01",
                            "content": '{"page_count": 1}',
                            "is_error": False,
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Decisões de design prontas. Autoriza gerar?"}
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Decisões de design prontas. Autoriza gerar?",
                "session_id": "claude-sess-7",
                "total_cost_usd": 0.012,
            }
        ),
    ]

    harness = ClaudeCodeHarness(
        runner=make_mock_runner(stdout_lines=ndjson_lines, captured=captured),
        which_resolver=lambda name: "/usr/local/bin/claude" if name == "claude" else None,
    )

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="jrxml",
        prompt="Analise o PDF para construir o layout.",
        gate_authorized=False,
        model="claude-sonnet-4-5",
    )
    events = await harness.run_to_completion(req)

    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TEXT_DELTA,
        EventType.GATE_REQUEST,
        EventType.DONE,
    ]
    # Garante que `result` não duplicou o texto já emitido em `assistant`
    text_events = [e for e in events if e.type == EventType.TEXT_DELTA]
    assert len(text_events) == 1
    assert text_events[0].content == "Decisões de design prontas. Autoriza gerar?"

    cmd = captured["cmd"]
    assert cmd[:5] == ["/usr/local/bin/claude", "-p", "--output-format", "stream-json", "--verbose"]
    assert "--append-system-prompt" in cmd
    assert "--add-dir" in cmd
    assert "--model" in cmd
    assert events[-1].metadata["session_id"] == "claude-sess-7"


# ---------------------------------------------------------------------------
# 7. CodexHarness — Stream JSONL (`codex exec --json -C <workspace_dir>`)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_harness_parses_jsonl_stream(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    jsonl_lines = [
        json.dumps({"type": "thread.started", "thread_id": "th_codex_99"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "reasoning",
                    "text": "Validando UUIDs v4 e isBlankWhenNull em todos os textField...",
                },
            }
        ),
        json.dumps(
            {
                "type": "item.started",
                "item": {
                    "id": "item_2",
                    "type": "command_execution",
                    "command": "python validate_jrxml.py",
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "command_execution",
                    "command": "python validate_jrxml.py",
                    "aggregated_output": "XML OK",
                    "exit_code": 0,
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_3",
                    "type": "agent_message",
                    "text": "Arquivo ficha_avaliacao.jrxml gerado e validado no workspace.",
                },
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 1200, "output_tokens": 340},
            }
        ),
    ]

    harness = CodexHarness(
        runner=make_mock_runner(stdout_lines=jsonl_lines, captured=captured),
        which_resolver=lambda name: "/usr/local/bin/codex" if name == "codex" else None,
    )

    req = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="jrxml",
        prompt="Gere o JRXML autorizado.",
        gate_authorized=True,
        model="gpt-5-codex",
    )
    events = await harness.run_to_completion(req)

    assert [e.type for e in events] == [
        EventType.THOUGHT_DELTA,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TEXT_DELTA,
        EventType.DONE,
    ]
    assert events[1].tool_name == "command_execution"
    assert events[1].tool_args == {"command": "python validate_jrxml.py"}
    assert events[2].tool_output["exit_code"] == 0
    assert events[-1].metadata["thread_id"] == "th_codex_99"
    assert events[-1].metadata["usage"] == {"input_tokens": 1200, "output_tokens": 340}

    cmd = captured["cmd"]
    assert cmd[:4] == ["/usr/local/bin/codex", "exec", "--json", "-C"]
    assert "--skip-git-repo-check" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert any("mcp_servers.salutem_studio.command=" in arg for arg in cmd)
    assert cmd[-1] == "-"
    assert "GATE 2" in captured["stdin"]


@pytest.mark.asyncio
async def test_all_harnesses_mcp_wiring_and_windows_claude_prompt_limit(tmp_path: Path) -> None:
    # 1. AGY materializa plugin limpo `salutem` + server `studio` com todas tools habilitadas
    legacy_dir = tmp_path / ".agents" / "plugins" / "salutem-ficha-studio"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "plugin.json").write_text("{}", encoding="utf-8")

    agy_cfg = AgyHarness.ensure_workspace_mcp_config(tmp_path)
    assert agy_cfg is not None and agy_cfg.is_file()
    assert not legacy_dir.exists()
    agy_data = json.loads(agy_cfg.read_text(encoding="utf-8"))
    studio_entry = agy_data["mcpServers"]["studio"]
    assert studio_entry["disabled"] is False
    assert studio_entry["disabledTools"] == []
    assert "validate_and_compile_jrxml" in studio_entry["alwaysAllow"]

    # 2. Claude Code evita estourar limite de 32KB no Windows na fase jrxml e acopla --mcp-config
    captured_claude: dict[str, Any] = {}
    claude_h = ClaudeCodeHarness(
        runner=make_mock_runner(
            stdout_lines=[json.dumps({"type": "result", "subtype": "success", "result": "OK"})],
            captured=captured_claude,
        ),
        which_resolver=lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    req_jrxml = HarnessRunRequest(
        workspace_dir=tmp_path,
        phase="jrxml",
        prompt="Analisar layout JRXML",
        gate_authorized=True,
    )
    await claude_h.run_to_completion(req_jrxml)
    claude_cmd = captured_claude["cmd"]
    assert "--dangerously-skip-permissions" in claude_cmd
    assert "--mcp-config" in claude_cmd
    sys_prompt_arg = claude_cmd[claude_cmd.index("--append-system-prompt") + 1]
    assert len(sys_prompt_arg) < 16000
    assert "gerador-layout-jrxml-salutem-v3" in captured_claude["stdin"]

    # 3. OpenCode materializa opencode.json com MCP e permissões por Gate
    oc_cfg = OpenCodeHarness.ensure_workspace_mcp_config(tmp_path, gate_authorized=True)
    assert oc_cfg is not None and oc_cfg.is_file()
    oc_data = json.loads(oc_cfg.read_text(encoding="utf-8"))
    assert oc_data["mcp"]["salutem_studio"]["enabled"] is True
    assert oc_data["permission"]["edit"] == "allow"

    # 4. Codex interpreta eventos file_change no JSONL
    codex_h = CodexHarness(which_resolver=lambda name: "/usr/bin/codex" if name == "codex" else None)
    state: dict[str, Any] = {}
    fc_events = codex_h.parse_jsonl_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "fc_1",
                    "type": "file_change",
                    "status": "completed",
                    "changes": [{"path": "ficha_clinica.json", "kind": "update"}],
                },
            }
        ),
        state,
    )
    assert [e.type for e in fc_events] == [EventType.TOOL_CALL, EventType.TOOL_RESULT]
    assert fc_events[0].tool_name == "file_change"
