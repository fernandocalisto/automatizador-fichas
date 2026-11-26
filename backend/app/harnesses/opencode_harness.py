# -*- coding: utf-8 -*-
"""Adaptador OpenCode suportando `opencode serve` (HTTP/SSE) e `opencode run --format json` (CLI)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from app.harnesses.base import (
    STUDIO_MCP_SERVER_NAME,
    BaseSubprocessHarness,
    SubprocessRunner,
    build_studio_mcp_server_spec,
)
from app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)


class OpenCodeHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do OpenCode (`opencode`).

    Suporta dois modos complementares:
    1. Modo Servidor HTTP/SSE (`OPENCODE_SERVER_URL`, ex.: `http://127.0.0.1:4096`) via
       `httpx.AsyncClient` criando sessão (`/session`) e transmitindo mensagem (`/session/{id}/message`).
    2. Modo CLI (`opencode run --format json`) via subprocesso assíncrono.
    """

    kind = HarnessKind.OPENCODE
    display_name = "OpenCode"

    def __init__(
        self,
        *,
        server_url: str | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            runner=runner,
            which_resolver=which_resolver,
            default_timeout=default_timeout,
        )
        self._explicit_server_url = server_url
        self._http_transport = http_transport

    def get_server_url(self) -> str | None:
        """Retorna a URL configurada para `opencode serve`, se definida."""
        raw = self._explicit_server_url or os.environ.get("OPENCODE_SERVER_URL", "")
        cleaned = raw.strip().rstrip("/")
        return cleaned or None

    def _find_cli_executable(self) -> str | None:
        return self._resolve_executable("opencode")

    def check_status(self) -> HarnessStatus:
        exe = self._find_cli_executable()
        server_url = self.get_server_url()
        version = self._probe_version(exe) if exe else (f"serve ({server_url})" if server_url else None)

        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=bool(exe or server_url),
            executable_path=exe,
            sdk_available=bool(server_url),
            version=version,
            auth_hint=(
                "Autentique provedores via 'opencode auth login' ou aponte OPENCODE_SERVER_URL "
                "para uma instância 'opencode serve' (ex.: http://127.0.0.1:4096)."
            ),
            supports_vision=True,
            supports_mcp=True,
        )

    def parse_opencode_payload(
        self,
        obj: dict[str, Any],
        state: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Normaliza eventos JSON/SSE do OpenCode (`opencode serve` ou `opencode run --format json`)."""
        events: list[HarnessEvent] = []

        # Caso 1: Resposta agregada HTTP `/session/{id}/message` contendo `parts: [...]`
        parts = obj.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    events.extend(self._convert_part(part, state))
            return events

        ev_type = str(obj.get("type") or "")

        # Caso 2: Evento SSE `message.part.updated` ou `message.part.delta`
        if ev_type in ("message.part.updated", "part.updated"):
            props = obj.get("properties") or {}
            part = props.get("part") or obj.get("part")
            delta = props.get("delta")
            if isinstance(delta, str) and delta:
                part_type = (part or {}).get("type", "text") if isinstance(part, dict) else "text"
                target_ev = (
                    EventType.THOUGHT_DELTA
                    if part_type in ("reasoning", "thought", "thinking")
                    else EventType.TEXT_DELTA
                )
                events.append(HarnessEvent(type=target_ev, content=delta, harness=self.kind))
                return events
            if isinstance(part, dict):
                events.extend(self._convert_part(part, state))
                return events

        if ev_type in ("message.part.delta", "part.delta"):
            props = obj.get("properties") or obj
            field_name = str(props.get("field") or "text")
            delta_text = str(props.get("delta") or "")
            if delta_text:
                target_ev = (
                    EventType.THOUGHT_DELTA
                    if "reason" in field_name or "thought" in field_name
                    else EventType.TEXT_DELTA
                )
                events.append(HarnessEvent(type=target_ev, content=delta_text, harness=self.kind))
            return events

        # Caso 3: Eventos JSONL do `opencode run --format json`
        part_obj = obj.get("part")
        if ev_type in ("text", "text_delta"):
            text_val = (
                part_obj.get("text", "")
                if isinstance(part_obj, dict)
                else str(obj.get("text") or obj.get("content") or "")
            )
            if text_val:
                events.append(
                    HarnessEvent(type=EventType.TEXT_DELTA, content=str(text_val), harness=self.kind)
                )
            return events

        if ev_type in ("reasoning", "thought", "thinking"):
            thought_val = (
                part_obj.get("text", "")
                if isinstance(part_obj, dict)
                else str(obj.get("text") or obj.get("content") or "")
            )
            if thought_val:
                events.append(
                    HarnessEvent(
                        type=EventType.THOUGHT_DELTA,
                        content=str(thought_val),
                        harness=self.kind,
                    )
                )
            return events

        if ev_type in ("tool_use", "tool", "tool_call"):
            if isinstance(part_obj, dict):
                events.extend(self._convert_part({**part_obj, "type": "tool"}, state))
            else:
                events.append(
                    HarnessEvent(
                        type=EventType.TOOL_CALL,
                        tool_name=str(obj.get("tool") or obj.get("name") or "tool"),
                        tool_call_id=obj.get("callID") or obj.get("id"),
                        tool_args=obj.get("input") or obj.get("args") or {},
                        harness=self.kind,
                    )
                )
            return events

        if ev_type == "tool_result":
            events.append(
                HarnessEvent(
                    type=EventType.TOOL_RESULT,
                    tool_name=obj.get("tool") or obj.get("name"),
                    tool_call_id=obj.get("callID") or obj.get("id"),
                    tool_output=obj.get("output") or obj.get("content"),
                    harness=self.kind,
                )
            )
            return events

        if ev_type in ("error", "session.error"):
            err_raw = obj.get("error") or (obj.get("properties") or {}).get("error") or obj
            if isinstance(err_raw, dict):
                msg = str(
                    (err_raw.get("data") or {}).get("message")
                    or err_raw.get("message")
                    or err_raw.get("name")
                    or "Erro reportado pelo OpenCode"
                )
            else:
                msg = str(err_raw)
            state["had_error"] = True
            events.append(HarnessEvent(type=EventType.ERROR, content=msg, harness=self.kind))

        return events

    def _convert_part(
        self,
        part: dict[str, Any],
        state: dict[str, Any],
    ) -> list[HarnessEvent]:
        out: list[HarnessEvent] = []
        p_type = str(part.get("type") or "")
        if p_type == "text":
            txt = str(part.get("text") or "")
            if txt:
                out.append(HarnessEvent(type=EventType.TEXT_DELTA, content=txt, harness=self.kind))
        elif p_type in ("reasoning", "thought", "thinking"):
            txt = str(part.get("text") or "")
            if txt:
                out.append(
                    HarnessEvent(type=EventType.THOUGHT_DELTA, content=txt, harness=self.kind)
                )
        elif p_type in ("tool", "tool_use", "tool-invocation"):
            tool_name = str(part.get("tool") or part.get("name") or "tool")
            call_id = part.get("callID") or part.get("id")
            tool_state = part.get("state") if isinstance(part.get("state"), dict) else {}
            tool_input = tool_state.get("input") or part.get("input") or {}
            emitted_calls: set[str] = state.setdefault("emitted_calls", set())

            if not call_id or call_id not in emitted_calls:
                if call_id:
                    emitted_calls.add(str(call_id))
                out.append(
                    HarnessEvent(
                        type=EventType.TOOL_CALL,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        tool_args=tool_input if isinstance(tool_input, dict) else {"value": tool_input},
                        harness=self.kind,
                    )
                )

            status = str(tool_state.get("status") or "")
            if "output" in tool_state or status in ("completed", "error"):
                output_val = tool_state.get("output")
                if output_val is None and "error" in tool_state:
                    output_val = tool_state.get("error")
                out.append(
                    HarnessEvent(
                        type=EventType.TOOL_RESULT,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        tool_output=output_val,
                        harness=self.kind,
                    )
                )
        return out

    async def _stream_via_http(
        self,
        server_url: str,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Cria sessão em `opencode serve` e consome a resposta via SSE ou JSON."""
        state: dict[str, Any] = {"had_error": False}

        async with httpx.AsyncClient(
            base_url=server_url,
            transport=self._http_transport,
            timeout=httpx.Timeout(request.timeout_seconds),
        ) as client:
            sess_resp = await client.post(
                "/session",
                json={
                    "title": f"Salutem Ficha Studio ({request.phase})",
                    "directory": str(request.workspace_dir.resolve()),
                },
            )
            sess_resp.raise_for_status()
            sess_data = sess_resp.json()
            session_id = sess_data.get("id")
            if not session_id:
                raise RuntimeError("Resposta inválida de /session no OpenCode Server (sem id).")

            parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            for img in request.image_paths:
                parts.append(
                    {
                        "type": "file",
                        "mime": "image/png",
                        "url": Path(img).resolve().as_uri(),
                        "filename": Path(img).name,
                    }
                )

            msg_body: dict[str, Any] = {
                "system": system_prompt,
                "parts": parts,
            }
            if request.model:
                if "/" in request.model:
                    provider_id, model_id = request.model.split("/", 1)
                    msg_body["model"] = {"providerID": provider_id, "modelID": model_id}
                else:
                    msg_body["modelID"] = request.model

            async with client.stream(
                "POST",
                f"/session/{session_id}/message",
                json=msg_body,
                headers={"Accept": "text/event-stream, application/json"},
            ) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").lower()

                if "text/event-stream" in content_type or "ndjson" in content_type:
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line or line.startswith(":") or line.startswith("event:"):
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(payload, dict):
                            for ev in self.parse_opencode_payload(payload, state):
                                yield ev
                else:
                    body_bytes = await resp.aread()
                    if body_bytes.strip():
                        payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
                        if isinstance(payload, dict):
                            for ev in self.parse_opencode_payload(payload, state):
                                yield ev

        if not state.get("had_error"):
            gate_ev = self._make_gate_event_if_needed(request)
            if gate_ev is not None:
                yield gate_ev
            yield HarnessEvent(
                type=EventType.DONE,
                harness=self.kind,
                metadata={"mode": "http", "session_id": session_id},
            )

    @staticmethod
    def ensure_workspace_mcp_config(
        workspace_dir: Path,
        *,
        gate_authorized: bool = False,
    ) -> Path | None:
        """
        Materializa `opencode.json` no workspace configurando o servidor MCP local do Studio
        e políticas de permissão não-interativas por Gate.
        """
        try:
            ws_root = Path(workspace_dir).resolve()
            ws_root.mkdir(parents=True, exist_ok=True)
            cfg_path = ws_root / "opencode.json"
            spec = build_studio_mcp_server_spec()
            payload = {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    STUDIO_MCP_SERVER_NAME: {
                        "type": "local",
                        "command": [spec["command"], *spec["args"]],
                        "environment": spec["env"],
                        "enabled": True,
                    }
                },
                "permission": {
                    "edit": "allow" if gate_authorized else "deny",
                    "bash": "allow",
                },
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if not cfg_path.is_file() or cfg_path.read_text(encoding="utf-8") != text:
                cfg_path.write_text(text, encoding="utf-8")
            return cfg_path
        except OSError:
            return None

    def build_cli_command(self, executable: str, request: HarnessRunRequest) -> list[str]:
        """Monta o comando `opencode run --format json`."""
        cmd = [executable, "run", "--format", "json"]
        if request.model:
            cmd.extend(["--model", request.model])
        for img in request.image_paths:
            cmd.extend(["--file", str(Path(img).resolve())])
        return cmd

    async def _stream_via_cli(
        self,
        executable: str,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        self.ensure_workspace_mcp_config(
            request.workspace_dir,
            gate_authorized=request.gate_authorized,
        )
        cmd = self.build_cli_command(executable, request)
        combined = f"{system_prompt}\n\n---\n\n{user_prompt}"
        state: dict[str, Any] = {"had_error": False}
        stderr_lines: list[str] = []

        async for chunk in self._exec_lines(
            cmd,
            cwd=request.workspace_dir,
            stdin_data=combined.encode("utf-8"),
            timeout_seconds=request.timeout_seconds,
        ):
            if chunk.stream == "stdout":
                stripped = chunk.line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    yield HarnessEvent(
                        type=EventType.TEXT_DELTA,
                        content=chunk.line + "\n",
                        harness=self.kind,
                    )
                    continue
                if isinstance(payload, dict):
                    for ev in self.parse_opencode_payload(payload, state):
                        yield ev
            elif chunk.stream == "stderr":
                if chunk.line.strip():
                    stderr_lines.append(chunk.line.strip())
            elif chunk.stream == "exit":
                if chunk.returncode not in (0, None) and not state.get("had_error"):
                    state["had_error"] = True
                    detail = "\n".join(stderr_lines[-10:]) or f"Código de saída {chunk.returncode}"
                    yield HarnessEvent(
                        type=EventType.ERROR,
                        content=f"Falha no OpenCode CLI: {detail}",
                        harness=self.kind,
                        metadata={"returncode": chunk.returncode},
                    )

        if not state.get("had_error"):
            gate_ev = self._make_gate_event_if_needed(request)
            if gate_ev is not None:
                yield gate_ev
            yield HarnessEvent(
                type=EventType.DONE,
                harness=self.kind,
                metadata={"mode": "cli"},
            )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        system_prompt, user_prompt = self._build_prompts(request)
        server_url = self.get_server_url()
        exe = self._find_cli_executable()

        try:
            if server_url:
                try:
                    async for ev in self._stream_via_http(
                        server_url, request, system_prompt, user_prompt
                    ):
                        yield ev
                    return
                except httpx.ConnectError as conn_err:
                    if not exe:
                        yield HarnessEvent(
                            type=EventType.ERROR,
                            content=(
                                f"Não foi possível conectar ao servidor OpenCode em {server_url}: "
                                f"{conn_err}"
                            ),
                            harness=self.kind,
                        )
                        return

            if exe:
                async for ev in self._stream_via_cli(exe, request, system_prompt, user_prompt):
                    yield ev
                return

            yield HarnessEvent(
                type=EventType.ERROR,
                content=(
                    "OpenCode indisponível: instale o binário 'opencode' no PATH ou defina "
                    "OPENCODE_SERVER_URL apontando para 'opencode serve'."
                ),
                harness=self.kind,
            )
        except TimeoutError:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Tempo limite excedido ({request.timeout_seconds}s) no OpenCode.",
                harness=self.kind,
            )
        except Exception as exc:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Erro inesperado no OpenCode Harness: {exc}",
                harness=self.kind,
            )
