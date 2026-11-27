# -*- coding: utf-8 -*-
"""Tests for read-only DB MCP tools (`list_db_tables`, `describe_db_table`, `preview_db_select`) and `manutencao_relatorio` skill."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.mcp_tools import (
    STUDIO_TOOL_DEFINITIONS,
    StudioMcpServer,
    describe_db_table,
    get_salutem_skill,
    list_db_tables,
    preview_db_select,
)
from backend.app.services.postgres_service import (
    DbProfileCreate,
    DbProfileValidationError,
    PostgresService,
)
from backend.app.services.workspace_service import WorkspaceService


class FakeDbCursor:
    def __init__(self, conn: FakeDbConn) -> None:
        self.conn = conn
        self.description: list[Any] = []
        self._rows: list[Any] = []

    def __enter__(self) -> FakeDbCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.executed.append((sql.strip(), params))
        low = sql.strip().lower()
        if "from information_schema.tables" in low:
            self._rows = [
                ("public", "internacao", "BASE TABLE", 420),
                ("public", "paciente", "BASE TABLE", 8500),
            ]
        elif "from information_schema.columns" in low:
            self._rows = [
                ("id", "bigint", "int8", "NO", None),
                ("leito", "character varying", "varchar", "YES", None),
            ]
        elif "tc.constraint_type = 'primary key'" in low:
            self._rows = [("id",)]
        elif "tc.constraint_type = 'foreign key'" in low:
            self._rows = []
        elif "_studio_preview" in low:
            self.description = [
                SimpleNamespace(name="id", type_code=20, null_ok=False),
                SimpleNamespace(name="leito", type_code=1043, null_ok=True),
            ]
            # 30 synthetic rows to verify hard cap at 20
            self._rows = [(idx, f"LEITO-{idx:02d}") for idx in range(1, 31)]

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchmany(self, size: int) -> list[Any]:
        return list(self._rows[:size])


class FakeDbConn:
    def __init__(self, dbname: str) -> None:
        self.dbname = dbname
        self.executed: list[tuple[str, Any]] = []
        self.rolled_back = False

    def cursor(self) -> FakeDbCursor:
        return FakeDbCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        return None


@pytest.fixture
def db_mcp_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[WorkspaceService, PostgresService, str, str, list[FakeDbConn]]:
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-mcp-db-key-32-chars-minimum-ok!")
    store = SQLiteStore(db_path=data_dir / "studio.db")
    ws = WorkspaceService(store=store, data_dir=data_dir)
    opened: list[FakeDbConn] = []

    def _factory(**kwargs: Any) -> FakeDbConn:
        conn = FakeDbConn(dbname=str(kwargs.get("dbname", "")))
        opened.append(conn)
        return conn

    pg = PostgresService(
        store=store,
        connection_factory=_factory,
        vault_path=data_dir / ".vault.json",
    )
    default_prof = pg.create_profile(
        DbProfileCreate(
            name="Default PG",
            host="127.0.0.1",
            port=5432,
            dbname="db_default",
            user="ro_user",
            password="pw",
            read_only=True,
            is_default=True,
        )
    )
    project_prof = pg.create_profile(
        DbProfileCreate(
            name="Hospitalar PG",
            host="127.0.0.1",
            port=5432,
            dbname="db_hospitalar",
            user="ro_hosp",
            password="pw2",
            read_only=True,
            is_default=False,
        )
    )
    return ws, pg, default_prof.id, project_prof.id, opened


def test_db_tools_resolve_profile_directly_via_project_and_via_default(
    db_mcp_env: tuple[WorkspaceService, PostgresService, str, str, list[FakeDbConn]],
) -> None:
    ws, pg, default_prof_id, project_prof_id, opened = db_mcp_env
    proj = ws.create_project(
        ProjectCreate(
            name="Relatório Internações",
            project_kind="free_report",
            entry_mode="blank_report",
            default_db_profile_id=project_prof_id,
        )
    )

    # 1. Explicit profile_id
    res_explicit = list_db_tables(
        profile_id=default_prof_id,
        postgres_service=pg,
        workspace_service=ws,
    )
    assert res_explicit["ok"] is True
    assert res_explicit["profile_id"] == default_prof_id
    assert res_explicit["count"] == 2
    assert opened[-1].dbname == "db_default"

    # 2. Via project.default_db_profile_id
    res_project = describe_db_table(
        table="internacao",
        project_id=proj.id,
        postgres_service=pg,
        workspace_service=ws,
    )
    assert res_project["ok"] is True
    assert res_project["profile_id"] == project_prof_id
    assert res_project["primary_keys"] == ["id"]
    assert opened[-1].dbname == "db_hospitalar"

    # 3. Fallback to default PG profile when neither profile_id nor project_id provided
    res_default = list_db_tables(postgres_service=pg, workspace_service=ws)
    assert res_default["profile_id"] == default_prof_id
    assert opened[-1].dbname == "db_default"


def test_preview_db_select_hard_caps_at_20_rows_and_blocks_dml(
    db_mcp_env: tuple[WorkspaceService, PostgresService, str, str, list[FakeDbConn]],
) -> None:
    ws, pg, default_prof_id, _, opened = db_mcp_env

    res = preview_db_select(
        sql_select="SELECT id, leito FROM internacao",
        limit=100,
        profile_id=default_prof_id,
        postgres_service=pg,
        workspace_service=ws,
    )
    assert res["ok"] is True
    assert res["limit"] == 20
    assert res["row_count"] == 20
    assert res["truncated"] is True
    assert opened[-1].rolled_back is True

    with pytest.raises(DbProfileValidationError):
        preview_db_select(
            sql_select="UPDATE internacao SET leito = 'X'",
            profile_id=default_prof_id,
            postgres_service=pg,
            workspace_service=ws,
        )


def test_db_tools_mcp_annotations_and_server_dispatch(
    db_mcp_env: tuple[WorkspaceService, PostgresService, str, str, list[FakeDbConn]],
) -> None:
    ws, pg, default_prof_id, _, _ = db_mcp_env
    by_name = {d["name"]: d for d in STUDIO_TOOL_DEFINITIONS}

    for tool_name in ("list_db_tables", "describe_db_table", "preview_db_select"):
        assert tool_name in by_name
        assert by_name[tool_name]["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }

    # Skill registration
    skill = get_salutem_skill("manutencao_relatorio")
    assert skill["skill_name"] == "manutencao_relatorio"
    assert "list_db_tables" in skill["content"]
    assert "preview_db_select" in skill["content"]
    assert get_salutem_skill("free_report")["skill_name"] == "manutencao_relatorio"

    # End-to-end JSON-RPC call through StudioMcpServer
    server = StudioMcpServer(workspace_service=ws, postgres_service=pg)
    resp = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "preview_db_select",
                "arguments": {
                    "profile_id": default_prof_id,
                    "sql_select": "SELECT id, leito FROM internacao",
                    "limit": 5,
                },
            },
        }
    )
    assert resp is not None
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["row_count"] == 5
