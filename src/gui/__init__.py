#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pacote de interface gráfica (src/gui) do Automatizador de Fichas."""

from src.gui.json_editor_tab import JsonEditorTab
from src.gui.landing import SKILL_TOOLTIP_TEXT, LandingFrame, ToolTip
from src.gui.perguntas_tab import AnswerRowWidgets, PerguntasTab, QuestionAccordionItem
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
    "JsonEditorTab",
    "LandingFrame",
    "PerguntasTab",
    "QuestionAccordionItem",
    "SKILL_TOOLTIP_TEXT",
    "ToolTip",
    "apply_uppercase_to_text_fields",
    "load_json_file",
    "save_json_file",
    "uppercase_target_fields",
    "validate_clinical_json_structure",
    "validate_json_text",
]
