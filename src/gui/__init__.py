#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pacote de interface gráfica (src/gui) do Automatizador de Fichas (PySide6)."""

from src.gui.main_window import APP_TITLE_BASE, APP_VERSION, AboutDialog, MainApp, MainWindow
from src.gui.wizard import (
    SHORT_EXPLANATION_TEXT,
    SKILL_TOOLTIP_TEXT,
    AnswerRowWidgets,
    JsonEditorPage,
    JsonSyntaxHighlighter,
    LandingPage,
    QuestionAccordionItem,
    QuestionsPage,
    SqlInsertPage,
    SqlSelectPage,
)
from src.utils.json_utils import (
    apply_uppercase_to_text_fields,
    load_json_file,
    save_json_file,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)

# Aliases de compatibilidade
JsonEditorTab = JsonEditorPage
LandingFrame = LandingPage
PerguntasTab = QuestionsPage
SqlInsertTab = SqlInsertPage
SqlSelectTab = SqlSelectPage

__all__ = [
    "APP_TITLE_BASE",
    "APP_VERSION",
    "AboutDialog",
    "AnswerRowWidgets",
    "JsonEditorPage",
    "JsonEditorTab",
    "JsonSyntaxHighlighter",
    "LandingFrame",
    "LandingPage",
    "MainApp",
    "MainWindow",
    "PerguntasTab",
    "QuestionAccordionItem",
    "QuestionsPage",
    "SHORT_EXPLANATION_TEXT",
    "SKILL_TOOLTIP_TEXT",
    "SqlInsertPage",
    "SqlInsertTab",
    "SqlSelectPage",
    "SqlSelectTab",
    "apply_uppercase_to_text_fields",
    "load_json_file",
    "save_json_file",
    "uppercase_target_fields",
    "validate_clinical_json_structure",
    "validate_json_text",
]
