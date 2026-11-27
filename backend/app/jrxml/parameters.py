# -*- coding: utf-8 -*-
"""Utilities to extract JRXML `<parameter>` declarations and extract/replace `<queryString>`."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Literal

from pydantic import BaseModel

ParameterInputKind = Literal["string", "integer", "number", "boolean", "date", "datetime"]

SYSTEM_PARAMETER_NAMES: frozenset[str] = frozenset(
    {
        "SUBREPORT_DIR",
        "caminho_relatorio",
        "JASPER_REPORT",
        "JASPER_REPORTS_CONTEXT",
        "IS_IGNORE_PAGINATION",
        "SORT_FIELDS",
        "FILTER",
        "HIBERNATE_SESSION",
        "JPA_ENTITY_MANAGER",
        "MONDRIAN_CONNECTION",
        "XML_DATA_DOCUMENT",
        "JSON_INPUT_STREAM",
    }
)

_QUERY_STRING_TAG_RE = re.compile(
    r"(<queryString\b[^>]*>)(.*?)(</queryString\s*>)",
    re.DOTALL,
)
_SELF_CLOSING_QUERY_RE = re.compile(r"<queryString\b[^>]*/>")
_PARAMETER_BLOCK_END_RE = re.compile(
    r"(?:<parameter\b[^>]*>.*?</parameter\s*>|<parameter\b[^>]*/>)",
    re.DOTALL,
)
_PROPERTY_BLOCK_END_RE = re.compile(
    r"(?:<property\b[^>]*>.*?</property\s*>|<property\b[^>]*/>)",
    re.DOTALL,
)
_ROOT_OPEN_TAG_RE = re.compile(r"<jasperReport\b[^>]*>", re.DOTALL)


class JrxmlParameterInfo(BaseModel):
    """Metadata for a single `<parameter>` declared in a JasperReports `.jrxml` file."""

    name: str
    java_class: str = "java.lang.String"
    default_expression: str | None = None
    is_system: bool = False
    input_kind: ParameterInputKind = "string"


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def is_system_jrxml_parameter(name: str) -> bool:
    """Return True for JasperReports built-in/system parameters and Salutem subreport dirs."""
    cleaned = name.strip()
    if not cleaned:
        return False
    if cleaned in SYSTEM_PARAMETER_NAMES:
        return True
    if cleaned.upper().startswith("REPORT_"):
        return True
    return False


def infer_parameter_input_kind(java_class: str | None) -> ParameterInputKind:
    """Infer UI input kind from a JasperReports Java parameter class name."""
    cls = (java_class or "java.lang.String").strip()
    short = cls.rsplit(".", 1)[-1]
    if short in {"Long", "Integer", "Short", "Byte", "BigInteger"}:
        return "integer"
    if short in {"Double", "Float", "BigDecimal", "Number"}:
        return "number"
    if short == "Boolean":
        return "boolean"
    if cls in {"java.sql.Date", "java.time.LocalDate"} or short == "LocalDate":
        return "date"
    if short in {"Timestamp", "Date", "LocalDateTime", "OffsetDateTime", "ZonedDateTime"}:
        return "datetime"
    return "string"


def extract_jrxml_parameters(jrxml_xml: str) -> list[JrxmlParameterInfo]:
    """
    Parse top-level `<parameter>` elements from a `.jrxml` XML document, marking
    system parameters (`SUBREPORT_DIR`, `caminho_relatorio`, `REPORT_*`) and inferring
    the appropriate `input_kind`.
    """
    if not isinstance(jrxml_xml, str) or not jrxml_xml.strip():
        return []

    root = ET.fromstring(jrxml_xml)
    if _strip_ns(root.tag) != "jasperReport":
        raise ValueError(f"Expected <jasperReport> root element, got <{_strip_ns(root.tag)}>.")

    params: list[JrxmlParameterInfo] = []
    seen: set[str] = set()

    for child in list(root):
        if _strip_ns(child.tag) != "parameter":
            continue
        name = (child.attrib.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        java_class = (child.attrib.get("class") or "java.lang.String").strip()
        default_expr: str | None = None
        for sub in list(child):
            if _strip_ns(sub.tag) == "defaultValueExpression":
                raw_expr = "".join(sub.itertext()).strip()
                default_expr = raw_expr if raw_expr else None
                break

        params.append(
            JrxmlParameterInfo(
                name=name,
                java_class=java_class,
                default_expression=default_expr,
                is_system=is_system_jrxml_parameter(name),
                input_kind=infer_parameter_input_kind(java_class),
            )
        )

    return params


def extract_jrxml_query(jrxml_xml: str) -> str:
    """Extract the top-level `<queryString>` SQL text from a `.jrxml` document (or `""`)."""
    if not isinstance(jrxml_xml, str) or not jrxml_xml.strip():
        return ""

    root = ET.fromstring(jrxml_xml)
    if _strip_ns(root.tag) != "jasperReport":
        raise ValueError(f"Expected <jasperReport> root element, got <{_strip_ns(root.tag)}>.")

    for child in list(root):
        if _strip_ns(child.tag) == "queryString":
            return "".join(child.itertext()).strip()
    return ""


def _wrap_cdata(text: str) -> str:
    safe = text.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _find_top_level_query_span(jrxml_xml: str) -> tuple[int, int, str] | None:
    """Locate the character span `(start, end, open_tag)` of the report-level `<queryString>`."""
    # Exclude regions inside <subDataset>...</subDataset>
    excluded_spans: list[tuple[int, int]] = [
        (m.start(), m.end())
        for m in re.finditer(r"<subDataset\b[^>]*>.*?</subDataset\s*>", jrxml_xml, re.DOTALL)
    ]

    def _in_excluded(pos: int) -> bool:
        return any(s <= pos < e for s, e in excluded_spans)

    for match in _QUERY_STRING_TAG_RE.finditer(jrxml_xml):
        if not _in_excluded(match.start()):
            return match.start(), match.end(), match.group(1)

    for match in _SELF_CLOSING_QUERY_RE.finditer(jrxml_xml):
        if not _in_excluded(match.start()):
            return match.start(), match.end(), '<queryString language="SQL">'

    return None


def replace_jrxml_query(jrxml_xml: str, new_sql: str) -> str:
    """
    Replace (or insert in valid XSD order) the report-level `<queryString>` in a `.jrxml`
    XML string while preserving the rest of the XML formatting verbatim.
    """
    if not isinstance(jrxml_xml, str) or not jrxml_xml.strip():
        raise ValueError("JRXML content cannot be empty.")

    # Verify input XML is well-formed
    root = ET.fromstring(jrxml_xml)
    if _strip_ns(root.tag) != "jasperReport":
        raise ValueError(f"Expected <jasperReport> root element, got <{_strip_ns(root.tag)}>.")

    cleaned_sql = (new_sql or "").strip()
    cdata = _wrap_cdata(cleaned_sql)

    span = _find_top_level_query_span(jrxml_xml)
    if span is not None:
        start, end, open_tag = span
        replacement = f"{open_tag}\n\t\t{cdata}\n\t</queryString>"
        updated = jrxml_xml[:start] + replacement + jrxml_xml[end:]
    else:
        # Insert after last report-level <parameter> (outside subDataset), else after <property>, else after <jasperReport ...>
        excluded_spans: list[tuple[int, int]] = [
            (m.start(), m.end())
            for m in re.finditer(r"<subDataset\b[^>]*>.*?</subDataset\s*>", jrxml_xml, re.DOTALL)
        ]

        def _in_excluded(pos: int) -> bool:
            return any(s <= pos < e for s, e in excluded_spans)

        insert_pos: int | None = None
        for pattern in (_PARAMETER_BLOCK_END_RE, _PROPERTY_BLOCK_END_RE):
            matches = [m for m in pattern.finditer(jrxml_xml) if not _in_excluded(m.start())]
            if matches:
                insert_pos = matches[-1].end()
                break

        if insert_pos is None:
            root_match = _ROOT_OPEN_TAG_RE.search(jrxml_xml)
            if root_match is None:
                raise ValueError("Could not locate <jasperReport> opening tag.")
            insert_pos = root_match.end()

        query_block = f'\n\t<queryString language="SQL">\n\t\t{cdata}\n\t</queryString>'
        updated = jrxml_xml[:insert_pos] + query_block + jrxml_xml[insert_pos:]

    # Validate output XML remains well-formed
    ET.fromstring(updated)
    return updated


def coerce_report_param_value(
    raw_value: Any,
    param_info: JrxmlParameterInfo | None = None,
) -> Any:
    """Coerce a user-supplied report parameter value according to its declared JRXML type."""
    if raw_value is None:
        return None

    kind: ParameterInputKind = param_info.input_kind if param_info is not None else "string"

    if kind == "string":
        return str(raw_value)

    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return None
        if kind == "integer":
            try:
                return int(stripped)
            except ValueError:
                return int(float(stripped))
        if kind == "number":
            return float(stripped.replace(",", "."))
        if kind == "boolean":
            low = stripped.lower()
            if low in ("true", "1", "sim", "yes", "t", "s"):
                return True
            if low in ("false", "0", "nao", "não", "no", "f", "n"):
                return False
            return bool(stripped)
        if kind in ("date", "datetime"):
            return stripped

    if kind == "integer":
        return int(raw_value)
    if kind == "number":
        return float(raw_value)
    if kind == "boolean":
        return bool(raw_value)
    return raw_value


__all__ = [
    "JrxmlParameterInfo",
    "ParameterInputKind",
    "SYSTEM_PARAMETER_NAMES",
    "coerce_report_param_value",
    "extract_jrxml_parameters",
    "extract_jrxml_query",
    "infer_parameter_input_kind",
    "is_system_jrxml_parameter",
    "replace_jrxml_query",
]
