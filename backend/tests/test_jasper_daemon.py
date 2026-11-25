# -*- coding: utf-8 -*-
"""
Testes end-to-end contra o daemon JVM real (`jasper-daemon.jar --action serve`):
- Healthcheck `/health` e ciclo de vida aquecido
- Compilação aquecida + `export_pdf` com `mock_rows` e coerção automática de tipos
  (`String`, `Boolean`, `Double`, `Long`, `java.sql.Date`) em `.jrxml` construído com `DetailBandBuilder`,
  validando o texto renderizado no PDF via PyMuPDF (`fitz`)
- Diagnóstico estruturado (`JasperDaemonError` HTTP 422) em `$F{inexistente}` mantendo o daemon saudável
- Descompilação de `resources/subreports/rodape_retrato.jasper`
- Auto-restart transparente caso o processo JVM seja encerrado abruptamente
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import fitz
import pytest

from backend.app.config import BUILTIN_SUBREPORTS_DIR
from backend.app.jrxml.builder import DetailBandBuilder, inject_detail_bands
from backend.app.jrxml.scaffolder import scaffold_salutem_jrxml
from backend.app.services.jasper_daemon import (
    JasperDaemonError,
    JasperDaemonService,
    get_jasper_daemon,
)


@pytest.fixture(scope="module")
def daemon() -> Iterator[JasperDaemonService]:
    svc = JasperDaemonService()
    svc.ensure_started()
    try:
        yield svc
    finally:
        svc.stop()


def _sample_clinical_json() -> dict:
    return {
        "template": {
            "nome": "Ficha de Triagem Ambulatorial",
            "descricao": "Triagem ambulatorial",
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "quantidade_pagina": 1,
        },
        "perguntas": [
            {
                "nome": "Triagem Clínica",
                "titulo": False,
                "respostas": [
                    {"label": "Queixa Principal", "tipo_campo": "TEXTO"},
                    {"label": "Hipertenso", "tipo_campo": "BOOLEANO"},
                    {"label": "Temperatura Axilar", "tipo_campo": "NUMERICO"},
                ],
            }
        ],
    }


def test_daemon_health_and_singleton_accessor(daemon: JasperDaemonService) -> None:
    health = daemon.health()
    assert health["status"] == "UP"
    assert health["ok"] is True
    assert isinstance(health["port"], int) and health["port"] > 0
    assert isinstance(health["pid"], int) and health["pid"] > 0
    assert daemon.is_running is True
    assert daemon.port == health["port"]
    assert daemon.pid == health["pid"]

    shared = get_jasper_daemon()
    assert isinstance(shared, JasperDaemonService)


def test_warm_compile_and_mock_pdf_export_renders_detail_band(
    daemon: JasperDaemonService,
    tmp_path: Path,
) -> None:
    base_jrxml = scaffold_salutem_jrxml(_sample_clinical_json())

    band = (
        DetailBandBuilder(height=120)
        .add_section_header(0, "AVALIACAO DE ENFERMAGEM")
        .add_styled_gap_text(
            0,
            22,
            555,
            18,
            "Paciente: {pac_nome} | Queixa: {queixa_principal}",
        )
        .add_checkbox(0, 46, "hipertenso", label="Paciente Hipertenso")
        .add_text_field(
            200,
            46,
            355,
            16,
            expression='"Temp: " + String.valueOf($F{temperatura_axilar}) + " C | Pront: " + String.valueOf($F{pac_pront})',
        )
        .add_text_field(
            0,
            70,
            555,
            16,
            "pac_nasc",
            pattern="dd/MM/yyyy",
        )
    )
    final_jrxml = inject_detail_bands(base_jrxml, band)

    jrxml_path = tmp_path / "ficha_triagem.jrxml"
    jasper_path = tmp_path / "ficha_triagem.jasper"
    pdf_path = tmp_path / "ficha_triagem_mock.pdf"
    jrxml_path.write_text(final_jrxml, encoding="utf-8")

    # 1. Compilação aquecida
    compile_res = daemon.compile(jrxml_path, jasper_path, subreport_dir=BUILTIN_SUBREPORTS_DIR)
    assert compile_res["status"] == "SUCCESS"
    assert compile_res["action"] == "compile"
    assert jasper_path.is_file()
    assert jasper_path.stat().st_size > 0

    # 2. Inspeção de parâmetros/campos
    inspect_res = daemon.inspect_params(jrxml_path)
    assert inspect_res["status"] == "SUCCESS"
    field_names = {f["name"] for f in inspect_res["metadata"]["fields"]}
    assert {"pac_nome", "queixa_principal", "hipertenso", "temperatura_axilar", "pac_nasc"} <= field_names

    # 3. Exportação PDF com mock_rows e coerção automática de tipos (Long, Date, Double, Boolean, String)
    mock_rows = [
        {
            "pac_id": 501,
            "pac_nome": "MARIA OLIVEIRA DA SILVA",
            "pac_nasc": "1985-04-20",
            "pac_idade_a": 41.0,
            "pac_pront": 998877,
            "atendimento_id": 123456,
            "queixa_principal": "CEFALÉIA FRONTAL HÁ 2 DIAS",
            "hipertenso": "sim",
            "temperatura_axilar": "37.4",
            "prof_nome": "DR. CARLOS MENDES",
        }
    ]
    export_res = daemon.export_pdf(
        jrxml_path,
        pdf_path,
        params={"id": 123456},
        mock_rows=mock_rows,
        subreport_dir=BUILTIN_SUBREPORTS_DIR,
    )
    assert export_res["status"] == "SUCCESS"
    assert export_res["action"] == "export"
    assert export_res["pages"] == 1
    assert export_res["metadata"]["dataSource"] == "mock"
    assert export_res["metadata"]["mockRowCount"] == 1
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 1000

    # 4. Valida texto efetivamente renderizado dentro do PDF via PyMuPDF (fitz)
    with fitz.open(pdf_path) as doc:
        assert doc.page_count == 1
        pdf_text = doc[0].get_text("text")

    assert "FICHA DE TRIAGEM AMBULATORIAL" in pdf_text
    assert "AVALIACAO DE ENFERMAGEM" in pdf_text
    assert "MARIA OLIVEIRA DA SILVA" in pdf_text
    assert "CEFALÉIA FRONTAL HÁ 2 DIAS" in pdf_text
    assert "Paciente Hipertenso" in pdf_text
    assert "37.4" in pdf_text
    assert "998877" in pdf_text
    assert "20/04/1985" in pdf_text


def test_invalid_field_returns_structured_422_error_without_crashing_daemon(
    daemon: JasperDaemonService,
    tmp_path: Path,
) -> None:
    pid_before = daemon.pid
    assert pid_before is not None

    base_jrxml = scaffold_salutem_jrxml(_sample_clinical_json())
    bad_band = DetailBandBuilder(height=40).add_text_field(0, 4, 300, 16, "inexistente")
    bad_jrxml = inject_detail_bands(base_jrxml, bad_band)

    bad_path = tmp_path / "ficha_quebrada.jrxml"
    bad_path.write_text(bad_jrxml, encoding="utf-8")

    with pytest.raises(JasperDaemonError) as exc_info:
        daemon.compile(bad_path)

    err = exc_info.value
    assert err.status_code == 422
    assert err.error_type == "COMPILATION_ERROR"
    combined_diag = f"{err.message}\n{err.stack_trace_snippet or ''}"
    assert "inexistente" in combined_diag

    # O daemon deve continuar vivo e saudável no mesmo PID após erro de compilação
    health_after = daemon.health()
    assert health_after["status"] == "UP"
    assert health_after["pid"] == pid_before


def test_decompile_builtin_rodape_retrato_subreport(
    daemon: JasperDaemonService,
    tmp_path: Path,
) -> None:
    rodape_jasper = BUILTIN_SUBREPORTS_DIR / "rodape_retrato.jasper"
    assert rodape_jasper.is_file()

    decompiled_jrxml = tmp_path / "rodape_retrato.jrxml"
    res = daemon.decompile(rodape_jasper, decompiled_jrxml)

    assert res["status"] == "SUCCESS"
    assert res["action"] == "decompile"
    assert res["metadata"]["reportName"] == "rodape_retrato"
    assert decompiled_jrxml.is_file()

    xml_content = decompiled_jrxml.read_text(encoding="utf-8")
    assert not xml_content.startswith("\ufeff")
    assert xml_content.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<jasperReport" in xml_content
    assert 'name="rodape_retrato"' in xml_content


def test_daemon_auto_restarts_after_unexpected_jvm_death(tmp_path: Path) -> None:
    svc = JasperDaemonService()
    try:
        h1 = svc.health()
        pid1 = h1["pid"]
        assert h1["status"] == "UP"

        # Simula queda abrupta da JVM
        assert svc._process is not None
        svc._process.kill()
        svc._process.wait(timeout=5.0)

        # Uma chamada subsequente deve reiniciar a JVM automaticamente
        out_jrxml = tmp_path / "rodape_after_restart.jrxml"
        res = svc.decompile(BUILTIN_SUBREPORTS_DIR / "rodape_retrato.jasper", out_jrxml)
        assert res["status"] == "SUCCESS"
        assert out_jrxml.is_file()

        h2 = svc.health()
        assert h2["status"] == "UP"
        assert h2["pid"] != pid1
    finally:
        svc.stop()
        assert svc.is_running is False
