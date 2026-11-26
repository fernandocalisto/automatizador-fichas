# -*- coding: utf-8 -*-
"""Adaptador Google Antigravity (AGY) com suporte primário ao Python SDK e fallback CLI."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from app.harnesses.base import BaseSubprocessHarness, SubprocessRunner
from app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)


class AgyHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do Google Antigravity (`agy`).

    Modo primário: `google-antigravity` Python SDK (`google.antigravity`), fazendo streaming
    concorrente de `response` (texto), `response.thoughts` (raciocínio) e `response.tool_calls`.
    Modo fallback: executável CLI `agy` (no PATH ou `%LOCALAPPDATA%/agy/bin/agy.exe` no Windows).
    """

    kind = HarnessKind.AGY
    display_name = "Google Antigravity (AGY)"

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        sdk_spec_finder: Callable[[str], Any] | None = None,
        sdk_importer: Callable[[str], ModuleType | Any] | None = None,
        local_appdata_dir: str | Path | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            runner=runner,
            which_resolver=which_resolver,
            default_timeout=default_timeout,
        )
        self._sdk_spec_finder = sdk_spec_finder or importlib.util.find_spec
        self._sdk_importer = sdk_importer or importlib.import_module
        self._local_appdata_dir = local_appdata_dir

    def is_sdk_available(self) -> bool:
        """Verifica dinamicamente se o pacote `google.antigravity` está instalado."""
        try:
            return self._sdk_spec_finder("google.antigravity") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _candidate_windows_paths(self) -> list[Path]:
        raw_appdata = (
            str(self._local_appdata_dir)
            if self._local_appdata_dir is not None
            else os.environ.get("LOCALAPPDATA", "")
        )
        if not raw_appdata:
            return []
        base = Path(raw_appdata)
        return [
            base / "agy" / "bin" / "agy.exe",
            base / "Programs" / "Antigravity" / "bin" / "agy.exe",
        ]

    def _find_cli_executable(self) -> str | None:
        return self._resolve_executable("agy", fallback_paths=self._candidate_windows_paths())

    def check_status(self) -> HarnessStatus:
        sdk_ok = self.is_sdk_available()
        exe = self._find_cli_executable()
        version = self._probe_version(exe) if exe else None

        if version is None and sdk_ok:
            try:
                mod = self._sdk_importer("google.antigravity")
                version = getattr(mod, "__version__", None) or "sdk"
            except Exception:
                version = "sdk"

        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=bool(sdk_ok or exe),
            executable_path=exe,
            sdk_available=sdk_ok,
            version=version,
            auth_hint="Execute 'agy' no terminal para autenticar ou instale 'pip install google-antigravity'.",
            supports_vision=True,
            supports_mcp=True,
        )

    async def _stream_via_sdk(
        self,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Executa o turno usando `Agent`, `LocalAgentConfig` e `CapabilitiesConfig` do SDK."""
        mod = self._sdk_importer("google.antigravity")
        agent_cls = getattr(mod, "Agent")
        config_cls = getattr(mod, "LocalAgentConfig")
        caps_cls = getattr(mod, "CapabilitiesConfig")

        cfg_kwargs: dict[str, Any] = {
            "system_instructions": system_prompt,
            "capabilities": caps_cls(),
        }
        try:
            sig = inspect.signature(config_cls)
            params = sig.parameters
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if request.model and ("model" in params or accepts_var_kw):
                cfg_kwargs["model"] = request.model
            if "cwd" in params:
                cfg_kwargs["cwd"] = str(request.workspace_dir.resolve())
            elif "workspace_dir" in params:
                cfg_kwargs["workspace_dir"] = str(request.workspace_dir.resolve())
        except (TypeError, ValueError):
            pass

        config = config_cls(**cfg_kwargs)

        async with asyncio.timeout(request.timeout_seconds):
            async with agent_cls(config) as agent:
                response = await agent.chat(user_prompt)

                queue: asyncio.Queue[HarnessEvent | BaseException | None] = asyncio.Queue()

                async def _consume_tokens() -> None:
                    try:
                        async for token in response:
                            if token:
                                await queue.put(
                                    HarnessEvent(
                                        type=EventType.TEXT_DELTA,
                                        content=str(token),
                                        harness=self.kind,
                                    )
                                )
                    except BaseException as exc:
                        await queue.put(exc)

                async def _consume_thoughts() -> None:
                    thoughts_iter = getattr(response, "thoughts", None)
                    if thoughts_iter is None:
                        return
                    try:
                        async for thought in thoughts_iter:
                            if thought:
                                await queue.put(
                                    HarnessEvent(
                                        type=EventType.THOUGHT_DELTA,
                                        content=str(thought),
                                        harness=self.kind,
                                    )
                                )
                    except BaseException as exc:
                        await queue.put(exc)

                async def _consume_tool_calls() -> None:
                    calls_iter = getattr(response, "tool_calls", None)
                    if calls_iter is None:
                        return
                    try:
                        async for call in calls_iter:
                            raw_args = getattr(call, "args", None)
                            tool_args = (
                                dict(raw_args)
                                if isinstance(raw_args, dict)
                                else ({"value": raw_args} if raw_args is not None else {})
                            )
                            await queue.put(
                                HarnessEvent(
                                    type=EventType.TOOL_CALL,
                                    tool_name=str(getattr(call, "name", "tool")),
                                    tool_call_id=getattr(call, "id", None),
                                    tool_args=tool_args,
                                    harness=self.kind,
                                )
                            )
                    except BaseException as exc:
                        await queue.put(exc)

                tasks = [
                    asyncio.create_task(_consume_thoughts()),
                    asyncio.create_task(_consume_tool_calls()),
                    asyncio.create_task(_consume_tokens()),
                ]

                async def _join_streams() -> None:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await queue.put(None)

                join_task = asyncio.create_task(_join_streams())
                try:
                    while True:
                        item = await queue.get()
                        if item is None:
                            break
                        if isinstance(item, BaseException):
                            raise item
                        yield item
                finally:
                    for t in (*tasks, join_task):
                        if not t.done():
                            t.cancel()

        gate_ev = self._make_gate_event_if_needed(request)
        if gate_ev is not None:
            yield gate_ev
        yield HarnessEvent(
            type=EventType.DONE,
            harness=self.kind,
            metadata={"mode": "sdk"},
        )

    def build_cli_command(
        self,
        executable: str,
        request: HarnessRunRequest,
    ) -> list[str]:
        """Constrói o comando oficial headless/streaming do `agy` CLI (`--input-format stream-json`)."""
        cmd: list[str] = [
            executable,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--add-dir",
            str(request.workspace_dir.resolve()),
            "--mode",
            "accept-edits" if request.gate_authorized else "plan",
        ]
        if request.model:
            cmd.extend(["--model", request.model])
        if request.timeout_seconds and request.timeout_seconds > 0:
            cmd.extend(["--print-timeout", f"{max(1, int(request.timeout_seconds))}s"])
        return cmd

    def _parse_cli_line(
        self,
        line: str,
        state: dict[str, Any] | None = None,
    ) -> list[HarnessEvent]:
        """
        Converte uma linha stdout do `agy` CLI em `HarnessEvent`s normalizados.

        Suporta:
        1. Protocolo oficial `agy --output-format stream-json` (`init`, `step_update`, `result`);
        2. Envelopes JSON simples (`{"type": "text"|"thought"|"tool_call"|"tool_result"|"error"}`);
        3. Fallback de texto plano.
        """
        stripped = line.strip()
        if not stripped:
            return []

        if state is None:
            state = {}
        emitted_tool_steps: set[str] = state.setdefault("emitted_tool_steps", set())

        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                obj = None

            if isinstance(obj, dict):
                # 1) Formato oficial agy --output-format stream-json
                event_name = obj.get("event")
                if isinstance(event_name, str):
                    if event_name == "init":
                        conv_id = obj.get("conversation_id")
                        if conv_id:
                            state["conversation_id"] = str(conv_id)
                        return []

                    if event_name == "step_update":
                        su = obj.get("step_update")
                        if not isinstance(su, dict):
                            return []
                        if su.get("conversation_id"):
                            state["conversation_id"] = str(su["conversation_id"])

                        step_type = str(su.get("step_type") or "")
                        step_state = str(su.get("state") or "")
                        step_index = su.get("step_index")
                        call_id = (
                            f"agy-step-{step_index}"
                            if step_index is not None
                            else str(su.get("id") or "agy-step")
                        )
                        events: list[HarnessEvent] = []

                        # Pensamento / raciocínio incremental
                        thought_val = su.get("thought_delta") or su.get("thinking_delta")
                        if thought_val:
                            events.append(
                                HarnessEvent(
                                    type=EventType.THOUGHT_DELTA,
                                    content=str(thought_val),
                                    harness=self.kind,
                                )
                            )
                        elif step_type in ("thinking", "thought") and su.get("text_delta"):
                            events.append(
                                HarnessEvent(
                                    type=EventType.THOUGHT_DELTA,
                                    content=str(su["text_delta"]),
                                    harness=self.kind,
                                )
                            )

                        # Texto de resposta do agente
                        if step_type == "agent_response" and su.get("text_delta"):
                            state["emitted_text"] = True
                            events.append(
                                HarnessEvent(
                                    type=EventType.TEXT_DELTA,
                                    content=str(su["text_delta"]),
                                    harness=self.kind,
                                )
                            )

                        # Chamadas e resultados de ferramenta
                        if step_type in ("tool", "tool_call", "tool_use"):
                            tool_info = su.get("tool_info")
                            info = tool_info if isinstance(tool_info, dict) else {}
                            tool_name = str(
                                info.get("name") or su.get("tool_name") or "tool"
                            )
                            params = info.get("parameters")
                            tool_args = (
                                dict(params)
                                if isinstance(params, dict)
                                else ({"value": params} if params is not None else {})
                            )

                            if call_id not in emitted_tool_steps:
                                emitted_tool_steps.add(call_id)
                                events.append(
                                    HarnessEvent(
                                        type=EventType.TOOL_CALL,
                                        tool_name=tool_name,
                                        tool_call_id=call_id,
                                        tool_args=tool_args,
                                        harness=self.kind,
                                    )
                                )

                            if step_state == "DONE" and (
                                "output" in info or "error" in info
                            ):
                                tool_err = info.get("error")
                                tool_out = (
                                    info.get("output")
                                    if "output" in info
                                    else tool_err
                                )
                                res_meta: dict[str, Any] = {}
                                if tool_err is not None:
                                    res_meta["error"] = (
                                        tool_err.get("message")
                                        if isinstance(tool_err, dict)
                                        else str(tool_err)
                                    )
                                events.append(
                                    HarnessEvent(
                                        type=EventType.TOOL_RESULT,
                                        tool_name=tool_name,
                                        tool_call_id=call_id,
                                        tool_output=tool_out,
                                        harness=self.kind,
                                        metadata=res_meta,
                                    )
                                )

                        return events

                    if event_name == "result":
                        res = obj.get("result")
                        if not isinstance(res, dict):
                            return []
                        if res.get("conversation_id"):
                            state["conversation_id"] = str(res["conversation_id"])
                        if isinstance(res.get("usage"), dict):
                            state["usage"] = dict(res["usage"])

                        status_val = str(res.get("status") or "SUCCESS").upper()
                        if status_val != "SUCCESS":
                            err_msg = str(
                                res.get("error")
                                or f"AGY CLI encerrou com status {status_val}."
                            )
                            return [
                                HarnessEvent(
                                    type=EventType.ERROR,
                                    content=err_msg,
                                    harness=self.kind,
                                    metadata={"status": status_val},
                                )
                            ]

                        response_text = res.get("response")
                        if response_text and not state.get("emitted_text"):
                            state["emitted_text"] = True
                            return [
                                HarnessEvent(
                                    type=EventType.TEXT_DELTA,
                                    content=str(response_text),
                                    harness=self.kind,
                                )
                            ]
                        return []

                # 2) Formato JSON flat (retrocompatibilidade / adapters auxiliares)
                if "type" in obj:
                    ev_type = str(obj["type"])
                    if ev_type in ("text", "text_delta", "message"):
                        state["emitted_text"] = True
                        return [
                            HarnessEvent(
                                type=EventType.TEXT_DELTA,
                                content=str(obj.get("content") or obj.get("text") or ""),
                                harness=self.kind,
                            )
                        ]
                    if ev_type in ("thought", "thought_delta", "thinking", "reasoning"):
                        return [
                            HarnessEvent(
                                type=EventType.THOUGHT_DELTA,
                                content=str(obj.get("content") or obj.get("text") or ""),
                                harness=self.kind,
                            )
                        ]
                    if ev_type in ("tool_call", "tool_use"):
                        return [
                            HarnessEvent(
                                type=EventType.TOOL_CALL,
                                tool_name=str(obj.get("name") or obj.get("tool_name") or "tool"),
                                tool_call_id=obj.get("id"),
                                tool_args=obj.get("args") or obj.get("input") or {},
                                harness=self.kind,
                            )
                        ]
                    if ev_type == "tool_result":
                        return [
                            HarnessEvent(
                                type=EventType.TOOL_RESULT,
                                tool_name=obj.get("name") or obj.get("tool_name"),
                                tool_call_id=obj.get("id"),
                                tool_output=obj.get("output") or obj.get("content"),
                                harness=self.kind,
                            )
                        ]
                    if ev_type == "error":
                        return [
                            HarnessEvent(
                                type=EventType.ERROR,
                                content=str(obj.get("message") or obj.get("content") or "Erro AGY CLI"),
                                harness=self.kind,
                            )
                        ]

        return [
            HarnessEvent(
                type=EventType.TEXT_DELTA,
                content=line + "\n",
                harness=self.kind,
            )
        ]

    async def _stream_via_cli(
        self,
        executable: str,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Executa o turno via binário CLI `agy` em modo headless `--input-format stream-json --output-format stream-json`."""
        cmd = self.build_cli_command(executable, request)

        combined_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        stdin_envelope = (
            json.dumps(
                {"event": "user", "message": {"content": combined_prompt}},
                ensure_ascii=False,
            )
            + "\n"
        )
        stderr_lines: list[str] = []
        had_error = False
        parse_state: dict[str, Any] = {}

        async for chunk in self._exec_lines(
            cmd,
            cwd=request.workspace_dir,
            stdin_data=stdin_envelope.encode("utf-8"),
            timeout_seconds=request.timeout_seconds,
        ):
            if chunk.stream == "stdout":
                for ev in self._parse_cli_line(chunk.line, state=parse_state):
                    if ev.type == EventType.ERROR:
                        had_error = True
                    yield ev
            elif chunk.stream == "stderr":
                if chunk.line.strip():
                    stderr_lines.append(chunk.line.strip())
            elif chunk.stream == "exit":
                if chunk.returncode not in (0, None) and not had_error:
                    had_error = True
                    detail = "\n".join(stderr_lines[-10:]) or f"Código de saída {chunk.returncode}"
                    yield HarnessEvent(
                        type=EventType.ERROR,
                        content=f"Falha na execução do AGY CLI: {detail}",
                        harness=self.kind,
                        metadata={"returncode": chunk.returncode},
                    )

        if not had_error:
            gate_ev = self._make_gate_event_if_needed(request)
            if gate_ev is not None:
                yield gate_ev
            done_meta: dict[str, Any] = {"mode": "cli"}
            if parse_state.get("conversation_id"):
                done_meta["conversation_id"] = parse_state["conversation_id"]
            if parse_state.get("usage"):
                done_meta["usage"] = parse_state["usage"]
            yield HarnessEvent(
                type=EventType.DONE,
                harness=self.kind,
                metadata=done_meta,
            )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        system_prompt, user_prompt = self._build_prompts(request)

        try:
            if self.is_sdk_available():
                async for ev in self._stream_via_sdk(request, system_prompt, user_prompt):
                    yield ev
                return

            exe = self._find_cli_executable()
            if exe:
                async for ev in self._stream_via_cli(exe, request, system_prompt, user_prompt):
                    yield ev
                return

            yield HarnessEvent(
                type=EventType.ERROR,
                content=(
                    "Google Antigravity (AGY) indisponível: instale o SDK "
                    "'pip install google-antigravity' ou adicione o CLI 'agy' ao PATH."
                ),
                harness=self.kind,
            )
        except TimeoutError:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Tempo limite excedido ({request.timeout_seconds}s) no Google Antigravity.",
                harness=self.kind,
            )
        except Exception as exc:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Erro inesperado no AGY Harness: {exc}",
                harness=self.kind,
            )
