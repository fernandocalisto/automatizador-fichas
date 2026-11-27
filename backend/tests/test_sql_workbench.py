# -*- coding: utf-8 -*-
"""Tests for PgSchemaInspector and SQL Workbench REST endpoints (`/api/db/profiles/{id}/*`)."""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import database as database_api
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.pg_schema_inspector import (
    PgSchemaInspector,
    serialize_pg_value,
    validate_and_bind_readonly_select,
)
from backend.app.services.postgres_service import (
    DbProfileCreate,
    DbProfileValidationError,
    PostgresService,
)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self.description: list[Any] = []
        self._rows: list[Any] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.executed.append((sql.strip(), params))
        low = sql.strip().lower()
        if low.startswith("set transaction read only"):
            self.conn.read_only_tx = True
            return
        if low.startswith("set local statement_timeout"):
            self.conn.statement_timeout_set = True
            return
        if self.conn.fail_on_query and "_studio_preview" in low:
            raise RuntimeError("synthetic query failure")

        if "from information_schema.schemata" in low:
            self._rows = [("public",), ("hospitalar",), ("pg_catalog",), ("ambulatorial",)]
        elif "from information_schema.tables" in low:
            self._rows = [
                ("public", "atendimento", "BASE TABLE", 15420),
                ("public", "vw_atendimento_resumo", "VIEW", -1),
            ]
        elif "from information_schema.columns" in low:
            if params and params[1] == "tabela_inexistente":
                self._rows = []
            else:
                self._rows = [
                    ("id", "bigint", "int8", "NO", "nextval('atendimento_id_seq'::regclass)"),
                    ("paciente_id", "bigint", "int8", "NO", None),
                    ("data_atendimento", "date", "date", "YES", None),
                    ("valor_total", "numeric", "numeric", "YES", "0.00"),
                    ("ativo", "boolean", "bool", "NO", "true"),
                    ("observacao", "character varying", "varchar", "YES", None),
                ]
        elif "tc.constraint_type = 'primary key'" in low:
            self._rows = [("id",)]
        elif "tc.constraint_type = 'foreign key'" in low:
            self._rows = [
                ("fk_atendimento_paciente", "paciente_id", "public", "paciente", "id"),
            ]
        elif "_studio_preview" in low:
            self.description = [
                SimpleNamespace(name="id", type_code=20, null_ok=False),
                SimpleNamespace(name="nome", type_code=1043, null_ok=True),
                SimpleNamespace(name="valor", type_code=1700, null_ok=True),
                SimpleNamespace(name="criado_em", type_code=1114, null_ok=True),
                SimpleNamespace(name="uid", type_code=2950, null_ok=True),
                SimpleNamespace(name="assinatura", type_code=17, null_ok=True),
            ]
            self._rows = list(self.conn.preview_rows)

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchmany(self, size: int) -> list[Any]:
        return list(self._rows[:size])


class FakeConnection:
    def __init__(
        self,
        *,
        preview_rows: list[Any] | None = None,
        fail_on_query: bool = False,
    ) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.read_only_tx = False
        self.statement_timeout_set = False
        self.rolled_back = False
        self.closed = False
        self.fail_on_query = fail_on_query
        self.preview_rows = preview_rows if preview_rows is not None else []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _make_pg_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conn_factory: Any,
) -> tuple[PostgresService, str]:
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-workbench-key-32-chars-minimum-ok!")
    store = SQLiteStore(db_path=tmp_path / "data" / "studio.db")
    pg = PostgresService(
        store=store,
        connection_factory=conn_factory,
        vault_path=tmp_path / "data" / ".vault.json",
    )
    prof = pg.create_profile(
        DbProfileCreate(
            name="Ambiente Teste",
            host="127.0.0.1",
            port=5432,
            dbname="salutem_test",
            user="readonly_user",
            password="secret-password",
            read_only=True,
            is_default=True,
        )
    )
    return pg, prof.id


def test_validate_and_bind_readonly_select_rejects_dml_ddl_and_multistatement() -> None:
    forbidden_queries = [
        "",
        "   ",
        "INSERT INTO paciente (nome) VALUES ('A')",
        "UPDATE paciente SET nome = 'B'",
        "DELETE FROM paciente WHERE id = 1",
        "DROP TABLE paciente",
        "ALTER TABLE paciente ADD COLUMN x TEXT",
        "TRUNCATE paciente",
        "CREATE TABLE hack (id INT)",
        "GRANT ALL ON paciente TO public",
        "REVOKE SELECT ON paciente FROM public",
        "DO $$ BEGIN PERFORM 1; END $$;",
        "SELECT 1; DROP TABLE paciente",
        "WITH del AS (DELETE FROM paciente RETURNING id) SELECT * FROM del",
    ]
    for bad_sql in forbidden_queries:
        with pytest.raises(DbProfileValidationError):
            validate_and_bind_readonly_select(bad_sql)


def test_validate_and_bind_readonly_select_binds_jasper_placeholders_and_escapes_percent() -> None:
    sql = """
    -- Comentário com $P{ignorado} e DELETE fake
    SELECT id, nome
    FROM paciente
    WHERE id = $P{id}
      AND status = ${status}
      AND codigo = $P!{cod}
      AND nome ILIKE '%MARIA%'
    """
    bound_sql, values = validate_and_bind_readonly_select(
        sql,
        params={"id": 42, "status": "ATIVO", "cod": "ABC_1"},
    )
    assert "DELETE" not in bound_sql
    assert "$P{" not in bound_sql
    assert "${" not in bound_sql
    assert "'%%MARIA%%'" in bound_sql
    assert bound_sql.count("%s") == 3
    assert values == [42, "ATIVO", "ABC_1"]

    # Rejects unsafe SQL fragment in $P!{...}
    with pytest.raises(DbProfileValidationError):
        validate_and_bind_readonly_select(
            "SELECT * FROM paciente WHERE id = $P!{raw}",
            params={"raw": "1; DROP TABLE paciente"},
        )


def test_schema_inspector_lists_schemas_tables_and_describes_table_readonly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_conns: list[FakeConnection] = []

    def _factory(**_kwargs: Any) -> FakeConnection:
        c = FakeConnection()
        created_conns.append(c)
        return c

    pg, profile_id = _make_pg_service(tmp_path, monkeypatch, _factory)
    inspector = PgSchemaInspector(pg)

    schemas = inspector.list_schemas(profile_id)
    assert schemas == ["public", "ambulatorial", "hospitalar"]
    assert "pg_catalog" not in schemas

    tables = inspector.list_tables(profile_id, schema="public", search="atend", limit=50)
    assert len(tables) == 2
    assert tables[0].table_name == "atendimento"
    assert tables[0].estimated_rows == 15420
    assert tables[1].estimated_rows is None

    detail = inspector.describe_table(profile_id, schema="public", table="atendimento")
    assert detail.schema_name == "public"
    assert detail.table_name == "atendimento"
    assert detail.primary_keys == ["id"]
    assert len(detail.foreign_keys) == 1
    assert detail.foreign_keys[0].foreign_table == "paciente"

    col_map = {c.name: c for c in detail.columns}
    assert col_map["id"].is_primary_key is True
    assert col_map["id"].java_class == "java.lang.Long"
    assert col_map["data_atendimento"].java_class == "java.sql.Date"
    assert col_map["valor_total"].java_class == "java.math.BigDecimal"
    assert col_map["ativo"].java_class == "java.lang.Boolean"
    assert col_map["observacao"].java_class == "java.lang.String"

    # Every connection used READ ONLY + statement_timeout + ROLLBACK + close
    assert len(created_conns) == 3
    for conn in created_conns:
        assert conn.read_only_tx is True
        assert conn.statement_timeout_set is True
        assert conn.rolled_back is True
        assert conn.closed is True


def test_preview_select_serializes_types_caps_limit_and_rolls_back_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_uuid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    sample_dt = dt.datetime(2026, 11, 27, 14, 30, 0)
    rows = [
        (1, "Pac A", decimal.Decimal("125.50"), sample_dt, sample_uuid, b"\x01\x02\x03"),
        (2, "Pac B", decimal.Decimal("200.00"), sample_dt, sample_uuid, b"x" * 100),
        (3, "Pac C", None, None, None, None),
    ]
    created_conns: list[FakeConnection] = []

    def _factory(**_kwargs: Any) -> FakeConnection:
        c = FakeConnection(preview_rows=rows)
        created_conns.append(c)
        return c

    pg, profile_id = _make_pg_service(tmp_path, monkeypatch, _factory)
    inspector = PgSchemaInspector(pg)

    res = inspector.preview_select_query(
        profile_id,
        "SELECT id, nome, valor, criado_em, uid, assinatura FROM atendimento WHERE id > $P{min_id}",
        params={"min_id": 0},
        limit=2,
    )
    assert res.ok is True
    assert res.row_count == 2
    assert res.truncated is True
    assert res.limit == 2
    assert res.rows[0]["valor"] == 125.5
    assert res.rows[0]["criado_em"] == "2026-11-27T14:30:00"
    assert res.rows[0]["uid"] == "11111111-2222-3333-4444-555555555555"
    assert res.rows[0]["assinatura"].startswith("base64:")
    assert res.rows[1]["assinatura"] == "<bytea:100 bytes>"
    assert created_conns[-1].read_only_tx is True
    assert created_conns[-1].statement_timeout_set is True
    assert created_conns[-1].rolled_back is True
    assert created_conns[-1].closed is True

    # Limit capped to 200 even if larger requested
    res_cap = inspector.preview_select_query(profile_id, "SELECT 1", limit=999)
    assert res_cap.limit == 200

    # Rollback happens unconditionally even on DB error
    err_conn = FakeConnection(fail_on_query=True)
    pg_err, prof_err_id = _make_pg_service(tmp_path / "err", monkeypatch, lambda **_kw: err_conn)
    with pytest.raises(Exception, match="synthetic query failure"):
        PgSchemaInspector(pg_err).preview_select_query(prof_err_id, "SELECT 1")
    assert err_conn.rolled_back is True
    assert err_conn.closed is True

    # Direct serialize_pg_value checks
    assert serialize_pg_value(dt.date(2026, 5, 10)) == "2026-05-10"
    assert serialize_pg_value(decimal.Decimal("NaN")) == "NaN"


def test_database_router_workbench_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_rows = [
        (10, "Teste", decimal.Decimal("9.99"), dt.datetime(2026, 1, 1, 8, 0), None, None)
    ]
    pg, profile_id = _make_pg_service(
        tmp_path,
        monkeypatch,
        lambda **_kw: FakeConnection(preview_rows=sample_rows),
    )

    app = FastAPI()
    app.state.postgres_service = pg
    app.include_router(database_api.router)
    client = TestClient(app)

    r_schemas = client.get(f"/api/db/profiles/{profile_id}/schemas")
    assert r_schemas.status_code == 200
    assert r_schemas.json()["schemas"][0] == "public"

    r_tables = client.get(f"/api/db/profiles/{profile_id}/tables?schema=public&search=atend")
    assert r_tables.status_code == 200
    assert r_tables.json()[0]["table_name"] == "atendimento"

    r_desc = client.get(f"/api/db/profiles/{profile_id}/tables/atendimento?schema=public")
    assert r_desc.status_code == 200
    assert r_desc.json()["primary_keys"] == ["id"]

    r_prev = client.post(
        f"/api/db/profiles/{profile_id}/preview-select",
        json={"sql_select": "SELECT * FROM atendimento WHERE id = $P{id}", "params": {"id": 10}, "limit": 25},
    )
    assert r_prev.status_code == 200
    body = r_prev.json()
    assert body["ok"] is True
    assert body["row_count"] == 1
    assert body["rows"][0]["valor"] == 9.99

    r_bad = client.post(
        f"/api/db/profiles/{profile_id}/preview-select",
        json={"sql_select": "DELETE FROM atendimento"},
    )
    assert r_bad.status_code == 400
