# -*- coding: utf-8 -*-
"""End-to-end integration test combining all 3 Etapa 1 parallel tracks over HTTP."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend.app.main import create_app


def _make_sample_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 60), "FICHA DE AVALIACAO PRE-ANESTESICA", fontsize=14)
    page.insert_text((40, 210), "JEJUM ADEQUADO?", fontsize=10)
    page.draw_rect(fitz.Rect(160, 200, 170, 210), color=(0, 0, 0), width=0.75)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_etapa1_full_integrated_pipeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(tmp_path / "studio_data"))
    app = create_app()

    with TestClient(app) as client:
        # 1. Discover all 4 harnesses + skills + subreports
        harnesses_resp = client.get("/api/harnesses")
        assert harnesses_resp.status_code == 200
        harnesses = harnesses_resp.json()
        harness_ids = [h["id"] for h in harnesses]
        assert harness_ids == ["agy", "opencode", "claude", "codex"]

        skills_resp = client.get("/api/skills")
        assert skills_resp.status_code == 200
        assert len(skills_resp.json()) == 2

        subreports_resp = client.get("/api/subreports")
        assert subreports_resp.status_code == 200
        assert len(subreports_resp.json()) == 4

        # 2. Create project with clinical JSON
        initial_json = {
            "template": {
                "nome": "Avaliação Pré-Anestésica",
                "descricao": "Ficha pré-operatória",
                "ativo": True,
                "layout": "ficha-clinica",
                "orientacao": "RETRATO",
                "posicao_assinatura": "RODAPE",
                "quantidade_pagina": 1,
                "importa_historico_ficha_clinica": False,
            },
            "perguntas": [
                {
                    "nome": "Jejum Adequado?",
                    "titulo": False,
                    "respostas": [
                        {"label": "Sim", "tipo_campo": "BOOLEANO_RADIO", "observacao": False},
                        {"label": "Não", "tipo_campo": "BOOLEANO_RADIO", "observacao": True},
                    ],
                }
            ],
        }
        proj_resp = client.post(
            "/api/projects",
            json={
                "name": "Avaliação Pré-Anestésica",
                "entry_mode": "json",
                "initial_json": json.dumps(initial_json, ensure_ascii=False),
            },
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 3. Upload PDF and inspect PDF geometry (checkbox detection)
        pdf_resp = client.post(
            f"/api/projects/{project_id}/pdf",
            files={"file": ("pre_anestesica.pdf", _make_sample_pdf_bytes(), "application/pdf")},
        )
        assert pdf_resp.status_code == 200

        geom_resp = client.get(f"/api/projects/{project_id}/pdf/geometry")
        assert geom_resp.status_code == 200
        geom = geom_resp.json()
        assert geom["page_count"] == 1
        assert geom["pages"][0]["orientation"] == "RETRATO"
        assert len(geom["pages"][0]["candidate_markers"]) >= 1

        # 4. Mutate via Form Builder CRUD (add a new question + answer)
        mut_resp = client.post(
            f"/api/projects/{project_id}/form-builder/mutate",
            json={
                "action": "add_question",
                "data": {
                    "nome": "Observações Gerais",
                    "titulo": False,
                    "respostas": [{"label": "", "tipo_campo": "TEXTO", "quantidade_linhas": 2}],
                },
            },
        )
        assert mut_resp.status_code == 200

        # 5. Verify SQL SELECT uses $P{id} and scaffold Salutem .jrxml
        scaf_resp = client.post(f"/api/projects/{project_id}/jrxml/scaffold", json={"save_artifact": True})
        assert scaf_resp.status_code == 200
        scaf_data = scaf_resp.json()
        assert scaf_data["lint"]["is_valid"] is True
        assert scaf_data["lint"]["errors"] == []
        assert "fc.id = $P{id}" in scaf_data["jrxml"]
        assert "cabecalho_retrato.jasper" in scaf_data["jrxml"]
        assert '<field name="nao_obs" class="java.lang.String">' in scaf_data["jrxml"]

        # 6. Lint stored .jrxml directly
        lint_resp = client.post(f"/api/projects/{project_id}/jrxml/lint", json={})
        assert lint_resp.status_code == 200
        assert lint_resp.json()["is_valid"] is True
