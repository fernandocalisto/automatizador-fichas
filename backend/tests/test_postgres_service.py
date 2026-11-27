# -*- coding: utf-8 -*-
"""Unit and FastAPI integration tests for PostgresService, vault secrets, Dry-Run/Commit, and SELECT inspector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.errors import KeyringError, PasswordDeleteError

from backend.app.api.database import router as database_router
from backend.app.core.sql_insert import generate_insert_sql
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.main import create_app
from backend.app.services.postgres_service import (
    KEYRING_SERVICE_NAME,
    DbProfileCreate,
    DbProfileNotFoundError,
    DbProfileUpdate,
    DbProfileValidationError,
    DryRunRequiredError,
    PostgresExecutionError,
    PostgresService,
    PostgresServiceError,
    ReadOnlyProfileError,
)
from backend.app.services.workspace_service import WorkspaceService


# =============================================================================
# Fake psycopg Connection / Cursor / Keyring Test Doubles
# =============================================================================


@dataclass
class FakeDiagnostic:
    """Mimics `psycopg.errors.Diagnostic` passed to `conn.add_notice_handler`."""

    message_primary: str


@dataclass
class FakeColumnDesc:
    """Mimics `psycopg.Column` entries on `cur.description`."""

    name: str
    type_code: int
    null_ok: bool | None = True


class FakePgCursor:
    """Controllable DB-API 2.0 / psycopg v3 cursor recorder."""

    def __init__(self, conn: FakePgConnection) -> None:
        self._conn = conn
        self.description: list[FakeColumnDesc] | None = None
        self._next_row: Any = None
        self.closed = False

    def __enter__(self) -> FakePgCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn.executed_queries.append((sql, params))
        if self._conn.raise_on_execute is not None:
            raise self._conn.raise_on_execute

        upper = sql.strip().upper()
        if "SELECT VERSION()" in upper:
            self._next_row = (
                "PostgreSQL 16.4 on x86_64-pc-linux-gnu",
                self._conn.connect_kwargs.get("dbname", "salutem"),
                self._conn.connect_kwargs.get("user", "postgres"),
            )
            return

        if "AS _SALUTEM_INSPECT LIMIT 0" in upper:
            self.description = list(self._conn.inspect_columns)
            self._next_row = None
            return

        if "FROM PUBLIC.ATENDIMENTO" in upper:
            self._next_row = (
                (self._conn.sample_atendimento_id,)
                if self._conn.sample_atendimento_id is not None
                else None
            )
            return

        if "RAISE NOTICE" in upper or "INSERT INTO PUBLIC.TEMPLATE_FICHA_CLINICA" in upper:
            generated_id = self._conn.allocate_template_id()
            diag = FakeDiagnostic(
                message_primary=f"Template inserido com sucesso! ID gerado: {generated_id}"
            )
            for handler in self._conn.notice_handlers:
                handler(diag)

    def fetchone(self) -> Any:
        return self._next_row


class FakePgConnection:
    """Controllable psycopg v3 connection spy tracking commits, rollbacks, closes, and notices."""

    def __init__(
        self,
        *,
        connect_kwargs: dict[str, Any] | None = None,
        id_allocator: Any = None,
        sample_atendimento_id: int | None = 98765,
        inspect_columns: list[FakeColumnDesc] | None = None,
        raise_on_execute: Exception | None = None,
    ) -> None:
        self.connect_kwargs = connect_kwargs or {}
        self._id_allocator = id_allocator
        self.sample_atendimento_id = sample_atendimento_id
        self.inspect_columns = inspect_columns or [
            FakeColumnDesc("atendimento_id", 20),
            FakeColumnDesc("paciente_nome", 1043),
            FakeColumnDesc("alergia_medicamentosa", 16),
            FakeColumnDesc("data_nascimento", 1082),
            FakeColumnDesc("data_hora_atendimento", 1114),
            FakeColumnDesc("peso_kg", 1700),
        ]
        self.raise_on_execute = raise_on_execute
        self.notice_handlers: list[Any] = []
        self.executed_queries: list[tuple[str, Any]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def allocate_template_id(self) -> int:
        if callable(self._id_allocator):
            return int(self._id_allocator())
        return 501

    def add_notice_handler(self, callback: Any) -> None:
        self.notice_handlers.append(callback)

    def cursor(self) -> FakePgConnection | FakePgCursor:
        return FakePgCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class FakeConnectionDriver:
    """Factory that records every opened `FakePgConnection` instance."""

    def __init__(
        self,
        *,
        start_template_id: int = 501,
        sample_atendimento_id: int | None = 98765,
        raise_on_connect: Exception | None = None,
        raise_on_execute: Exception | None = None,
    ) -> None:
        self.connections: list[FakePgConnection] = []
        self._next_id = start_template_id
        self.sample_atendimento_id = sample_atendimento_id
        self.raise_on_connect = raise_on_connect
        self.raise_on_execute = raise_on_execute

    def _allocate_id(self) -> int:
        val = self._next_id
        self._next_id += 1
        return val

    def __call__(self, **kwargs: Any) -> FakePgConnection:
        if self.raise_on_connect is not None:
            raise self.raise_on_connect
        conn = FakePgConnection(
            connect_kwargs=kwargs,
            id_allocator=self._allocate_id,
            sample_atendimento_id=self.sample_atendimento_id,
            raise_on_execute=self.raise_on_execute,
        )
        self.connections.append(conn)
        return conn


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate `FICHA_STUDIO_DATA_DIR` and mock OS keyring in memory by default."""
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.delenv("FICHA_STUDIO_DB_PATH", raising=False)
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "unit-test-master-vault-secret-2026")

    memory_keyring: dict[tuple[str, str], str] = {}

    def _set_pw(service: str, account: str, pw: str) -> None:
        memory_keyring[(service, account)] = pw

    def _get_pw(service: str, account: str) -> str | None:
        return memory_keyring.get((service, account))

    def _del_pw(service: str, account: str) -> None:
        if (service, account) not in memory_keyring:
            raise PasswordDeleteError("Secret not found")
        del memory_keyring[(service, account)]

    monkeypatch.setattr(keyring, "set_password", _set_pw)
    monkeypatch.setattr(keyring, "get_password", _get_pw)
    monkeypatch.setattr(keyring, "delete_password", _del_pw)
    return data_dir


def _sample_clinical_json() -> dict[str, Any]:
    return {
        "template": {
            "nome": "Ficha de Acolhimento Obstétrico",
            "descricao": "Ficha clínica obstétrica",
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "posicao_assinatura": "RODAPE",
        },
        "perguntas": [
            {
                "nome": "Avaliação Inicial",
                "titulo": False,
                "respostas": [
                    {"label": "Pressão Arterial", "tipo_campo": "TEXTO"},
                    {"label": "Gestante de Alto Risco", "tipo_campo": "BOOLEANO"},
                ],
            }
        ],
    }


@pytest.fixture()
def api_setup(isolated_env: Path) -> tuple[TestClient, FakeConnectionDriver, SQLiteStore]:
    """Create a FastAPI TestClient with `database.router` mounted and fake PostgreSQL driver."""
    store = SQLiteStore()
    ws_service = WorkspaceService(store=store)
    driver = FakeConnectionDriver(start_template_id=1042, sample_atendimento_id=44556)
    pg_service = PostgresService(store=store, connection_factory=driver)

    app = create_app(store=store, workspace_service=ws_service)
    app.state.postgres_service = pg_service
    if not any(getattr(r, "path", "") == "/api/db/profiles" for r in app.routes):
        app.include_router(database_router)

    with TestClient(app) as client:
        yield client, driver, store


# =============================================================================
# 1. Profile CRUD, Password Redaction & Encrypted Vault Fallback Tests
# =============================================================================


def test_profile_crud_password_redaction_and_jdbc_credentials(isolated_env: Path) -> None:
    store = SQLiteStore()
    svc = PostgresService(store=store)

    created = svc.create_profile(
        DbProfileCreate(
            name="Homologação Salutem",
            host="pg-hml.salutem.local",
            port=5433,
            dbname="salutem_hml",
            user="salutem_app",
            password="SuperSecret!Password#99",
            sslmode="require",
            read_only=False,
            is_default=True,
        )
    )

    dumped = created.model_dump()
    assert "password" not in dumped
    assert "db_pass" not in dumped
    assert created.has_password is True
    assert created.is_default is True
    assert created.port == 5433
    assert created.sslmode == "require"

    # Verify OS keyring used KEYRING_SERVICE_NAME and SQLite contains zero plaintext secrets
    assert (
        keyring.get_password(KEYRING_SERVICE_NAME, f"db_profile:{created.id}")
        == "SuperSecret!Password#99"
    )
    raw_sqlite_bytes = store.db_path.read_bytes()
    assert b"SuperSecret!Password#99" not in raw_sqlite_bytes

    # Creating a second profile with is_default=True unsets the first profile's default flag
    second = svc.create_profile(
        DbProfileCreate(
            name="Produção Réplica Leitura",
            host="pg-ro.salutem.local",
            dbname="salutem_prod",
            user="relatorio_ro",
            password="RoSecretPassword!1",
            read_only=True,
            is_default=True,
        )
    )
    profiles = svc.list_profiles()
    assert len(profiles) == 2
    by_id = {p.id: p for p in profiles}
    assert by_id[second.id].is_default is True
    assert by_id[created.id].is_default is False

    # Verify JDBC credentials helper
    jdbc = svc.get_jdbc_credentials(created.id)
    assert jdbc == {
        "db_url": "jdbc:postgresql://pg-hml.salutem.local:5433/salutem_hml?sslmode=require",
        "db_user": "salutem_app",
        "db_pass": "SuperSecret!Password#99",
        "read_only": False,
    }

    # Updating metadata without sending password preserves existing secret
    updated = svc.update_profile(created.id, DbProfileUpdate(name="HML Atualizado"))
    assert updated.name == "HML Atualizado"
    assert updated.has_password is True

    # Clearing password with empty string sets has_password=False
    cleared = svc.update_profile(created.id, DbProfileUpdate(password=""))
    assert cleared.has_password is False
    assert svc.get_jdbc_credentials(created.id)["db_pass"] == ""

    # Deleting profile removes metadata and raises DbProfileNotFoundError afterwards
    assert svc.delete_profile(second.id) is True
    with pytest.raises(DbProfileNotFoundError):
        svc.get_profile(second.id)


def test_keyring_error_falls_back_to_encrypted_vault_with_hmac_tamper_check(
    isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingKeyringError(KeyringError):
        pass

    def _always_fail(*_args: Any, **_kwargs: Any) -> Any:
        raise FailingKeyringError("No OS keyring daemon available in headless container")

    monkeypatch.setattr(keyring, "set_password", _always_fail)
    monkeypatch.setattr(keyring, "get_password", _always_fail)
    monkeypatch.setattr(keyring, "delete_password", _always_fail)

    store = SQLiteStore()
    svc = PostgresService(store=store)
    secret_pw = "Senh@ Clínica Ção 2026! 🔐"

    profile = svc.create_profile(
        DbProfileCreate(
            name="Docker Headless PG",
            host="10.0.0.25",
            dbname="salutem",
            user="docker_user",
            password=secret_pw,
        )
    )
    assert profile.has_password is True
    assert svc.vault_path == isolated_env / ".vault.json"
    assert svc.vault_path.is_file()

    vault_raw_text = svc.vault_path.read_text(encoding="utf-8")
    assert secret_pw not in vault_raw_text
    assert "Senh@" not in vault_raw_text

    creds = svc.get_jdbc_credentials(profile.id)
    assert creds["db_pass"] == secret_pw

    # Corrupting authenticated ciphertext inside .vault.json must raise PostgresServiceError
    corrupted_text = vault_raw_text.replace('"ciphertext": "', '"ciphertext": "AAAA')
    svc.vault_path.write_text(corrupted_text, encoding="utf-8")
    with pytest.raises(PostgresServiceError, match="HMAC"):
        svc.get_jdbc_credentials(profile.id)


# =============================================================================
# 2. Connection Test, Read-Only Guard, Unconditional Dry-Run Rollback & Tamper Guard
# =============================================================================


def test_connection_latency_and_failure_reporting(isolated_env: Path) -> None:
    store = SQLiteStore()
    ok_driver = FakeConnectionDriver()
    svc = PostgresService(store=store, connection_factory=ok_driver)
    prof = svc.create_profile(
        DbProfileCreate(name="Local PG", host="localhost", dbname="salutem", user="postgres")
    )

    ok_res = svc.test_connection(prof.id)
    assert ok_res.ok is True
    assert ok_res.latency_ms >= 0.0
    assert ok_res.server_version is not None and "PostgreSQL 16.4" in ok_res.server_version
    assert ok_res.current_database == "salutem"
    assert ok_driver.connections[0].close_count == 1

    fail_driver = FakeConnectionDriver(raise_on_connect=OSError("Connection refused"))
    fail_svc = PostgresService(store=store, connection_factory=fail_driver)
    fail_res = fail_svc.test_connection(prof.id)
    assert fail_res.ok is False
    assert fail_res.error is not None and "Connection refused" in fail_res.error


def test_dry_run_unconditional_rollback_on_success_and_on_runtime_error(
    isolated_env: Path,
) -> None:
    store = SQLiteStore()
    driver = FakeConnectionDriver(start_template_id=777)
    svc = PostgresService(store=store, connection_factory=driver)
    prof = svc.create_profile(
        DbProfileCreate(name="Staging PG", host="localhost", dbname="salutem", user="postgres")
    )

    sql_insert = generate_insert_sql(_sample_clinical_json())
    dry_res = svc.dry_run_insert("proj-unit-1", prof.id, sql_insert)

    assert dry_res.ok is True
    assert dry_res.rolled_back is True
    assert dry_res.simulated_template_id == 777
    assert dry_res.template_id == 777
    assert any("ID gerado: 777" in n for n in dry_res.notices)
    assert len(dry_res.dry_run_token) > 40

    conn_used = driver.connections[0]
    assert conn_used.connect_kwargs["autocommit"] is False
    assert conn_used.rollback_count == 1
    assert conn_used.commit_count == 0
    assert conn_used.close_count == 1

    # Even if PostgreSQL raises a constraint/syntax error during execution, rollback MUST run
    err_driver = FakeConnectionDriver(
        raise_on_execute=RuntimeError("duplicate key value violates unique constraint")
    )
    err_svc = PostgresService(store=store, connection_factory=err_driver)
    with pytest.raises(PostgresExecutionError, match="duplicate key"):
        err_svc.dry_run_insert("proj-unit-1", prof.id, sql_insert)

    failed_conn = err_driver.connections[0]
    assert failed_conn.rollback_count == 1
    assert failed_conn.commit_count == 0
    assert failed_conn.close_count == 1


def test_sql_tamper_guard_and_token_replay_protection(isolated_env: Path) -> None:
    store = SQLiteStore()
    driver = FakeConnectionDriver(start_template_id=888)
    svc = PostgresService(store=store, connection_factory=driver)
    prof_a = svc.create_profile(
        DbProfileCreate(name="DB A", host="localhost", dbname="salutem_a", user="postgres")
    )
    prof_b = svc.create_profile(
        DbProfileCreate(name="DB B", host="localhost", dbname="salutem_b", user="postgres")
    )

    sql_insert = generate_insert_sql(_sample_clinical_json())
    dry_res = svc.dry_run_insert("proj-tamper", prof_a.id, sql_insert)
    assert len(driver.connections) == 1

    # 1. Tampering with SQL by appending a harmless comment must be blocked BEFORE opening connection
    tampered_sql = sql_insert + "\n-- subtle modification after dry-run"
    with pytest.raises(DryRunRequiredError):
        svc.commit_insert("proj-tamper", prof_a.id, tampered_sql, dry_res.dry_run_token)
    assert len(driver.connections) == 1

    # 2. Swapping target profile_id with valid token must be blocked
    with pytest.raises(DryRunRequiredError):
        svc.commit_insert("proj-tamper", prof_b.id, sql_insert, dry_res.dry_run_token)
    assert len(driver.connections) == 1

    # 3. Swapping project_id with valid token must be blocked
    with pytest.raises(DryRunRequiredError):
        svc.commit_insert("other-project", prof_a.id, sql_insert, dry_res.dry_run_token)
    assert len(driver.connections) == 1

    # 4. Exact matching SQL + project + profile succeeds and commits
    commit_res = svc.commit_insert("proj-tamper", prof_a.id, sql_insert, dry_res.dry_run_token)
    assert commit_res.committed is True
    assert commit_res.template_id == 889
    assert driver.connections[1].commit_count == 1

    # 5. Replaying the already-consumed dry_run_token must be blocked
    with pytest.raises(DryRunRequiredError, match="consumed"):
        svc.commit_insert("proj-tamper", prof_a.id, sql_insert, dry_res.dry_run_token)


# =============================================================================
# 3. FastAPI End-to-End Flow: 403 Read-Only, Dry-Run, Commit Gate2 & Inspect-Select
# =============================================================================


def test_fastapi_readonly_403_dry_run_commit_updates_project_and_gate2(
    api_setup: tuple[TestClient, FakeConnectionDriver, SQLiteStore],
) -> None:
    client, driver, _store = api_setup

    # Create a clinical project with initial JSON (which auto-generates sql_insert & sql_select)
    proj_resp = client.post(
        "/api/projects",
        json={
            "name": "Ficha Pré-Natal Salutem",
            "entry_mode": "json",
            "initial_json": _sample_clinical_json(),
        },
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["id"]

    # Create a read-only profile and a read-write profile via API
    ro_resp = client.post(
        "/api/db/profiles",
        json={
            "name": "Replica Somente Leitura",
            "host": "ro.salutem.local",
            "dbname": "salutem",
            "user": "viewer",
            "password": "ro-password-123",
            "read_only": True,
        },
    )
    assert ro_resp.status_code == 201
    ro_body = ro_resp.json()
    assert "password" not in ro_body
    assert ro_body["has_password"] is True
    ro_id = ro_body["id"]

    rw_resp = client.post(
        "/api/db/profiles",
        json={
            "name": "Homologação Escrita",
            "host": "rw.salutem.local",
            "dbname": "salutem",
            "user": "writer",
            "password": "rw-password-456",
            "read_only": False,
            "is_default": True,
        },
    )
    assert rw_resp.status_code == 201
    rw_id = rw_resp.json()["id"]

    # Test connection endpoint
    test_conn_resp = client.post(f"/api/db/profiles/{rw_id}/test")
    assert test_conn_resp.status_code == 200
    assert test_conn_resp.json()["ok"] is True
    conn_count_after_ping = len(driver.connections)

    # Attempting dry-run-insert or commit-insert on read_only=True MUST return 403 Forbidden
    ro_dry_resp = client.post(
        f"/api/projects/{project_id}/db/dry-run-insert",
        json={"profile_id": ro_id},
    )
    assert ro_dry_resp.status_code == 403
    assert len(driver.connections) == conn_count_after_ping

    ro_commit_resp = client.post(
        f"/api/projects/{project_id}/db/commit-insert",
        json={"profile_id": ro_id, "dry_run_token": "fake.token"},
    )
    assert ro_commit_resp.status_code == 403

    # Execute Dry-Run on read-write profile (using project's stored sql_insert artifact)
    latest_sql_resp = client.get(f"/api/projects/{project_id}/artifacts/sql_insert")
    assert latest_sql_resp.status_code == 200
    sql_text = latest_sql_resp.json()["content"]
    initial_sql_version = latest_sql_resp.json()["version_num"]

    dry_resp = client.post(
        f"/api/projects/{project_id}/db/dry-run-insert",
        json={"profile_id": rw_id, "sql_text": sql_text},
    )
    assert dry_resp.status_code == 200
    dry_data = dry_resp.json()
    assert dry_data["rolled_back"] is True
    assert dry_data["simulated_template_id"] == 1042
    dry_token = dry_data["dry_run_token"]

    # Verify project template_db_id and gate2_sql_insert are STILL unchanged after Dry-Run
    proj_after_dry = client.get(f"/api/projects/{project_id}").json()
    assert proj_after_dry["template_db_id"] is None
    gates_after_dry = {g["gate_name"]: g["status"] for g in proj_after_dry["gates"]}
    assert gates_after_dry["gate2_sql_insert"] == "pending"

    # Tampered SQL before commit-insert MUST be rejected with 400
    tamper_resp = client.post(
        f"/api/projects/{project_id}/db/commit-insert",
        json={
            "profile_id": rw_id,
            "sql_text": sql_text.replace("RETRATO", "PAISAGEM"),
            "dry_run_token": dry_token,
        },
    )
    assert tamper_resp.status_code == 400

    # Valid commit-insert persists template_db_id, increments sql_insert revision, and approves gate2
    commit_resp = client.post(
        f"/api/projects/{project_id}/db/commit-insert",
        json={
            "profile_id": rw_id,
            "sql_text": sql_text,
            "dry_run_token": dry_token,
        },
    )
    assert commit_resp.status_code == 200
    commit_data = commit_resp.json()
    assert commit_data["committed"] is True
    assert commit_data["template_id"] == 1043
    assert commit_data["gate2_status"] == "approved"
    assert commit_data["artifact_version"] == initial_sql_version + 1

    proj_after_commit = client.get(f"/api/projects/{project_id}").json()
    assert proj_after_commit["template_db_id"] == 1043
    gates_after_commit = {g["gate_name"]: g["status"] for g in proj_after_commit["gates"]}
    assert gates_after_commit["gate2_sql_insert"] == "approved"


def test_inspect_select_query_placeholders_oids_and_sample_atendimento_api(
    api_setup: tuple[TestClient, FakeConnectionDriver, SQLiteStore],
) -> None:
    client, driver, store = api_setup

    proj_resp = client.post(
        "/api/projects",
        json={
            "name": "Ficha Inspeção Jasper",
            "entry_mode": "json",
            "initial_json": _sample_clinical_json(),
        },
    )
    project_id = proj_resp.json()["id"]

    # Read-only profile IS allowed to run SELECT metadata inspection and sample atendimento lookup
    ro_resp = client.post(
        "/api/db/profiles",
        json={
            "name": "Banco Leitura Jasper",
            "host": "ro.salutem.local",
            "dbname": "salutem",
            "user": "jasper_ro",
            "read_only": True,
        },
    )
    ro_id = ro_resp.json()["id"]

    sample_resp = client.get(f"/api/db/profiles/{ro_id}/sample-atendimento")
    assert sample_resp.status_code == 200
    assert sample_resp.json()["sample_atendimento_id"] == 44556

    jasper_select = """
    -- Consulta principal JasperReports com literal '%' e parâmetros $P{id} / ${id}
    SELECT
        a.id AS atendimento_id,
        'Álcool 70%' AS antisseptico_padrao,
        p.nome AS paciente_nome
    FROM public.atendimento a
    JOIN public.paciente p ON p.id = a.paciente_id
    WHERE a.id = $P{id} OR a.id = ${id};
    """

    inspect_resp = client.post(
        f"/api/projects/{project_id}/db/inspect-select",
        json={
            "profile_id": ro_id,
            "sql_select": jasper_select,
            "lookup_sample_id": True,
        },
    )
    assert inspect_resp.status_code == 200
    body = inspect_resp.json()
    assert body["ok"] is True
    assert body["sample_atendimento_id"] == 44556
    assert body["sample_id_used"] == 44556
    assert body["parameter_placeholders_replaced"] == 2

    cols_by_name = {c["name"]: c for c in body["columns"]}
    assert cols_by_name["atendimento_id"]["java_class"] == "java.lang.Long"
    assert cols_by_name["paciente_nome"]["java_class"] == "java.lang.String"
    assert cols_by_name["alergia_medicamentosa"]["java_class"] == "java.lang.Boolean"
    assert cols_by_name["data_nascimento"]["java_class"] == "java.sql.Date"
    assert cols_by_name["data_hora_atendimento"]["java_class"] == "java.sql.Timestamp"
    assert cols_by_name["peso_kg"]["java_class"] == "java.math.BigDecimal"

    # Verify wrapped SQL used LIMIT 0, escaped literal '%', replaced placeholders, and rolled back
    inspect_conn = driver.connections[-1]
    executed_sql, executed_params = inspect_conn.executed_queries[0]
    assert "AS _salutem_inspect LIMIT 0" in executed_sql
    assert "70%%" in executed_sql
    assert "$P{id}" not in executed_sql
    assert "${id}" not in executed_sql
    assert executed_params == (44556, 44556)
    assert inspect_conn.rollback_count == 1
    assert inspect_conn.commit_count == 0

    # Also test implicit artifact fallback (inspecting project's auto-generated sql_select)
    stored_inspect_resp = client.post(
        f"/api/projects/{project_id}/db/inspect-select",
        json={"profile_id": ro_id, "sample_id": 123},
    )
    assert stored_inspect_resp.status_code == 200
    assert stored_inspect_resp.json()["sample_id_used"] == 123
    assert len(stored_inspect_resp.json()["columns"]) == 6

    # Mutating SQL passed into inspect_select_query must be rejected
    pg_service = PostgresService(store=store, connection_factory=driver)
    with pytest.raises(DbProfileValidationError):
        pg_service.inspect_select_query(ro_id, "DELETE FROM public.atendimento WHERE id = 1;")


def test_encrypted_vault_rejects_insecure_placeholder_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.services.postgres_service import _EncryptedVault

    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "change-me-in-production")
    vault = _EncryptedVault(lambda: tmp_path / ".vault.json")
    with pytest.raises(PostgresServiceError, match="placeholder inseguro"):
        vault.set_secret("profile-1", "super-secret")
