# -*- coding: utf-8 -*-
"""Testes unitários abrangentes do motor Core SQL, Custom OCR Regex e Form Builder CRUD."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from backend.app.core import (
    CustomRegexRule,
    add_answer,
    add_question,
    apply_custom_regex_rules,
    audit_clinical_json_warnings,
    delete_answer,
    delete_question,
    extract_select_fields_metadata,
    find_unknown_field_types,
    generate_insert_sql,
    generate_select_jasper,
    limpar_ocr_texto,
    load_custom_regex_rules,
    load_default_model_sql,
    normalizar_slug,
    reorder_answers,
    reorder_questions,
    save_custom_regex_rules,
    update_answer,
    update_question,
    uppercase_target_fields,
    validate_custom_regex_rules,
    validate_postgres_syntax,
)


def _sample_clinical_json() -> dict[str, Any]:
    return {
        "template": {
            "nome": "Avaliação Pré-Anestésica",
            "descricao": "Ficha clínica de avaliação",
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "posicao_assinatura": "RODAPE",
            "quantidade_pagina": 1,
        },
        "perguntas": [
            {
                "nome": "1. IDENTIFICAÇÃO SETORIAL",
                "titulo": True,
                "respostas": [],
            },
            {
                "nome": "Sinais Vitais e Alergias",
                "titulo": False,
                "respostas": [
                    {"label": "Alergia medicamentosa", "tipo_campo": "BOOLEANO", "observacao": True},
                    {"label": "Peso (kg)", "tipo_campo": "NUMERICO"},
                    {"label": "Data jejum", "tipo_campo": "DATA"},
                    {"label": "Hora jejum", "tipo_campo": "HORA"},
                    {"label": "CID Principal", "tipo_campo": "CID", "cid_codigo": "J01.9"},
                ],
            },
            {
                "nome": "Observações Livres",
                "titulo": False,
                "respostas": [
                    {"label": "", "tipo_campo": "TEXTO", "quantidade_linhas": 3},
                ],
            },
            {
                "nome": "Risco Cirúrgico ASA",
                "titulo": False,
                "respostas": [
                    {"label": "ASA I", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "ASA II", "tipo_campo": "BOOLEANO_RADIO"},
                ],
            },
        ],
    }


# =============================================================================
# 1. SQL INSERT & Validação Sintática PostgreSQL
# =============================================================================


def test_generate_insert_sql_patterns_and_immutability() -> None:
    original = _sample_clinical_json()
    snapshot = copy.deepcopy(original)

    sql = generate_insert_sql(original)

    # Não deve mutar o dicionário de entrada
    assert original == snapshot

    # Estrutura PL/pgSQL e regras fixas do Salutem
    assert sql.startswith("DO $$")
    assert sql.endswith("END $$;")
    assert "'ficha-clinica'" in sql
    assert "'AVALIAÇÃO PRÉ-ANESTÉSICA'" in sql
    # Padrão 1: generate_series para 3 linhas de TEXTO vazio
    assert "FROM generate_series(1, 3) AS gs" in sql
    # Padrão 2: unnest(ARRAY[...]) WITH ORDINALITY para lista homogênea BOOLEANO_RADIO
    assert "FROM unnest(ARRAY[" in sql
    assert "'ASA I'" in sql and "'ASA II'" in sql
    # Padrão 3: VALUES com colunas extras (cid_codigo preservado)
    assert "'J01.9'" in sql

    ok, msg = validate_postgres_syntax(sql)
    assert ok is True, msg


def test_generate_insert_sql_rejects_invalid_field_type() -> None:
    bad = {
        "template": {"nome": "Ficha Inválida"},
        "perguntas": [
            {
                "nome": "Pergunta",
                "titulo": False,
                "respostas": [{"label": "Campo", "tipo_campo": "TIPO_INEXISTENTE"}],
            }
        ],
    }
    with pytest.raises(ValueError, match="tipo_campo inválido"):
        generate_insert_sql(bad)


def test_validate_postgres_syntax_catches_errors() -> None:
    ok_empty, _ = validate_postgres_syntax("   ")
    assert ok_empty is False

    ok_quote, msg_quote = validate_postgres_syntax("SELECT 'texto sem fechar FROM dual;")
    assert ok_quote is False
    assert "Aspas simples" in msg_quote

    ok_paren, msg_paren = validate_postgres_syntax("SELECT max((id) FROM paciente;")
    assert ok_paren is False
    assert "Parênteses" in msg_paren

    ok_dollar, msg_dollar = validate_postgres_syntax("DO $$ BEGIN PERFORM 1; END;")
    assert ok_dollar is False
    assert "$$" in msg_dollar


# =============================================================================
# 2. Custom OCR Regex (`custom_regex.py` + `sql_insert.py`)
# =============================================================================


def test_custom_regex_rules_load_save_and_apply(tmp_path: Path) -> None:
    rules_raw = [
        {
            "pattern": r"\bPacinte\b",
            "replacement": "Paciente",
            "is_regex": True,
            "ignore_case": True,
        },
        {
            "pattern": "[ARTEFATO_OCR]",
            "replacement": "",
            "is_regex": False,
            "ignore_case": True,
        },
        {
            "pattern": r"NAO_APLICAR",
            "replacement": "ERRO",
            "is_regex": True,
            "enabled": False,
        },
    ]

    rules_file = tmp_path / "custom_ocr.json"
    saved = save_custom_regex_rules(rules_file, rules_raw)
    assert len(saved) == 3
    assert all(isinstance(r, CustomRegexRule) for r in saved)

    loaded = load_custom_regex_rules(rules_file)
    assert loaded == saved

    # Também aceita wrapper {"rules": [...]}
    wrapped = validate_custom_regex_rules({"rules": rules_raw})
    assert len(wrapped) == 3

    cleaned = apply_custom_regex_rules(
        "O pacinte apresentou [artefato_ocr] melhora NAO_APLICAR",
        loaded,
    )
    assert cleaned == "O Paciente apresentou  melhora NAO_APLICAR"


def test_custom_regex_literal_backslash_and_invalid_pattern() -> None:
    # Em modo literal (is_regex=False), barras invertidas no replacement não podem falhar
    res = apply_custom_regex_rules(
        "S/V",
        [{"pattern": "S/V", "replacement": r"SEM\VASO", "is_regex": False}],
    )
    assert res == r"SEM\VASO"

    with pytest.raises(ValueError, match="Expressão regular inválida"):
        validate_custom_regex_rules([{"pattern": "[regex_invalida(", "is_regex": True}])


def test_sql_insert_wires_custom_regex_rules_and_path(tmp_path: Path) -> None:
    rules_path = tmp_path / "ocr_rules.json"
    save_custom_regex_rules(
        rules_path,
        [{"pattern": r"\bAnamneze\b", "replacement": "Anamnese", "is_regex": True, "ignore_case": True}],
    )

    doc = {
        "template": {"nome": "Ficha de Anamneze"},
        "perguntas": [
            {
                "nome": "Queixa de Dispneya",
                "titulo": False,
                "respostas": [{"label": "Equipo de Bonba de Infusão", "tipo_campo": "BOOLEANO"}],
            }
        ],
    }

    sql = generate_insert_sql(
        doc,
        options={
            "custom_regex_path": rules_path,
            "custom_regex_rules": [
                {"pattern": r"\bDispneya\b", "replacement": "Dispneia", "is_regex": True}
            ],
        },
    )

    assert "'FICHA DE ANAMNESE'" in sql
    assert "'QUEIXA DE DISPNEIA'" in sql
    assert "'EQUIPO DE BOMBA DE INFUSÃO'" in sql
    assert limpar_ocr_texto("Anamneze", forcar_maiusculo=True, custom_regex_path=rules_path) == "ANAMNESE"


# =============================================================================
# 3. SQL SELECT & Metadados 1:1 (`sql_select.py`)
# =============================================================================


def test_sql_select_loads_template_and_supports_param_syntax() -> None:
    model_sql = load_default_model_sql()
    assert "----- PERGUNTAS -----" in model_sql

    doc = _sample_clinical_json()

    sql_jasper = generate_select_jasper(doc)
    assert "fc.id = $P{id}" in sql_jasper
    assert "fc.id = ${id}" not in sql_jasper
    ok_j, msg_j = validate_postgres_syntax(sql_jasper)
    assert ok_j is True, msg_j

    sql_salutem = generate_select_jasper(doc, options={"param_syntax": "salutem"})
    assert "fc.id = ${id}" in sql_salutem
    assert "fc.id = $P{id}" not in sql_salutem
    ok_s, msg_s = validate_postgres_syntax(sql_salutem)
    assert ok_s is True, msg_s

    with pytest.raises(ValueError, match="param_syntax"):
        generate_select_jasper(doc, options={"param_syntax": "invalido"})


def test_extract_select_fields_metadata_matches_sql_1_to_1() -> None:
    doc = _sample_clinical_json()
    # Adiciona colisão proposital de alias ("ASA I" repetido como TEXTO com observacao=True)
    doc["perguntas"].append(
        {
            "nome": "Detalhamento ASA",
            "titulo": False,
            "respostas": [
                {"label": "ASA I", "tipo_campo": "TEXTO", "observacao": True},
                {"label": "ASA I", "tipo_campo": "BOOLEANO_RADIO"},
            ],
        }
    )

    sql = generate_select_jasper(doc)
    meta = extract_select_fields_metadata(doc)

    expected = [
        ("alergia_medicamentosa", "java.lang.Boolean", "BOOLEANO", False),
        ("alergia_medicamentosa_obs", "java.lang.String", "BOOLEANO", True),
        ("peso_kg", "java.lang.Double", "NUMERICO", False),
        ("data_jejum", "java.lang.String", "DATA", False),
        ("hora_jejum", "java.lang.String", "HORA", False),
        ("cid_principal", "java.lang.String", "CID", False),
        ("p3_r1", "java.lang.String", "TEXTO", False),
        ("p3_r2", "java.lang.String", "TEXTO", False),
        ("p3_r3", "java.lang.String", "TEXTO", False),
        ("asa_i", "java.lang.Boolean", "BOOLEANO_RADIO", False),
        ("asa_ii", "java.lang.Boolean", "BOOLEANO_RADIO", False),
        # TEXTO com observacao=True NÃO gera coluna _obs!
        ("asa_i_txt", "java.lang.String", "TEXTO", False),
        ("asa_i_bool", "java.lang.Boolean", "BOOLEANO_RADIO", False),
    ]

    actual = [(m["name"], m["java_class"], m["source_type"], m["is_obs"]) for m in meta]
    assert actual == expected

    for alias, _, _, _ in expected:
        assert f" as {alias}," in sql

    # Quando boolean_style != coalesce_bool_or, booleanos projetam texto -> java.lang.String
    meta_x = extract_select_fields_metadata(doc, options={"boolean_style": "x_empty"})
    assert meta_x[0]["java_class"] == "java.lang.String"


def test_normalizar_slug_edge_cases() -> None:
    assert normalizar_slug("CIRURGIÃO / AUXILIAR:") == "cirurgiao_auxiliar"
    assert normalizar_slug("123 TESTE") == "f_123_teste"
    assert normalizar_slug("   ---   ") == "campo"
    assert normalizar_slug(None) == "campo"


# =============================================================================
# 4. Auditoria de Avisos Clínicos & Helpers CRUD do Form Builder (`json_utils.py`)
# =============================================================================


def test_audit_clinical_json_warnings_clean_and_violations() -> None:
    clean = _sample_clinical_json()
    assert audit_clinical_json_warnings(clean) == []

    violating = {
        "template_ficha_clinica": {},
        "template": {
            "nome": "FICHA COM PROBLEMAS",
            "layout": "LAYOUT-ERRADO",
            "quantidade_pagina": 2,
        },
        "perguntas": [
            {
                "nome": "SEÇÃO COM RESPOSTA INDEVIDA",
                "titulo": True,
                "respostas": [{"label": "SIM", "tipo_campo": "BOOLEANO"}],
            },
            {
                "nome": "PERGUNTA SEM RESPOSTAS",
                "titulo": False,
                "respostas": [],
            },
            {
                "nome": "DOIS PARES DE RÁDIO JUNTOS",
                "titulo": False,
                "respostas": [
                    {"label": "Gestante Sim", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "Gestante Não", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "Fumante Sim", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "Fumante Não", "tipo_campo": "BOOLEANO_RADIO"},
                ],
            },
            {
                "nome": "TIPO INVÁLIDO",
                "titulo": False,
                "respostas": [{"label": "Assinatura", "tipo_campo": "ASSINATURA_DIGITAL"}],
            },
        ],
    }

    warnings = audit_clinical_json_warnings(violating)
    codes = {w["code"] for w in warnings}
    assert "LEGACY_TEMPLATE_KEY" in codes
    assert "TEMPLATE_LAYOUT_INVALID" in codes
    assert "TEMPLATE_PAGE_COUNT_INVALID" in codes
    assert "TITLE_WITH_ANSWERS" in codes
    assert "QUESTION_WITHOUT_ANSWERS" in codes
    assert "MULTIPLE_RADIO_GROUPS_RISK" in codes
    assert "UNKNOWN_FIELD_TYPE" in codes
    assert find_unknown_field_types(violating) == ["ASSINATURA_DIGITAL"]


def test_form_builder_crud_and_reordering_preserves_uppercase_and_ordenacao() -> None:
    base: dict[str, Any] = {
        "template": {"nome": "ficha ambulatorial", "layout": "ficha-clinica"},
        "perguntas": [],
    }

    # 1. add_question (append e insert por posição)
    d1 = add_question(base, {"nome": "segunda pergunta", "titulo": False, "respostas": []})
    assert base["perguntas"] == []  # imutável por padrão
    assert d1["template"]["nome"] == "FICHA AMBULATORIAL"
    assert d1["template"]["layout"] == "ficha-clinica"

    d2 = add_question(
        d1,
        {"nome": "seção inicial", "titulo": True, "respostas": []},
        position=0,
    )
    d3 = add_question(
        d2,
        {
            "nome": "terceira pergunta",
            "titulo": False,
            "respostas": [{"label": "opção inicial", "tipo_campo": "booleano"}],
        },
    )

    assert [q["nome"] for q in d3["perguntas"]] == [
        "SEÇÃO INICIAL",
        "SEGUNDA PERGUNTA",
        "TERCEIRA PERGUNTA",
    ]
    assert [q["ordenacao"] for q in d3["perguntas"]] == [1, 2, 3]

    # 2. update_question
    d4 = update_question(d3, 1, {"nome": "anamnese dirigida"})
    assert d4["perguntas"][1]["nome"] == "ANAMNESE DIRIGIDA"
    assert [q["ordenacao"] for q in d4["perguntas"]] == [1, 2, 3]

    # 3. add_answer, update_answer, reorder_answers, delete_answer
    d5 = add_answer(d4, 1, {"label": "febre", "tipo_campo": "booleano"})
    d5 = add_answer(d5, 1, {"label": "outros", "tipo_campo": "booleano", "observacao": True})
    d5 = add_answer(
        d5,
        1,
        {"label": "cid suspeito", "tipo_campo": "cid", "cid_codigo": "a90"},
        position=1,
    )

    resps = d5["perguntas"][1]["respostas"]
    assert [r["label"] for r in resps] == ["FEBRE", "CID SUSPEITO", "OUTROS"]
    assert resps[1]["cid_codigo"] == "a90"  # cid_codigo preserva case!
    assert [r["ordenacao"] for r in resps] == [1, 2, 3]

    d6 = update_answer(d5, 1, 0, {"label": "febre aferida", "campo_obrigatorio": True})
    assert d6["perguntas"][1]["respostas"][0]["label"] == "FEBRE AFERIDA"
    assert d6["perguntas"][1]["respostas"][0]["campo_obrigatorio"] is True

    # Reordenação 0-based [2, 0, 1]
    d7 = reorder_answers(d6, 1, [2, 0, 1])
    assert [r["label"] for r in d7["perguntas"][1]["respostas"]] == [
        "OUTROS",
        "FEBRE AFERIDA",
        "CID SUSPEITO",
    ]
    assert [r["ordenacao"] for r in d7["perguntas"][1]["respostas"]] == [1, 2, 3]

    d8 = delete_answer(d7, 1, 1)
    assert [r["label"] for r in d8["perguntas"][1]["respostas"]] == ["OUTROS", "CID SUSPEITO"]
    assert [r["ordenacao"] for r in d8["perguntas"][1]["respostas"]] == [1, 2]

    # 4. reorder_questions (suporta permutação 1-based [3, 1, 2] e delete_question)
    d9 = reorder_questions(d8, [3, 1, 2])
    assert [q["nome"] for q in d9["perguntas"]] == [
        "TERCEIRA PERGUNTA",
        "SEÇÃO INICIAL",
        "ANAMNESE DIRIGIDA",
    ]
    assert [q["ordenacao"] for q in d9["perguntas"]] == [1, 2, 3]

    d10 = delete_question(d9, 0)
    assert [q["nome"] for q in d10["perguntas"]] == ["SEÇÃO INICIAL", "ANAMNESE DIRIGIDA"]
    assert [q["ordenacao"] for q in d10["perguntas"]] == [1, 2]

    # Índices negativos ou fora de alcance devem lançar IndexError
    with pytest.raises(IndexError):
        delete_question(d10, -1)
    with pytest.raises(IndexError):
        update_answer(d10, 1, 99, {"label": "X"})
    with pytest.raises(ValueError):
        reorder_questions(d10, [0, 0])

    # uppercase_target_fields preserva booleanos intactos
    norm = uppercase_target_fields({"titulo": False, "nome": "teste"})
    assert norm == {"titulo": False, "nome": "TESTE"}
