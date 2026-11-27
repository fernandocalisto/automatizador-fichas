# -*- coding: utf-8 -*-
"""Read-only PostgreSQL introspection MCP tools for AI agents (`backend/app/mcp_tools/db_tools.py`)."""

from __future__ import annotations

from typing import Any

try:
    from backend.app.services.pg_schema_inspector import PgSchemaInspector
    from backend.app.services.postgres_service import PostgresService
    from backend.app.services.workspace_service import WorkspaceService
except ModuleNotFoundError:  # pragma: no cover
    from app.services.pg_schema_inspector import PgSchemaInspector  # type: ignore[no-redef]
    from app.services.postgres_service import PostgresService  # type: ignore[no-redef]
    from app.services.workspace_service import WorkspaceService  # type: ignore[no-redef]

MAX_MCP_PREVIEW_ROWS = 20
MAX_MCP_TABLES_LIMIT = 200

READONLY_MCP_ANNOTATIONS: dict[str, bool] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _resolve_db_profile_id(
    *,
    profile_id: str | None,
    project_id: str | None,
    postgres_service: PostgresService,
    workspace_service: WorkspaceService | None = None,
) -> str:
    """
    Resolve PostgreSQL profile ID in priority order:
    1. Explicit `profile_id`
    2. `project.default_db_profile_id` when `project_id` is supplied
    3. Default profile (`is_default=True`) or first configured profile in `PostgresService`
    """
    if profile_id and str(profile_id).strip():
        return str(profile_id).strip()

    if project_id and str(project_id).strip():
        ws = workspace_service or WorkspaceService(store=postgres_service.store)
        project = ws.get_project(str(project_id).strip())
        if project.default_db_profile_id:
            return project.default_db_profile_id

    profiles = postgres_service.list_profiles()
    if not profiles:
        raise ValueError(
            "Nenhum perfil PostgreSQL configurado. Cadastre uma conexão em Configurações antes de inspecionar o banco."
        )
    for prof in profiles:
        if prof.is_default:
            return prof.id
    return profiles[0].id


def list_db_tables(
    profile_id: str | None = None,
    project_id: str | None = None,
    schema: str = "public",
    search: str = "",
    limit: int = 50,
    *,
    postgres_service: PostgresService | None = None,
    workspace_service: WorkspaceService | None = None,
) -> dict[str, Any]:
    """Lista tabelas e views de um schema PostgreSQL em modo estritamente READ ONLY."""
    pg = postgres_service or PostgresService()
    resolved_profile_id = _resolve_db_profile_id(
        profile_id=profile_id,
        project_id=project_id,
        postgres_service=pg,
        workspace_service=workspace_service,
    )
    clamped_limit = max(1, min(int(limit or 50), MAX_MCP_TABLES_LIMIT))
    inspector = PgSchemaInspector(pg)
    tables = inspector.list_tables(
        resolved_profile_id,
        schema=schema or "public",
        search=search or None,
        limit=clamped_limit,
    )
    return {
        "ok": True,
        "profile_id": resolved_profile_id,
        "schema": (schema or "public").strip() or "public",
        "count": len(tables),
        "tables": [t.model_dump() for t in tables],
    }


def describe_db_table(
    table: str,
    schema: str = "public",
    profile_id: str | None = None,
    project_id: str | None = None,
    *,
    postgres_service: PostgresService | None = None,
    workspace_service: WorkspaceService | None = None,
) -> dict[str, Any]:
    """Descreve colunas, tipos PostgreSQL, classes Java, PKs e FKs de uma tabela/view (READ ONLY)."""
    pg = postgres_service or PostgresService()
    resolved_profile_id = _resolve_db_profile_id(
        profile_id=profile_id,
        project_id=project_id,
        postgres_service=pg,
        workspace_service=workspace_service,
    )
    inspector = PgSchemaInspector(pg)
    detail = inspector.describe_table(
        resolved_profile_id,
        schema=schema or "public",
        table=table,
    )
    return {
        "ok": True,
        "profile_id": resolved_profile_id,
        **detail.model_dump(),
    }


def preview_db_select(
    sql_select: str,
    params: dict[str, Any] | None = None,
    limit: int = 10,
    profile_id: str | None = None,
    project_id: str | None = None,
    *,
    postgres_service: PostgresService | None = None,
    workspace_service: WorkspaceService | None = None,
) -> dict[str, Any]:
    """
    Executa uma consulta SELECT estritamente READ ONLY com teto rígido de 20 linhas,
    `statement_timeout = 10s` e `ROLLBACK` incondicional, retornando colunas e linhas de amostra.
    """
    pg = postgres_service or PostgresService()
    resolved_profile_id = _resolve_db_profile_id(
        profile_id=profile_id,
        project_id=project_id,
        postgres_service=pg,
        workspace_service=workspace_service,
    )
    clamped_limit = max(1, min(int(limit or 10), MAX_MCP_PREVIEW_ROWS))
    inspector = PgSchemaInspector(pg)
    result = inspector.preview_select_query(
        resolved_profile_id,
        sql_select,
        params=params,
        limit=clamped_limit,
    )
    return result.model_dump()


DB_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_db_tables",
        "description": (
            "Lista tabelas e views de um schema PostgreSQL (com contagem estimada de linhas) "
            "em transação estritamente READ ONLY. Resolve o perfil via `profile_id`, "
            "`project_id` (`default_db_profile_id`) ou perfil PostgreSQL padrão."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "string",
                    "description": "ID opcional do perfil PostgreSQL.",
                },
                "project_id": {
                    "type": "string",
                    "description": "ID opcional do projeto para usar seu `default_db_profile_id`.",
                },
                "schema": {
                    "type": "string",
                    "default": "public",
                    "description": "Nome do schema PostgreSQL (padrão: 'public').",
                },
                "search": {
                    "type": "string",
                    "default": "",
                    "description": "Filtro opcional por substring (case-insensitive) no nome da tabela.",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "minimum": 1,
                    "maximum": MAX_MCP_TABLES_LIMIT,
                    "description": "Número máximo de tabelas retornadas (padrão: 50, máximo: 200).",
                },
            },
            "additionalProperties": False,
        },
        "annotations": dict(READONLY_MCP_ANNOTATIONS),
    },
    {
        "name": "describe_db_table",
        "description": (
            "Inspeciona a estrutura de uma tabela ou view PostgreSQL (colunas, tipos PG, "
            "classes Java equivalentes para JRXML, chaves primárias e chaves estrangeiras) "
            "em transação estritamente READ ONLY."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Nome da tabela ou view (pode incluir prefixo 'schema.tabela').",
                },
                "schema": {
                    "type": "string",
                    "default": "public",
                    "description": "Schema da tabela (padrão: 'public').",
                },
                "profile_id": {
                    "type": "string",
                    "description": "ID opcional do perfil PostgreSQL.",
                },
                "project_id": {
                    "type": "string",
                    "description": "ID opcional do projeto para resolver `default_db_profile_id`.",
                },
            },
            "required": ["table"],
            "additionalProperties": False,
        },
        "annotations": dict(READONLY_MCP_ANNOTATIONS),
    },
    {
        "name": "preview_db_select",
        "description": (
            "Executa uma consulta SELECT/WITH em transação estritamente READ ONLY com "
            "timeout de 10s, ROLLBACK incondicional e teto máximo de 20 linhas, suportando "
            "parâmetros Jasper ($P{nome} / ${nome}) para validar queries e tipos de colunas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql_select": {
                    "type": "string",
                    "description": "Consulta SQL SELECT ou WITH (apenas leitura; DML/DDL são bloqueados).",
                },
                "params": {
                    "type": "object",
                    "description": "Mapa opcional de valores para substituir parâmetros $P{...} / ${...}.",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": MAX_MCP_PREVIEW_ROWS,
                    "description": "Quantidade máxima de linhas retornadas (padrão: 10, máximo: 20).",
                },
                "profile_id": {
                    "type": "string",
                    "description": "ID opcional do perfil PostgreSQL.",
                },
                "project_id": {
                    "type": "string",
                    "description": "ID opcional do projeto para resolver `default_db_profile_id`.",
                },
            },
            "required": ["sql_select"],
            "additionalProperties": False,
        },
        "annotations": dict(READONLY_MCP_ANNOTATIONS),
    },
]

DB_TOOL_HANDLERS = {
    "list_db_tables": list_db_tables,
    "describe_db_table": describe_db_table,
    "preview_db_select": preview_db_select,
}

__all__ = [
    "DB_TOOL_DEFINITIONS",
    "DB_TOOL_HANDLERS",
    "MAX_MCP_PREVIEW_ROWS",
    "READONLY_MCP_ANNOTATIONS",
    "describe_db_table",
    "list_db_tables",
    "preview_db_select",
]
