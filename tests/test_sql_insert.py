# -*- coding: utf-8 -*-
"""
Testes unitários e de integração para `src/core/sql_insert.py` e `src/gui/sql_insert_tab.py`
conforme `spec_sql_perguntas.md`.
"""

import copy
import json
from pathlib import Path
from tkinter import messagebox
import pytest

from src.core.sql_insert import (
    CORRECOES_OCR_EXATAS,
    HOMOGLIFOS_OCR,
    PADROES_OCR_REGEX,
    TIPOS_VALIDOS,
    apply_syntax_highlighting,
    eh_lista_homogenea,
    eh_serie_texto_vazio,
    generate_insert_sql,
    limpar_ocr_texto,
    sql_bool,
    sql_num,
    sql_str,
    usa_colunas_extras,
    validate_postgres_syntax,
)
from src.gui.sql_insert_tab import SqlInsertTab
from src.main import MainApp


def test_eleven_valid_types_constant() -> None:
    expected = {
        "BOOLEANO",
        "BOOLEANO_RADIO",
        "CID",
        "COMBOBOX",
        "DATA",
        "EXAME",
        "HORA",
        "NUMERICO",
        "PROCEDIMENTO",
        "PROCEDIMENTO_CID",
        "TEXTO",
    }
    assert TIPOS_VALIDOS == expected
    assert len(TIPOS_VALIDOS) == 11


def test_ocr_cleaning_and_uppercase() -> None:
    # Homóglifo grego Nu 'Ν' (U+039D) e espaços múltiplos + zero-width space
    raw = "  \u200bEquipo de   Bonba de Infusão\u00a0"
    assert limpar_ocr_texto(raw, forcar_maiusculo=False) == "Equipo de Bomba de Infusão"
    assert limpar_ocr_texto(raw, forcar_maiusculo=True) == "EQUIPO DE BOMBA DE INFUSÃO"

    # Termos com erro de OCR conhecidos (mesmo quando já em maiúsculas)
    assert limpar_ocr_texto("HIDROCORTIZONA 100MG - 500MG", forcar_maiusculo=True) == "HIDROCORTISONA 100MG - 500MG"
    assert limpar_ocr_texto("Ondasentrona", forcar_maiusculo=True) == "ONDANSETRONA"
    assert limpar_ocr_texto("Alcool 70%", forcar_maiusculo=True) == "ÁLCOOL 70%"
    assert limpar_ocr_texto("Cupula", forcar_maiusculo=True) == "CÚPULA"
    assert limpar_ocr_texto("Xylocaina 1% gel", forcar_maiusculo=True) == "XYLOCAÍNA 1% GEL"
    assert limpar_ocr_texto("Cânula Endotraquial \u039do", forcar_maiusculo=True) == "CÂNULA ENDOTRAQUEAL NO"
    assert limpar_ocr_texto("Extensão de faço", forcar_maiusculo=True) == "EXTENSÃO DE FACO"


def test_sql_escaping_and_helpers() -> None:
    assert sql_str(None) == "NULL"
    assert sql_str("caixa d'água", aplicar_ocr=True, forcar_maiusculo=True) == "'CAIXA D''ÁGUA'"
    assert sql_bool(True) == "true"
    assert sql_bool(False) == "false"
    assert sql_bool(None, padrao=True) == "true"
    assert sql_bool(None, padrao=False) == "false"
    assert sql_num(None) == "NULL"
    assert sql_num(None, padrao=0) == "0"
    assert sql_num(42) == "42"


def test_pattern_1_generate_series() -> None:
    data = {
        "template": {
            "nome": "ficha evolução",
            "descricao": "Descrição com Hidrocortizona",
            "quantidade_pagina": 99,
            "layout": "FICHA-CLINICA",
            "orientacao": "paisagem",
            "posicao_assinatura": "lateral",
        },
        "perguntas": [
            {
                "nome": "observações gerais",
                "titulo": False,
                "respostas": [
                    {
                        "label": "   ",
                        "tipo_campo": "TEXTO",
                        "quantidade_linhas": 4,
                        "campo_obrigatorio": True,
                        "importa_historico": False,
                        "observacao": False,
                        "minimo": 0,
                    }
                ],
            }
        ],
    }
    original_copy = copy.deepcopy(data)
    sql = generate_insert_sql(data)

    # Garante que json_data não foi modificado
    assert data == original_copy

    # Regras obrigatórias de template
    assert "DO $$" in sql
    assert "v_template_id bigint;" in sql
    assert "v_pergunta_id bigint;" in sql
    assert "'FICHA EVOLUÇÃO', 'Descrição com Hidrocortisona', true, 'ficha-clinica', 'PAISAGEM'" in sql
    assert "'LATERAL', 1, false," in sql

    # Padrão 1: generate_series
    assert "FROM generate_series(1, 4) AS gs" in sql
    assert "SELECT ''::varchar AS label, gs AS ordem" in sql
    assert "label, 'TEXTO', v_pergunta_id, true, false, ordem, false, 0" in sql
    assert "END $$;" in sql


def test_pattern_2_unnest_with_ordinality() -> None:
    data = {
        "template": {"nome": "ficha medicamentos"},
        "perguntas": [
            {
                "nome": "medicamentos utilizados",
                "titulo": False,
                "respostas": [
                    {
                        "label": "Alcool 70%",
                        "tipo_campo": "BOOLEANO",
                        "campo_obrigatorio": False,
                        "importa_historico": False,
                        "observacao": True,
                        "minimo": 0,
                    },
                    {
                        "label": "Ondasentrona",
                        "tipo_campo": "BOOLEANO",
                        "campo_obrigatorio": False,
                        "importa_historico": False,
                        "observacao": True,
                        "minimo": 0,
                    },
                ],
            }
        ],
    }

    sql = generate_insert_sql(data)
    assert "FROM unnest(ARRAY[" in sql
    assert "'ÁLCOOL 70%'" in sql
    assert "'ONDANSETRONA'" in sql
    assert "]) WITH ORDINALITY AS t(label, ordem)" in sql
    assert "label, 'BOOLEANO', v_pergunta_id, false, false, ordem, true, 0" in sql


def test_pattern_3_values_heterogeneous_and_extra_columns() -> None:
    data = {
        "template": {"nome": "ficha mista"},
        "perguntas": [
            {
                "nome": "identificação divisor",
                "titulo": True,
                "respostas": [],
            },
            {
                "nome": "equipe e horários",
                "titulo": False,
                "respostas": [
                    {
                        "label": "cirurgião:",
                        "tipo_campo": "TEXTO",
                        "campo_obrigatorio": True,
                        "observacao": False,
                    },
                    {
                        "label": "início:",
                        "tipo_campo": "HORA",
                        "campo_obrigatorio": False,
                        "observacao": False,
                    },
                ],
            },
            {
                "nome": "campos com extras",
                "titulo": False,
                "respostas": [
                    {
                        "label": "data atendimento:",
                        "tipo_campo": "DATA",
                        "campo_obrigatorio": True,
                        "observacao": False,
                        "valor_data_atual": True,
                        "cid_codigo": "J00",
                    }
                ],
            },
        ],
    }

    sql = generate_insert_sql(data)

    # Pergunta 1: divisor sem respostas
    assert "-- Pergunta 1: IDENTIFICAÇÃO DIVISOR (titulo=true)" in sql
    assert "v_template_id, 'IDENTIFICAÇÃO DIVISOR', true, 1" in sql

    # Pergunta 2: heterogênea sem colunas extras
    assert "(v_pergunta_id, 'CIRURGIÃO:', 'TEXTO', true, false, 1, false, 0)," in sql
    assert "(v_pergunta_id, 'INÍCIO:', 'HORA', false, false, 2, false, 0);" in sql

    # Pergunta 3: com colunas extras (20 colunas na tabela, 19 no INSERT sem id)
    assert "valor_numerico, valor_texto, valor_booleano, valor_data, valor_hora," in sql
    assert "cid_codigo, procedimento_codigo, exame_id, referencia," in sql
    assert "valor_data_atual, valor_hora_atual" in sql
    assert "'J00', NULL, NULL, NULL, true, NULL)" in sql


def test_invalid_tipo_campo_raises_clear_error() -> None:
    data = {
        "template": {"nome": "ficha erro"},
        "perguntas": [
            {
                "nome": "pergunta invalida",
                "titulo": False,
                "respostas": [
                    {
                        "label": "campo x",
                        "tipo_campo": "CHECKBOX_INVALIDO",
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValueError) as exc_info:
        generate_insert_sql(data)

    msg = str(exc_info.value)
    assert "PERGUNTA INVALIDA" in msg
    assert "CHECKBOX_INVALIDO" in msg
    for valid_t in TIPOS_VALIDOS:
        assert valid_t in msg


def test_sql_insert_tab_in_main_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    erros: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: erros.append((title, msg))
    )

    app = MainApp()
    app.withdraw()
    try:
        assert app.notebook.index("end") == 3
        tab_titles = [app.notebook.tab(i, "text") for i in range(app.notebook.index("end"))]
        assert tab_titles == ["Editar JSON", "Perguntas & Respostas", "Gerar SQL INSERT"]

        sample_data = {
            "template": {
                "nome": "Folha de Débito - Cirurgia Geral",
                "descricao": "Folha de Débito - Cirurgia Geral",
                "ativo": True,
                "layout": "ficha-clinica",
                "orientacao": "RETRATO",
                "posicao_assinatura": "RODAPE",
                "quantidade_pagina": 1,
            },
            "perguntas": [
                {
                    "nome": "medicamentos",
                    "titulo": False,
                    "respostas": [
                        {
                            "label": "Alcool 70%",
                            "tipo_campo": "BOOLEANO",
                            "campo_obrigatorio": False,
                            "observacao": True,
                        },
                        {
                            "label": "Ondasentrona",
                            "tipo_campo": "BOOLEANO",
                            "campo_obrigatorio": False,
                            "observacao": True,
                        },
                    ],
                }
            ],
        }
        app.set_json_data(sample_data)
        snapshot_before = copy.deepcopy(app.json_data)

        sql_tab: SqlInsertTab = app.sql_insert_tab
        assert sql_tab.shared_json is app.json_data

        # Clica em "Gerar SQL INSERT"
        assert sql_tab.generate_sql() is True
        assert sql_tab.status_var.get() == "SQL gerado com sucesso"

        preview = sql_tab.get_preview_text()
        assert "DO $$" in preview
        assert "'ÁLCOOL 70%'" in preview
        assert "'ONDANSETRONA'" in preview
        assert str(sql_tab.btn_copy.cget("state")) == "normal"
        assert str(sql_tab.btn_save.cget("state")) == "normal"

        # Garante que o JSON compartilhado não foi modificado durante a geração
        assert app.json_data == snapshot_before

        # Testa botão Copiar para Área de Transferência
        assert sql_tab.copy_to_clipboard() is True
        assert app.clipboard_get() == preview

        # Testa salvar como .sql em UTF-8
        sql_out_path = tmp_path / "saida_teste.sql"
        assert sql_tab.save_sql_to_path(sql_out_path) is True
        assert sql_out_path.exists()
        assert sql_out_path.read_text(encoding="utf-8") == preview

        # Testa erro quando tipo_campo é inválido
        app.json_data["perguntas"][0]["respostas"][0]["tipo_campo"] = "TIPO_INEXISTENTE"
        assert sql_tab.generate_sql() is False
        assert "tipo_campo inválido" in sql_tab.status_var.get()
        assert len(erros) == 1
    finally:
        app.destroy()
