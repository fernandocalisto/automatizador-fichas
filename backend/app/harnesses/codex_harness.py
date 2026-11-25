# -*- coding: utf-8 -*-
"""Adaptador OpenAI Codex CLI (`codex exec --json -C <workspace_dir>`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from app.harnesses.base import BaseSubprocessHarness, SubprocessRunner
from app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)


class CodexHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do OpenAI Codex CLI (`codex`).

    Executa `codex exec --json -C <workspace_dir>` passando o prompt composto via stdin (`-`)
    e interpreta os eventos JSONL (`thread.started`, `item.started`, `item.completed` para
    `agent_message`, `reasoning` e `command_execution`, e `turn.completed`).
    """

    kind = HarnessKind.CODEX
    display_name = "OpenAI Codex"

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            runner=runner,
            which_resolver=which_resolver,
            default_timeout=default_timeout,
        )

    def _find_cli_executable(self) -> str | None:
        return self._resolve_executable("codex")

    def check_status(self) -> HarnessStatus:
        exe = self._find_cli_executable()
        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=exe is not None,
            executable_path=exe,
            sdk_available=False,
            version=self._probe_version(exe),
            auth_hint="Execute 'codex login' no terminal ou defina OPENAI_API_KEY.",
            supports_vision=True,
            supports_mcp=True,
        )

    def build_command(self, executable: str, request: HarnessRunRequest) -> list[str]:
        """Constrói o comando `codex exec --json -C <workspace_dir>`."""
        cmd = [
            executable,
            "exec",
            "--json",
            "-C",
            str(request.workspace_dir.resolve()),
        ]
        if request.model:
            cmd.extend(["--model", request.model])
        for img in request.image_paths:
            cmd.extend(["-i", str(Path(img).resolve())])
        cmd.append("-")
        return cmd

    def parse_jsonl_line(
        self,
        line: str,
        state: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Converte uma linha JSONL do `codex exec --json` em eventos `HarnessEvent`."""
        stripped = line.strip()
        if not stripped:
            return []

        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return [
                HarnessEvent(
                    type=EventType.TEXT_DELTA,
                    content=line + "\n",
                    harness=self.kind,
                )
            ]

        if not isinstance(obj, dict):
            return []

        events: list[HarnessEvent] = []
        ev_type = str(obj.get("type") or "")
        started_tools: set[str] = state.setdefault("started_tools", set())

        if ev_type == "thread.started":
            state["thread_id"] = obj.get("thread_id")

        elif ev_type == "item.started":
            item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
            i_type = str(item.get("type") or "")
            item_id = str(item.get("id") or "")
            if i_type == "command_execution":
                if item_id:
                    started_tools.add(item_id)
                events.append(
                    HarnessEvent(
                        type=EventType.TOOL_CALL,
                        tool_name="command_execution",
                        tool_call_id=item_id or None,
                        tool_args={"command": item.get("command", "")},
                        harness=self.kind,
                    )
                )
            elif i_type == "mcp_tool_call":
                t_name = str(item.get("tool") or item.get("name") or "mcp_tool")
                if item_id:
                    started_tools.add(item_id)
                events.append(
                    HarnessEvent(
                        type=EventType.TOOL_CALL,
                        tool_name=t_name,
                        tool_call_id=item_id or None,
                        tool_args=(
                            item.get("arguments")
                            if isinstance(item.get("arguments"), dict)
                            else {}
                        ),
                        harness=self.kind,
                    )
                )

        elif ev_type == "item.completed":
            item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
            i_type = str(item.get("type") or "")
            item_id = str(item.get("id") or "")

            if i_type in ("agent_message", "message"):
                text_val = item.get("text")
                if not text_val and isinstance(item.get("content"), list):
                    text_val = "".join(
                        str(part.get("text") or "")
                        for part in item["content"]
                        if isinstance(part, dict)
                    )
                if text_val:
                    events.append(
                        HarnessEvent(
                            type=EventType.TEXT_DELTA,
                            content=str(text_val),
                            harness=self.kind,
                        )
                    )

            elif i_type == "reasoning":
                thought_val = item.get("text")
                if not thought_val and isinstance(item.get("summary"), list):
                    thought_val = "\n".join(
                        str(s.get("text") or s) if isinstance(s, dict) else str(s)
                        for s in item["summary"]
                    )
                if thought_val:
                    events.append(
                        HarnessEvent(
                            type=EventType.THOUGHT_DELTA,
                            content=str(thought_val),
                            harness=self.kind,
                        )
                    )

            elif i_type == "command_execution":
                if not item_id or item_id not in started_tools:
                    if item_id:
                        started_tools.add(item_id)
                    events.append(
                        HarnessEvent(
                            type=EventType.TOOL_CALL,
                            tool_name="command_execution",
                            tool_call_id=item_id or None,
                            tool_args={"command": item.get("command", "")},
                            harness=self.kind,
                        )
                    )
                events.append(
                    HarnessEvent(
                        type=EventType.TOOL_RESULT,
                        tool_name="command_execution",
                        tool_call_id=item_id or None,
                        tool_output={
                            "command": item.get("command", ""),
                            "aggregated_output": item.get("aggregated_output", ""),
                            "exit_code": item.get("exit_code"),
                        },
                        harness=self.kind,
                    )
                )

            elif i_type == "mcp_tool_call":
                t_name = str(item.get("tool") or item.get("name") or "mcp_tool")
                if not item_id or item_id not in started_tools:
                    if item_id:
                        started_tools.add(item_id)
                    events.append(
                        HarnessEvent(
                            type=EventType.TOOL_CALL,
                            tool_name=t_name,
                            tool_call_id=item_id or None,
                            tool_args=(
                                item.get("arguments")
                                if isinstance(item.get("arguments"), dict)
                                else {}
                            ),
                            harness=self.kind,
                        )
                    )
                events.append(
                    HarnessEvent(
                        type=EventType.TOOL_RESULT,
                        tool_name=t_name,
                        tool_call_id=item_id or None,
                        tool_output=item.get("result") or item.get("error"),
                        harness=self.kind,
                    )
                )

            elif i_type == "error":
                state["had_error"] = True
                events.append(
                    HarnessEvent(
                        type=EventType.ERROR,
                        content=str(item.get("message") or "Erro de item no Codex."),
                        harness=self.kind,
                    )
                )

        elif ev_type == "turn.completed":
            state["turn_completed"] = True
            if isinstance(obj.get("usage"), dict):
                state["usage"] = obj["usage"]

        elif ev_type in ("turn.failed", "error"):
            state["had_error"] = True
            err_obj = obj.get("error")
            msg = (
                err_obj.get("message")
                if isinstance(err_obj, dict)
                else (obj.get("message") or str(err_obj or "Falha no turno do Codex."))
            )
            events.append(
                HarnessEvent(
                    type=EventType.ERROR,
                    content=str(msg),
                    harness=self.kind,
                )
            )

        return events

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        exe = self._find_cli_executable()
        if not exe:
            yield HarnessEvent(
                type=EventType.ERROR,
                content="OpenAI Codex CLI ('codex') não encontrado no PATH.",
                harness=self.kind,
            )
            return

        system_prompt, user_prompt = self._build_prompts(request)
        combined_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        cmd = self.build_command(exe, request)
        state: dict[str, Any] = {"had_error": False}
        stderr_lines: list[str] = []

        try:
            async for chunk in self._exec_lines(
                cmd,
                cwd=request.workspace_dir,
                stdin_data=combined_prompt.encode("utf-8"),
                timeout_seconds=request.timeout_seconds,
            ):
                if chunk.stream == "stdout":
                    for ev in self.parse_jsonl_line(chunk.line, state):
                        yield ev
                elif chunk.stream == "stderr":
                    if chunk.line.strip():
                        stderr_lines.append(chunk.line.strip())
                elif chunk.stream == "exit":
                    if chunk.returncode not in (0, None) and not state.get("had_error"):
                        state["had_error"] = True
                        detail = (
                            "\n".join(stderr_lines[-10:]) or f"Código de saída {chunk.returncode}"
                        )
                        yield HarnessEvent(
                            type=EventType.ERROR,
                            content=f"Falha no OpenAI Codex CLI: {detail}",
                            harness=self.kind,
                            metadata={"returncode": chunk.returncode},
                        )

            if not state.get("had_error"):
                gate_ev = self._make_gate_event_if_needed(request)
                if gate_ev is not None:
                    yield gate_ev
                done_meta: dict[str, Any] = {"mode": "cli"}
                if state.get("thread_id"):
                    done_meta["thread_id"] = state["thread_id"]
                if state.get("usage"):
                    done_meta["usage"] = state["usage"]
                yield HarnessEvent(
                    type=EventType.DONE,
                    harness=self.kind,
                    metadata=done_meta,
                )
        except TimeoutError:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Tempo limite excedido ({request.timeout_seconds}s) no OpenAI Codex.",
                harness=self.kind,
            )
        except Exception as exc:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Erro inesperado no Codex Harness: {exc}",
                harness=self.kind,
            )
