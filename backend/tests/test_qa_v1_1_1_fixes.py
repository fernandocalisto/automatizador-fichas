# -*- coding: utf-8 -*-
"""Regression test suite covering all backend fixes from QA report v1.1.1."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import fitz
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from backend.app.api import (
    clients as clients_api,
    credentials as credentials_api,
    database as database_api,
    harnesses_and_tools as tools_api,
    jasper_preview as preview_api,
    jasperserver as jasperserver_api,
    projects as projects_api,
    sftp as sftp_api,
    system as system_api,
)
from backend.app.config import APP_VERSION
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.jrxml import lint_jrxml, scaffold_free_report_jrxml
from backend.app.services import secret_vault as secret_vault_mod
from backend.app.services.client_catalog_service import (
    ClientCatalogService,
    ClientSystemCreate,
    ClientUnitCreate,
)
from backend.app.services.default_credentials_service import DefaultCredentialsService
from backend.app.services.jasperserver_service import (
    JasperServerError,
    JasperServerProfileCreate,
    JasperServerService,
    JasperServerValidationError,
)
from backend.app.services.pg_schema_inspector import validate_and_bind_readonly_select
from backend.app.services.postgres_service import (
    DbProfileCreate,
    DbProfileValidationError,
    PostgresService,
)
from backend.app.services.secret_vault import SecretVaultService
from backend.app.services.sftp_service import SftpProfileCreate, SftpService
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import WorkspaceService


class _MarkerPdfDaemon:
    """Fake JasperDaemon that embeds a text marker from the JRXML into a real PyMuPDF PDF."""

    def __init__(self) -> None:
        self.compile_calls: list[tuple[str, str]] = []
        self.export_calls: list[dict[str, Any]] = []

    def compile(self, jrxml_path: str, jasper_path: str, **_kwargs: Any) -> dict[str, Any]:
        self.compile_calls.append((jrxml_path, jasper_path))
        Path(jasper_path).parent.mkdir(parents=True, exist_ok=True)
        Path(jasper_path).write_bytes(b"\xac\xed\x00\x05FAKE_JASPER")
        return {"ok": True, "status": "SUCCESS", "output": jasper_path}

    def export_pdf(
        self,
        jrxml_path: str,
        output_pdf: str,
        *,
        params: dict[str, Any] | None = None,
        mock_rows: list[dict[str, Any]] | None = None,
        subreport_dir: str | None = None,
        db_url: str | None = None,
        db_user: str | None = None,
        db_pass: str | None = None,
    ) -> dict[str, Any]:
        jrxml_content = Path(jrxml_path).read_text(encoding="utf-8")
        self.export_calls.append(
            {
                "jrxml_path": jrxml_path,
                "jrxml_content": jrxml_content,
                "output_pdf": output_pdf,
                "params": dict(params or {}),
            }
        )
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        y = 72
        for marker in ("VERSAO_UM_ANTIGA", "VERSAO_DOIS_NOVA"):
            if marker in jrxml_content:
                page.insert_text((36, y), marker, fontsize=12)
                y += 20
        page.insert_text((36, y), f"LEN={len(jrxml_content)}", fontsize=10)
        Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_pdf)
        doc.close()
        return {"ok": True, "status": "SUCCESS", "pdf": output_pdf}


@pytest.fixture()
def qa_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    def _fail_keyring(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyringError("disabled in unit tests")

    monkeypatch.setattr(secret_vault_mod.keyring, "set_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_mod.keyring, "get_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_mod.keyring, "delete_password", _fail_keyring)
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "qa-v111-test-vault-key-32-chars-minimum!")

    data_dir = tmp_path / "data"
    store = SQLiteStore(db_path=data_dir / "studio.db")
    vault = SecretVaultService(vault_path=data_dir / ".vault.json")
    defaults_svc = DefaultCredentialsService(store=store, vault=vault)
    workspace_svc = WorkspaceService(store=store, data_dir=data_dir / "workspaces")
    subreport_svc = SubreportService()
    daemon = _MarkerPdfDaemon()

    def _unreachable_pg(**_kwargs: Any) -> Any:
        raise TimeoutError("connection timed out to 198.51.100.10:5432")

    pg_svc = PostgresService(
        store=store,
        vault=vault,
        default_credentials_service=defaults_svc,
        connection_factory=_unreachable_pg,
    )
    sftp_svc = SftpService(
        store=store,
        vault=vault,
        default_credentials_service=defaults_svc,
    )
    js_svc = JasperServerService(
        store=store,
        vault=vault,
        default_credentials_service=defaults_svc,
        http_transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})),
    )
    catalog_svc = ClientCatalogService(
        store=store,
        vault=vault,
        postgres_service=pg_svc,
        default_credentials_service=defaults_svc,
    )

    app = FastAPI()
    app.state.store = store
    app.state.secret_vault = vault
    app.state.default_credentials_service = defaults_svc
    app.state.workspace_service = workspace_svc
    app.state.subreport_service = subreport_svc
    app.state.jasper_daemon = daemon
    app.state.postgres_service = pg_svc
    app.state.sftp_service = sftp_svc
    app.state.jasperserver_service = js_svc
    app.state.client_catalog_service = catalog_svc

    for router in (
        system_api.router,
        projects_api.router,
        tools_api.router,
        preview_api.router,
        database_api.router,
        sftp_api.router,
        jasperserver_api.router,
        credentials_api.router,
        clients_api.router,
    ):
        app.include_router(router)

    client = TestClient(app)
    return {
        "client": client,
        "store": store,
        "workspace": workspace_svc,
        "daemon": daemon,
        "pg": pg_svc,
        "sftp": sftp_svc,
        "js": js_svc,
        "catalog": catalog_svc,
        "defaults": defaults_svc,
    }


# -----------------------------------------------------------------------------
# 1. Version Sync
# -----------------------------------------------------------------------------


def test_app_version_is_synced_to_1_1_1(qa_env: dict[str, Any]) -> None:
    assert APP_VERSION == "1.1.1"
    resp = qa_env["client"].get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.1.1"


# -----------------------------------------------------------------------------
# 2. blank_report starter JRXML & /jrxml/scaffold free-report fallback
# -----------------------------------------------------------------------------


def test_blank_report_creates_valid_starter_jrxml_and_supports_sync_compile_and_scaffold(
    qa_env: dict[str, Any],
) -> None:
    client: TestClient = qa_env["client"]

    # Create blank_report with no initial_jrxml
    create_resp = client.post(
        "/api/projects",
        json={"name": "Relatório Financeiro Livre", "entry_mode": "blank_report"},
    )
    assert create_resp.status_code == 201
    proj = create_resp.json()
    assert proj["project_kind"] == "free_report"
    assert proj["latest_artifacts"].get("jrxml") == 1

    # Starter JRXML is valid, passes strict linter, and has SELECT 1 AS exemplo + field exemplo
    art_resp = client.get(f"/api/projects/{proj['id']}/artifacts/jrxml")
    assert art_resp.status_code == 200
    starter_xml = art_resp.json()["content"]
    assert "SELECT 1 AS exemplo" in starter_xml
    assert 'name="exemplo"' in starter_xml
    lint = lint_jrxml(starter_xml)
    assert lint.is_valid is True, lint.to_dict()
    assert lint.errors == []
    assert lint.warnings == []

    # sync-query works immediately out of the box (both directions)
    sync_out = client.post(
        f"/api/projects/{proj['id']}/jasper/sync-query",
        json={"direction": "jrxml_to_sql"},
    )
    assert sync_out.status_code == 200
    assert "SELECT 1 AS exemplo" in sync_out.json()["sql_select"]

    sync_in = client.post(
        f"/api/projects/{proj['id']}/jasper/sync-query",
        json={"direction": "sql_to_jrxml", "sql_select": "SELECT 42 AS total_atendimentos"},
    )
    assert sync_in.status_code == 200
    assert "SELECT 42 AS total_atendimentos" in sync_in.json()["jrxml"]

    # compile works immediately out of the box
    comp_resp = client.post(f"/api/projects/{proj['id']}/jasper/compile", json={})
    assert comp_resp.status_code == 200
    assert comp_resp.json()["compiled"] is True

    # POST /jrxml/scaffold without any clinical JSON succeeds (NOT 404), supports PAISAGEM, and uses sql_select
    client.put(
        f"/api/projects/{proj['id']}/artifacts/sql_select",
        json={"content": "SELECT id, nome FROM paciente LIMIT 10"},
    )
    scaf_resp = client.post(
        f"/api/projects/{proj['id']}/jrxml/scaffold",
        json={"save_artifact": True, "options": {"orientation": "PAISAGEM"}},
    )
    assert scaf_resp.status_code == 200
    scaf_body = scaf_resp.json()
    assert scaf_body["lint"]["is_valid"] is True
    assert 'orientation="Landscape"' in scaf_body["jrxml"]
    assert 'pageWidth="842"' in scaf_body["jrxml"]
    assert "SELECT id, nome FROM paciente LIMIT 10" in scaf_body["jrxml"]


# -----------------------------------------------------------------------------
# 3. export-bundle stale PDF regeneration & JRXML-only 404 fix
# -----------------------------------------------------------------------------


def test_export_bundle_regenerates_stale_pdf_and_handles_jrxml_only_project(
    qa_env: dict[str, Any],
) -> None:
    client: TestClient = qa_env["client"]
    daemon: _MarkerPdfDaemon = qa_env["daemon"]

    jrxml_v1 = scaffold_free_report_jrxml(title="VERSAO_UM_ANTIGA", report_name="rel_teste")
    jrxml_v2 = scaffold_free_report_jrxml(title="VERSAO_DOIS_NOVA", report_name="rel_teste")

    # Import JRXML as clinical_form WITHOUT json or sql_insert (previously crashed with 404)
    create_resp = client.post(
        "/api/projects",
        json={
            "name": "Relatório Importado JRXML",
            "entry_mode": "jrxml",
            "project_kind": "clinical_form",
            "initial_jrxml": jrxml_v1,
        },
    )
    assert create_resp.status_code == 201
    proj = create_resp.json()
    project_id = proj["id"]
    slug = proj["slug"]

    # 1. Generate preview for v1
    prev_resp = client.post(
        f"/api/projects/{project_id}/jasper/preview",
        json={"scenario": "full", "mode": "offline"},
    )
    assert prev_resp.status_code == 200
    assert len(daemon.export_calls) == 1

    # 2. Save v2 WITHOUT re-running preview manually -> latest_preview.json becomes stale
    save_resp = client.put(
        f"/api/projects/{project_id}/artifacts/jrxml",
        json={"content": jrxml_v2, "summary": "Atualização v2"},
    )
    assert save_resp.status_code == 200

    # 3. Export bundle MUST succeed (no 404 despite missing json) AND re-run preview for v2
    bundle_resp = client.get(f"/api/projects/{project_id}/jasper/export-bundle?scenario=full&mode=offline")
    assert bundle_resp.status_code == 200
    assert len(daemon.export_calls) == 2

    with zipfile.ZipFile(io.BytesIO(bundle_resp.content), "r") as zf:
        names = set(zf.namelist())
        assert f"{slug}.jrxml" in names
        assert f"{slug}_relatorio_ficticio.pdf" in names
        assert f"{slug}_select.sql" in names  # fell back cleanly to <queryString>

        bundled_xml = zf.read(f"{slug}.jrxml").decode("utf-8")
        assert "VERSAO_DOIS_NOVA" in bundled_xml

        pdf_bytes = zf.read(f"{slug}_relatorio_ficticio.pdf")
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_text = "\n".join(p.get_text() for p in pdf_doc)
        pdf_doc.close()
        assert "VERSAO_DOIS_NOVA" in pdf_text
        assert "VERSAO_UM_ANTIGA" not in pdf_text

    # 4. Calling export-bundle again when NOT stale reuses cached PDF without extra export
    bundle_resp_2 = client.get(f"/api/projects/{project_id}/jasper/export-bundle?scenario=full&mode=offline")
    assert bundle_resp_2.status_code == 200
    assert len(daemon.export_calls) == 2

    # 5. JRXML-only project without <queryString> omits SQL cleanly instead of 404
    no_sql_xml = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="sem_sql" pageWidth="595" pageHeight="842" columnWidth="555" leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20" uuid="11111111-1111-4111-8111-111111111111">
    <detail><band height="20"/></detail>
</jasperReport>
"""
    no_sql_resp = client.post(
        "/api/projects",
        json={
            "name": "Sem SQL",
            "entry_mode": "jrxml",
            "project_kind": "clinical_form",
            "initial_jrxml": no_sql_xml,
        },
    )
    assert no_sql_resp.status_code == 201
    no_sql_proj = no_sql_resp.json()
    no_sql_zip = client.get(
        f"/api/projects/{no_sql_proj['id']}/jasper/export-bundle?scenario=full&mode=offline"
    )
    assert no_sql_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(no_sql_zip.content), "r") as zf:
        names = set(zf.namelist())
        assert names == {
            f"{no_sql_proj['slug']}.jrxml",
            f"{no_sql_proj['slug']}_relatorio_ficticio.pdf",
        }


# -----------------------------------------------------------------------------
# 4. JasperServer invalid base_url returns 422 instead of 500
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "10.0.0.5:8080/jasperserver",
        "file:///etc/passwd",
        "ftp://jasper.example.local",
        "http://",
        "   ",
    ],
)
def test_jasperserver_invalid_base_url_returns_422_not_500(
    qa_env: dict[str, Any],
    bad_url: str,
) -> None:
    assert issubclass(JasperServerValidationError, ValueError)
    assert issubclass(JasperServerValidationError, JasperServerError)

    client: TestClient = qa_env["client"]
    resp = client.post(
        "/api/jasperserver/profiles",
        json={
            "name": "Jasper Inválido",
            "base_url": bad_url,
            "username": "admin",
            "password": "secret",
        },
    )
    assert resp.status_code == 422

    # Valid profile update with invalid base_url also returns 422
    ok_resp = client.post(
        "/api/jasperserver/profiles",
        json={
            "name": "Jasper OK",
            "base_url": "https://jasper.example.local/jasperserver",
            "username": "admin",
            "password": "secret",
        },
    )
    assert ok_resp.status_code == 201
    prof_id = ok_resp.json()["id"]

    upd_resp = client.patch(
        f"/api/jasperserver/profiles/{prof_id}",
        json={"base_url": bad_url},
    )
    assert upd_resp.status_code == 422


# -----------------------------------------------------------------------------
# 5. SSH Private Key PEM Format Validation
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        "NOT A PEM",
        "-----BEGIN OPENSSH PRIVATE KEY-----\n-----END OPENSSH PRIVATE KEY-----",
        "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----",
        "   ",
    ],
)
def test_ssh_private_key_pem_validation_rejects_garbage_in_sftp_and_defaults(
    qa_env: dict[str, Any],
    bad_key: str,
) -> None:
    client: TestClient = qa_env["client"]

    # 1. SFTP profile create
    r_create = client.post(
        "/api/sftp/profiles",
        json={
            "name": "SFTP Chave Ruim",
            "host": "10.0.0.10",
            "username": "deploy",
            "auth_type": "private_key",
            "private_key": bad_key,
        },
    )
    assert r_create.status_code == 422

    # 2. Default SFTP credentials
    r_def = client.put(
        "/api/credentials/defaults/sftp",
        json={
            "username": "deploy",
            "auth_type": "private_key",
            "private_key": bad_key,
        },
    )
    assert r_def.status_code == 422

    # 3. Valid PEM succeeds and empty string clears
    valid_pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE_KEY_BODY_DATA\n-----END OPENSSH PRIVATE KEY-----"
    r_ok = client.post(
        "/api/sftp/profiles",
        json={
            "name": "SFTP Chave OK",
            "host": "10.0.0.11",
            "username": "deploy",
            "auth_type": "private_key",
            "private_key": valid_pem,
        },
    )
    assert r_ok.status_code == 201
    prof_id = r_ok.json()["id"]

    r_upd_bad = client.patch(
        f"/api/sftp/profiles/{prof_id}",
        json={"private_key": bad_key},
    )
    assert r_upd_bad.status_code == 422

    r_clear = client.patch(
        f"/api/sftp/profiles/{prof_id}",
        json={"private_key": ""},
    )
    assert r_clear.status_code == 200
    assert r_clear.json()["has_secret"] is False


# -----------------------------------------------------------------------------
# 6. Client System `system_url` scheme validation
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "ftp://files.example.local",
        "sem-esquema.example.local",
    ],
)
def test_client_system_url_rejects_unsafe_schemes(
    qa_env: dict[str, Any],
    bad_url: str,
) -> None:
    client: TestClient = qa_env["client"]

    unit_resp = client.post("/api/clients", json={"name": "Hospital Teste Segurança"})
    assert unit_resp.status_code == 201
    unit_id = unit_resp.json()["id"]

    r_create = client.post(
        f"/api/clients/{unit_id}/systems",
        json={"label": "Sistema XSS", "system_url": bad_url},
    )
    assert r_create.status_code == 422

    # Valid https:// and empty "" are accepted
    r_ok = client.post(
        f"/api/clients/{unit_id}/systems",
        json={"label": "Ambulatorial PRD", "system_url": "HTTPS://amb.example.local"},
    )
    assert r_ok.status_code == 201
    sys_id = r_ok.json()["id"]

    r_upd_bad = client.patch(
        f"/api/clients/{unit_id}/systems/{sys_id}",
        json={"system_url": bad_url},
    )
    assert r_upd_bad.status_code == 422

    r_upd_empty = client.patch(
        f"/api/clients/{unit_id}/systems/{sys_id}",
        json={"system_url": ""},
    )
    assert r_upd_empty.status_code == 200
    assert r_upd_empty.json()["system_url"] == ""


# -----------------------------------------------------------------------------
# 7. SELECT ... INTO blocked pre-connection & DB connection errors return 502
# -----------------------------------------------------------------------------


def test_select_into_blocked_pre_connection_and_unreachable_db_returns_502(
    qa_env: dict[str, Any],
) -> None:
    client: TestClient = qa_env["client"]
    pg: PostgresService = qa_env["pg"]

    for forbidden in (
        "SELECT * INTO nova_tabela FROM paciente",
        "SELECT id, nome INTO TEMP TABLE tmp_pac FROM paciente",
        "SELECT id INTO UNLOGGED t FROM paciente",
        "WITH cte AS (SELECT 1 AS x) SELECT * INTO hack_table FROM cte",
    ):
        with pytest.raises(DbProfileValidationError, match="SELECT ... INTO"):
            validate_and_bind_readonly_select(forbidden)

    # String literals and quoted identifiers containing "into" are NOT falsely rejected
    sql_ok, vals_ok = validate_and_bind_readonly_select(
        "SELECT 'SELECT * INTO ok' AS texto, \"into\" FROM paciente WHERE id = $P{id}",
        params={"id": 5},
    )
    assert vals_ok == [5]
    assert "%s" in sql_ok

    prof = pg.create_profile(
        DbProfileCreate(
            name="DB Timeout",
            host="198.51.100.10",
            dbname="salutem",
            user="readonly",
            password="pw",
            read_only=True,
        )
    )

    # Blocked BEFORE opening connection -> 400 (not 502 timeout)
    r_into = client.post(
        f"/api/db/profiles/{prof.id}/preview-select",
        json={"sql_select": "SELECT * INTO tabela_hack FROM paciente"},
    )
    assert r_into.status_code == 400
    assert "INTO" in r_into.json()["detail"]

    # Network timeout on schemas / tables / preview-select / databases -> 502 Bad Gateway
    assert client.get(f"/api/db/profiles/{prof.id}/schemas").status_code == 502
    assert client.get(f"/api/db/profiles/{prof.id}/tables").status_code == 502
    assert client.get(f"/api/db/profiles/{prof.id}/databases").status_code == 502
    r_prev_timeout = client.post(
        f"/api/db/profiles/{prof.id}/preview-select",
        json={"sql_select": "SELECT 1"},
    )
    assert r_prev_timeout.status_code == 502


# -----------------------------------------------------------------------------
# 8. Clean dangling profile references on delete
# -----------------------------------------------------------------------------


def test_deleting_profiles_clears_dangling_references_in_clients_and_projects(
    qa_env: dict[str, Any],
) -> None:
    pg: PostgresService = qa_env["pg"]
    sftp: SftpService = qa_env["sftp"]
    js: JasperServerService = qa_env["js"]
    catalog: ClientCatalogService = qa_env["catalog"]
    workspace: WorkspaceService = qa_env["workspace"]

    db_prof = pg.create_profile(
        DbProfileCreate(
            name="PG Principal",
            host="10.0.0.5",
            dbname="salutem",
            user="salutem_ro",
            password="secret",
            read_only=True,
        )
    )
    sftp_prof = sftp.create_profile(
        SftpProfileCreate(
            name="SFTP Principal",
            host="10.0.0.6",
            username="deploy",
            password="secret",
            linked_db_profile_id=db_prof.id,
        )
    )
    js_prof = js.create_profile(
        JasperServerProfileCreate(
            name="Jasper Principal",
            base_url="https://jasper.example.local/jasperserver",
            username="jasperadmin",
            password="secret",
            linked_db_profile_id=db_prof.id,
        )
    )

    unit = catalog.create_client(ClientUnitCreate(name="Unidade Referência"))
    system = catalog.upsert_system(
        unit.id,
        ClientSystemCreate(
            label="Ambulatorial PRD",
            system_url="https://amb.example.local",
            db_profile_id=db_prof.id,
            sftp_profile_id=sftp_prof.id,
            jasperserver_profile_id=js_prof.id,
        ),
    )
    project = workspace.create_project(
        ProjectCreate(
            name="Relatório Vinculado",
            entry_mode="blank_report",
            default_db_profile_id=db_prof.id,
            client_system_id=system.id,
        )
    )

    # 1. Delete DB profile -> clears client_systems.db_profile_id, projects.default_db_profile_id,
    #    sftp_profiles.linked_db_profile_id, and jasperserver_profiles.linked_db_profile_id
    assert pg.delete_profile(db_prof.id) is True
    refreshed_unit = catalog.get_client(unit.id)
    assert refreshed_unit.systems[0].db_profile_id is None
    assert refreshed_unit.systems[0].sftp_profile_id == sftp_prof.id
    assert refreshed_unit.systems[0].jasperserver_profile_id == js_prof.id
    assert workspace.get_project(project.id).default_db_profile_id is None
    assert sftp.get_profile(sftp_prof.id).linked_db_profile_id is None
    assert js.get_profile(js_prof.id).linked_db_profile_id is None

    # 2. Delete SFTP profile -> clears client_systems.sftp_profile_id
    assert sftp.delete_profile(sftp_prof.id) is True
    assert catalog.get_client(unit.id).systems[0].sftp_profile_id is None
    assert catalog.get_client(unit.id).systems[0].jasperserver_profile_id == js_prof.id

    # 3. Delete JasperServer profile -> clears client_systems.jasperserver_profile_id
    js.delete_profile(js_prof.id)
    assert catalog.get_client(unit.id).systems[0].jasperserver_profile_id is None
