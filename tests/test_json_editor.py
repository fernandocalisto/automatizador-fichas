# -*- coding: utf-8 -*-
"""
Testes unitários e de integração para a especificação atualizada (spec_json_editor.md):
- src/utils/resource_path.py e SKILL.md embutido
- src/utils/json_utils.py (uppercase_target_fields, validação de estrutura)
- src/gui/landing.py (Tela Inicial, download de SKILL.md, tooltip, arquivo/clipboard)
- src/gui/json_editor_tab.py (Aba 1: Validar & Formatar, Salvar JSON como…, Voltar)
- src/gui/perguntas_tab.py (Aba 2: Accordion expansível, edição UPPERCASE e checkboxes)
- src/main.py (MainApp, dicionário JSON compartilhado in-place entre as abas)
"""

import json
from pathlib import Path
from tkinter import messagebox
import pytest

from src.gui.json_editor_tab import JsonEditorTab
from src.gui.landing import SKILL_TOOLTIP_TEXT, LandingFrame
from src.gui.perguntas_tab import PerguntasTab
from src.main import MainApp
from src.utils.json_utils import (
    apply_uppercase_to_text_fields,
    load_json_file,
    parse_and_validate_clinical_json,
    save_json_file,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)
from src.utils.resource_path import get_skill_file_path, resource_path


def test_resource_path_finds_embedded_skill_md() -> None:
    skill_path = get_skill_file_path()
    assert skill_path.exists()
    assert skill_path.name == "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    assert "extrator-ficha-clinica-salutem" in content
    assert resource_path("SKILL.md").exists()


def test_uppercase_target_fields_preserves_types_and_layout() -> None:
    sample = {
        "template": {
            "nome": "Folha de Débito - Cirurgia Geral",
            "descricao": "Descrição sucinta da ficha clínica",
            "ativo": True,
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "quantidade_pagina": 1,
        },
        "perguntas": [
            {
                "nome": "Equipe Cirúrgica e Horários",
                "titulo": False,
                "respostas": [
                    {
                        "label": "Cirurgião / Auxiliar:",
                        "tipo_campo": "TEXTO",
                        "campo_obrigatorio": False,
                        "observacao": True,
                        "minimo": 0,
                        "cid_codigo": "a00.1",
                    }
                ],
            }
        ],
    }

    res = uppercase_target_fields(sample)

    assert res["template"]["nome"] == "FOLHA DE DÉBITO - CIRURGIA GERAL"
    assert res["template"]["descricao"] == "DESCRIÇÃO SUCINTA DA FICHA CLÍNICA"
    assert res["template"]["ativo"] is True
    assert res["template"]["layout"] == "ficha-clinica"
    assert res["template"]["quantidade_pagina"] == 1

    pergunta = res["perguntas"][0]
    assert pergunta["nome"] == "EQUIPE CIRÚRGICA E HORÁRIOS"
    assert pergunta["titulo"] is False

    resposta = pergunta["respostas"][0]
    assert resposta["label"] == "CIRURGIÃO / AUXILIAR:"
    assert resposta["campo_obrigatorio"] is False
    assert resposta["observacao"] is True
    assert resposta["minimo"] == 0
    assert resposta["cid_codigo"] == "a00.1"


def test_validate_clinical_json_structure() -> None:
    ok, msg = validate_clinical_json_structure({"template": {}, "perguntas": []})
    assert ok is True
    assert msg == ""

    ok_no_tmpl, msg_no_tmpl = validate_clinical_json_structure({"perguntas": []})
    assert ok_no_tmpl is False
    assert "template" in msg_no_tmpl

    ok_no_perg, msg_no_perg = validate_clinical_json_structure({"template": {}})
    assert ok_no_perg is False
    assert "perguntas" in msg_no_perg

    with pytest.raises(ValueError):
        parse_and_validate_clinical_json('{"apenas_outra_chave": 123}')


def test_load_and_save_json_file_utf8(tmp_path: Path) -> None:
    file_path = tmp_path / "ficha.json"
    dados = {
        "template": {"nome": "ficha de evolução médica", "descricao": "evolução diária"},
        "perguntas": [{"nome": "identificação", "titulo": True, "respostas": []}],
    }

    formatted = save_json_file(file_path, dados, apply_uppercase=True)
    assert '"FICHA DE EVOLUÇÃO MÉDICA"' in formatted

    reloaded = load_json_file(file_path)
    assert reloaded["template"]["nome"] == "FICHA DE EVOLUÇÃO MÉDICA"
    assert reloaded["template"]["descricao"] == "EVOLUÇÃO DIÁRIA"
    assert reloaded["perguntas"][0]["nome"] == "IDENTIFICAÇÃO"
    assert reloaded["perguntas"][0]["titulo"] is True


def test_landing_skill_download_and_tooltip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    infos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messagebox, "showinfo", lambda title, msg: infos.append((title, msg))
    )

    app = MainApp()
    app.withdraw()
    try:
        assert app.current_view == "landing"
        landing: LandingFrame = app.landing_frame

        # Verifica texto do tooltip do botão Baixar Skill
        assert "Como usar:" in landing.skill_tooltip.text
        assert landing.skill_tooltip.text == SKILL_TOOLTIP_TEXT

        # Testa exibição e ocultação do tooltip sem erros
        landing.skill_tooltip.show_tooltip()
        assert landing.skill_tooltip.tip_window is not None
        landing.skill_tooltip.hide_tooltip()
        assert landing.skill_tooltip.tip_window is None

        # Testa download do SKILL.md
        dest_skill = tmp_path / "SKILL_baixada.md"
        assert landing.download_skill(destination_path=dest_skill) is True
        assert dest_skill.exists()
        assert "Extrator de Ficha Clinica Salutem" in dest_skill.read_text(encoding="utf-8")
        assert len(infos) == 1
    finally:
        app.destroy()


def test_full_workflow_landing_to_tabs_and_shared_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    erros: list[tuple[str, str]] = []
    monkeypatch.setattr(
        messagebox, "showerror", lambda title, msg: erros.append((title, msg))
    )

    app = MainApp()
    app.withdraw()
    try:
        # 1. Inicia na tela inicial
        assert app.current_view == "landing"
        assert app.notebook.index("end") == 2

        # 2. Tenta carregar JSON inválido na Landing -> permanece na Landing e exibe erro
        bad_json_path = tmp_path / "invalido.json"
        bad_json_path.write_text('{"template": {erro_sintaxe}', encoding="utf-8")
        assert app.landing_frame.load_json_from_path(bad_json_path) is False
        assert app.current_view == "landing"
        assert len(erros) == 1

        # 3. Tenta carregar JSON sem estrutura de ficha clínica -> erro claro
        incomplete_path = tmp_path / "incompleto.json"
        incomplete_path.write_text('{"foo": "bar"}', encoding="utf-8")
        assert app.landing_frame.load_json_from_path(incomplete_path) is False
        assert app.current_view == "landing"
        assert len(erros) == 2

        # 4. Carrega JSON válido -> transição para o Notebook com 2 abas e dict compartilhado
        valid_path = tmp_path / "ficha_valida.json"
        sample_data = {
            "template": {
                "nome": "ficha cirurgia geral",
                "descricao": "descrição da ficha",
                "ativo": True,
                "layout": "ficha-clinica",
            },
            "perguntas": [
                {
                    "nome": "equipe cirúrgica",
                    "titulo": False,
                    "respostas": [
                        {
                            "ordenacao": 1,
                            "label": "cirurgião principal:",
                            "tipo_campo": "TEXTO",
                            "campo_obrigatorio": False,
                            "observacao": True,
                            "importa_historico": False,
                            "valor_data_atual": False,
                            "valor_hora_atual": False,
                        }
                    ],
                },
                {
                    "nome": "materiais especiais",
                    "titulo": False,
                    "respostas": [
                        {
                            "ordenacao": 1,
                            "label": "fio cirúrgico",
                            "tipo_campo": "BOOLEANO",
                            "campo_obrigatorio": False,
                            "observacao": False,
                        }
                    ],
                },
            ],
        }
        valid_path.write_text(json.dumps(sample_data, ensure_ascii=False), encoding="utf-8")

        assert app.landing_frame.load_json_from_path(valid_path) is True
        assert app.current_view == "notebook"

        # Garante que o dicionário compartilhado é exatamente a mesma instância nas duas abas
        assert app.json_editor_tab.shared_json is app.json_data
        assert app.perguntas_tab.shared_json is app.json_data

        assert app.json_data["template"]["nome"] == "FICHA CIRURGIA GERAL"
        assert app.json_data["perguntas"][0]["nome"] == "EQUIPE CIRÚRGICA"
        assert (
            app.json_data["perguntas"][0]["respostas"][0]["label"]
            == "CIRURGIÃO PRINCIPAL:"
        )

        # 5. Interação na Aba 2 (Perguntas & Respostas): expandir, editar texto (UPPERCASE) e checkboxes
        perguntas_tab: PerguntasTab = app.perguntas_tab
        assert len(perguntas_tab.question_items) == 2

        q1_card = perguntas_tab.question_items[0]
        assert q1_card.is_expanded is True  # Primeira pergunta expandida automaticamente
        assert len(q1_card.answer_rows) == 1

        # Edita o nome da pergunta 1 em minúsculas e simula perda de foco
        q1_card.nome_var.set("equipe médica atualizada")
        q1_card.commit_question_name_uppercase()
        assert app.json_data["perguntas"][0]["nome"] == "EQUIPE MÉDICA ATUALIZADA"

        # Edita o label da resposta 1 em minúsculas e marca checkboxes
        r1_row = q1_card.answer_rows[0]
        r1_row.label_var.set("cirurgião titular:")
        r1_row.commit_label_uppercase()
        assert (
            app.json_data["perguntas"][0]["respostas"][0]["label"]
            == "CIRURGIÃO TITULAR:"
        )

        # Marca 'campo_obrigatorio' e 'importa_historico' via checkbox
        r1_row.obrigatorio_var.set(True)
        r1_row.on_boolean_toggled("campo_obrigatorio", r1_row.obrigatorio_var)
        r1_row.importa_historico_var.set(True)
        r1_row.on_boolean_toggled("importa_historico", r1_row.importa_historico_var)

        assert app.json_data["perguntas"][0]["respostas"][0]["campo_obrigatorio"] is True
        assert app.json_data["perguntas"][0]["respostas"][0]["importa_historico"] is True

        # Verifica que o texto da Aba 1 (Editar JSON) já reflete as edições da Aba 2
        editor_text = app.json_editor_tab.get_editor_text()
        assert '"EQUIPE MÉDICA ATUALIZADA"' in editor_text
        assert '"CIRURGIÃO TITULAR:"' in editor_text

        # Expande a pergunta 2 e edita sua resposta
        q2_card = perguntas_tab.question_items[1]
        assert q2_card.is_expanded is False
        q2_card.expand()
        assert q2_card.is_expanded is True
        q2_card.answer_rows[0].label_var.set("grampeador linear")
        perguntas_tab.apply_changes()
        assert (
            app.json_data["perguntas"][1]["respostas"][0]["label"]
            == "GRAMPEADOR LINEAR"
        )

        # 6. Edição na Aba 1 (Editar JSON) -> Validar & Formatar reflete na Aba 2
        editor_tab: JsonEditorTab = app.json_editor_tab
        edited_from_tab1 = json.loads(editor_tab.get_editor_text())
        edited_from_tab1["perguntas"][0]["respostas"][0]["label"] = "anestesista chefe:"
        editor_tab.set_editor_text(json.dumps(edited_from_tab1, ensure_ascii=False, indent=2))
        assert editor_tab.validate_and_format() is True

        assert (
            app.json_data["perguntas"][0]["respostas"][0]["label"]
            == "ANESTESISTA CHEFE:"
        )
        assert (
            perguntas_tab.question_items[0].answer_rows[0].label_var.get()
            == "ANESTESISTA CHEFE:"
        )

        # 7. Testar botão "Voltar à Tela Inicial"
        perguntas_tab.btn_back.invoke()
        assert app.current_view == "landing"
        assert app.get_json_data() is None
    finally:
        app.destroy()
