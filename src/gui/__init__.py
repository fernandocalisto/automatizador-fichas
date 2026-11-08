#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pacote de interface gráfica (src/gui) do Automatizador de Fichas - PySide6."""

from src.gui.components.sql_editor import SqlEditorWidget
from src.gui.components.theme_switch import THEME_LABELS, ThemeSwitch
from src.gui.components.toast import Toast
from src.gui.settings.dialog import SettingsDialog
from src.gui.wizard.json_editor_page import JsonEditorPage, JsonSyntaxHighlighter
from src.gui.wizard.landing_page import (
    SHORT_EXPLANATION_TEXT,
    SKILL_TOOLTIP_TEXT,
    LandingPage,
)
from src.gui.wizard.questions_page import (
    AnswerRowWidgets,
    QuestionAccordionItem,
    QuestionsPage,
)
from src.gui.wizard.sql_insert_page import SqlInsertPage
from src.gui.wizard.sql_select_page import SqlSelectPage
from src.gui.settings.dialog import SettingsDialog
from src.utils.json_utils import (
    apply_uppercase_to_text_fields,
    load_json_file,
    save_json_file,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)

__all__ = [
    "AnswerRowWidgets",
    "JsonEditorPage",
    "JsonSyntaxHighlighter",
    "LandingPage",
    "QuestionAccordionItem",
    "QuestionsPage",
    "SHORT_EXPLANATION_TEXT",
    "SKILL_TOOLTIP_TEXT",
    "SettingsDialog",
    "SqlEditorWidget",
    "SqlInsertPage",
    "SqlSelectPage",
    "ThemeSwitch",
    "Toast",
    "apply_uppercase_to_text_fields",
    "load_json_file",
    "save_json_file",
    "uppercase_target_fields",
    "validate_clinical_json_structure",
    "validate_json_text",
]
