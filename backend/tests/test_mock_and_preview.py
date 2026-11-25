# -*- coding: utf-8 -*-
"""
Testes unitários e de API FastAPI para geração de dados fictícios (`full`, `stress`, `blank`),
subreports mock offline, reescrita híbrida/offline de `.jrxml`, preview PDF/PNG e pacote `.zip`
(`backend/tests/test_mock_and_preview.py`).
"""

from __future__ import annotations

import io
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from backend.app.api import jasper_preview
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.jrxml.linter import lint_jrxml
from backend.app.jrxml.mock_data import (
    build_offline_mock_subreports_jrxml,
    generate_fictitious_row,
    parse_jrxml_declared_fields,
    prepare_preview_jrxml,
)
from backend.app.jrxml.scaffolder import STANDARD_SALUTEM_FIELDS, scaffold_salutem_jrxml
from backend.app.main import create_app
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import WorkspaceService


# -----------------------------------------------------------------------------
# Fixtures e Fakes
# -----------------------------------------------------------------------------


def _sample_clinical_json() -> dict[str, Any]:
    """Ficha clínica completa exercitando BOOLEANO_RADIO, BOOLEANO, _obs, NUMERICO, DATA, HORA e TEXTO."""
    return {
        "template": {
            "nome": "FICHA DE AVALIACAO PRE ANESTESICA",
            "orientacao": "RETRATO",
        },
        "perguntas": [
            {
                "nome": "NIVEL DE CONSCIENCIA",
                "obrigatoria": True,
                "observacao": False,
                "respostas": [
                    {"label": "ACORDADO", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "SONOLENTO", "tipo_campo": "BOOLEANO_RADIO"},
                    {
                        "label": "TORPOROSO",
                        "tipo_campo": "BOOLEANO_RADIO",
                        "observacao": True,
                    },
                ],
            },
            {
                "nome": "CLASSIFICACAO ASA",
                "obrigatoria": True,
                "observacao": False,
                "respostas": [
                    {"label": "ASA I", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "ASA II", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "ASA III", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "ASA IV", "tipo_campo": "BOOLEANO_RADIO"},
                ],
            },
            {
                "nome": "COMORBIDADES PREVIAS",
                "obrigatoria": False,
                "observacao": False,
                "respostas": [
                    {"label": "HIPERTENSAO", "tipo_campo": "BOOLEANO", "observacao": True},
                    {"label": "DIABETES", "tipo_campo": "BOOLEANO", "observacao": True},
                    {"label": "ASMA", "tipo_campo": "BOOLEANO"},
                    {"label": "CARDIOPATIA", "tipo_campo": "BOOLEANO"},
                    {"label": "TABAGISMO", "tipo_campo": "BOOLEANO"},
                    {"label": "ETILISMO", "tipo_campo": "BOOLEANO"},
                ],
            },
            {
                "nome": "DADOS VITAIS E ANTROPOMETRIA",
                "obrigatoria": False,
                "observacao": False,
                "respostas": [
                    {"label": "HORA AVALIACAO", "tipo_campo": "HORA"},
                    {"label": "DATA ULTIMO EXAME", "tipo_campo": "DATA"},
                    {"label": "PESO", "tipo_campo": "NUMERICO", "observacao": True},
                    {"label": "TEMPERATURA", "tipo_campo": "NUMERICO"},
                    {"label": "PA", "tipo_campo": "TEXTO"},
                    {"label": "CID PRINCIPAL", "tipo_campo": "CID"},
                    {"label": "CONDUTA ANESTESICA", "tipo_campo": "TEXTO"},
                ],
            },
        ],
    }


def _has_accent(text: str) -> bool:
    return any(
        unicodedata.decomposition(ch) != "" and ord(ch) > 127
        for ch in text
    )


class FakeJasperDaemon:
    """Fake determinístico do JasperDaemonService gerando PDFs reais via PyMuPDF."""

    def __init__(self, *, num_pages: int = 1) -> None:
        self.num_pages = num_pages
        self.compile_calls: list[tuple[str, str | None]] = []
        self.export_calls: list[dict[str, Any]] = []

    def compile(self, input_path: str, output_path: str | None = None) -> dict[str, Any]:
        self.compile_calls.append((input_path, output_path))
        src = Path(input_path)
        assert src.is_file(), f"JRXML de entrada inexistente: {src}"
        # Garante que o JRXML enviado ao compilador é XML bem-formado
        ET.fromstring(src.read_text(encoding="utf-8"))

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"FAKE_COMPILED_JASPER_BINARY")

        return {
            "ok": True,
            "input_path": str(src),
            "output_path": output_path,
            "elapsed_ms": 12,
        }

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
        jrxml_content = Path(input_path).read_text(encoding="utf-8")
        ET.fromstring(jrxml_content)

        call_record = {
            "input_path": input_path,
            "output_path": output_path,
            "jrxml_content": jrxml_content,
            "params": params,
            "mock_rows": mock_rows,
            "subreport_dir": subreport_dir,
            "db_url": db_url,
            "db_user": db_user,
            "db_pass": db_pass,
        }
        self.export_calls.append(call_record)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open() as doc:
            for p_idx in range(self.num_pages):
                page = doc.new_page(width=595, height=842)
                page.insert_text(
                    (36, 60),
                    f"Salutem Preview Page {p_idx + 1} | Params={params}",
                    fontsize=10,
                )
            doc.save(str(out))

        return {"ok": True, "output_path": str(out), "pages": self.num_pages}


class FakePostgresService:
    """Fake determinístico do PostgresService para testes de modo `db_hybrid` e `auto`."""

    def __init__(self, *, sample_atendimento_id: int | None = 88421, fail: bool = False) -> None:
        self.sample_atendimento_id = sample_atendimento_id
        self.fail = fail
        self.credentials_calls: list[str] = []
        self.sample_calls: list[str] = []

    def get_jdbc_credentials(self, profile_id: str) -> dict[str, str]:
        self.credentials_calls.append(profile_id)
        if self.fail:
            raise RuntimeError(f"Profile '{profile_id}' unreachable.")
        return {
            "db_url": f"jdbc:postgresql://localhost:5432/salutem_{profile_id}",
            "db_user": "salutem_ro",
            "db_pass": "secret_ro",
        }

    def find_sample_atendimento_id(self, profile_id: str) -> int | None:
        self.sample_calls.append(profile_id)
        if self.fail:
            raise RuntimeError("Cannot query atendimento sample.")
        return self.sample_atendimento_id


@pytest.fixture()
def studio_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Ambiente isolado com SQLiteStore, WorkspaceService, SubreportService e TestClient."""
    data_dir = tmp_path / "studio_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FICHA_STUDIO_DB_PATH", str(data_dir / "test_studio.db"))

    store = SQLiteStore(db_path=data_dir / "test_studio.db")
    store.init_db()
    ws_service = WorkspaceService(store=store, data_dir=data_dir)

    builtin_subs = tmp_path / "builtin_subs"
    builtin_subs.mkdir(parents=True, exist_ok=True)
    for sub_name in (
        "cabecalho_retrato.jasper",
        "cabecalho_paisagem.jasper",
        "dados_paciente.jasper",
        "rodape_retrato.jasper",
    ):
        (builtin_subs / sub_name).write_bytes(b"REAL_SALUTEM_SUBREPORT")

    sub_service = SubreportService(
        builtin_dir=builtin_subs,
        custom_dir=data_dir / "custom_subreports",
        runtime_dir=data_dir / "runtime_subreports",
    )

    fake_daemon = FakeJasperDaemon(num_pages=1)
    fake_pg = FakePostgresService(sample_atendimento_id=77501)

    app = create_app(
        store=store,
        workspace_service=ws_service,
        subreport_service=sub_service,
    )
    if not any(
        getattr(r, "path", "").endswith("/jasper/preview")
        for r in app.routes
    ):
        app.include_router(jasper_preview.router)

    app.dependency_overrides[jasper_preview.get_jasper_daemon_dep] = lambda: fake_daemon
    app.dependency_overrides[jasper_preview.get_postgres_service_dep] = lambda: fake_pg

    clinical_json = _sample_clinical_json()
    jrxml_text = scaffold_salutem_jrxml(clinical_json)
    project = ws_service.create_project(
        ProjectCreate(
            name="Ficha de Avaliação Pré-Anestésica",
            entry_mode="json",
            initial_json=clinical_json,
        )
    )
    ws_service.save_artifact(
        project.id,
        "jrxml",
        jrxml_text,
        summary="Scaffolded JRXML inicial",
        created_by="agent",
    )

    with TestClient(app) as client:
        yield {
            "client": client,
            "app": app,
            "project": project,
            "clinical_json": clinical_json,
            "jrxml_text": jrxml_text,
            "ws_service": ws_service,
            "sub_service": sub_service,
            "fake_daemon": fake_daemon,
            "fake_pg": fake_pg,
            "data_dir": data_dir,
        }


# -----------------------------------------------------------------------------
# 1. Testes Unitários: generate_fictitious_row (full, stress, blank)
# -----------------------------------------------------------------------------


def test_generate_fictitious_row_standard_fields_and_java_types() -> None:
    clinical_json = _sample_clinical_json()
    jrxml_text = scaffold_salutem_jrxml(clinical_json)

    row = generate_fictitious_row(
        jrxml_text,
        json_data=clinical_json,
        scenario="full",
        atendimento_id=42099,
    )

    assert row["atendimento_id"] == 42099
    assert type(row["atendimento_id"]) is int

    for field_name, java_class, _ in STANDARD_SALUTEM_FIELDS:
        assert field_name in row, f"Campo padrão '{field_name}' ausente no mock_row"
        val = row[field_name]
        if java_class == "java.lang.Long":
            assert type(val) is int
        elif java_class == "java.lang.Double":
            assert isinstance(val, float)
        elif java_class == "java.sql.Date":
            assert isinstance(val, str) and len(val) == 10 and val[4] == "-"
        elif java_class == "java.lang.String":
            assert isinstance(val, str) and len(val) > 0

    assert row["pac_nasc"] == "1985-04-12"


def test_generate_fictitious_row_full_radio_single_true_checkbox_half_and_obs() -> None:
    clinical_json = _sample_clinical_json()
    jrxml_text = scaffold_salutem_jrxml(clinical_json)

    row = generate_fictitious_row(jrxml_text, json_data=clinical_json, scenario="full")

    # Grupo BOOLEANO_RADIO #1: exatamente 1 True, irmãos False
    radio_grp_1 = ["acordado", "sonolento", "torporoso"]
    assert sum(1 for k in radio_grp_1 if row[k] is True) == 1
    assert all(isinstance(row[k], bool) for k in radio_grp_1)
    # Torporoso possui observacao=True, devendo ser priorizado e ter torporoso_obs preenchido
    assert row["torporoso"] is True
    assert isinstance(row["torporoso_obs"], str) and len(row["torporoso_obs"]) > 10

    # Grupo BOOLEANO_RADIO #2: exatamente 1 True entre 4 opções ASA
    radio_grp_2 = ["asa_i", "asa_ii", "asa_iii", "asa_iv"]
    assert sum(1 for k in radio_grp_2 if row[k] is True) == 1
    assert sum(1 for k in radio_grp_2 if row[k] is False) == 3

    # Checkboxes BOOLEANO (6 itens): ~metade True (3 True, 3 False)
    checkboxes = [
        "hipertensao",
        "diabetes",
        "asma",
        "cardiopatia",
        "tabagismo",
        "etilismo",
    ]
    true_checkboxes = [k for k in checkboxes if row[k] is True]
    assert len(true_checkboxes) == 3

    # Vínculo _obs ativo vs inativo no preset "full"
    assert row["hipertensao"] is True
    assert isinstance(row["hipertensao_obs"], str) and len(row["hipertensao_obs"]) > 5
    assert row["diabetes"] is False
    assert row["diabetes_obs"] is None

    # Campos numéricos/textos/datas/horas preenchidos realisticamente
    assert isinstance(row["peso"], float) and 40.0 <= row["peso"] <= 150.0
    assert isinstance(row["peso_obs"], str) and len(row["peso_obs"]) > 5
    assert row["pa"] == "120/80 mmHg"
    assert ":" in row["hora_avaliacao"]
    assert "/" in row["data_ultimo_exame"]


def test_generate_fictitious_row_stress_preset() -> None:
    clinical_json = _sample_clinical_json()
    jrxml_text = scaffold_salutem_jrxml(clinical_json)

    row = generate_fictitious_row(jrxml_text, json_data=clinical_json, scenario="stress")

    # Mesmo no stress, grupos BOOLEANO_RADIO mantêm invariante de exatamente 1 True
    assert sum(1 for k in ("acordado", "sonolento", "torporoso") if row[k] is True) == 1
    assert sum(1 for k in ("asa_i", "asa_ii", "asa_iii", "asa_iv") if row[k] is True) == 1

    # Todos os checkboxes BOOLEANO ficam True no stress
    for cb in ("hipertensao", "diabetes", "asma", "cardiopatia", "tabagismo", "etilismo"):
        assert row[cb] is True

    # Todos os _obs e textos clínicos têm 180..240 caracteres com acentuação
    for str_field in (
        "torporoso_obs",
        "hipertensao_obs",
        "diabetes_obs",
        "peso_obs",
        "pa",
        "cid_principal",
        "conduta_anestesica",
    ):
        val = row[str_field]
        assert isinstance(val, str), f"{str_field} deveria ser str no stress"
        assert 180 <= len(val) <= 240, f"{str_field} fora da faixa 180-240: len={len(val)}"
        assert _has_accent(val), f"{str_field} deve conter acentuação portuguesa"

    # Números grandes para teste de largura numérica
    assert isinstance(row["peso"], float) and row["peso"] >= 10000.0
    assert isinstance(row["temperatura"], float) and row["temperatura"] >= 10000.0


def test_generate_fictitious_row_blank_preset_and_without_json() -> None:
    clinical_json = _sample_clinical_json()
    jrxml_text = scaffold_salutem_jrxml(clinical_json)

    row_blank = generate_fictitious_row(jrxml_text, json_data=clinical_json, scenario="blank")

    for bool_field in (
        "acordado",
        "sonolento",
        "torporoso",
        "asa_i",
        "hipertensao",
        "diabetes",
    ):
        assert row_blank[bool_field] is False

    for nullable_field in (
        "torporoso_obs",
        "hipertensao_obs",
        "diabetes_obs",
        "peso",
        "peso_obs",
        "pa",
        "conduta_anestesica",
        "hora_avaliacao",
    ):
        assert row_blank[nullable_field] is None

    # Modo heurístico (json_data=None) também funciona sem erro
    row_no_json = generate_fictitious_row(jrxml_text, json_data=None, scenario="full")
    assert isinstance(row_no_json["conduta_anestesica"], str)
    assert isinstance(row_no_json["peso"], float)

    with pytest.raises(ValueError, match="Cenário inválido"):
        generate_fictitious_row(jrxml_text, scenario="invalid")  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# 2. Testes Unitários: Subreports Offline Mock & prepare_preview_jrxml
# -----------------------------------------------------------------------------


def test_build_offline_mock_subreports_xml_validity_and_dimensions() -> None:
    subs = build_offline_mock_subreports_jrxml(
        unit_name="AME LORENA — UNIDADE TESTE",
        patient_info={"pac_nome": "JOÃO CARLOS PEREIRA", "atendimento_id": 99123},
    )

    expected_dims = {
        "cabecalho_retrato.jrxml": (555, 45, False),
        "cabecalho_paisagem.jrxml": (800, 45, True),
        "dados_paciente.jrxml": (555, 77, False),
        "rodape_retrato.jrxml": (555, 17, False),
    }
    assert set(subs.keys()) == set(expected_dims.keys())

    for filename, (exp_w, exp_h, is_landscape) in expected_dims.items():
        xml_str = subs[filename]
        root = ET.fromstring(xml_str)
        assert int(root.attrib["pageWidth"]) == exp_w
        assert int(root.attrib["pageHeight"]) == exp_h
        assert int(root.attrib["columnWidth"]) == exp_w
        if is_landscape:
            assert root.attrib.get("orientation") == "Landscape"

        # Deve renderizar em <title><band height="..."> sem <queryString> SQL
        ns = {"jr": "http://jasperreports.sourceforge.net/jasperreports"}
        assert root.find("jr:queryString", ns) is None
        title_band = root.find("jr:title/jr:band", ns)
        assert title_band is not None
        assert int(title_band.attrib["height"]) == exp_h

        lint = lint_jrxml(xml_str)
        assert lint.is_valid, f"Linter falhou em {filename}: {lint.errors}"

    assert "AME LORENA — UNIDADE TESTE" in subs["cabecalho_retrato.jrxml"]
    assert "JOÃO CARLOS PEREIRA" in subs["dados_paciente.jrxml"]


def test_prepare_preview_jrxml_offline_and_db_hybrid_modes() -> None:
    clinical_json = _sample_clinical_json()
    original_jrxml = scaffold_salutem_jrxml(clinical_json)
    original_snapshot = str(original_jrxml)

    mock_row = generate_fictitious_row(
        original_jrxml,
        json_data=clinical_json,
        scenario="full",
        atendimento_id=10042,
    )
    mock_row["pa"] = "120/80 'em repouso'"
    mock_row["diabetes_obs"] = None

    # 1. Modo offline
    offline_jrxml = prepare_preview_jrxml(
        original_jrxml,
        mode="offline",
        mock_row=mock_row,
    )
    assert original_jrxml == original_snapshot  # Imutabilidade garantida
    assert "<connectionExpression>" not in offline_jrxml
    assert (
        "new net.sf.jasperreports.engine.JREmptyDataSource(1)" in offline_jrxml
    )
    assert offline_jrxml.count("<dataSourceExpression>") == 3
    assert lint_jrxml(offline_jrxml).is_valid

    # 2. Modo db_hybrid
    hybrid_jrxml = prepare_preview_jrxml(
        original_jrxml,
        mode="db_hybrid",
        mock_row=mock_row,
    )
    assert "<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>" in hybrid_jrxml
    assert "JREmptyDataSource" not in hybrid_jrxml
    assert "from ficha_clinica" not in hybrid_jrxml.lower()

    root = ET.fromstring(hybrid_jrxml)
    ns = {"jr": "http://jasperreports.sourceforge.net/jasperreports"}
    query_el = root.find("jr:queryString", ns)
    assert query_el is not None and query_el.text is not None
    sql_text = query_el.text.strip()

    assert sql_text.startswith("SELECT")
    assert "false::boolean AS acordado" in sql_text
    assert "true::boolean AS torporoso" in sql_text
    assert "'120/80 ''em repouso'''::varchar AS pa" in sql_text
    assert "NULL::varchar AS diabetes_obs" in sql_text
    assert "10042::bigint AS atendimento_id" in sql_text
    assert "'1985-04-12'::date AS pac_nasc" in sql_text

    # Verifica que todas as colunas declaradas aparecem na mesma ordem exata dos <field>
    declared = [fname for fname, _ in parse_jrxml_declared_fields(original_jrxml)]
    positions = [sql_text.index(f" AS {fname}") for fname in declared]
    assert positions == sorted(positions)
    assert lint_jrxml(hybrid_jrxml).is_valid


# -----------------------------------------------------------------------------
# 3. Testes de Rotas FastAPI (compile, preview offline/db_hybrid, pdf, png, zip)
# -----------------------------------------------------------------------------


def test_api_compile_and_offline_preview_caches_mock_subreports(
    studio_env: dict[str, Any],
) -> None:
    client: TestClient = studio_env["client"]
    project = studio_env["project"]
    fake_daemon: FakeJasperDaemon = studio_env["fake_daemon"]
    data_dir: Path = studio_env["data_dir"]
    ws_service: WorkspaceService = studio_env["ws_service"]

    original_saved_jrxml = ws_service.get_latest_artifact(project.id, "jrxml").content

    # 1. Rota POST /jasper/compile
    comp_resp = client.post(f"/api/projects/{project.id}/jasper/compile", json={})
    assert comp_resp.status_code == 200
    comp_body = comp_resp.json()
    assert comp_body["ok"] is True
    assert comp_body["compiled"] is True
    assert comp_body["lint"]["is_valid"] is True
    assert len(fake_daemon.compile_calls) == 1

    # 2. Rota POST /jasper/preview (modo auto sem db_profile_id -> offline)
    prev_resp = client.post(
        f"/api/projects/{project.id}/jasper/preview",
        json={"scenario": "full", "mode": "auto", "dpi": 120},
    )
    assert prev_resp.status_code == 200
    prev_body = prev_resp.json()
    assert prev_body["ok"] is True
    assert prev_body["effective_mode"] == "offline"
    assert prev_body["scenario"] == "full"
    assert prev_body["page_count"] == 1
    assert prev_body["single_page_ok"] is True
    assert len(prev_body["page_urls"]) == 1

    # Os 4 subreports mock foram compilados em get_data_dir() / "mock_subreports_runtime"
    mock_runtime = data_dir / "mock_subreports_runtime"
    assert mock_runtime.is_dir()
    assert len(fake_daemon.compile_calls) == 1 + 4  # 1 compile explícito + 4 mock subreports

    # Segunda chamada offline NÃO recompila os 4 subreports mock ("compiles mock subreports once")
    prev_resp_2 = client.post(
        f"/api/projects/{project.id}/jasper/preview",
        json={"scenario": "stress", "mode": "offline", "dpi": 120},
    )
    assert prev_resp_2.status_code == 200
    assert len(fake_daemon.compile_calls) == 1 + 4

    # O .jrxml original salvo no projeto permanece 100% intacto
    after_jrxml = ws_service.get_latest_artifact(project.id, "jrxml").content
    assert after_jrxml == original_saved_jrxml
    assert "$P{REPORT_CONNECTION}" in after_jrxml

    # 3. Streaming GET /jasper/preview/pdf e GET /jasper/preview/pages/1
    pdf_resp = client.get(f"/api/projects/{project.id}/jasper/preview/pdf?scenario=full")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")

    png_resp = client.get(f"/api/projects/{project.id}/jasper/preview/pages/1?scenario=full")
    assert png_resp.status_code == 200
    assert png_resp.headers["content-type"] == "image/png"
    assert png_resp.content.startswith(b"\x89PNG")

    missing_page = client.get(f"/api/projects/{project.id}/jasper/preview/pages/99?scenario=full")
    assert missing_page.status_code == 404


def test_api_preview_db_hybrid_and_export_bundle_zip(
    studio_env: dict[str, Any],
) -> None:
    client: TestClient = studio_env["client"]
    project = studio_env["project"]
    fake_daemon: FakeJasperDaemon = studio_env["fake_daemon"]
    fake_pg: FakePostgresService = studio_env["fake_pg"]

    # 1. Preview em modo db_hybrid com descoberta automática de sample_atendimento_id
    hyb_resp = client.post(
        f"/api/projects/{project.id}/jasper/preview",
        json={
            "scenario": "full",
            "mode": "db_hybrid",
            "db_profile_id": "homolog_ame",
            "dpi": 150,
        },
    )
    assert hyb_resp.status_code == 200
    hyb_body = hyb_resp.json()
    assert hyb_body["effective_mode"] == "db_hybrid"
    assert hyb_body["atendimento_id"] == 77501
    assert fake_pg.credentials_calls == ["homolog_ame"]
    assert fake_pg.sample_calls == ["homolog_ame"]

    last_export = fake_daemon.export_calls[-1]
    assert last_export["mock_rows"] is None
    assert last_export["db_url"] == "jdbc:postgresql://localhost:5432/salutem_homolog_ame"
    assert last_export["db_user"] == "salutem_ro"
    assert "77501::bigint AS atendimento_id" in last_export["jrxml_content"]
    assert "$P{REPORT_CONNECTION}" in last_export["jrxml_content"]

    # 2. Pacote final GET /jasper/export-bundle (<slug>_entrega_salutem.zip)
    bundle_resp = client.get(f"/api/projects/{project.id}/jasper/export-bundle")
    assert bundle_resp.status_code == 200
    assert bundle_resp.headers["content-type"] == "application/zip"
    slug = project.slug
    assert f"{slug}_entrega_salutem.zip" in bundle_resp.headers.get("content-disposition", "")

    with zipfile.ZipFile(io.BytesIO(bundle_resp.content), mode="r") as zf:
        names = set(zf.namelist())
        expected_names = {
            f"{slug}.jrxml",
            f"{slug}_relatorio_ficticio.pdf",
            f"{slug}_insert_template.sql",
        }
        assert names == expected_names

        bundled_jrxml = zf.read(f"{slug}.jrxml").decode("utf-8")
        assert "<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>" in bundled_jrxml
        assert "JREmptyDataSource" not in bundled_jrxml
        assert "from ficha_clinica" in bundled_jrxml.lower()

        bundled_pdf = zf.read(f"{slug}_relatorio_ficticio.pdf")
        assert bundled_pdf.startswith(b"%PDF")

        bundled_sql = zf.read(f"{slug}_insert_template.sql").decode("utf-8")
        assert "INSERT INTO" in bundled_sql.upper()


def test_api_auto_fallback_to_offline_and_on_demand_bundle_generation(
    studio_env: dict[str, Any],
) -> None:
    client: TestClient = studio_env["client"]
    app = studio_env["app"]
    project = studio_env["project"]

    # Simula falha no PostgresService durante mode="auto" com db_profile_id -> fallback limpo p/ offline
    failing_pg = FakePostgresService(fail=True)
    app.dependency_overrides[jasper_preview.get_postgres_service_dep] = lambda: failing_pg

    resp = client.post(
        f"/api/projects/{project.id}/jasper/preview",
        json={"scenario": "blank", "mode": "auto", "db_profile_id": "offline_db"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["effective_mode"] == "offline"
    assert body["fallback_reason"] is not None

    # Export bundle para cenário 'stress' ainda não gerado cria o PDF automaticamente sob demanda
    bundle_resp = client.get(
        f"/api/projects/{project.id}/jasper/export-bundle?scenario=stress&mode=offline"
    )
    assert bundle_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle_resp.content), mode="r") as zf:
        assert f"{project.slug}_relatorio_ficticio.pdf" in zf.namelist()

