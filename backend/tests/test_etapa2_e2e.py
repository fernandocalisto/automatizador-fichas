# -*- coding: utf-8 -*-
"""Real JVM end-to-end integration test for Etapa 2 (Jasper Daemon + Offline Subreports + Fictitious PDF + Bundle)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend.app.jrxml import DetailBandBuilder, inject_detail_bands
from backend.app.main import create_app
from backend.app.services.jasper_daemon import JasperDaemonService


def test_etapa2_real_jvm_preview_and_export_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(tmp_path / "studio_data"))
    monkeypatch.setenv("FICHA_STUDIO_SECRET_KEY", "test-secret-etapa2")

    daemon = JasperDaemonService()
    app = create_app(jasper_daemon=daemon)

    try:
        with TestClient(app) as client:
            # 1. Verify warm Java Jasper Daemon health via HTTP API
            health_resp = client.get("/api/jasper/health")
            assert health_resp.status_code == 200
            assert health_resp.json()["status"] == "UP"

            # 2. Verify DB profile vault creation + password redaction over HTTP
            db_resp = client.post(
                "/api/db/profiles",
                json={
                    "name": "Homologação Salutem",
                    "host": "127.0.0.1",
                    "port": 5432,
                    "dbname": "salutem_homolog",
                    "user": "salutem",
                    "password": "super-secret-password",
                    "read_only": True,
                },
            )
            assert db_resp.status_code == 201
            db_prof = db_resp.json()
            assert db_prof["has_password"] is True
            assert "password" not in db_prof

            # 3. Create clinical form project and scaffold Salutem .jrxml
            clinical_json = {
                "template": {
                    "nome": "Evolução de Enfermagem UTI",
                    "descricao": "Ficha diária da UTI adulto",
                    "ativo": True,
                    "layout": "ficha-clinica",
                    "orientacao": "RETRATO",
                    "posicao_assinatura": "RODAPE",
                    "quantidade_pagina": 1,
                    "importa_historico_ficha_clinica": False,
                },
                "perguntas": [
                    {
                        "nome": "Nível de Consciência",
                        "titulo": False,
                        "respostas": [
                            {"label": "Lúcido", "tipo_campo": "BOOLEANO_RADIO"},
                            {"label": "Sedado", "tipo_campo": "BOOLEANO_RADIO"},
                        ],
                    },
                    {
                        "nome": "Conduta de Enfermagem",
                        "titulo": False,
                        "respostas": [
                            {"label": " Anotação Clínica ", "tipo_campo": "TEXTO"},
                        ],
                    },
                ],
            }
            proj_resp = client.post(
                "/api/projects",
                json={
                    "name": "Evolução de Enfermagem UTI",
                    "entry_mode": "json",
                    "initial_json": json.dumps(clinical_json, ensure_ascii=False),
                },
            )
            assert proj_resp.status_code == 201
            project_id = proj_resp.json()["id"]

            scaf_resp = client.post(
                f"/api/projects/{project_id}/jrxml/scaffold",
                json={"save_artifact": True},
            )
            assert scaf_resp.status_code == 200
            base_jrxml = scaf_resp.json()["jrxml"]

            # 4. Build a rich <detail> band with radio circles + text field and save JRXML
            band = DetailBandBuilder(height=90, column_width=555)
            band.add_static_text(0, 6, 180, 14, "NÍVEL DE CONSCIÊNCIA:", bold=True, font_size=9)
            band.add_radio_circle(190, 8, "lucido", label="Lúcido", label_width=70)
            band.add_radio_circle(280, 8, "sedado", label="Sedado", label_width=70)
            band.add_static_text(0, 30, 180, 14, "CONDUTA DE ENFERMAGEM:", bold=True, font_size=9)
            band.add_text_field(0, 46, 555, 32, "anotacao_clinica", font_size=9, box=0.5)

            enriched_jrxml = inject_detail_bands(base_jrxml, [band.build()])
            save_jrxml_resp = client.put(
                f"/api/projects/{project_id}/artifacts/jrxml",
                json={"content": enriched_jrxml, "summary": "Layout UTI com rádios e conduta"},
            )
            assert save_jrxml_resp.status_code == 200

            # 5. Render REAL PDF + PNG preview via warm JVM daemon (compiles mock subreports + main report!)
            prev_resp = client.post(
                f"/api/projects/{project_id}/jasper/preview",
                json={"scenario": "full", "mode": "offline", "dpi": 120},
            )
            assert prev_resp.status_code == 200, prev_resp.text
            prev_data = prev_resp.json()
            assert prev_data["effective_mode"] == "offline"
            assert prev_data["page_count"] >= 1
            assert len(prev_data["pages"]) >= 1

            # Verify PNG page endpoint returns valid PNG bytes
            png_resp = client.get(f"/api/projects/{project_id}/jasper/preview/pages/1?scenario=full")
            assert png_resp.status_code == 200
            assert png_resp.content[:8] == b"\x89PNG\r\n\x1a\n"

            # 6. Download final Salutem delivery .zip bundle and inspect real rendered PDF text with PyMuPDF!
            zip_resp = client.get(f"/api/projects/{project_id}/jasper/export-bundle?scenario=full")
            assert zip_resp.status_code == 200
            with zipfile.ZipFile(io.BytesIO(zip_resp.content), "r") as zf:
                names = zf.namelist()
                jrxml_names = [n for n in names if n.endswith(".jrxml")]
                pdf_names = [n for n in names if n.endswith(".pdf")]
                sql_names = [n for n in names if n.endswith(".sql")]
                assert len(jrxml_names) == 1
                assert len(pdf_names) == 1
                assert len(sql_names) == 1

                # Production .jrxml inside zip must preserve $P{REPORT_CONNECTION} and $P{id}
                prod_jrxml = zf.read(jrxml_names[0]).decode("utf-8")
                assert "$P{REPORT_CONNECTION}" in prod_jrxml
                assert "fc.id = $P{id}" in prod_jrxml

                # Rendered fictitious PDF must contain title, subreport banner, and detail labels!
                pdf_bytes = zf.read(pdf_names[0])
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                full_pdf_text = "\n".join(page.get_text() for page in doc)
                doc.close()
                assert "EVOLUÇÃO DE ENFERMAGEM UTI" in full_pdf_text.upper()
                assert "SALUTEM" in full_pdf_text.upper()
                assert "CONSCIÊNCIA" in full_pdf_text.upper()
    finally:
        daemon.stop()
