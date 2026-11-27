# -*- coding: utf-8 -*-
"""Adaptador Claude Code CLI (`claude -p --output-format stream-json --verbose`)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from backend.app.harnesses.base import (
    STUDIO_MCP_SERVER_NAME,
    BaseSubprocessHarness,
    SubprocessRunner,
    build_studio_mcp_server_spec,
)
from backend.app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)

# Limite seguro para argumento CLI no Windows (CreateProcessW tem limite total de 32.767 chars)
_MAX_INLINE_SYSTEM_PROMPT_CHARS = 12000


class ClaudeCodeHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do Anthropic Claude Code CLI (`claude`).

    Executa `claude -p --output-format stream-json --verbose` com `--append-system-prompt`,
    `--add-dir`, `--mcp-config`, `--dangerously-skip-permissions` e `--model` opcional,
    fazendo parse em tempo real das mensagens NDJSON (`assistant`, `user` tool_result e `result`).
    """

    kind = HarnessKind.CLAUDE
    display_name = "Claude Code"

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        default_timeout: float = 300.0,
        dangerously_skip_permissions: bool | None = None,
    ) -> None:
        super().__init__(
            runner=runner,
            which_resolver=which_resolver,
            default_timeout=default_timeout,
        )
        if dangerously_skip_permissions is None:
            env_val = os.environ.get("CLAUDE_SKIP_PERMISSIONS", "1").strip().lower()
            self._dangerously_skip_permissions = env_val not in ("0", "false", "no", "off")
        else:
            self._dangerously_skip_permissions = bool(dangerously_skip_permissions)

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

    @staticmethod
    def ensure_workspace_mcp_config(workspace_dir: Path) -> Path | None:
        """Materializa `.claude/studio_mcp_config.json` apontando para o servidor MCP do Studio."""
        try:
            ws_root = Path(workspace_dir).resolve()
            claude_dir = ws_root / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = claude_dir / "studio_mcp_config.json"
            payload = {"mcpServers": {STUDIO_MCP_SERVER_NAME: build_studio_mcp_server_spec()}}
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if not cfg_path.is_file() or cfg_path.read_text(encoding="utf-8") != text:
                cfg_path.write_text(text, encoding="utf-8")
            return cfg_path
        except OSError:
            return None

    @staticmethod
    def _prepare_system_prompt(
        workspace_dir: Path,
        system_prompt: str,
    ) -> tuple[str, str | None]:
        """
        Evita estourar o limite de 32 KB da linha de comando do Windows (`WinError 206`)
        quando `system_prompt` é longo (ex.: `gerador_jrxml/SKILL.md` com ~34 KB).
        Retorna `(cli_system_prompt, stdin_system_prompt_prefix)`.
        """
        if len(system_prompt) <= _MAX_INLINE_SYSTEM_PROMPT_CHARS:
            return system_prompt, None

        try:
            ws_root = Path(workspace_dir).resolve()
            claude_dir = ws_root / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            prompt_file = claude_dir / "studio_system_prompt.md"
            if not prompt_file.is_file() or prompt_file.read_text(encoding="utf-8") != system_prompt:
                prompt_file.write_text(system_prompt, encoding="utf-8")
            file_note = f"Arquivo completo de referência: {prompt_file}"
        except OSError:
            file_note = ""

        # Mantém o cabeçalho 2-Gate compacto na CLI e envia o SKILL completo via stdin
        header_part = system_prompt.split("\n---\n", 1)[0].strip()
        cli_prompt = (
            f"{header_part[:4000]}\n\n"
            f"As instruções completas da Skill Salutem foram anexadas no início do prompt de entrada. "
            f"{file_note}"
        ).strip()
        return cli_prompt, system_prompt

    def build_command(
        self,
        executable: str,
        request: HarnessRunRequest,
        system_prompt: str,
        *,
        mcp_config_path: Path | None = None,
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
        if self._dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        elif not request.gate_authorized:
            cmd.extend(["--permission-mode", "plan"])
        if mcp_config_path is not None:
            cmd.extend(["--mcp-config", str(mcp_config_path.resolve())])
        if request.resume_session_id:
            cmd.extend(["--resume", request.resume_session_id])
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

        if ev_type == "system" and obj.get("session_id"):
            state["session_id"] = obj.get("session_id")
            return events

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
        mcp_config_path = self.ensure_workspace_mcp_config(request.workspace_dir)
        cli_system_prompt, stdin_system_prefix = self._prepare_system_prompt(
            request.workspace_dir, system_prompt
        )
        effective_stdin = (
            f"{stdin_system_prefix}\n\n---\n\n{user_prompt}"
            if stdin_system_prefix is not None
            else user_prompt
        )
        cmd = self.build_command(
            exe,
            request,
            cli_system_prompt,
            mcp_config_path=mcp_config_path,
        )
        state: dict[str, Any] = {
            "had_error": False,
            "emitted_assistant_text": False,
            "started_tools": {},
            "completed_tools": set(),
        }
        stderr_lines: list[str] = []

        try:
            async for chunk in self._exec_lines(
                cmd,
                cwd=request.workspace_dir,
                stdin_data=effective_stdin.encode("utf-8"),
                timeout_seconds=request.timeout_seconds,
            ):
                if chunk.stream == "stdout":
                    for ev in self.parse_ndjson_line(chunk.line, state):
                        if ev.type == EventType.TOOL_CALL and ev.tool_call_id:
                            state["started_tools"][ev.tool_call_id] = ev.tool_name or "tool"
                        elif ev.type == EventType.TOOL_RESULT and ev.tool_call_id:
                            state["completed_tools"].add(ev.tool_call_id)
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

            unfinished = [
                (cid, name)
                for cid, name in state["started_tools"].items()
                if cid not in state["completed_tools"]
            ]
            if not state.get("had_error") and unfinished and not state.get("emitted_assistant_text"):
                state["had_error"] = True
                for cid, name in unfinished:
                    err_text = "Ferramenta interrompida antes de retornar resultado no Claude Code CLI."
                    yield HarnessEvent(
                        type=EventType.TOOL_RESULT,
                        tool_name=name,
                        tool_call_id=cid,
                        tool_output=err_text,
                        harness=self.kind,
                        metadata={"error": err_text, "interrupted": True},
                    )
                yield HarnessEvent(
                    type=EventType.ERROR,
                    content=(
                        "O Claude Code CLI encerrou antes de concluir as ferramentas pendentes "
                        f"({', '.join(name for _, name in unfinished)})."
                    ),
                    harness=self.kind,
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
