#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pacote de utilitários do Automatizador de Fichas (src/utils)."""

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
from src.utils.resource_path import get_skill_file_path, resource_path

__all__ = [
    "PRESERVE_CASE_FIELDS",
    "TEXT_FIELDS_UPPERCASE",
    "apply_uppercase_to_text_fields",
    "format_json",
    "get_skill_file_path",
    "load_json_file",
    "parse_and_validate_clinical_json",
    "resource_path",
    "save_json_file",
    "uppercase_target_fields",
    "validate_clinical_json_structure",
    "validate_json_text",
]
