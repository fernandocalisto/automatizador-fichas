# -*- coding: utf-8 -*-
"""Comprehensive tests for JasperReports Server REST v2 connector (`jasperserver_service.py` + `api/jasperserver.py`)."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import keyring
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from backend.app.api.jasperserver import router as jasperserver_router
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.default_credentials_service import (
    DefaultCredentialsService,
    DefaultCredentialUpdate,
)
from backend.app.services.jasper_daemon import JasperDaemonError
from backend.app.services.jasperserver_service import (
    JasperServerCompileError,
    JasperServerDeployTokenError,
    JasperServerProfileCreate,
    JasperServerProfileUpdate,
    JasperServerService,
    ReadOnlyJasperServerProfileError,
)
from backend.app.services.secret_vault import SecretVaultService
from backend.app.services.workspace_service import WorkspaceService

SAMPLE_MAIN_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="relatorio_internacao">
    <queryString><![CDATA[SELECT id, nome FROM paciente LIMIT 10]]></queryString>
    <detail>
        <band height="100">
            <subreport>
                <subreportExpression><![CDATA["repo:/shared/subreports/cabecalho_hospital.jrxml"]]></subreportExpression>
            </subreport>
            <subreport>
                <subreportExpression><![CDATA["repo:sub_embutido.jrxml"]]></subreportExpression>
            </subreport>
        </band>
    </detail>
</jasperReport>
"""

SAMPLE_UPDATED_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="relatorio_internacao">
    <queryString><![CDATA[SELECT id, nome, leito FROM paciente LIMIT 20]]></queryString>
    <detail>
        <band height="120">
            <subreport>
                <subreportExpression><![CDATA["repo:/shared/subreports/cabecalho_hospital.jrxml"]]></subreportExpression>
            </subreport>
        </band>
    </detail>
</jasperReport>
"""

SAMPLE_SUBREPORT_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="subreport_mock">
    <title><band height="20"/></title>
</jasperReport>
"""


class FakeJasperDaemon:
    """Deterministic fake JasperDaemonService for compile/decompile testing."""

    def __init__(self, *, fail_compile: bool = False, decompiled_xml: str = SAMPLE_MAIN_JRXML) -> None:
        self.fail_compile = fail_compile
        self.decompiled_xml = decompiled_xml
        self.compiled_calls: list[tuple[Path, Path | None]] = []
        self.decompiled_calls: list[tuple[Path, Path | None]] = []

    def compile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path is not None else in_p.with_suffix(".jasper")
        self.compiled_calls.append((in_p, out_p))
        if self.fail_compile:
            raise JasperDaemonError("Erro de sintaxe JRXML", error_type="COMPILE_ERROR")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(b"\xac\xed\x00\x05compiled-jasper-bytes")
        return {"status": "SUCCESS", "output": str(out_p)}

    def decompile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path is not None else in_p.with_suffix(".jrxml")
        self.decompiled_calls.append((in_p, out_p))
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(self.decompiled_xml, encoding="utf-8")
        return {"status": "SUCCESS", "output": str(out_p)}


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Isolate SQLite DB, encrypted vault (bypassing OS keyring), and workspaces per test."""

    def _raise_keyring(*args: Any, **kwargs: Any) -> Any:
        raise KeyringError("Keyring disabled in unit tests")

    monkeypatch.setattr(keyring, "set_password", _raise_keyring)
    monkeypatch.setattr(keyring, "get_password", _raise_keyring)
    monkeypatch.setattr(keyring, "delete_password", _raise_keyring)
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-vault-master-key-jasperserver-v1-1")

    store = SQLiteStore(tmp_path / "studio.db")
    vault = SecretVaultService(vault_path=tmp_path / ".vault.json")
    default_creds = DefaultCredentialsService(store=store, vault=vault)
    workspace = WorkspaceService(store=store, data_dir=tmp_path / "workspaces")
    return {
        "tmp_path": tmp_path,
        "store": store,
        "vault": vault,
        "default_creds": default_creds,
        "workspace": workspace,
    }


def _make_service(
    env: dict[str, Any],
    handler: Any,
) -> JasperServerService:
    return JasperServerService(
        store=env["store"],
        vault=env["vault"],
        default_credentials_service=env["default_creds"],
        http_transport=httpx.MockTransport(handler),
    )


# =============================================================================
# 1. Profile CRUD, PRD read_only default, SecretVault isolation & Default creds
# =============================================================================


def test_profile_crud_secret_isolation_and_prd_default_readonly(isolated_env: dict[str, Any]) -> None:
    svc = _make_service(isolated_env, lambda req: httpx.Response(200, json={}))

    prd_profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Jasper PRD Hospitalar",
            base_url="https://jasper-prd.example.local/jasperserver/",
            organization="org_hosp",
            username="jasperadmin",
            password="super-secret-password",
            credential_mode="custom",
            environment="PRD",
        )
    )
    assert prd_profile.base_url == "https://jasper-prd.example.local/jasperserver"
    assert prd_profile.read_only is True
    assert prd_profile.has_password is True
    assert prd_profile.organization == "org_hosp"

    # Verify password is NEVER stored in SQLite
    raw_sqlite = sqlite3.connect(isolated_env["store"].db_path).execute(
        "SELECT * FROM jasperserver_profiles WHERE id = ?",
        (prd_profile.id,),
    ).fetchall()
    assert "super-secret-password" not in str(raw_sqlite)
    assert "super-secret-password" not in json.dumps(prd_profile.model_dump())

    # Verify HML defaults read_only=False when omitted
    hml_profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Jasper HML",
            base_url="http://jasper-hml.example.local:8080/jasperserver/rest_v2",
            username="devuser",
            password="hml-pass",
            environment="HML",
        )
    )
    assert hml_profile.base_url == "http://jasper-hml.example.local:8080/jasperserver"
    assert hml_profile.read_only is False

    listed = svc.list_profiles()
    assert len(listed) == 2

    updated = svc.update_profile(
        hml_profile.id,
        JasperServerProfileUpdate(name="Jasper HML Updated", read_only=True, default_folder_uri="/relatorios"),
    )
    assert updated.name == "Jasper HML Updated"
    assert updated.read_only is True
    assert updated.default_folder_uri == "/relatorios"

    svc.delete_profile(prd_profile.id)
    assert len(svc.list_profiles()) == 1
    assert isolated_env["vault"].get_secret(f"jasperserver_password:{prd_profile.id}") is None


# =============================================================================
# 2. Auth: JSESSIONID cache, username|org, Basic fallback, 401 re-login & Default creds
# =============================================================================


def test_auth_jsessionid_org_and_401_relogin(isolated_env: dict[str, Any]) -> None:
    calls: list[dict[str, Any]] = []
    login_count = 0
    server_info_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_count, server_info_calls
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "cookie": request.headers.get("cookie"),
                "auth": request.headers.get("authorization"),
                "body": request.content.decode("utf-8", errors="replace"),
            }
        )
        if request.url.path.endswith("/rest_v2/login"):
            login_count += 1
            parsed = parse_qs(request.content.decode("utf-8"))
            assert parsed["j_username"] == ["js_user|org_alpha"]
            assert parsed["j_password"] == ["secret123"]
            return httpx.Response(
                200,
                headers={"Set-Cookie": f"JSESSIONID=SESS_TOKEN_{login_count}; Path=/jasperserver"},
            )
        if request.url.path.endswith("/rest_v2/serverInfo"):
            server_info_calls += 1
            # Simulate expired session on 2nd call to trigger single 401 re-login
            if server_info_calls == 2:
                return httpx.Response(401, text="Session expired")
            return httpx.Response(
                200,
                json={"version": "8.2.0", "editionName": "Community", "build": "20230510_1200"},
            )
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Org Server",
            base_url="https://js.example.local/jasperserver",
            organization="org_alpha",
            username="js_user",
            password="secret123",
            environment="HML",
        )
    )

    # First call: logs in once + fetches serverInfo with JSESSIONID=SESS_TOKEN_1
    res1 = svc.test_connection(profile.id)
    assert res1.ok is True
    assert res1.version == "8.2.0"
    assert res1.edition == "Community"
    assert res1.build == "20230510_1200"
    assert res1.latency_ms >= 0
    assert login_count == 1

    # Second call: reuses cached JSESSIONID -> gets 401 -> auto re-logins -> succeeds with SESS_TOKEN_2
    res2 = svc.test_connection(profile.id)
    assert res2.ok is True
    assert login_count == 2
    assert calls[-1]["cookie"] == "JSESSIONID=SESS_TOKEN_2"


def test_auth_basic_fallback_and_default_credentials(isolated_env: dict[str, Any]) -> None:
    seen_auth_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rest_v2/login"):
            # No Set-Cookie issued -> must fall back to HTTP Basic Auth
            return httpx.Response(200, text="OK")
        if request.url.path.endswith("/rest_v2/serverInfo"):
            auth_header = request.headers.get("authorization", "")
            seen_auth_headers.append(auth_header)
            expected = base64.b64encode(b"default_admin|default_org:default_secret").decode("ascii")
            assert auth_header == f"Basic {expected}"
            return httpx.Response(200, json={"version": "9.0.0", "edition": "CE", "build": "2025"})
        return httpx.Response(404)

    isolated_env["default_creds"].update_default(
        "jasperserver",
        DefaultCredentialUpdate(
            username="default_admin",
            organization="default_org",
            password="default_secret",
        ),
    )

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Default Creds Server",
            base_url="https://js-default.example.local/jasperserver",
            credential_mode="default",
            environment="DEV",
        )
    )
    assert profile.has_password is True

    res = svc.test_connection(profile.id)
    assert res.ok is True
    assert res.version == "9.0.0"
    assert len(seen_auth_headers) == 1


# =============================================================================
# 3. Repository Browsing & Report Unit Inspection
# =============================================================================


def test_list_resources_and_inspect_report_unit(isolated_env: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=TOK1"})
        if request.url.path.endswith("/rest_v2/resources") and request.method == "GET":
            folder_uri = request.url.params.get("folderUri")
            if folder_uri == "/empty":
                return httpx.Response(204)
            return httpx.Response(
                200,
                json={
                    "resourceLookup": [
                        {
                            "uri": "/reports/internacao_resumo",
                            "label": "Resumo de Internação",
                            "description": "Relatório hospitalar",
                            "resourceType": "reportUnit",
                            "updateDate": "2026-03-01T10:00:00",
                        },
                        {
                            "uri": "/reports/hospitalar",
                            "label": "Hospitalar",
                            "resourceType": "folder",
                        },
                        {
                            "uri": "/datasources/pg_hospitalar",
                            "label": "PG Hospitalar",
                            "resourceType": "jdbcDataSource",
                        },
                        {
                            "uri": "/shared/cabecalho.jrxml",
                            "label": "cabecalho.jrxml",
                            "resourceType": "file",
                        },
                        {
                            "uri": "/shared/rodape.jasper",
                            "label": "rodape.jasper",
                            "resourceType": "file",
                        },
                    ]
                },
            )
        if request.url.path.endswith("/rest_v2/resources/reports/internacao_resumo"):
            assert request.headers.get("accept") == "application/repository.reportUnit+json"
            return httpx.Response(
                200,
                json={
                    "uri": "/reports/internacao_resumo",
                    "label": "Resumo de Internação",
                    "description": "Alta hospitalar",
                    "jrxml": {
                        "jrxmlFileReference": {
                            "uri": "/reports/internacao_resumo_files/main_jrxml"
                        }
                    },
                    "dataSource": {
                        "dataSourceReference": {"uri": "/datasources/pg_hospitalar"}
                    },
                    "inputControls": [
                        {"inputControlReference": {"uri": "/reports/internacao_resumo_files/p_id"}}
                    ],
                    "resources": {
                        "resource": [
                            {
                                "name": "sub_embutido.jrxml",
                                "file": {
                                    "fileReference": {
                                        "uri": "/reports/internacao_resumo_files/sub_embutido.jrxml",
                                        "type": "jrxml",
                                    }
                                },
                            },
                            {
                                "name": "logo.png",
                                "file": {
                                    "fileResource": {
                                        "uri": "/reports/internacao_resumo_files/logo.png",
                                        "type": "img",
                                    }
                                },
                            },
                        ]
                    },
                },
            )
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Browse Server",
            base_url="https://js.example.local/jasperserver",
            username="admin",
            password="pw",
        )
    )

    items = svc.list_resources(profile.id, folder_uri="/reports")
    types_by_uri = {item.uri: item.resource_type for item in items}
    assert types_by_uri["/reports/hospitalar"] == "folder"
    assert types_by_uri["/reports/internacao_resumo"] == "reportUnit"
    assert types_by_uri["/datasources/pg_hospitalar"] == "datasource"
    assert types_by_uri["/shared/cabecalho.jrxml"] == "jrxml"
    assert types_by_uri["/shared/rodape.jasper"] == "jasper"
    assert items[0].resource_type == "folder"  # Folders sorted first

    assert svc.list_resources(profile.id, folder_uri="/empty") == []

    detail = svc.inspect_report_unit(profile.id, "/reports/internacao_resumo")
    assert detail.main_jrxml_uri == "/reports/internacao_resumo_files/main_jrxml"
    assert detail.datasource_uri == "/datasources/pg_hospitalar"
    assert detail.input_controls == ["/reports/internacao_resumo_files/p_id"]
    assert len(detail.resources) == 2


# =============================================================================
# 4. Import Report Unit with Hybrid Subreports ({uri}_files/* + repo:/...) & .jasper Decompile
# =============================================================================


def test_import_report_unit_hybrid_subreports(isolated_env: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=IMP1"})
        if path.endswith("/rest_v2/resources/reports/alta"):
            if request.url.params.get("file") == "jrxml":
                # Simulate server returning 404 on ?file=jrxml to test fallback to main_jrxml_uri
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "uri": "/reports/alta",
                    "label": "Relatório de Alta",
                    "description": "Resumo hospitalar",
                    "jrxml": {
                        "jrxmlFileReference": {"uri": "/reports/alta_files/main_jrxml"}
                    },
                    "dataSource": {
                        "dataSourceReference": {"uri": "/datasources/pg_hosp"}
                    },
                    "resources": {
                        "resource": [
                            {
                                "name": "sub_embutido.jrxml",
                                "file": {
                                    "fileReference": {
                                        "uri": "/reports/alta_files/sub_embutido.jrxml",
                                        "type": "jrxml",
                                    }
                                },
                            },
                            {
                                "name": "logo.png",
                                "file": {
                                    "fileReference": {
                                        "uri": "/reports/alta_files/logo.png",
                                        "type": "img",
                                    }
                                },
                            },
                        ]
                    },
                },
            )
        if path.endswith("/rest_v2/resources/reports/alta_files/main_jrxml"):
            return httpx.Response(200, content=SAMPLE_MAIN_JRXML.encode("utf-8"))
        if path.endswith("/rest_v2/resources/reports/alta_files/sub_embutido.jrxml"):
            return httpx.Response(200, content=SAMPLE_SUBREPORT_JRXML.encode("utf-8"))
        if path.endswith("/rest_v2/resources/reports/alta_files/logo.png"):
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfake-png")
        if path.endswith("/rest_v2/resources/shared/subreports/cabecalho_hospital.jrxml"):
            return httpx.Response(200, content=SAMPLE_SUBREPORT_JRXML.encode("utf-8"))
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Hospitalar HML",
            base_url="https://js.example.local/jasperserver",
            username="admin",
            password="pw",
            linked_db_profile_id="pg-hosp-1",
        )
    )
    daemon = FakeJasperDaemon()

    project = svc.import_report_to_project(
        profile.id,
        "/reports/alta",
        isolated_env["workspace"],
        daemon,
        sync_subreports=True,
    )

    assert project.project_kind == "free_report"
    assert project.entry_mode == "jasperserver_import"
    assert project.default_db_profile_id == "pg-hosp-1"
    assert project.source_origin["provider"] == "jasperserver"
    assert project.source_origin["profile_id"] == profile.id
    assert project.source_origin["resource_uri"] == "/reports/alta"
    assert project.source_origin["main_jrxml_uri"] == "/reports/alta_files/main_jrxml"
    assert project.source_origin["datasource_uri"] == "/datasources/pg_hosp"

    # Original main_jrxml kept intact with repo:/... references for clean re-deploy
    saved_jrxml = isolated_env["workspace"].get_latest_artifact(project.id, "jrxml").content
    assert 'repo:/shared/subreports/cabecalho_hospital.jrxml' in saved_jrxml

    # Both embedded ({uri}_files/*) and shared (repo:/...) subreports downloaded & compiled!
    res_dir = Path(project.workspace_dir) / "report_unit_resources"
    assert (res_dir / "sub_embutido.jrxml").is_file()
    assert (res_dir / "sub_embutido.jasper").is_file()
    assert (res_dir / "logo.png").is_file()
    assert (res_dir / "cabecalho_hospital.jrxml").is_file()
    assert (res_dir / "cabecalho_hospital.jasper").is_file()
    assert len(daemon.compiled_calls) == 2


def test_import_decompiles_jasper_binary_automatically(isolated_env: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=DEC1"})
        if request.url.path.endswith("/rest_v2/resources/reports/legado"):
            if request.url.params.get("file") == "jrxml":
                return httpx.Response(200, content=b"\xac\xed\x00\x05binary-jasper")
            return httpx.Response(
                200,
                json={
                    "uri": "/reports/legado",
                    "label": "Relatório Legado",
                    "jrxml": {"jrxmlFileReference": {"uri": "/reports/legado_files/main.jasper"}},
                },
            )
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Legacy Server",
            base_url="https://js.example.local/jasperserver",
            username="admin",
            password="pw",
        )
    )
    daemon = FakeJasperDaemon(decompiled_xml=SAMPLE_SUBREPORT_JRXML)

    project = svc.import_report_to_project(
        profile.id,
        "/reports/legado",
        isolated_env["workspace"],
        daemon,
        sync_subreports=False,
    )
    assert len(daemon.decompiled_calls) == 1
    saved = isolated_env["workspace"].get_latest_artifact(project.id, "jrxml").content
    assert 'name="subreport_mock"' in saved


# =============================================================================
# 5. Deploy Safety: read_only block, failed compile block, Update + Backup, Create, Single-Use Token
# =============================================================================


def test_deploy_blocks_readonly_and_failed_compile(isolated_env: dict[str, Any]) -> None:
    svc = _make_service(isolated_env, lambda req: httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=D1"}))
    project = isolated_env["workspace"].create_project(
        ProjectCreate(
            name="Ficha Deploy Test",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_UPDATED_JRXML,
        )
    )

    prd_profile = svc.create_profile(
        JasperServerProfileCreate(
            name="PRD Locked",
            base_url="https://js-prd.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="PRD",  # defaults read_only=True
        )
    )
    with pytest.raises(ReadOnlyJasperServerProfileError):
        svc.prepare_deploy_preview(
            project.id,
            prd_profile.id,
            isolated_env["workspace"],
            FakeJasperDaemon(),
            mode="update",
            target_uri="/reports/alta",
        )

    hml_profile = svc.create_profile(
        JasperServerProfileCreate(
            name="HML Writable",
            base_url="https://js-hml.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="HML",
            read_only=False,
        )
    )
    with pytest.raises(JasperServerCompileError):
        svc.prepare_deploy_preview(
            project.id,
            hml_profile.id,
            isolated_env["workspace"],
            FakeJasperDaemon(fail_compile=True),
            mode="update",
            target_uri="/reports/alta",
        )


def test_deploy_update_with_backup_and_single_use_token(isolated_env: dict[str, Any]) -> None:
    put_requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=UPD1"})
        if request.method == "GET" and path.endswith("/rest_v2/resources/reports/alta"):
            return httpx.Response(
                200,
                json={
                    "uri": "/reports/alta",
                    "label": "Alta",
                    "jrxml": {"jrxmlFileReference": {"uri": "/reports/alta_files/main_jrxml"}},
                },
            )
        if request.method == "GET" and path.endswith("/rest_v2/resources/reports/alta_files/main_jrxml"):
            return httpx.Response(200, content=SAMPLE_MAIN_JRXML.encode("utf-8"))
        if request.method == "PUT" and path.endswith("/rest_v2/resources/reports/alta_files/main_jrxml"):
            put_requests.append(
                {
                    "params": dict(request.url.params),
                    "content_type": request.headers.get("content-type"),
                    "body": json.loads(request.content.decode("utf-8")),
                }
            )
            return httpx.Response(200, json={"uri": "/reports/alta_files/main_jrxml"})
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    hml_profile = svc.create_profile(
        JasperServerProfileCreate(
            name="HML Deploy",
            base_url="https://js-hml.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="HML",
            read_only=False,
        )
    )
    project = isolated_env["workspace"].create_project(
        ProjectCreate(
            name="Alta Atualizada",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_UPDATED_JRXML,
        )
    )

    preview = svc.prepare_deploy_preview(
        project.id,
        hml_profile.id,
        isolated_env["workspace"],
        FakeJasperDaemon(),
        mode="update",
        target_uri="/reports/alta",
    )
    assert preview.ok is True
    assert preview.compiled_ok is True
    assert preview.remote_exists is True
    assert preview.main_jrxml_uri == "/reports/alta_files/main_jrxml"
    assert preview.remote_sha256 is not None
    assert preview.local_sha256 != preview.remote_sha256
    assert "-    <queryString><![CDATA[SELECT id, nome FROM paciente LIMIT 10]]></queryString>" in preview.unified_diff
    assert "+    <queryString><![CDATA[SELECT id, nome, leito FROM paciente LIMIT 20]]></queryString>" in preview.unified_diff

    result = svc.execute_deploy(project.id, preview.deploy_token, isolated_env["workspace"])
    assert result.ok is True
    assert result.mode == "update"
    assert result.local_backup_path is not None

    backup_path = Path(result.local_backup_path)
    assert backup_path.is_file()
    assert backup_path.name.startswith("jasperserver_")
    assert backup_path.name.endswith("_main.jrxml")
    assert "SELECT id, nome FROM paciente LIMIT 10" in backup_path.read_text(encoding="utf-8")

    assert len(put_requests) == 1
    assert put_requests[0]["params"] == {"overwrite": "true", "createFolders": "true"}
    assert put_requests[0]["content_type"] == "application/repository.file+json"
    assert put_requests[0]["body"]["type"] == "jrxml"
    decoded_sent = base64.b64decode(put_requests[0]["body"]["content"]).decode("utf-8")
    assert "SELECT id, nome, leito FROM paciente LIMIT 20" in decoded_sent

    # Single-use token MUST fail on replay
    with pytest.raises(JasperServerDeployTokenError):
        svc.execute_deploy(project.id, preview.deploy_token, isolated_env["workspace"])


def test_deploy_create_new_report_unit(isolated_env: dict[str, Any]) -> None:
    put_requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=CRT1"})
        if request.method == "GET" and path.endswith("/rest_v2/resources/reports/novo_relatorio"):
            return httpx.Response(404)
        if request.method == "PUT" and path.endswith("/rest_v2/resources/reports/novo_relatorio"):
            put_requests.append(
                {
                    "params": dict(request.url.params),
                    "content_type": request.headers.get("content-type"),
                    "body": json.loads(request.content.decode("utf-8")),
                }
            )
            return httpx.Response(201, json={"uri": "/reports/novo_relatorio"})
        return httpx.Response(404)

    svc = _make_service(isolated_env, handler)
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="HML Create",
            base_url="https://js-hml.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="HML",
            read_only=False,
        )
    )
    project = isolated_env["workspace"].create_project(
        ProjectCreate(
            name="Novo Relatório Hospitalar",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_UPDATED_JRXML,
        )
    )

    preview = svc.prepare_deploy_preview(
        project.id,
        profile.id,
        isolated_env["workspace"],
        FakeJasperDaemon(),
        mode="create",
        target_uri="/reports/novo_relatorio",
        label="Relatório Novo",
        datasource_uri="/datasources/pg_hosp",
    )
    assert preview.remote_exists is False
    assert preview.mode == "create"

    res = svc.execute_deploy(project.id, preview.deploy_token, isolated_env["workspace"])
    assert res.ok is True
    assert res.mode == "create"
    assert res.target_uri == "/reports/novo_relatorio"
    assert len(put_requests) == 1
    assert put_requests[0]["params"] == {"overwrite": "false", "createFolders": "true"}
    assert put_requests[0]["content_type"] == "application/repository.reportUnit+json"
    body = put_requests[0]["body"]
    assert body["label"] == "Relatório Novo"
    assert body["dataSource"]["dataSourceReference"]["uri"] == "/datasources/pg_hosp"
    assert body["jrxml"]["jrxmlFile"]["type"] == "jrxml"
    decoded_xml = base64.b64decode(body["jrxml"]["jrxmlFile"]["content"]).decode("utf-8")
    assert "relatorio_internacao" in decoded_xml


# =============================================================================
# 6. FastAPI Router End-to-End Test (incl. HTTP 403 on read_only)
# =============================================================================


def test_fastapi_router_endpoints_and_403_readonly(isolated_env: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=API1"})
        if path.endswith("/rest_v2/serverInfo"):
            return httpx.Response(200, json={"version": "8.1.1", "edition": "CE", "build": "B1"})
        if path.endswith("/rest_v2/resources"):
            return httpx.Response(
                200,
                json={"resourceLookup": [{"uri": "/reports/u1", "label": "Unit 1", "resourceType": "reportUnit"}]},
            )
        if path.endswith("/rest_v2/resources/reports/u1"):
            if request.url.params.get("file") == "jrxml":
                return httpx.Response(200, content=SAMPLE_SUBREPORT_JRXML.encode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "uri": "/reports/u1",
                    "label": "Unit 1",
                    "jrxml": {"jrxmlFileReference": {"uri": "/reports/u1_files/main_jrxml"}},
                },
            )
        return httpx.Response(404)

    app = FastAPI()
    app.include_router(jasperserver_router)
    app.state.store = isolated_env["store"]
    app.state.workspace_service = isolated_env["workspace"]
    app.state.jasperserver_service = _make_service(isolated_env, handler)
    app.state.jasper_daemon = FakeJasperDaemon()

    client = TestClient(app)

    # Create PRD profile via API -> read_only defaults True
    resp = client.post(
        "/api/jasperserver/profiles",
        json={
            "name": "API PRD",
            "base_url": "https://api-js.example.local/jasperserver",
            "username": "admin",
            "password": "secret",
            "environment": "PRD",
        },
    )
    assert resp.status_code == 201
    prof = resp.json()
    assert prof["read_only"] is True
    assert prof["has_password"] is True
    assert "password" not in prof

    # Test connection
    t_resp = client.post(f"/api/jasperserver/profiles/{prof['id']}/test")
    assert t_resp.status_code == 200
    assert t_resp.json()["ok"] is True
    assert t_resp.json()["version"] == "8.1.1"

    # List resources
    r_resp = client.get(f"/api/jasperserver/profiles/{prof['id']}/resources", params={"folder_uri": "/reports"})
    assert r_resp.status_code == 200
    assert r_resp.json()[0]["uri"] == "/reports/u1"

    # Import report unit
    imp_resp = client.post(
        "/api/jasperserver/import",
        json={"profile_id": prof["id"], "resource_uri": "/reports/u1", "sync_subreports": False},
    )
    assert imp_resp.status_code == 201
    proj = imp_resp.json()
    assert proj["entry_mode"] == "jasperserver_import"

    # Deploy prepare on read_only PRD profile MUST return HTTP 403
    prep_resp = client.post(
        f"/api/projects/{proj['id']}/deploy/jasperserver/prepare",
        json={
            "profile_id": prof["id"],
            "mode": "update",
            "target_uri": "/reports/u1",
        },
    )
    assert prep_resp.status_code == 403
