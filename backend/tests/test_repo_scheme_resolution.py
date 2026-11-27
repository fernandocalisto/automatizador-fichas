# -*- coding: utf-8 -*-
"""
Testes E2E (JVM real + JasperServerService + FastAPI Preview) para resolução nativa
do esquema `repo:/...` (`backend/tests/test_repo_scheme_resolution.py`).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Iterator

import fitz
import httpx
import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from backend.app.api import jasper_preview
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.main import create_app
from backend.app.services.default_credentials_service import DefaultCredentialsService
from backend.app.services.jasper_daemon import JasperDaemonError, JasperDaemonService
from backend.app.services.jasperserver_service import (
    JasperServerProfileCreate,
    JasperServerService,
    _extract_repo_uris_from_jrxml,
)
from backend.app.services.secret_vault import SecretVaultService
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import WorkspaceService

# Minimal valid 1x1 red PNG (67 bytes)
TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

SAMPLE_STYLE_JRTX = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE jasperTemplate PUBLIC "-//JasperReports//DTD Template//EN"
  "http://jasperreports.sourceforge.net/dtds/jaspertemplate.dtd">
<jasperTemplate>
    <style name="TituloHospitalar" fontName="SansSerif" fontSize="12" isBold="true"/>
</jasperTemplate>
"""

HEADER_SUBREPORT_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="cabecalho_receituario"
              pageWidth="555" pageHeight="80" columnWidth="555"
              leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0"
              whenNoDataType="AllSectionsNoDetail">
    <title>
        <band height="60">
            <image>
                <reportElement x="0" y="5" width="40" height="40"/>
                <imageExpression><![CDATA["repo:/Hospitalar/Imagens/logo.png"]]></imageExpression>
            </image>
            <staticText>
                <reportElement x="50" y="10" width="480" height="30"/>
                <textElement verticalAlignment="Middle">
                    <font size="12" isBold="true"/>
                </textElement>
                <text><![CDATA[HOSPITAL SALUTEM - CABECALHO RECEITUARIO]]></text>
            </staticText>
        </band>
    </title>
</jasperReport>
"""

HEADER_WITH_STYLE_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="cabecalho_com_estilo"
              pageWidth="555" pageHeight="80" columnWidth="555"
              leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0"
              whenNoDataType="AllSectionsNoDetail">
    <template><![CDATA["repo:/Hospitalar/Estilos/base.jrtx"]]></template>
    <title>
        <band height="60">
            <image>
                <reportElement x="0" y="5" width="40" height="40"/>
                <imageExpression><![CDATA["repo:/Hospitalar/Imagens/logo.png"]]></imageExpression>
            </image>
            <staticText>
                <reportElement x="50" y="10" width="480" height="30" style="TituloHospitalar"/>
                <text><![CDATA[CABECALHO COM ESTILO JRTX E LOGO]]></text>
            </staticText>
        </band>
    </title>
</jasperReport>
"""

MAIN_GUIA_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="GUIA_ENCAMINHAMENTO"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20"
              whenNoDataType="AllSectionsNoDetail">
    <field name="pac_nome" class="java.lang.String"/>
    <title>
        <band height="75">
            <subreport>
                <reportElement x="0" y="0" width="555" height="65"/>
                <dataSourceExpression><![CDATA[new net.sf.jasperreports.engine.JREmptyDataSource(1)]]></dataSourceExpression>
                <subreportExpression><![CDATA["repo:/Hospitalar/Cabecalhos/cabecalho_receituario"]]></subreportExpression>
            </subreport>
        </band>
    </title>
    <detail>
        <band height="60">
            <staticText>
                <reportElement x="0" y="5" width="555" height="20"/>
                <textElement><font size="11" isBold="true"/></textElement>
                <text><![CDATA[GUIA DE ENCAMINHAMENTO AMBULATORIAL]]></text>
            </staticText>
            <textField isBlankWhenNull="true">
                <reportElement x="0" y="30" width="555" height="20"/>
                <textFieldExpression><![CDATA["Paciente: " + ($F{pac_nome} != null ? $F{pac_nome} : "N/A")]]></textFieldExpression>
            </textField>
        </band>
    </detail>
</jasperReport>
"""

RELATIVE_SUBREPORT_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="sub_local"
              pageWidth="555" pageHeight="40" columnWidth="555"
              leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0"
              whenNoDataType="AllSectionsNoDetail">
    <title>
        <band height="30">
            <staticText>
                <reportElement x="0" y="0" width="555" height="24"/>
                <text><![CDATA[SUBREPORT RELATIVO RESOLVIDO COM SUCESSO]]></text>
            </staticText>
        </band>
    </title>
</jasperReport>
"""

MAIN_RELATIVE_REPO_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="RELATORIO_RELATIVO"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20"
              whenNoDataType="AllSectionsNoDetail">
    <title>
        <band height="50">
            <subreport>
                <reportElement x="0" y="0" width="555" height="40"/>
                <dataSourceExpression><![CDATA[new net.sf.jasperreports.engine.JREmptyDataSource(1)]]></dataSourceExpression>
                <subreportExpression><![CDATA["repo:sub_local.jrxml"]]></subreportExpression>
            </subreport>
        </band>
    </title>
</jasperReport>
"""


@pytest.fixture(scope="module")
def jvm_daemon() -> Iterator[JasperDaemonService]:
    svc = JasperDaemonService()
    svc.ensure_started()
    try:
        yield svc
    finally:
        svc.stop()


# =============================================================================
# 1. JVM E2E: Native `repo:/...` Resolution (extensionless subreport + nested image + style)
# =============================================================================


def test_jvm_e2e_repo_scheme_extensionless_subreport_and_nested_image(
    jvm_daemon: JasperDaemonService,
    tmp_path: Path,
) -> None:
    """
    Compila e exporta PDF na JVM real para `GUIA_ENCAMINHAMENTO` referenciando
    `"repo:/Hospitalar/Cabecalhos/cabecalho_receituario"` (sem extensão!), cujo
    subreport compilado referencia `"repo:/Hospitalar/Imagens/logo.png"`, sem
    alterar 1 caractere do JRXML original.
    """
    resources_dir = tmp_path / "report_unit_resources"
    cab_dir = resources_dir / "repo" / "Hospitalar" / "Cabecalhos"
    img_dir = resources_dir / "repo" / "Hospitalar" / "Imagens"
    cab_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    # Logo PNG no espelho repo/
    (img_dir / "logo.png").write_bytes(TINY_PNG_BYTES)

    # Subreport compilado (.jasper) no espelho repo/
    sub_jrxml = cab_dir / "cabecalho_receituario.jrxml"
    sub_jasper = cab_dir / "cabecalho_receituario.jasper"
    sub_jrxml.write_text(HEADER_SUBREPORT_JRXML, encoding="utf-8")
    comp = jvm_daemon.compile(sub_jrxml, sub_jasper, subreport_dir=resources_dir)
    assert comp["status"] == "SUCCESS"
    assert sub_jasper.is_file()

    # JRXML principal sem nenhuma alteração
    main_jrxml_path = tmp_path / "GUIA_ENCAMINHAMENTO.jrxml"
    main_jrxml_path.write_text(MAIN_GUIA_JRXML, encoding="utf-8")
    original_snapshot = main_jrxml_path.read_text(encoding="utf-8")

    pdf_path = tmp_path / "GUIA_ENCAMINHAMENTO.pdf"
    export_res = jvm_daemon.export_pdf(
        main_jrxml_path,
        pdf_path,
        mock_rows=[{"pac_nome": "JOAO CARLOS DE SOUZA"}],
        subreport_dir=resources_dir,
    )
    assert export_res["status"] == "SUCCESS"
    assert export_res["pages"] == 1
    assert pdf_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF")

    # JRXML original preservado byte a byte
    assert main_jrxml_path.read_text(encoding="utf-8") == original_snapshot

    with fitz.open(pdf_path) as doc:
        assert doc.page_count == 1
        text = doc[0].get_text("text")
        images = doc[0].get_images(full=True)

    assert "HOSPITAL SALUTEM - CABECALHO RECEITUARIO" in text
    assert "GUIA DE ENCAMINHAMENTO AMBULATORIAL" in text
    assert "JOAO CARLOS DE SOUZA" in text
    assert len(images) >= 1, "Logo referenciado via repo:/Hospitalar/Imagens/logo.png deve estar embutido no PDF"


def test_jvm_e2e_repo_scheme_relative_basename_style_and_traversal_blocked(
    jvm_daemon: JasperDaemonService,
    tmp_path: Path,
) -> None:
    """
    Valida:
    - Fallback por basename para `repo:sub_local.jrxml` -> `sub_local.jasper` em `<subreportDir>`;
    - Resolução de `<template><![CDATA["repo:/Hospitalar/Estilos/base.jrtx"]]></template>`;
    - Bloqueio de path traversal (`repo:/../../segredo.jasper`).
    """
    resources_dir = tmp_path / "res"
    resources_dir.mkdir(parents=True, exist_ok=True)

    # 1. Basename fallback: só o .jasper em resources_dir (sem pasta repo/)
    sub_jrxml = tmp_path / "sub_local.jrxml"
    sub_jrxml.write_text(RELATIVE_SUBREPORT_JRXML, encoding="utf-8")
    sub_jasper = resources_dir / "sub_local.jasper"
    jvm_daemon.compile(sub_jrxml, sub_jasper)
    assert sub_jasper.is_file()

    main_rel = tmp_path / "main_rel.jrxml"
    main_rel.write_text(MAIN_RELATIVE_REPO_JRXML, encoding="utf-8")
    pdf_rel = tmp_path / "main_rel.pdf"
    res = jvm_daemon.export_pdf(main_rel, pdf_rel, subreport_dir=resources_dir)
    assert res["status"] == "SUCCESS"
    with fitz.open(pdf_rel) as doc:
        assert "SUBREPORT RELATIVO RESOLVIDO COM SUCESSO" in doc[0].get_text("text")

    # 2. Style template (.jrtx) + image via repo:/...
    (resources_dir / "repo" / "Hospitalar" / "Estilos").mkdir(parents=True, exist_ok=True)
    (resources_dir / "repo" / "Hospitalar" / "Imagens").mkdir(parents=True, exist_ok=True)
    (resources_dir / "repo" / "Hospitalar" / "Estilos" / "base.jrtx").write_text(
        SAMPLE_STYLE_JRTX, encoding="utf-8"
    )
    (resources_dir / "repo" / "Hospitalar" / "Imagens" / "logo.png").write_bytes(TINY_PNG_BYTES)

    styled_jrxml = tmp_path / "styled.jrxml"
    styled_jrxml.write_text(HEADER_WITH_STYLE_JRXML, encoding="utf-8")
    styled_pdf = tmp_path / "styled.pdf"
    res_style = jvm_daemon.export_pdf(styled_jrxml, styled_pdf, subreport_dir=resources_dir)
    assert res_style["status"] == "SUCCESS"
    with fitz.open(styled_pdf) as doc:
        assert "CABECALHO COM ESTILO JRTX E LOGO" in doc[0].get_text("text")
        assert len(doc[0].get_images(full=True)) >= 1

    # 3. Path traversal rejeitado (não acessa arquivo fora do diretório de recursos)
    outside_jasper = tmp_path / "outside_secret.jasper"
    outside_jasper.write_bytes(sub_jasper.read_bytes())
    traversal_jrxml = MAIN_RELATIVE_REPO_JRXML.replace(
        "repo:sub_local.jrxml",
        "repo:/../outside_secret.jasper",
    )
    traversal_path = tmp_path / "traversal.jrxml"
    traversal_path.write_text(traversal_jrxml, encoding="utf-8")
    with pytest.raises(JasperDaemonError) as exc_info:
        jvm_daemon.export_pdf(
            traversal_path,
            tmp_path / "traversal.pdf",
            subreport_dir=resources_dir,
        )
    assert exc_info.value.error_type == "FILL_ERROR"


# =============================================================================
# 2. Backend JasperServerService: extraction, reportUnit subreport, tree mirror & cache reuse
# =============================================================================


def test_jasperserver_extract_mirror_reportunit_subreport_and_shared_cache(
    jvm_daemon: JasperDaemonService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "studio_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-repo-engine-vault-key")

    def _raise_keyring(*args: Any, **kwargs: Any) -> Any:
        raise KeyringError("disabled in test")

    monkeypatch.setattr(keyring, "set_password", _raise_keyring)
    monkeypatch.setattr(keyring, "get_password", _raise_keyring)
    monkeypatch.setattr(keyring, "delete_password", _raise_keyring)

    # Valida extração expandida (<subreportExpression>, <imageExpression>, <template>)
    extracted = _extract_repo_uris_from_jrxml(HEADER_WITH_STYLE_JRXML)
    assert "/Hospitalar/Estilos/base.jrtx" in extracted
    assert "/Hospitalar/Imagens/logo.png" in extracted

    remote_hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=REPO_CACHE_1"})

        remote_hits.append(f"{path}?{request.url.query.decode()}" if request.url.query else path)

        # Extensionless reportUnit used as subreport!
        if path.endswith("/rest_v2/resources/Hospitalar/Cabecalhos/cabecalho_receituario"):
            if request.url.params.get("file") == "jrxml":
                return httpx.Response(200, content=HEADER_WITH_STYLE_JRXML.encode("utf-8"))
            return httpx.Response(
                200,
                headers={"Content-Type": "application/repository.reportUnit+json"},
                json={
                    "uri": "/Hospitalar/Cabecalhos/cabecalho_receituario",
                    "label": "cabecalho_receituario",
                    "jrxml": {
                        "jrxmlFileReference": {
                            "uri": "/Hospitalar/Cabecalhos/cabecalho_receituario_files/main_jrxml"
                        }
                    },
                },
            )
        if path.endswith("/rest_v2/resources/Hospitalar/Imagens/logo.png"):
            return httpx.Response(200, content=TINY_PNG_BYTES, headers={"Content-Type": "image/png"})
        if path.endswith("/rest_v2/resources/Hospitalar/Estilos/base.jrtx"):
            return httpx.Response(
                200,
                content=SAMPLE_STYLE_JRTX.encode("utf-8"),
                headers={"Content-Type": "application/xml"},
            )
        return httpx.Response(404)

    store = SQLiteStore(data_dir / "studio.db")
    vault = SecretVaultService(vault_path=data_dir / ".vault.json")
    default_creds = DefaultCredentialsService(store=store, vault=vault)
    svc = JasperServerService(
        store=store,
        vault=vault,
        default_credentials_service=default_creds,
        http_transport=httpx.MockTransport(handler),
    )
    profile = svc.create_profile(
        JasperServerProfileCreate(
            name="Hosp Test",
            base_url="https://jasper.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="HML",
        )
    )

    # Projeto 1: baixa tudo do servidor remoto, espelha em repo/ + cache + basename e compila
    res_dir_1 = tmp_path / "proj1" / "report_unit_resources"
    sync1 = svc.sync_missing_repo_resources(
        profile.id,
        MAIN_GUIA_JRXML,
        res_dir_1,
        jvm_daemon,
        resource_uri="/Hospitalar/Guias/GUIA_ENCAMINHAMENTO",
    )
    assert sync1["total"] == 3
    assert sync1["resolved_count"] == 3
    assert sync1["missing_count"] == 0
    assert (res_dir_1 / "repo" / "Hospitalar" / "Cabecalhos" / "cabecalho_receituario.jrxml").is_file()
    assert (res_dir_1 / "repo" / "Hospitalar" / "Cabecalhos" / "cabecalho_receituario.jasper").is_file()
    assert (res_dir_1 / "repo" / "Hospitalar" / "Imagens" / "logo.png").is_file()
    assert (res_dir_1 / "repo" / "Hospitalar" / "Estilos" / "base.jrtx").is_file()
    # Basename compatibility copies also present
    assert (res_dir_1 / "cabecalho_receituario.jasper").is_file()
    assert (res_dir_1 / "logo.png").is_file()
    assert (res_dir_1 / "base.jrtx").is_file()

    # Shared server cache populated
    cache_root = data_dir / "jasperserver_repo_cache" / profile.id
    assert (cache_root / "Hospitalar" / "Cabecalhos" / "cabecalho_receituario.jasper").is_file()
    assert (cache_root / "Hospitalar" / "Imagens" / "logo.png").is_file()
    assert (cache_root / "Hospitalar" / "Estilos" / "base.jrtx").is_file()

    # Projeto 2: deve reutilizar o cache compartilhado sem bater no servidor remoto!
    remote_hits.clear()
    res_dir_2 = tmp_path / "proj2" / "report_unit_resources"
    sync2 = svc.sync_missing_repo_resources(
        profile.id,
        MAIN_GUIA_JRXML,
        res_dir_2,
        jvm_daemon,
    )
    assert remote_hits == [], f"Esperava 0 chamadas HTTP usando cache compartilhado, mas houve: {remote_hits}"
    assert sync2["total"] == 3
    assert sync2["resolved_count"] == 3
    assert sync2["missing_count"] == 0
    assert (res_dir_2 / "repo" / "Hospitalar" / "Cabecalhos" / "cabecalho_receituario.jasper").is_file()
    assert (res_dir_2 / "repo" / "Hospitalar" / "Imagens" / "logo.png").is_file()
    assert (res_dir_2 / "repo" / "Hospitalar" / "Estilos" / "base.jrtx").is_file()


# =============================================================================
# 3. FastAPI Endpoints: GET/POST /jasper/repo-resources + Auto-fetch & Offline Preview E2E
# =============================================================================


def test_api_repo_resources_endpoints_and_offline_preview_autofetch_e2e(
    jvm_daemon: JasperDaemonService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "api_studio_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FICHA_STUDIO_DB_PATH", str(data_dir / "studio.db"))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-api-repo-vault-key")

    def _raise_keyring(*args: Any, **kwargs: Any) -> Any:
        raise KeyringError("disabled in test")

    monkeypatch.setattr(keyring, "set_password", _raise_keyring)
    monkeypatch.setattr(keyring, "get_password", _raise_keyring)
    monkeypatch.setattr(keyring, "delete_password", _raise_keyring)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rest_v2/login"):
            return httpx.Response(200, headers={"Set-Cookie": "JSESSIONID=API_AUTO_1"})
        if path.endswith("/rest_v2/resources/Hospitalar/Cabecalhos/cabecalho_receituario"):
            return httpx.Response(200, content=HEADER_SUBREPORT_JRXML.encode("utf-8"))
        if path.endswith("/rest_v2/resources/Hospitalar/Imagens/logo.png"):
            return httpx.Response(200, content=TINY_PNG_BYTES, headers={"Content-Type": "image/png"})
        return httpx.Response(404)

    store = SQLiteStore(data_dir / "studio.db")
    store.init_db()
    vault = SecretVaultService(vault_path=data_dir / ".vault.json")
    default_creds = DefaultCredentialsService(store=store, vault=vault)
    ws_service = WorkspaceService(store=store, data_dir=data_dir)
    sub_service = SubreportService(
        builtin_dir=tmp_path / "builtin",
        custom_dir=data_dir / "custom_subs",
        runtime_dir=data_dir / "runtime_subs",
    )
    js_service = JasperServerService(
        store=store,
        vault=vault,
        default_credentials_service=default_creds,
        http_transport=httpx.MockTransport(handler),
    )

    profile = js_service.create_profile(
        JasperServerProfileCreate(
            name="Jasper API E2E",
            base_url="https://jasper-api.example.local/jasperserver",
            username="admin",
            password="pw",
            environment="HML",
        )
    )

    app = create_app(
        store=store,
        workspace_service=ws_service,
        subreport_service=sub_service,
        jasperserver_service=js_service,
        jasper_daemon=jvm_daemon,
    )
    app.dependency_overrides[jasper_preview.get_jasper_daemon_dep] = lambda: jvm_daemon
    app.dependency_overrides[jasper_preview.get_jasperserver_service_dep] = lambda: js_service

    # Projeto A: testa auto-fetch transparente durante POST /jasper/preview em modo offline!
    project_auto = ws_service.create_project(
        ProjectCreate(
            name="GUIA ENCAMINHAMENTO AUTO",
            project_kind="free_report",
            entry_mode="jasperserver_import",
            source_origin={
                "provider": "jasperserver",
                "profile_id": profile.id,
                "resource_uri": "/Hospitalar/Guias/GUIA_ENCAMINHAMENTO",
            },
            initial_jrxml=MAIN_GUIA_JRXML,
        )
    )

    # Projeto B: testa POST /jasper/sync-repo-resources explicitamente
    project_sync = ws_service.create_project(
        ProjectCreate(
            name="GUIA ENCAMINHAMENTO SYNC",
            project_kind="free_report",
            entry_mode="jasperserver_import",
            source_origin={
                "provider": "jasperserver",
                "profile_id": profile.id,
                "resource_uri": "/Hospitalar/Guias/GUIA_ENCAMINHAMENTO",
            },
            initial_jrxml=MAIN_GUIA_JRXML,
        )
    )

    # Projeto C: sem origem JasperServer -> POST sync deve retornar 400
    project_local = ws_service.create_project(
        ProjectCreate(
            name="RELATORIO LOCAL",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=MAIN_GUIA_JRXML,
        )
    )

    with TestClient(app) as client:
        # 1. GET /repo-resources antes do preview -> 1 pendente
        status_before = client.get(f"/api/projects/{project_auto.id}/jasper/repo-resources")
        assert status_before.status_code == 200
        body_before = status_before.json()
        assert body_before["project_id"] == project_auto.id
        assert body_before["total"] == 1
        assert body_before["resolved_count"] == 0
        assert body_before["missing_count"] == 1
        assert body_before["can_sync_remote"] is True
        assert body_before["items"][0]["uri"] == "repo:/Hospitalar/Cabecalhos/cabecalho_receituario"
        assert body_before["items"][0]["kind"] == "subreport"
        assert body_before["items"][0]["resolved"] is False

        # 2. POST /jasper/preview (mode=offline) -> auto-fetch + merge report_unit_resources + PDF real na JVM!
        prev_resp = client.post(
            f"/api/projects/{project_auto.id}/jasper/preview",
            json={"scenario": "full", "mode": "offline", "dpi": 120},
        )
        assert prev_resp.status_code == 200, prev_resp.text
        prev_body = prev_resp.json()
        assert prev_body["ok"] is True
        assert prev_body["effective_mode"] == "offline"
        assert prev_body["page_count"] == 1

        pdf_resp = client.get(f"/api/projects/{project_auto.id}/jasper/preview/pdf?scenario=full")
        assert pdf_resp.status_code == 200
        with fitz.open(stream=pdf_resp.content, filetype="pdf") as doc:
            page_text = doc[0].get_text("text")
            assert "HOSPITAL SALUTEM - CABECALHO RECEITUARIO" in page_text
            assert "GUIA DE ENCAMINHAMENTO AMBULATORIAL" in page_text
            assert len(doc[0].get_images(full=True)) >= 1

        # 3. GET /repo-resources após preview -> 2 itens (subreport + logo aninhado) todos resolvidos!
        status_after = client.get(f"/api/projects/{project_auto.id}/jasper/repo-resources")
        assert status_after.status_code == 200
        body_after = status_after.json()
        assert body_after["total"] == 2
        assert body_after["resolved_count"] == 2
        assert body_after["missing_count"] == 0
        by_uri = {item["uri"]: item for item in body_after["items"]}
        assert by_uri["repo:/Hospitalar/Cabecalhos/cabecalho_receituario"]["resolved"] is True
        assert by_uri["repo:/Hospitalar/Cabecalhos/cabecalho_receituario"]["compiled"] is True
        assert by_uri["repo:/Hospitalar/Imagens/logo.png"]["resolved"] is True
        assert by_uri["repo:/Hospitalar/Imagens/logo.png"]["kind"] == "image"

        # 4. POST /jasper/sync-repo-resources explícito
        sync_resp = client.post(f"/api/projects/{project_sync.id}/jasper/sync-repo-resources")
        assert sync_resp.status_code == 200, sync_resp.text
        sync_body = sync_resp.json()
        assert sync_body["project_id"] == project_sync.id
        assert sync_body["total"] == 2
        assert sync_body["resolved_count"] == 2
        assert sync_body["missing_count"] == 0
        assert sync_body["can_sync_remote"] is True

        # 5. Projeto sem origem JasperServer -> GET ok (can_sync_remote=False), POST 400
        local_get = client.get(f"/api/projects/{project_local.id}/jasper/repo-resources")
        assert local_get.status_code == 200
        assert local_get.json()["can_sync_remote"] is False

        local_sync = client.post(f"/api/projects/{project_local.id}/jasper/sync-repo-resources")
        assert local_sync.status_code == 400
