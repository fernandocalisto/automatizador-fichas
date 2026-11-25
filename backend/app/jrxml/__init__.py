# -*- coding: utf-8 -*-
"""API pública do motor JRXML Salutem: Scaffolder, Linter XSD/Geométrico e Detail Builder."""

from __future__ import annotations

try:
    from backend.app.jrxml.builder import (
        DetailBandBuilder,
        estimate_text_width,
        extract_detail_xml,
        inject_detail_bands,
        make_checkbox,
        make_radio_circle,
        make_static_text,
        make_styled_gap_text,
        make_text_field,
    )
    from backend.app.jrxml.linter import (
        BUILTIN_JASPER_PARAMS,
        XSD_STRICT_SEQUENCES,
        JrxmlLintIssue,
        JrxmlLintReport,
        lint_jrxml,
    )
    from backend.app.jrxml.scaffolder import (
        STANDARD_HEADER_FIELDS,
        STANDARD_SALUTEM_FIELDS,
        STANDARD_TAIL_FIELDS,
        get_page_metrics,
        scaffold_salutem_jrxml,
    )
except ModuleNotFoundError:  # pragma: no cover
    from app.jrxml.builder import (  # type: ignore[no-redef]
        DetailBandBuilder,
        estimate_text_width,
        extract_detail_xml,
        inject_detail_bands,
        make_checkbox,
        make_radio_circle,
        make_static_text,
        make_styled_gap_text,
        make_text_field,
    )
    from app.jrxml.linter import (  # type: ignore[no-redef]
        BUILTIN_JASPER_PARAMS,
        XSD_STRICT_SEQUENCES,
        JrxmlLintIssue,
        JrxmlLintReport,
        lint_jrxml,
    )
    from app.jrxml.scaffolder import (  # type: ignore[no-redef]
        STANDARD_HEADER_FIELDS,
        STANDARD_SALUTEM_FIELDS,
        STANDARD_TAIL_FIELDS,
        get_page_metrics,
        scaffold_salutem_jrxml,
    )

__all__ = [
    "BUILTIN_JASPER_PARAMS",
    "DetailBandBuilder",
    "JrxmlLintIssue",
    "JrxmlLintReport",
    "STANDARD_HEADER_FIELDS",
    "STANDARD_SALUTEM_FIELDS",
    "STANDARD_TAIL_FIELDS",
    "XSD_STRICT_SEQUENCES",
    "estimate_text_width",
    "extract_detail_xml",
    "get_page_metrics",
    "inject_detail_bands",
    "lint_jrxml",
    "make_checkbox",
    "make_radio_circle",
    "make_static_text",
    "make_styled_gap_text",
    "make_text_field",
    "scaffold_salutem_jrxml",
]
