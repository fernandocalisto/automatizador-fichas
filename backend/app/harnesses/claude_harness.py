# -*- coding: utf-8 -*-
"""Adaptador Claude Code CLI (`claude -p --output-format stream-json --verbose`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.harnesses.base import BaseSubprocessHarness, SubprocessRunner
from app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)


class ClaudeCodeHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do Anthropic Claude Code CLI (`claude`).

    Executa `claude -p --output-format stream-json --verbose` com `--append-system-prompt`,
    `--add-dir` e `--model` opcional, fazendo parse em tempo real das mensagens NDJSON
    (`assistant` text/thinking/tool_use, `user` tool_result e `result`).
    """

    kind = HarnessKind.CLAUDE
    display_name = "Claude Code"

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
        return self._resolve_executable("claude")

    def check_status(self) -> HarnessStatus:
        exe = self._find_cli_executable()
        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=exe is not None,
            executable_path=exe,
            sdk_available=False,
            version=self._probe_version(exe),
            auth_hint="Execute 'claude login' no terminal ou configure ANTHROPIC_API_KEY.",
            supports_vision=True,
            supports_mcp=True,
        )

    def build_command(
        self,
        executable: str,
        request: HarnessRunRequest,
        system_prompt: str,
    ) -> list[str]:
        """Constrói os argumentos de linha de comando para `claude -p --output-format stream-json`."""
        cmd = [
            executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--append-system-prompt",
            system_prompt,
            "--add-dir",
            str(request.workspace_dir.resolve()),
        ]
        if request.model:
            cmd.extend(["--model", request.model])
        return cmd

    def parse_ndjson_line(
        self,
        line: str,
        state: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Converte uma linha NDJSON do `claude --output-format stream-json` em `HarnessEvent`s."""
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

        if ev_type == "assistant":
            message = obj.get("message") or {}
            content_blocks = message.get("content") if isinstance(message, dict) else []
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    b_type = str(block.get("type") or "")
                    if b_type == "text":
                        text_val = str(block.get("text") or "")
                        if text_val:
                            state["emitted_assistant_text"] = True
                            events.append(
                                HarnessEvent(
                                    type=EventType.TEXT_DELTA,
                                    content=text_val,
                                    harness=self.kind,
                                )
                            )
                    elif b_type in ("thinking", "redacted_thinking"):
                        thought_val = str(block.get("thinking") or block.get("text") or "")
                        if thought_val:
                            events.append(
                                HarnessEvent(
                                    type=EventType.THOUGHT_DELTA,
                                    content=thought_val,
                                    harness=self.kind,
                                )
                            )
                    elif b_type == "tool_use":
                        events.append(
                            HarnessEvent(
                                type=EventType.TOOL_CALL,
                                tool_name=str(block.get("name") or "tool"),
                                tool_call_id=block.get("id"),
                                tool_args=(
                                    block.get("input")
                                    if isinstance(block.get("input"), dict)
                                    else {}
                                ),
                                harness=self.kind,
                            )
                        )

        elif ev_type == "stream_event":
            inner = obj.get("event") if isinstance(obj.get("event"), dict) else {}
            delta = inner.get("delta") if isinstance(inner.get("delta"), dict) else {}
            d_type = str(delta.get("type") or "")
            if d_type == "text_delta" and delta.get("text"):
                state["emitted_assistant_text"] = True
                events.append(
                    HarnessEvent(
                        type=EventType.TEXT_DELTA,
                        content=str(delta["text"]),
                        harness=self.kind,
                    )
                )
            elif d_type == "thinking_delta" and delta.get("thinking"):
                events.append(
                    HarnessEvent(
                        type=EventType.THOUGHT_DELTA,
                        content=str(delta["thinking"]),
                        harness=self.kind,
                    )
                )

        elif ev_type == "user":
            message = obj.get("message") or {}
            content_blocks = message.get("content") if isinstance(message, dict) else []
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        events.append(
                            HarnessEvent(
                                type=EventType.TOOL_RESULT,
                                tool_call_id=block.get("tool_use_id"),
                                tool_output=block.get("content"),
                                harness=self.kind,
                                metadata={"is_error": bool(block.get("is_error", False))},
                            )
                        )

        elif ev_type == "result":
            subtype = str(obj.get("subtype") or "")
            is_err = bool(obj.get("is_error", False)) or subtype.startswith("error")
            state["session_id"] = obj.get("session_id")
            if obj.get("total_cost_usd") is not None:
                state["total_cost_usd"] = obj.get("total_cost_usd")

            if is_err:
                state["had_error"] = True
                err_msg = str(
                    obj.get("result") or obj.get("error") or "Falha reportada pelo Claude Code."
                )
                events.append(
                    HarnessEvent(
                        type=EventType.ERROR,
                        content=err_msg,
                        harness=self.kind,
                        metadata={"subtype": subtype},
                    )
                )
            else:
                result_text = obj.get("result")
                if (
                    isinstance(result_text, str)
                    and result_text
                    and not state.get("emitted_assistant_text")
                ):
                    state["emitted_assistant_text"] = True
                    events.append(
                        HarnessEvent(
                            type=EventType.TEXT_DELTA,
                            content=result_text,
                            harness=self.kind,
                        )
                    )

        elif ev_type == "error":
            state["had_error"] = True
            err_detail = obj.get("error") or obj.get("message") or "Erro no Claude Code."
            if isinstance(err_detail, dict):
                err_detail = err_detail.get("message") or json.dumps(err_detail)
            events.append(
                HarnessEvent(
                    type=EventType.ERROR,
                    content=str(err_detail),
                    harness=self.kind,
                )
            )

        return events

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        exe = self._find_cli_executable()
        if not exe:
            yield HarnessEvent(
                type=EventType.ERROR,
                content="Claude Code CLI ('claude') não encontrado no PATH.",
                harness=self.kind,
            )
            return

        system_prompt, user_prompt = self._build_prompts(request)
        cmd = self.build_command(exe, request, system_prompt)
        state: dict[str, Any] = {"had_error": False, "emitted_assistant_text": False}
        stderr_lines: list[str] = []

        try:
            async for chunk in self._exec_lines(
                cmd,
                cwd=request.workspace_dir,
                stdin_data=user_prompt.encode("utf-8"),
                timeout_seconds=request.timeout_seconds,
            ):
                if chunk.stream == "stdout":
                    for ev in self.parse_ndjson_line(chunk.line, state):
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
                            content=f"Falha no Claude Code CLI: {detail}",
                            harness=self.kind,
                            metadata={"returncode": chunk.returncode},
                        )

            if not state.get("had_error"):
                gate_ev = self._make_gate_event_if_needed(request)
                if gate_ev is not None:
                    yield gate_ev
                done_meta: dict[str, Any] = {"mode": "cli"}
                if state.get("session_id"):
                    done_meta["session_id"] = state["session_id"]
                if "total_cost_usd" in state:
                    done_meta["total_cost_usd"] = state["total_cost_usd"]
                yield HarnessEvent(
                    type=EventType.DONE,
                    harness=self.kind,
                    metadata=done_meta,
                )
        except TimeoutError:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Tempo limite excedido ({request.timeout_seconds}s) no Claude Code.",
                harness=self.kind,
            )
        except Exception as exc:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Erro inesperado no Claude Code Harness: {exc}",
                harness=self.kind,
            )
