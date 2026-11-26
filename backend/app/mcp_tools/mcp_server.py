# -*- coding: utf-8 -*-
"""
Servidor MCP Stdio JSON-RPC 2.0 leve (zero dependências externas) do Salutem Ficha Studio.

Executável diretamente via:
    python -m backend.app.mcp_tools.mcp_server

Métodos JSON-RPC 2.0 suportados:
- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call`
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .studio_tools import (
    STUDIO_TOOL_DEFINITIONS,
    STUDIO_TOOL_HANDLERS,
    dispatch_studio_tool,
)

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "salutem-ficha-studio-mcp"
SERVER_VERSION = "1.0.0"

# Códigos padrão JSON-RPC 2.0
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


class StudioMcpServer:
    """Servidor MCP JSON-RPC 2.0 sobre stdio para expor as ferramentas do Salutem Ficha Studio."""

    def __init__(
        self,
        *,
        tool_definitions: list[dict[str, Any]] | None = None,
        tool_dispatcher: Callable[[str, dict[str, Any] | None], dict[str, Any]] | None = None,
        workspace_service: Any | None = None,
        subreport_service: Any | None = None,
        jasper_daemon: Any | None = None,
        postgres_service: Any | None = None,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
        protocol_version: str = MCP_PROTOCOL_VERSION,
    ) -> None:
        self.tool_definitions = (
            list(tool_definitions)
            if tool_definitions is not None
            else list(STUDIO_TOOL_DEFINITIONS)
        )
        self._custom_dispatcher = tool_dispatcher
        self._injected_services: dict[str, Any] = {
            k: v
            for k, v in {
                "workspace_service": workspace_service,
                "subreport_service": subreport_service,
                "jasper_daemon": jasper_daemon,
                "postgres_service": postgres_service,
            }.items()
            if v is not None
        }
        self.server_name = server_name
        self.server_version = server_version
        self.protocol_version = protocol_version
        self.initialized = False

    @staticmethod
    def _ok_response(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    @staticmethod
    def _error_response(
        req_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": err,
        }

    def _dispatch_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._custom_dispatcher is not None:
            return self._custom_dispatcher(tool_name, arguments)

        call_args = dict(arguments)
        handler = STUDIO_TOOL_HANDLERS.get(tool_name)
        if handler is not None and self._injected_services:
            sig = inspect.signature(handler)
            for svc_name, svc_inst in self._injected_services.items():
                if svc_name in sig.parameters and svc_name not in call_args:
                    call_args[svc_name] = svc_inst

        return dispatch_studio_tool(tool_name, call_args)

    def handle_message(self, payload: Any) -> dict[str, Any] | None:
        """
        Processa uma única mensagem JSON-RPC 2.0 decodificada.
        Retorna `None` para notificações (mensagens sem `id`).
        """
        if not isinstance(payload, dict):
            return self._error_response(
                None,
                JSONRPC_INVALID_REQUEST,
                "Requisição JSON-RPC inválida: esperado objeto JSON.",
            )

        req_id = payload.get("id")
        is_notification = "id" not in payload
        jsonrpc_ver = payload.get("jsonrpc")
        method = payload.get("method")
        params = payload.get("params")

        if jsonrpc_ver != "2.0" or not isinstance(method, str) or not method.strip():
            if is_notification:
                return None
            return self._error_response(
                req_id,
                JSONRPC_INVALID_REQUEST,
                "Requisição JSON-RPC 2.0 inválida: 'jsonrpc' deve ser '2.0' e 'method' deve ser string.",
            )

        if method == "notifications/initialized":
            self.initialized = True
            return None

        if method.startswith("notifications/") and is_notification:
            return None

        if method == "initialize":
            return self._ok_response(
                req_id,
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                },
            )

        if method == "ping":
            return self._ok_response(req_id, {})

        if method == "tools/list":
            return self._ok_response(
                req_id,
                {"tools": list(self.tool_definitions)},
            )

        if method == "tools/call":
            if not isinstance(params, dict):
                return self._error_response(
                    req_id,
                    JSONRPC_INVALID_PARAMS,
                    "Parâmetros inválidos para 'tools/call': esperado objeto com 'name' e 'arguments'.",
                )
            tool_name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(tool_name, str) or not tool_name.strip():
                return self._error_response(
                    req_id,
                    JSONRPC_INVALID_PARAMS,
                    "Parâmetro obrigatório 'name' ausente ou inválido em 'tools/call'.",
                )
            if arguments is None:
                arguments = {}
            elif not isinstance(arguments, dict):
                return self._error_response(
                    req_id,
                    JSONRPC_INVALID_PARAMS,
                    "Parâmetro 'arguments' em 'tools/call' deve ser um objeto JSON.",
                )

            try:
                result_data = self._dispatch_tool(tool_name.strip(), arguments)
                serialized = json.dumps(result_data, ensure_ascii=False, default=str)
                return self._ok_response(
                    req_id,
                    {
                        "content": [{"type": "text", "text": serialized}],
                        "isError": False,
                    },
                )
            except Exception as exc:
                error_payload = {
                    "ok": False,
                    "tool": tool_name.strip(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                return self._ok_response(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(error_payload, ensure_ascii=False),
                            }
                        ],
                        "isError": True,
                    },
                )

        if is_notification:
            return None

        return self._error_response(
            req_id,
            JSONRPC_METHOD_NOT_FOUND,
            f"Método JSON-RPC não suportado: '{method}'.",
        )

    def handle_raw_line(self, raw_line: str) -> str | None:
        """Decodifica uma linha JSON-RPC, processa e retorna a linha de resposta serializada (ou `None`)."""
        stripped = raw_line.strip()
        if not stripped:
            return None

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            err = self._error_response(
                None,
                JSONRPC_PARSE_ERROR,
                f"Erro ao decodificar JSON: {exc}",
            )
            return json.dumps(err, ensure_ascii=False)

        response = self.handle_message(payload)
        if response is None:
            return None
        return json.dumps(response, ensure_ascii=False)

    def serve_stdio(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        """Executa o loop stdio (uma mensagem JSON-RPC 2.0 por linha) até EOF."""
        in_stream = stdin if stdin is not None else sys.stdin
        out_stream = stdout if stdout is not None else sys.stdout

        while True:
            raw_line = in_stream.readline()
            if not raw_line:
                break
            reply = self.handle_raw_line(raw_line)
            if reply is not None:
                out_stream.write(reply + "\n")
                out_stream.flush()


def main(argv: list[str] | None = None) -> int:
    """Entrypoint CLI (`python -m backend.app.mcp_tools.mcp_server`)."""
    _ = argv
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    server = StudioMcpServer()
    server.serve_stdio()
    return 0


__all__ = [
    "JSONRPC_INTERNAL_ERROR",
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_PARSE_ERROR",
    "MCP_PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "StudioMcpServer",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
