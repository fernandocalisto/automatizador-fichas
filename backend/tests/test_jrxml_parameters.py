# -*- coding: utf-8 -*-
"""Tests for JRXML parameter/query helpers, `/jasper/parameters`, `/jasper/sync-query`, and `db_live` preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from backend.app.api import jasper_preview
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.jrxml.parameters import (
    extract_jrxml_parameters,
    extract_jrxml_query,
    replace_jrxml_query,
)
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import WorkspaceService

SAMPLE_FREE_REPORT_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              name="relatorio_faturamento"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20"
              uuid="11111111-2222-3333-4444-555555555555">
    <subDataset name="ds_itens" uuid="22222222-2222-3333-4444-555555555555">
        <parameter name="sub_param_ignorado" class="java.lang.String"/>
        <queryString><![CDATA[SELECT 999 AS sub_col]]></queryString>
    </subDataset>
    <parameter name="SUBREPORT_DIR" class="java.lang.String"/>
    <parameter name="caminho_relatorio" class="java.lang.String"/>
    <parameter name="REPORT_LOCALE" class="java.util.Locale"/>
    <parameter name="atendimento_id" class="java.lang.Long">
        <defaultValueExpression><![CDATA[100L]]></defaultValueExpression>
    </parameter>
    <parameter name="data_inicio" class="java.sql.Date"/>
    <parameter name="data_hora_ref" class="java.sql.Timestamp"/>
    <parameter name="valor_minimo" class="java.math.BigDecimal"/>
    <parameter name="somente_ativos" class="java.lang.Boolean"/>
    <parameter name="filtro_nome" class="java.lang.String"/>
    <queryString language="SQL">
        <![CDATA[SELECT id, nome FROM paciente WHERE id = $P{atendimento_id}]]>
    </queryString>
    <field name="id" class="java.lang.Long"/>
    <field name="nome" class="java.lang.String"/>
    <detail>
        <band height="24">
            <textField isBlankWhenNull="true">
                <reportElement x="0" y="0" width="200" height="20" uuid="33333333-2222-3333-4444-555555555555"/>
                <textFieldExpression><![CDATA[$F{nome}]]></textFieldExpression>
            </textField>
        </band>
    </detail>
</jasperReport>
"""

JRXML_WITHOUT_QUERY = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              name="relatorio_sem_query"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20"
              uuid="44444444-2222-3333-4444-555555555555">
    <parameter name="unidade_id" class="java.lang.Integer"/>
    <field name="total" class="java.lang.Long"/>
    <detail>
        <band height="20"/>
    </detail>
</jasperReport>
"""


def _make_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(fitz.Point(40, 60), "RELATORIO LIVE OK", fontsize=12)
    raw = doc.tobytes()
    doc.close()
    return raw


class FakeLiveDaemon:
    def __init__(self) -> None:
        self.export_calls: list[dict[str, Any]] = []

    def compile(self, input_path: str, output_path: str | None = None, **_kw: Any) -> dict[str, Any]:
        if output_path:
            Path(output_path).write_bytes(b"FAKE_JASPER")
        return {"ok": True, "status": "SUCCESS"}

    def export_pdf(
        self,
        input_path: str,
        output_path: str,
        *,
        params: dict[str, Any] | None = None,
        mock_rows: list[dict[str, Any]] | None = None,
        subreport_dir: str | None = None,
        db_url: str | None = None,
        db_user: str | None = None,
        db_pass: str | None = None,
    ) -> dict[str, Any]:
        rendered_xml = Path(input_path).read_text(encoding="utf-8")
        self.export_calls.append(
            {
                "input_path": input_path,
                "rendered_xml": rendered_xml,
                "params": dict(params or {}),
                "mock_rows": mock_rows,
                "subreport_dir": subreport_dir,
                "db_url": db_url,
                "db_user": db_user,
                "db_pass": db_pass,
            }
        )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_make_pdf_bytes())
        return {"ok": True, "status": "SUCCESS"}


class FakePostgresForLive:
    def get_jdbc_credentials(self, profile_id: str) -> dict[str, Any]:
        return {
            "db_url": f"jdbc:postgresql://127.0.0.1:5432/salutem_{profile_id}?sslmode=prefer",
            "db_user": "live_user",
            "db_pass": "live_secret",
            "read_only": True,
        }


def test_extract_jrxml_parameters_system_flags_and_input_kinds() -> None:
    params = extract_jrxml_parameters(SAMPLE_FREE_REPORT_JRXML)
    by_name = {p.name: p for p in params}

    # SubDataset parameter must not leak into report-level params
    assert "sub_param_ignorado" not in by_name

    # System params
    assert by_name["SUBREPORT_DIR"].is_system is True
    assert by_name["caminho_relatorio"].is_system is True
    assert by_name["REPORT_LOCALE"].is_system is True

    # User params and input_kind inference
    assert by_name["atendimento_id"].is_system is False
    assert by_name["atendimento_id"].input_kind == "integer"
    assert by_name["atendimento_id"].default_expression == "100L"

    assert by_name["data_inicio"].input_kind == "date"
    assert by_name["data_hora_ref"].input_kind == "datetime"
    assert by_name["valor_minimo"].input_kind == "number"
    assert by_name["somente_ativos"].input_kind == "boolean"
    assert by_name["filtro_nome"].input_kind == "string"


def test_extract_and_replace_jrxml_query_preserves_subdataset_and_inserts_when_missing() -> None:
    original_sql = extract_jrxml_query(SAMPLE_FREE_REPORT_JRXML)
    assert original_sql == "SELECT id, nome FROM paciente WHERE id = $P{atendimento_id}"

    new_sql = "SELECT id, upper(nome) AS nome FROM paciente WHERE id = $P{atendimento_id} AND nome <> ']]>'"
    updated = replace_jrxml_query(SAMPLE_FREE_REPORT_JRXML, new_sql)
    assert extract_jrxml_query(updated) == new_sql
    # SubDataset query untouched
    assert "SELECT 999 AS sub_col" in updated

    # Insert <queryString> in valid XSD order when missing
    assert extract_jrxml_query(JRXML_WITHOUT_QUERY) == ""
    inserted = replace_jrxml_query(JRXML_WITHOUT_QUERY, "SELECT count(*) AS total FROM atendimento")
    assert extract_jrxml_query(inserted) == "SELECT count(*) AS total FROM atendimento"
    assert inserted.index("<parameter") < inserted.index("<queryString") < inserted.index("<field")


def test_jasper_parameters_sync_query_and_db_live_preview_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    store = SQLiteStore(db_path=data_dir / "studio.db")
    ws = WorkspaceService(store=store, data_dir=data_dir)
    subreports = SubreportService()
    daemon = FakeLiveDaemon()
    pg = FakePostgresForLive()

    proj = ws.create_project(
        ProjectCreate(
            name="Relatório Faturamento",
            project_kind="free_report",
            entry_mode="jrxml",
            default_db_profile_id="hosp1",
            initial_jrxml=SAMPLE_FREE_REPORT_JRXML,
        )
    )

    app = FastAPI()
    app.state.workspace_service = ws
    app.state.subreport_service = subreports
    app.state.jasper_daemon = daemon
    app.state.postgres_service = pg
    app.include_router(jasper_preview.router)
    client = TestClient(app)

    # 1. GET /jasper/parameters
    r_params = client.get(f"/api/projects/{proj.id}/jasper/parameters")
    assert r_params.status_code == 200
    p_data = r_params.json()
    assert p_data["project_id"] == proj.id
    assert any(p["name"] == "atendimento_id" and p["input_kind"] == "integer" for p in p_data["parameters"])
    assert "SELECT id, nome FROM paciente" in p_data["query"]

    # 2. POST /jasper/sync-query (jrxml_to_sql)
    r_extract = client.post(
        f"/api/projects/{proj.id}/jasper/sync-query",
        json={"direction": "jrxml_to_sql", "save_artifact": True},
    )
    assert r_extract.status_code == 200
    assert r_extract.json()["saved_revision"]["artifact_type"] == "sql_select"
    assert "SELECT id, nome FROM paciente" in ws.get_latest_artifact(proj.id, "sql_select").content

    # 3. POST /jasper/sync-query (sql_to_jrxml)
    updated_sql = "SELECT id, nome FROM paciente WHERE ativo = $P{somente_ativos} AND id = $P{atendimento_id}"
    r_apply = client.post(
        f"/api/projects/{proj.id}/jasper/sync-query",
        json={"direction": "sql_to_jrxml", "sql_select": updated_sql, "save_artifact": True},
    )
    assert r_apply.status_code == 200
    assert r_apply.json()["saved_revision"]["artifact_type"] == "jrxml"
    assert extract_jrxml_query(ws.get_latest_artifact(proj.id, "jrxml").content) == updated_sql

    # 4. POST /jasper/preview with mode="db_live" and typed report_params
    r_live = client.post(
        f"/api/projects/{proj.id}/jasper/preview",
        json={
            "mode": "db_live",
            "report_params": {
                "atendimento_id": "555",
                "valor_minimo": "123,45",
                "somente_ativos": "true",
                "data_inicio": "2026-11-01",
                "filtro_nome": "JOAO",
            },
        },
    )
    assert r_live.status_code == 200
    live_body = r_live.json()
    assert live_body["ok"] is True
    assert live_body["effective_mode"] == "db_live"
    assert live_body["page_count"] == 1

    assert len(daemon.export_calls) == 1
    call = daemon.export_calls[0]
    # Must NOT rewrite query with mock CTE!
    assert "_mock_cte" not in call["rendered_xml"].lower()
    assert "WHERE ativo = $P{somente_ativos}" in call["rendered_xml"]
    assert call["mock_rows"] is None
    assert call["db_url"] == "jdbc:postgresql://127.0.0.1:5432/salutem_hosp1?sslmode=prefer"
    assert call["db_user"] == "live_user"
    assert call["db_pass"] == "live_secret"
    # Typed parameters coerced properly
    assert call["params"]["atendimento_id"] == 555
    assert call["params"]["valor_minimo"] == 123.45
    assert call["params"]["somente_ativos"] is True
    assert call["params"]["data_inicio"] == "2026-11-01"
    assert call["params"]["filtro_nome"] == "JOAO"
    assert "SUBREPORT_DIR" in call["params"]

    # 5. Missing db_profile_id when project has no default_db_profile_id -> 400
    proj_no_db = ws.create_project(
        ProjectCreate(
            name="Sem DB",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_FREE_REPORT_JRXML,
        )
    )
    r_missing = client.post(
        f"/api/projects/{proj_no_db.id}/jasper/preview",
        json={"mode": "db_live"},
    )
    assert r_missing.status_code == 400
