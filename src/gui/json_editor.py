#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de compatibilidade do Editor JSON (src/gui/json_editor.py).
Reexporta `JsonEditorTab` de `src.gui.json_editor_tab` e utilitários de `src.utils.json_utils`.
"""

from src.gui.json_editor_tab import JsonEditorTab
from src.utils.json_utils import (
    PRESERVE_CASE_FIELDS,
    TEXT_FIELDS_UPPERCASE,
    apply_uppercase_to_text_fields,
    format_json,
    load_json_file,
    parse_and_validate_clinical_json,
    save_json_file,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)

JsonEditorFrame = JsonEditorTab
JsonEditor = JsonEditorTab

__all__ = [
    "JsonEditor",
    "JsonEditorFrame",
    "JsonEditorTab",
    "PRESERVE_CASE_FIELDS",
    "TEXT_FIELDS_UPPERCASE",
    "apply_uppercase_to_text_fields",
    "format_json",
    "load_json_file",
    "parse_and_validate_clinical_json",
    "save_json_file",
    "uppercase_target_fields",
    "validate_clinical_json_structure",
    "validate_json_text",
]
