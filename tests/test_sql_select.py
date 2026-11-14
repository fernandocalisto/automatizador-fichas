# -*- coding: utf-8 -*-
"""
Testes unitários e de integração para `src/core/sql_select.py` e
`src/gui/wizard/sql_select_page.py` (SELECT Jasper Padrão Ouro).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from src.core.sql_select import (
    find_unknown_field_types,
    generate_select_jasper,
    gerar_secao_perguntas,
    normalizar_slug,
    sufixo_tipo,
    validate_postgres_syntax,
)
from src.gui.wizard.sql_select_page import SqlSelectPage
from src.main import MainApp


def _sample_ficha_json() -> dict[str, Any]:
    return {
        "template": {
            "nome": "FICHA CIRURGIA TESTE",
            "descricao": "Ficha para testes SELECT Jasper",
            "ativo": True,
            "layout": "ficha-clinica",
        },
        "perguntas": [
            {
                "nome": "IDENTIFICAÇÃO",
                "titulo": True,
                "respostas": [],
            },
            {
                "nome": "EQUIPE E HORÁRIOS",
                "titulo": False,
                "observacao": False,
                "respostas": [
                    {
                        "label": "Cirurgião / Auxiliar:",
                        "tipo_campo": "TEXTO",
                        "observacao": True,
                    },
                    {
                        "label": "Início:",
                        "tipo_campo": "HORA",
                        "observacao": False,
                    },
                    {
                        "label": "Data Procedimento:",
                        "tipo_campo": "DATA",
                        "observacao": False,
                    },
                    {
                        "label": "Quantidade:",
                        "tipo_campo": "NUMERICO",
                        "observacao": False,
                    },
                ],
            },
            {
                "nome": "MEDICAMENTOS",
                "titulo": False,
                "respostas": [
                    {
                        "label": "Álcool 70%",
                        "tipo_campo": "BOOLEANO",
                        "observacao": True,
                    },
                    {
                        "label": "   ",
                        "tipo_campo": "TEXTO",
                        "quantidade_linhas": 2,
                        "observacao": False,
                    },
                ],
            },
        ],
    }


def test_normalizar_slug_and_sufixo_tipo() -> None:
    assert normalizar_slug("CIRURGIÃO / AUXILIAR:") == "cirurgiao_auxiliar"
    assert normalizar_slug("ÁLCOOL 70%") == "alcool_70"
    assert normalizar_slug("123 TESTE") == "f_123_teste"
    assert normalizar_slug("") == "campo"
    assert normalizar_slug(None) == "campo"

    assert sufixo_tipo("BOOLEANO") == "bool"
    assert sufixo_tipo("BOOLEANO_RADIO") == "bool"
    assert sufixo_tipo("HORA") == "hora"
    assert sufixo_tipo("DATA") == "data"
    assert sufixo_tipo("NUMERICO") == "num"
    assert sufixo_tipo("TEXTO") == "txt"
    assert sufixo_tipo("CID") == "cid"


@pytest.mark.parametrize(
    ("boolean_style", "expected_snippet"),
    [
        ("coalesce_bool_or", "coalesce(bool_or("),
        ("x_empty", "then 'X' end), '') as alcool_70,"),
        ("sim_nao", "then 'SIM' else 'NÃO' end as alcool_70,"),
        ("1_0", "then 1 else 0 end as alcool_70,"),
    ],
)
def test_boolean_styles_variations(
    boolean_style: str, expected_snippet: str
) -> None:
    data = _sample_ficha_json()
    secao = gerar_secao_perguntas(
        data,
        options={"boolean_style": boolean_style, "column_naming": "label_only"},
    )
    assert expected_snippet in secao


def test_column_naming_and_collision_resolution() -> None:
    data = {
        "template": {"nome": "FICHA COLISÃO"},
        "perguntas": [
            {
                "nome": "SINAIS VITAIS",
                "titulo": False,
                "respostas": [
                    {"label": "Pressão", "tipo_campo": "TEXTO"},
                    {"label": "Pressão", "tipo_campo": "NUMERICO"},
                    {"label": "Pressão", "tipo_campo": "NUMERICO"},
                    {"label": "", "tipo_campo": "TEXTO", "quantidade_linhas": 2},
                ],
            }
        ],
    }

    # label_only + colisões + expansão de quantidade_linhas
    secao_label_only = gerar_secao_perguntas(
        data, options={"column_naming": "label_only"}
    )
    assert " as pressao," in secao_label_only
    assert " as pressao_num," in secao_label_only
    assert " as pressao_num_2," in secao_label_only
    assert " as p1_r4," in secao_label_only
    assert " as p1_r5," in secao_label_only

    # pergunta_label
    secao_perg_label = gerar_secao_perguntas(
        data, options={"column_naming": "pergunta_label"}
    )
    assert " as sinais_vitais_pressao," in secao_perg_label
    assert " as sinais_vitais_r4," in secao_perg_label

    # label_sufixo
    secao_sufixo = gerar_secao_perguntas(
        data, options={"column_naming": "label_sufixo"}
    )
    assert " as pressao_txt," in secao_sufixo
    assert " as pressao_num," in secao_sufixo
    assert " as pressao_num_2," in secao_sufixo


def test_observations_and_metadata_and_title_filtering() -> None:
    data = _sample_ficha_json()

    # Padrão: inclui _obs para BOOLEANO com observacao=True, não para TEXTO
    secao_default = gerar_secao_perguntas(data)
    assert " as alcool_70_obs," in secao_default
    assert "cirurgiao_auxiliar_obs" not in secao_default
    assert "-- Pergunta 1: IDENTIFICAÇÃO" in secao_default

    # include_obs=False remove _obs
    secao_sem_obs = gerar_secao_perguntas(data, options={"include_obs": False})
    assert "alcool_70_obs" not in secao_sem_obs

    # include_metadata=True + only_non_title=True
    secao_meta = gerar_secao_perguntas(
        data, options={"include_metadata": True, "only_non_title": True}
    )
    assert "-- Pergunta 1: IDENTIFICAÇÃO" not in secao_meta
    assert "-- [Metadados] titulo=False" in secao_meta


def test_additional_blocks_and_trailing_comma_removal() -> None:
    data = _sample_ficha_json()
    original_copy = copy.deepcopy(data)

    sql_full = generate_select_jasper(data)
    assert data == original_copy
    assert "----- PERGUNTAS -----" in sql_full
    assert "----- PACIENTE" in sql_full
    assert "----- PROFISSIONAL -----" in sql_full
    assert "from ficha_clinica" in sql_full.lower()
    ok, _msg = validate_postgres_syntax(sql_full)
    assert ok is True

    # Sem blocos adicionais: substitui cabeçalho por `select` e remove vírgula antes de `from ficha_clinica`
    sql_no_blocks = generate_select_jasper(
        data, options={"include_all_blocks": False}
    )
    assert sql_no_blocks.startswith("select\n")
    assert "----- PACIENTE" not in sql_no_blocks
    assert "----- PROFISSIONAL -----" not in sql_no_blocks
    assert "----- ATENDIMENTO -----" not in sql_no_blocks

    lines_before_from = sql_no_blocks.split("\nfrom ficha_clinica")[0].rstrip().splitlines()
    last_code_line = next(
        line for line in reversed(lines_before_from) if line.strip() and not line.strip().startswith("--")
    )
    assert not last_code_line.rstrip().endswith(",")

    # Apenas Paciente ativo (sem Profissional e sem Atendimento)
    sql_only_paciente = generate_select_jasper(
        data,
        options={
            "include_all_blocks": True,
            "include_cabecalho": False,
            "include_paciente": True,
            "include_profissional": False,
            "include_atendimento": False,
        },
    )
    assert "----- PACIENTE" in sql_only_paciente
    assert "----- PROFISSIONAL -----" not in sql_only_paciente
    assert "----- ATENDIMENTO -----" not in sql_only_paciente


def test_find_unknown_field_types() -> None:
    data = {
        "template": {"nome": "TESTE"},
        "perguntas": [
            {
                "nome": "P1",
                "respostas": [
                    {"label": "A", "tipo_campo": "TEXTO"},
                    {"label": "B", "tipo_campo": "TIPO_DESCONHECIDO"},
                    {"label": "C", "tipo_campo": ""},
                ],
            }
        ],
    }
    assert find_unknown_field_types(data) == ["<VAZIO>", "TIPO_DESCONHECIDO"]


def test_sql_select_page_in_main_app(tmp_path: Path) -> None:
    app = MainApp()
    app.withdraw()
    try:
        data = _sample_ficha_json()
        app.set_json_data(data)

        select_page: SqlSelectPage = app.sql_select_page
        assert select_page.shared_json is app.json_data

        assert select_page.generate_sql(show_error_dialog=False) is True
        assert select_page.status_var.get() == "SELECT gerado com sucesso"
        preview = select_page.get_preview_text()
        assert "----- PERGUNTAS -----" in preview
        assert "coalesce(bool_or(" in preview
        assert str(select_page.btn_copy.cget("state")) == "normal"
        assert str(select_page.btn_save.cget("state")) == "normal"

        # Alterar opção na UI regenera automaticamente o SQL
        select_page.cmb_boolean_style.setCurrentIndex(2)  # 'SIM'/'NÃO'
        assert "then 'SIM' else 'NÃO' end" in select_page.get_preview_text()

        # Copiar para clipboard e salvar .sql
        assert select_page.copy_to_clipboard() is True
        assert app.clipboard_get() == select_page.get_preview_text()

        out_path = tmp_path / "select_jasper.sql"
        assert select_page.save_sql_to_path(out_path) is True
        assert out_path.exists()
        assert out_path.read_text(encoding="utf-8") == select_page.get_preview_text()

        # Aviso na barra de status para tipo_campo desconhecido
        app.json_data["perguntas"][1]["respostas"][0]["tipo_campo"] = "DESCONHECIDO"
        assert select_page.generate_sql(show_error_dialog=False) is True
        assert "Aviso: tipo_campo desconhecido" in select_page.status_var.get()
    finally:
        app.destroy()
