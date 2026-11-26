# -*- coding: utf-8 -*-
"""Comprehensive integration tests for SQLiteStore, WorkspaceService, SubreportService, and FastAPI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import BUILTIN_SUBREPORTS_DIR
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.main import create_app
from backend.app.services.subreport_service import STANDARD_SUBREPORTS, SubreportService


@pytest.fixture()
def studio_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate FICHA_STUDIO_DATA_DIR per test so SQLite, workspaces, and custom subreports stay in tmp_path."""
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.delenv("FICHA_STUDIO_DB_PATH", raising=False)
    return data_dir


@pytest.fixture()
def client(studio_env: Path) -> Any:
    """Yield a FastAPI TestClient wired to the isolated temporary studio_data directory."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _sample_clinical_json(
    *,
    titulo_ficha: str = "Ficha de Triagem Clínica",
    extra_question: bool = False,
) -> dict[str, Any]:
    perguntas: list[dict[str, Any]] = [
        {
            "nome": "Sinais Vitais",
            "titulo": False,
            "respostas": [
                {"label": "Pressão Arterial", "tipo_campo": "TEXTO"},
                {"label": "Hora da Aferição", "tipo_campo": "HORA"},
                {"label": "Alergia Medicamentosa", "tipo_campo": "BOOLEANO", "observacao": True},
            ],
        }
    ]
    if extra_question:
        perguntas.append(
            {
                "nome": "Evolução de Enfermagem",
                "titulo": False,
                "respostas": [
                    {"label": "", "tipo_campo": "TEXTO", "quantidade_linhas": 3},
                ],
            }
        )
    return {
        "template": {
            "nome": titulo_ficha,
            "descricao": "Ficha padrão de acolhimento hospitalar",
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "posicao_assinatura": "RODAPE",
        },
        "perguntas": perguntas,
    }


SAMPLE_JRXML = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              name="ficha_exemplo"
              pageWidth="595" pageHeight="842" columnWidth="555"
              leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
    <parameter name="id" class="java.lang.Long"/>
    <parameter name="caminho_relatorio" class="java.lang.String"/>
    <detail>
        <band height="40"/>
    </detail>
</jasperReport>
"""

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n"
    b"xref\n0 3\n0000000000 65535 f \n"
    b"trailer << /Root 1 0 R /Size 3 >>\nstartxref\n110\n%%EOF\n"
)


# =============================================================================
# 1. SQLiteStore Unit & Cascade Integrity Tests
# =============================================================================


def test_sqlite_store_wal_foreign_keys_and_cascade_delete(studio_env: Path) -> None:
    store = SQLiteStore()
    health = store.check_health()
    assert health["status"] == "ok"
    assert health["journal_mode"].lower() == "wal"
    assert health["foreign_keys"] is True
    assert health["projects_count"] == 0

    ws_path = studio_env / "avaliacao_12345678"
    proj = store.create_project(
        project_id="12345678-aaaa-bbbb-cccc-000000000001",
        slug="avaliacao",
        name="Avaliação Inicial",
        workspace_dir=ws_path,
    )
    pid = proj["id"]

    # Default 3 gates seeded as pending
    gates = store.list_gates(pid)
    assert [g["gate_name"] for g in gates] == ["gate1_json", "gate2_sql_insert", "gate3_jrxml"]
    assert all(g["status"] == "pending" for g in gates)

    # Sequential revisions per artifact_type
    r1 = store.add_artifact_revision(pid, "json", '{"a": 1}', summary="v1")
    r2 = store.add_artifact_revision(pid, "json", '{"a": 2}', summary="v2", created_by="agent")
    s1 = store.add_artifact_revision(pid, "sql_insert", "DO $$ BEGIN END $$;", created_by="system")
    assert r1["version_num"] == 1
    assert r2["version_num"] == 2
    assert s1["version_num"] == 1
    assert store.get_latest_artifact_versions_map(pid) == {"json": 2, "sql_insert": 1}

    # Chat messages + metadata roundtrip
    msg = store.add_chat_message(
        pid,
        phase="extraction",
        role="assistant",
        content="Identifiquei 4 seções na ficha.",
        metadata={"sections": 4, "harness": "agy"},
    )
    assert msg["metadata"] == {"sections": 4, "harness": "agy"}

    # Deleting project cascades to revisions, gates, and chat_messages
    assert store.delete_project(pid) is True
    assert store.get_project(pid) is None
    assert store.list_artifact_revisions(pid) == []
    assert store.list_gates(pid) == []
    assert store.list_chat_messages(pid) == []


# =============================================================================
# 2. Project Creation Modes, PDF Upload/Streaming & Cleanup
# =============================================================================


def test_project_empty_creation_and_pdf_upload_download_lifecycle(
    client: TestClient,
    studio_env: Path,
) -> None:
    # 1. Create empty project (default entry_mode='pdf', stage='landing')
    res = client.post(
        "/api/projects",
        json={
            "name": "Ficha Pré-Anestésica Ambulatorial",
            "description": "Fluxo completo a partir de PDF",
            "preferred_harness": "agy",
        },
    )
    assert res.status_code == 201, res.text
    proj = res.json()
    pid = proj["id"]
    assert proj["slug"] == "ficha_pre_anestesica_ambulatorial"
    assert proj["current_stage"] == "landing"
    assert proj["entry_mode"] == "pdf"
    assert proj["has_pdf"] is False

    ws_dir = Path(proj["workspace_dir"])
    assert ws_dir.parent == studio_env.resolve()
    assert (ws_dir / "uploads").is_dir()
    assert (ws_dir / "artifacts").is_dir()
    assert (ws_dir / "exports").is_dir()

    # Streaming PDF before uploading returns 404
    assert client.get(f"/api/projects/{pid}/pdf").status_code == 404

    # Invalid PDF upload is rejected with 400
    bad_upload = client.post(
        f"/api/projects/{pid}/pdf",
        files={"file": ("not_a_pdf.txt", b"hello world", "text/plain")},
    )
    assert bad_upload.status_code == 400

    # Valid PDF upload saves source.pdf and transitions stage -> 'extraction'
    ok_upload = client.post(
        f"/api/projects/{pid}/pdf",
        files={"file": ("ficha_original.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
    )
    assert ok_upload.status_code == 200, ok_upload.text
    updated_proj = ok_upload.json()
    assert updated_proj["has_pdf"] is True
    assert updated_proj["current_stage"] == "extraction"
    assert (ws_dir / "uploads" / "source.pdf").read_bytes() == SAMPLE_PDF_BYTES

    # GET /pdf streams back identical PDF bytes
    dl_res = client.get(f"/api/projects/{pid}/pdf")
    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"].startswith("application/pdf")
    assert dl_res.content == SAMPLE_PDF_BYTES

    # PATCH metadata & stage, then DELETE removes workspace directory
    patch_res = client.patch(
        f"/api/projects/{pid}",
        json={"current_stage": "completed", "template_db_id": 4201, "preferred_harness": "claude"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["current_stage"] == "completed"
    assert patch_res.json()["template_db_id"] == 4201
    assert patch_res.json()["preferred_harness"] == "claude"

    del_res = client.delete(f"/api/projects/{pid}")
    assert del_res.status_code == 200
    assert not ws_dir.exists()
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_project_direct_json_and_jrxml_entry_modes_and_validation(
    client: TestClient,
    studio_env: Path,
) -> None:
    # Direct JSON entry validates JSON, uppercases fields, and auto-generates both SQL scripts
    res_json = client.post(
        "/api/projects",
        json={
            "name": "Triagem Obstétrica",
            "entry_mode": "json",
            "initial_json": _sample_clinical_json(titulo_ficha="Triagem Obstétrica"),
        },
    )
    assert res_json.status_code == 201, res_json.text
    p_json = res_json.json()
    assert p_json["current_stage"] == "form_builder"
    assert p_json["entry_mode"] == "json"
    assert p_json["latest_artifacts"] == {"json": 1, "sql_insert": 1, "sql_select": 1}

    ws_json = Path(p_json["workspace_dir"])
    assert (ws_json / "artifacts" / "ficha.json").is_file()
    assert (ws_json / "artifacts" / "insert.sql").is_file()
    assert (ws_json / "artifacts" / "select_jasper.sql").is_file()

    stored_json = json.loads(
        client.get(f"/api/projects/{p_json['id']}/artifacts/json").json()["content"]
    )
    assert stored_json["template"]["nome"] == "TRIAGEM OBSTÉTRICA"

    # Direct JRXML entry validates XML root and sets stage='jrxml_design'
    res_jrxml = client.post(
        "/api/projects",
        json={
            "name": "Evolução UTI",
            "entry_mode": "jrxml",
            "initial_jrxml": SAMPLE_JRXML,
        },
    )
    assert res_jrxml.status_code == 201, res_jrxml.text
    p_jrxml = res_jrxml.json()
    assert p_jrxml["current_stage"] == "jrxml_design"
    assert p_jrxml["latest_artifacts"] == {"jrxml": 1}
    assert (Path(p_jrxml["workspace_dir"]) / "artifacts" / f"{p_jrxml['slug']}.jrxml").is_file()

    # Invalid JSON & invalid JRXML fail cleanly with 400 and leave no orphan projects
    before_count = len(client.get("/api/projects").json())
    bad_json = client.post(
        "/api/projects",
        json={"name": "Invalida JSON", "entry_mode": "json", "initial_json": {"sem_template": []}},
    )
    assert bad_json.status_code == 400
    bad_jrxml = client.post(
        "/api/projects",
        json={"name": "Invalida XML", "entry_mode": "jrxml", "initial_jrxml": "<div>not jrxml</div>"},
    )
    assert bad_jrxml.status_code == 400
    assert len(client.get("/api/projects").json()) == before_count


# =============================================================================
# 3. Artifact Revisions, Auto SQL Regeneration, Restore, Gates & Chat
# =============================================================================


def test_artifact_revisions_sql_regeneration_validation_gates_and_chat(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/projects",
        json={
            "name": "Ficha Cirurgia Segura",
            "entry_mode": "json",
            "initial_json": _sample_clinical_json(titulo_ficha="Cirurgia Segura", extra_question=False),
        },
    ).json()
    pid = created["id"]

    # Update JSON with extra_question=True and auto_regenerate_sql=True -> v2 across json + SQLs
    put_v2 = client.put(
        f"/api/projects/{pid}/artifacts/json",
        json={
            "content": json.dumps(
                _sample_clinical_json(titulo_ficha="Cirurgia Segura V2", extra_question=True),
                ensure_ascii=False,
            ),
            "summary": "Adicionada evolução de enfermagem",
            "created_by": "agent",
            "auto_regenerate_sql": True,
        },
    )
    assert put_v2.status_code == 200, put_v2.text
    body_v2 = put_v2.json()
    assert body_v2["artifact"]["version_num"] == 2
    assert body_v2["generated_sql_insert"]["version_num"] == 2
    assert body_v2["generated_sql_select"]["version_num"] == 2
    assert "generate_series(1, 3)" in body_v2["generated_sql_insert"]["content"]
    assert "p2_r1" in body_v2["generated_sql_select"]["content"]

    # Save JSON v3 with auto_regenerate_sql=False -> SQL stays at v2
    put_v3 = client.put(
        f"/api/projects/{pid}/artifacts/json",
        json={
            "content": json.dumps(
                _sample_clinical_json(titulo_ficha="Cirurgia Segura V3", extra_question=True),
                ensure_ascii=False,
            ),
            "summary": "Ajuste título sem regerar SQL",
            "auto_regenerate_sql": False,
        },
    )
    assert put_v3.status_code == 200
    assert put_v3.json()["artifact"]["version_num"] == 3
    assert put_v3.json()["generated_sql_insert"] is None
    assert client.get(f"/api/projects/{pid}/artifacts/sql_insert").json()["version_num"] == 2

    # Explicit SQL regenerate endpoint bumps SQLs to v3 with custom boolean_style
    regen = client.post(
        f"/api/projects/{pid}/sql/regenerate",
        json={"select_options": {"boolean_style": "sim_nao"}, "summary": "SQL com SIM/NÃO"},
    )
    assert regen.status_code == 200, regen.text
    assert regen.json()["sql_insert"]["version_num"] == 3
    assert regen.json()["sql_select"]["version_num"] == 3
    assert "'SIM' else 'NÃO'" in regen.json()["sql_select"]["content"]

    # Validate stored SQLs (both valid) and broken inline SQL (invalid)
    val_ins = client.post(f"/api/projects/{pid}/sql/validate", json={"artifact_type": "sql_insert"})
    assert val_ins.status_code == 200 and val_ins.json()["valid"] is True

    val_sel = client.post(f"/api/projects/{pid}/sql/validate", json={"artifact_type": "sql_select"})
    assert val_sel.status_code == 200 and val_sel.json()["valid"] is True

    val_bad = client.post(
        f"/api/projects/{pid}/sql/validate",
        json={"sql": "SELECT (1 + 2 FROM ficha_clinica"},
    )
    assert val_bad.status_code == 200 and val_bad.json()["valid"] is False

    # Revision listing & historical version fetch + restore v1 -> creates JSON v4 + SQLs v4
    json_revs = client.get(f"/api/projects/{pid}/revisions", params={"artifact_type": "json"}).json()
    assert [r["version_num"] for r in json_revs] == [3, 2, 1]

    v1_fetch = client.get(f"/api/projects/{pid}/artifacts/json", params={"version": 1})
    assert v1_fetch.status_code == 200
    assert "CIRURGIA SEGURA V2" not in v1_fetch.json()["content"]

    restored = client.post(
        f"/api/projects/{pid}/artifacts/json/restore",
        json={"version_num": 1, "created_by": "user", "auto_regenerate_sql": True},
    )
    assert restored.status_code == 200
    assert restored.json()["artifact"]["version_num"] == 4
    assert restored.json()["generated_sql_insert"]["version_num"] == 4

    # Approval Gates state transitions
    gates_initial = client.get(f"/api/projects/{pid}/gates").json()
    assert len(gates_initial) == 3
    g1_approved = client.put(
        f"/api/projects/{pid}/gates/gate1_json",
        json={"status": "approved", "decided_by": "dr.fernando", "notes": "Campos clínicos conferidos"},
    )
    assert g1_approved.status_code == 200
    assert g1_approved.json()["status"] == "approved"
    assert g1_approved.json()["decided_by"] == "dr.fernando"

    g2_rejected = client.put(
        f"/api/projects/{pid}/gates/gate2_sql_insert",
        json={"status": "rejected", "decided_by": "dba", "notes": "Revisar orientação"},
    )
    assert g2_rejected.status_code == 200
    assert g2_rejected.json()["status"] == "rejected"

    # Chat messages per phase
    c1 = client.post(
        f"/api/projects/{pid}/chat",
        json={"phase": "extraction", "role": "user", "content": "Extraia a página 1"},
    )
    c2 = client.post(
        f"/api/projects/{pid}/chat",
        json={
            "phase": "jrxml",
            "role": "assistant",
            "content": "Banda detail gerada com 555px.",
            "metadata": {"band_height": 320},
        },
    )
    assert c1.status_code == 201 and c2.status_code == 201
    assert len(client.get(f"/api/projects/{pid}/chat").json()) == 2
    assert len(client.get(f"/api/projects/{pid}/chat", params={"phase": "extraction"}).json()) == 1
    jrxml_msgs = client.get(f"/api/projects/{pid}/chat", params={"phase": "jrxml"}).json()
    assert len(jrxml_msgs) == 1 and jrxml_msgs[0]["metadata"]["band_height"] == 320


# =============================================================================
# 4. Subreport Override, Reset, Custom Upload & Runtime Materialization
# =============================================================================


def test_subreports_builtin_override_reset_and_runtime_materialization(
    client: TestClient,
    studio_env: Path,
) -> None:
    initial_list = client.get("/api/subreports").json()
    assert [item["filename"] for item in initial_list] == list(STANDARD_SUBREPORTS)
    assert all(item["source"] == "builtin" and item["is_overridden"] is False for item in initial_list)

    orig_header_bytes = (BUILTIN_SUBREPORTS_DIR / "cabecalho_retrato.jasper").read_bytes()
    orig_sha = hashlib.sha256(orig_header_bytes).hexdigest()

    # Reject non-.jasper extension
    bad_ext = client.post(
        "/api/subreports",
        files={"file": ("cabecalho_retrato.jrxml", b"<jasperReport/>", "application/xml")},
    )
    assert bad_ext.status_code == 400

    # Override standard `cabecalho_retrato.jasper`
    custom_header_bytes = b"\xca\xfe\xba\xbeCUSTOM_HEADER_JASPER_BINARY"
    custom_sha = hashlib.sha256(custom_header_bytes).hexdigest()
    up_override = client.post(
        "/api/subreports",
        files={"file": ("cabecalho_retrato.jasper", custom_header_bytes, "application/octet-stream")},
    )
    assert up_override.status_code == 201, up_override.text
    info_override = up_override.json()
    assert info_override["source"] == "custom_override"
    assert info_override["is_overridden"] is True
    assert info_override["is_builtin_standard"] is True
    assert info_override["sha256"] == custom_sha

    # Upload an additional custom unit-specific subreport
    extra_bytes = b"\xca\xfe\xba\xbeEXTRA_ASSINATURA_UNIDADE"
    up_extra = client.post(
        "/api/subreports",
        files={"file": ("assinatura_unidade_ame.jasper", extra_bytes, "application/octet-stream")},
    )
    assert up_extra.status_code == 201
    assert up_extra.json()["source"] == "custom_extra"
    assert up_extra.json()["is_builtin_standard"] is False

    # Materialize runtime directory for $P{caminho_relatorio}
    mat_res = client.post("/api/subreports/materialize")
    assert mat_res.status_code == 200
    mat_data = mat_res.json()
    assert mat_data["caminho_relatorio"].endswith("/")
    assert mat_data["count"] == 5

    svc = SubreportService()
    runtime_dir = svc.materialize_runtime_dir()
    assert isinstance(runtime_dir, Path)
    assert (runtime_dir / "cabecalho_retrato.jasper").read_bytes() == custom_header_bytes
    assert (runtime_dir / "assinatura_unidade_ame.jasper").read_bytes() == extra_bytes
    assert (runtime_dir / "dados_paciente.jasper").is_file()

    # Reset override back to built-in
    del_override = client.delete("/api/subreports/cabecalho_retrato.jasper")
    assert del_override.status_code == 200
    assert del_override.json()["reset_to_builtin"] is True
    assert del_override.json()["active"]["source"] == "builtin"
    assert del_override.json()["active"]["sha256"] == orig_sha
    assert (runtime_dir / "cabecalho_retrato.jasper").read_bytes() == orig_header_bytes

    # Delete extra custom subreport removes it from runtime_dir as well
    del_extra = client.delete("/api/subreports/assinatura_unidade_ame.jasper")
    assert del_extra.status_code == 200
    assert del_extra.json()["reset_to_builtin"] is False
    assert del_extra.json()["active"] is None
    assert not (runtime_dir / "assinatura_unidade_ame.jasper").exists()

    # Deleting a non-overridden built-in returns 404
    assert client.delete("/api/subreports/dados_paciente.jasper").status_code == 404


# =============================================================================
# 5. System Health, Settings Persistence, Embedded Skills & Root HTML/SPA
# =============================================================================


def test_system_health_settings_skills_and_root_html_fallback(
    client: TestClient,
    tmp_path: Path,
    studio_env: Path,
) -> None:
    # GET / fallback dark-themed HTML status page (when frontend/dist is absent)
    with TestClient(create_app(frontend_dist_dir=tmp_path / "missing_dist")) as fallback_client:
        root_res = fallback_client.get("/")
        assert root_res.status_code == 200
        assert "text/html" in root_res.headers["content-type"]
        for expected_link in ("/docs", "/api/health", "/api/projects", "/api/subreports"):
            assert expected_link in root_res.text

    # GET /api/health
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["builtin_subreports_count"] == 4
    assert health["effective_subreports_count"] == 4
    assert health["database"]["journal_mode"].lower() == "wal"

    # Settings persistence
    assert client.get("/api/settings").json() == {}
    put_settings = client.put(
        "/api/settings",
        json={
            "default_harness": "agy",
            "jaspersoft_java_home": "C:/Program Files/Java/jdk-17",
            "postgres": {"host": "127.0.0.1", "port": 5432, "ssl": False},
        },
    )
    assert put_settings.status_code == 200
    saved_settings = client.get("/api/settings").json()
    assert saved_settings["default_harness"] == "agy"
    assert saved_settings["postgres"] == {"host": "127.0.0.1", "port": 5432, "ssl": False}

    # Embedded skills discovery
    skills = client.get("/api/skills").json()
    skill_ids = {s["id"] for s in skills}
    assert {"extrator_ficha", "gerador_jrxml"}.issubset(skill_ids)
    assert all(s["name"] and s["description"] for s in skills)

    # Verify create_app serves built SPA index.html when frontend_dist_dir exists
    fake_dist = tmp_path / "fake_dist"
    (fake_dist / "assets").mkdir(parents=True)
    (fake_dist / "index.html").write_text("<!doctype html><div id='root'>SPA</div>", encoding="utf-8")
    (fake_dist / "assets" / "app.js").write_text("console.log('ready');", encoding="utf-8")

    with TestClient(create_app(frontend_dist_dir=fake_dist)) as spa_client:
        spa_root = spa_client.get("/")
        assert spa_root.status_code == 200
        assert "<div id='root'>SPA</div>" in spa_root.text
        spa_js = spa_client.get("/assets/app.js")
        assert spa_js.status_code == 200
        assert "console.log('ready');" in spa_js.text


def test_project_not_found_and_validation_error_responses(client: TestClient) -> None:
    missing_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/projects/{missing_id}").status_code == 404
    assert client.patch(f"/api/projects/{missing_id}", json={"name": "Novo"}).status_code == 404
    assert client.delete(f"/api/projects/{missing_id}").status_code == 404
    assert client.get(f"/api/projects/{missing_id}/artifacts/json").status_code == 404
    assert client.get(f"/api/projects/{missing_id}/revisions").status_code == 404
    assert client.get(f"/api/projects/{missing_id}/gates").status_code == 404
    assert client.get(f"/api/projects/{missing_id}/chat").status_code == 404
    assert client.post(f"/api/projects/{missing_id}/sql/regenerate").status_code == 404


def test_put_artifact_restore_by_revision_id_and_unknown_field_warning(
    client: TestClient,
) -> None:
    proj = client.post(
        "/api/projects",
        json={
            "name": "Ficha Ambulatorial",
            "entry_mode": "json",
            "initial_json": _sample_clinical_json(titulo_ficha="Original V1"),
        },
    ).json()
    pid = proj["id"]
    v1_rev_id = client.get(f"/api/projects/{pid}/artifacts/json").json()["id"]

    # Save v2
    client.put(
        f"/api/projects/{pid}/artifacts/json",
        json={
            "content": json.dumps(_sample_clinical_json(titulo_ficha="Alterada V2")),
            "summary": "v2",
        },
    )

    # Restore v1 via PUT restore_from_revision_id
    restore_put = client.put(
        f"/api/projects/{pid}/artifacts/json",
        json={
            "content": "",
            "restore_from_revision_id": v1_rev_id,
            "auto_regenerate_sql": True,
        },
    )
    assert restore_put.status_code == 200
    assert restore_put.json()["artifact"]["version_num"] == 3
    assert "ORIGINAL V1" in restore_put.json()["artifact"]["content"]


def test_subreport_path_traversal_and_empty_payload_rejected(
    studio_env: Path,
    client: TestClient,
) -> None:
    svc = SubreportService()
    with pytest.raises(Exception):
        svc.save_custom_subreport("../evil.jasper", b"binary")

    empty_upload = client.post(
        "/api/subreports",
        files={"file": ("vazio.jasper", b"", "application/octet-stream")},
    )
    assert empty_upload.status_code == 400


def test_multiple_projects_listing_order_and_slug_normalization(client: TestClient) -> None:
    p1 = client.post("/api/projects", json={"name": "123 Ficha Pediátrica — Urgência!"}).json()
    assert p1["slug"] == "ficha_123_ficha_pediatrica_urgencia"

    p2 = client.post("/api/projects", json={"name": "Evolução Clínica Geral"}).json()
    listed = client.get("/api/projects").json()
    assert [p["id"] for p in listed[:2]] == [p2["id"], p1["id"]]

    # Updating p1 moves p1 to top of list
    client.patch(f"/api/projects/{p1['id']}", json={"description": "Atualizada agora"})
    relisted = client.get("/api/projects").json()
    assert relisted[0]["id"] == p1["id"]
