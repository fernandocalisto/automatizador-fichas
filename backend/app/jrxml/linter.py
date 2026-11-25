# -*- coding: utf-8 -*-
"""
Linter estrito de relatórios JasperReports (`.jrxml`) do sistema Salutem
(`backend/app/jrxml/linter.py`).

Implementa todas as verificações das Fases 3 e 4 de `gerador_jrxml/SKILL.md`:
1. Bem-formação XML (`xml.etree.ElementTree.fromstring`).
2. 100% dos `<textField>` devem possuir `isBlankWhenNull="true"`.
3. Verificação de expressões:
   - Proíbe concatenação insegura `+` com `$F{...}` em `<textFieldExpression>` sem guarda ternária `!= null ?` / `== null ?`.
   - Proíbe comparação `$F{...} == true` / `== false` / `!= true` / `!= false` em `<printWhenExpression>`.
4. Todos os atributos `uuid` devem ser UUIDs válidos no formato `8-4-4-4-12` e únicos em todo o `.jrxml`.
5. Todos os `$F{...}` e `$P{...}` referenciados devem estar declarados em `<field>` ou `<parameter>`
   (permitindo parâmetros nativos do JasperReports).
6. Verificação matemática de bandas e geometria (`max_detail_height`, `columnWidth`, coordenadas `x`/`y`,
   permitindo `y >= -1` em `<pageHeader>` e `<pageFooter>` conforme template oficial do Salutem).
7. Ordem estrita das tags filhas exigida pelo `jasperreport.xsd` em `reportElement`, `staticText`,
   `textField`, `ellipse`, `rectangle`, `box` e `textElement`.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

BUILTIN_JASPER_PARAMS: frozenset[str] = frozenset(
    {
        "REPORT_CONNECTION",
        "REPORT_PARAMETERS_MAP",
        "REPORT_DATA_SOURCE",
        "REPORT_LOCALE",
        "REPORT_TIME_ZONE",
        "REPORT_FORMAT_FACTORY",
        "REPORT_CLASS_LOADER",
        "REPORT_MAX_COUNT",
        "REPORT_SCRIPTLET",
        "REPORT_RESOURCE_BUNDLE",
        "REPORT_VIRTUALIZER",
        "REPORT_CONTEXT",
        "IS_IGNORE_PAGINATION",
        "SUBREPORT_DIR",
        "JASPER_REPORT",
        "JASPER_REPORTS_CONTEXT",
    }
)

# Sequência estrita de tags filhas segundo jasperreport.xsd:
# Tupla de (tag_name, is_repeatable)
XSD_STRICT_SEQUENCES: dict[str, tuple[tuple[str, bool], ...]] = {
    "reportElement": (
        ("property", True),
        ("propertyExpression", True),
        ("printWhenExpression", False),
    ),
    "staticText": (
        ("reportElement", False),
        ("box", False),
        ("textElement", False),
        ("text", False),
    ),
    "textField": (
        ("reportElement", False),
        ("box", False),
        ("textElement", False),
        ("textFieldExpression", False),
        ("patternExpression", False),
        ("anchorNameExpression", False),
        ("hyperlinkReferenceExpression", False),
        ("hyperlinkWhenExpression", False),
        ("hyperlinkAnchorExpression", False),
        ("hyperlinkPageExpression", False),
        ("hyperlinkTooltipExpression", False),
        ("hyperlinkParameter", True),
    ),
    "ellipse": (
        ("reportElement", False),
        ("graphicElement", False),
    ),
    "rectangle": (
        ("reportElement", False),
        ("graphicElement", False),
    ),
    "box": (
        ("pen", False),
        ("topPen", False),
        ("leftPen", False),
        ("bottomPen", False),
        ("rightPen", False),
    ),
    "textElement": (
        ("font", False),
        ("paragraph", False),
    ),
}

_UUID_CANONICAL_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FIELD_REF_RE = re.compile(r"\$F\{([^}]+)\}")
_PARAM_REF_RE = re.compile(r"\$P!?\{([^}]+)\}")
_UNSAFE_BOOL_PRINT_WHEN_RE = re.compile(
    r"(?:\$F\{[^}]+\}\s*(?:==|!=)\s*(?:true|false)\b|\b(?:true|false)\s*(?:==|!=)\s*\$F\{[^}]+\})"
)


class JrxmlLintIssue(dict):  # type: ignore[type-arg]
    """
    Item estruturado de erro/aviso do linter JRXML.
    Compatível simultaneamente com acesso por chave (`issue["code"]`) e atributo (`issue.code`).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        severity: str = "error",
        element: str = "",
        element_uuid: str | None = None,
    ) -> None:
        super().__init__(
            code=code,
            severity=severity,
            message=message,
            element=element,
            uuid=element_uuid,
        )

    @property
    def code(self) -> str:
        return str(self["code"])

    @property
    def severity(self) -> str:
        return str(self["severity"])

    @property
    def message(self) -> str:
        return str(self["message"])

    @property
    def element(self) -> str:
        return str(self["element"])

    @property
    def uuid(self) -> str | None:
        val = self.get("uuid")
        return str(val) if val is not None else None


@dataclass
class JrxmlLintReport:
    """Relatório consolidado da validação XSD, de expressões e geométrica de um `.jrxml`."""

    is_valid: bool
    errors: list[JrxmlLintIssue] = field(default_factory=list)
    warnings: list[JrxmlLintIssue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [dict(e) for e in self.errors],
            "warnings": [dict(w) for w in self.warnings],
            "stats": dict(self.stats),
        }


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child_by_local_name(elem: ET.Element, target: str) -> ET.Element | None:
    for child in elem:
        if _local_name(child.tag) == target:
            return child
    return None


def _get_element_uuid(elem: ET.Element) -> str | None:
    if "uuid" in elem.attrib:
        return elem.attrib.get("uuid")
    rep = _find_child_by_local_name(elem, "reportElement")
    if rep is not None:
        return rep.attrib.get("uuid")
    return None


def _parse_int_attr(
    elem: ET.Element,
    attr_name: str,
    default: int,
    errors: list[JrxmlLintIssue],
    context_tag: str,
) -> int:
    raw = elem.attrib.get(attr_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        errors.append(
            JrxmlLintIssue(
                "INVALID_INTEGER_ATTRIBUTE",
                f"Atributo '{attr_name}=\"{raw}\"' em <{context_tag}> deve ser um inteiro válido.",
                element=context_tag,
                element_uuid=_get_element_uuid(elem),
            )
        )
        return default


def _check_uuid_value(
    raw_uuid: str | None,
    elem_name: str,
    seen_uuids: dict[str, str],
    errors: list[JrxmlLintIssue],
) -> None:
    if raw_uuid is None or not raw_uuid.strip():
        errors.append(
            JrxmlLintIssue(
                "MISSING_UUID",
                f"Elemento <{elem_name}> sem atributo obrigatório 'uuid'.",
                element=elem_name,
            )
        )
        return

    candidate = raw_uuid.strip()
    if not _UUID_CANONICAL_RE.match(candidate):
        errors.append(
            JrxmlLintIssue(
                "INVALID_UUID",
                f"UUID inválido '{raw_uuid}' em <{elem_name}> (esperado formato hexadecimal 8-4-4-4-12).",
                element=elem_name,
                element_uuid=raw_uuid,
            )
        )
        return

    try:
        parsed = uuid.UUID(candidate)
    except ValueError:
        errors.append(
            JrxmlLintIssue(
                "INVALID_UUID",
                f"UUID inválido '{raw_uuid}' em <{elem_name}>.",
                element=elem_name,
                element_uuid=raw_uuid,
            )
        )
        return

    norm = str(parsed).lower()
    if norm in seen_uuids:
        errors.append(
            JrxmlLintIssue(
                "DUPLICATE_UUID",
                f"UUID duplicado '{raw_uuid}' em <{elem_name}> (já utilizado em <{seen_uuids[norm]}>).",
                element=elem_name,
                element_uuid=raw_uuid,
            )
        )
    else:
        seen_uuids[norm] = elem_name


def _validate_xsd_child_order(
    elem: ET.Element,
    errors: list[JrxmlLintIssue],
) -> None:
    parent_name = _local_name(elem.tag)
    spec = XSD_STRICT_SEQUENCES.get(parent_name)
    if spec is None:
        return

    rank_map = {child_name: (idx, repeatable) for idx, (child_name, repeatable) in enumerate(spec)}
    expected_names = [c for c, _ in spec]
    prev_rank = -1
    prev_name = ""
    elem_uuid = _get_element_uuid(elem)

    for child in elem:
        c_name = _local_name(child.tag)
        if c_name not in rank_map:
            errors.append(
                JrxmlLintIssue(
                    "XSD_UNEXPECTED_CHILD_TAG",
                    (
                        f"Tag filha inesperada <{c_name}> dentro de <{parent_name}>. "
                        f"Filhos permitidos na ordem XSD: {expected_names}."
                    ),
                    element=parent_name,
                    element_uuid=elem_uuid,
                )
            )
            continue

        rank, repeatable = rank_map[c_name]
        if rank < prev_rank:
            errors.append(
                JrxmlLintIssue(
                    "XSD_CHILD_ORDER_INVALID",
                    (
                        f"Ordem XSD inválida dentro de <{parent_name}>: <{c_name}> não pode aparecer "
                        f"após <{prev_name}>. Ordem exigida pelo jasperreport.xsd: "
                        f"{' -> '.join(expected_names)}."
                    ),
                    element=parent_name,
                    element_uuid=elem_uuid,
                )
            )
        elif rank == prev_rank and not repeatable:
            errors.append(
                JrxmlLintIssue(
                    "XSD_DUPLICATE_SINGLETON_CHILD",
                    f"Tag <{c_name}> duplicada dentro de <{parent_name}>.",
                    element=parent_name,
                    element_uuid=elem_uuid,
                )
            )
        prev_rank = max(prev_rank, rank)
        prev_name = c_name


def _is_field_null_guarded_in_concat(expr: str, field_name: str) -> bool:
    """
    Verifica se `$F{field_name}` possui guarda ternária explícita contra nulo
    (`$F{campo} != null ? ...` ou `$F{campo} == null ? ...`) quando há concatenação `+`.
    """
    if "?" not in expr:
        return False
    esc = re.escape(field_name)
    guard_re = re.compile(
        rf"(?:\$F\{{{esc}\}}\s*(?:!=|==)\s*null\b|\bnull\s*(?:!=|==)\s*\$F\{{{esc}\}})"
    )
    return bool(guard_re.search(expr))


def _validate_band_elements_geometry(
    container: ET.Element,
    *,
    section_name: str,
    max_width: int,
    max_height: int,
    min_y: int,
    errors: list[JrxmlLintIssue],
) -> int:
    """Valida recursivamente os `<reportElement>` filhos de uma `<band>` (ou `<frame>`)."""
    count = 0
    for child in container:
        child_name = _local_name(child.tag)
        rep = _find_child_by_local_name(child, "reportElement")
        if rep is None:
            continue

        count += 1
        rep_uuid = rep.attrib.get("uuid")
        x = _parse_int_attr(rep, "x", 0, errors, f"{child_name}/reportElement")
        y = _parse_int_attr(rep, "y", 0, errors, f"{child_name}/reportElement")
        w = _parse_int_attr(rep, "width", 0, errors, f"{child_name}/reportElement")
        h = _parse_int_attr(rep, "height", 0, errors, f"{child_name}/reportElement")

        if x < 0:
            errors.append(
                JrxmlLintIssue(
                    "ELEMENT_NEGATIVE_X",
                    f"Elemento <{child_name}> em <{section_name}> possui x={x} (< 0).",
                    element=child_name,
                    element_uuid=rep_uuid,
                )
            )
        if y < min_y:
            errors.append(
                JrxmlLintIssue(
                    "ELEMENT_NEGATIVE_Y",
                    f"Elemento <{child_name}> em <{section_name}> possui y={y} (< {min_y}).",
                    element=child_name,
                    element_uuid=rep_uuid,
                )
            )
        if w < 0 or h < 0:
            errors.append(
                JrxmlLintIssue(
                    "ELEMENT_NEGATIVE_SIZE",
                    f"Elemento <{child_name}> em <{section_name}> possui dimensão negativa (width={w}, height={h}).",
                    element=child_name,
                    element_uuid=rep_uuid,
                )
            )
        if x + w > max_width:
            errors.append(
                JrxmlLintIssue(
                    "ELEMENT_EXCEEDS_COLUMN_WIDTH",
                    (
                        f"Elemento <{child_name}> em <{section_name}> excede a largura útil "
                        f"(x + width = {x} + {w} = {x + w} > {max_width})."
                    ),
                    element=child_name,
                    element_uuid=rep_uuid,
                )
            )
        if y + h > max_height:
            errors.append(
                JrxmlLintIssue(
                    "ELEMENT_EXCEEDS_BAND_HEIGHT",
                    (
                        f"Elemento <{child_name}> em <{section_name}> excede a altura da banda "
                        f"(y + height = {y} + {h} = {y + h} > {max_height})."
                    ),
                    element=child_name,
                    element_uuid=rep_uuid,
                )
            )

        if child_name == "frame":
            count += _validate_band_elements_geometry(
                child,
                section_name=f"{section_name}/frame",
                max_width=w,
                max_height=h,
                min_y=0,
                errors=errors,
            )

    return count


def lint_jrxml(xml_text: str) -> JrxmlLintReport:
    """
    Executa validação completa XSD, de expressões null-safe, UUIDs, fields/parameters
    e geometria sobre um documento `.jrxml`.
    """
    errors: list[JrxmlLintIssue] = []
    warnings: list[JrxmlLintIssue] = []

    if not isinstance(xml_text, str) or not xml_text.strip():
        errors.append(
            JrxmlLintIssue(
                "XML_EMPTY",
                "O conteúdo XML do relatório JRXML está vazio.",
                element="jasperReport",
            )
        )
        return JrxmlLintReport(is_valid=False, errors=errors, warnings=warnings, stats={})

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        errors.append(
            JrxmlLintIssue(
                "XML_PARSE_ERROR",
                f"Erro de sintaxe XML (SAXParseException): {exc}",
                element="jasperReport",
            )
        )
        return JrxmlLintReport(is_valid=False, errors=errors, warnings=warnings, stats={})

    root_name = _local_name(root.tag)
    if root_name != "jasperReport":
        errors.append(
            JrxmlLintIssue(
                "INVALID_ROOT_TAG",
                f"Elemento raiz inválido <{root_name}>: esperado <jasperReport>.",
                element=root_name,
            )
        )
        return JrxmlLintReport(is_valid=False, errors=errors, warnings=warnings, stats={})

    seen_uuids: dict[str, str] = {}
    _check_uuid_value(root.attrib.get("uuid"), "jasperReport", seen_uuids, errors)

    # 1. Coleta <parameter> e <field> declarados
    declared_params: set[str] = set()
    declared_fields: set[str] = set()

    for child in root:
        c_name = _local_name(child.tag)
        if c_name == "parameter":
            p_name = child.attrib.get("name", "").strip()
            if not p_name:
                errors.append(
                    JrxmlLintIssue(
                        "INVALID_PARAMETER_DECLARATION",
                        "Tag <parameter> sem atributo 'name'.",
                        element="parameter",
                    )
                )
            elif p_name in declared_params:
                errors.append(
                    JrxmlLintIssue(
                        "DUPLICATE_PARAMETER_DECLARATION",
                        f"Parâmetro '{p_name}' declarado mais de uma vez.",
                        element="parameter",
                    )
                )
            else:
                declared_params.add(p_name)
        elif c_name == "field":
            f_name = child.attrib.get("name", "").strip()
            if not f_name:
                errors.append(
                    JrxmlLintIssue(
                        "INVALID_FIELD_DECLARATION",
                        "Tag <field> sem atributo 'name'.",
                        element="field",
                    )
                )
            elif f_name in declared_fields:
                errors.append(
                    JrxmlLintIssue(
                        "DUPLICATE_FIELD_DECLARATION",
                        f"Field '{f_name}' declarado mais de uma vez.",
                        element="field",
                    )
                )
            else:
                declared_fields.add(f_name)

    allowed_params = declared_params | BUILTIN_JASPER_PARAMS

    # 2. Métricas de página e cálculo de max_detail_height
    page_width = _parse_int_attr(root, "pageWidth", 595, errors, "jasperReport")
    page_height = _parse_int_attr(root, "pageHeight", 842, errors, "jasperReport")
    column_width = _parse_int_attr(root, "columnWidth", 555, errors, "jasperReport")
    left_margin = _parse_int_attr(root, "leftMargin", 20, errors, "jasperReport")
    right_margin = _parse_int_attr(root, "rightMargin", 20, errors, "jasperReport")
    top_margin = _parse_int_attr(root, "topMargin", 20, errors, "jasperReport")
    bottom_margin = _parse_int_attr(root, "bottomMargin", 20, errors, "jasperReport")

    if left_margin + column_width + right_margin > page_width:
        errors.append(
            JrxmlLintIssue(
                "COLUMN_WIDTH_OVERFLOW",
                (
                    f"columnWidth ({column_width}) + margens laterais ({left_margin}+{right_margin}) "
                    f"excede pageWidth ({page_width})."
                ),
                element="jasperReport",
                element_uuid=root.attrib.get("uuid"),
            )
        )

    page_header_height = 0
    page_header_el = _find_child_by_local_name(root, "pageHeader")
    if page_header_el is not None:
        ph_band = _find_child_by_local_name(page_header_el, "band")
        if ph_band is not None:
            page_header_height = _parse_int_attr(ph_band, "height", 0, errors, "pageHeader/band")

    page_footer_height = 0
    page_footer_el = _find_child_by_local_name(root, "pageFooter")
    if page_footer_el is not None:
        pf_band = _find_child_by_local_name(page_footer_el, "band")
        if pf_band is not None:
            page_footer_height = _parse_int_attr(pf_band, "height", 0, errors, "pageFooter/band")

    max_detail_height = (
        page_height
        - top_margin
        - bottom_margin
        - page_header_height
        - page_footer_height
    )

    # 3. Geometria de bandas (detail, pageHeader, pageFooter e demais seções com band height)
    detail_band_count = 0
    detail_element_count = 0

    for section in root:
        sec_name = _local_name(section.tag)
        if sec_name == "detail":
            for band in section:
                if _local_name(band.tag) != "band":
                    continue
                detail_band_count += 1
                b_height = _parse_int_attr(band, "height", 0, errors, "detail/band")
                if b_height < 0:
                    errors.append(
                        JrxmlLintIssue(
                            "NEGATIVE_BAND_HEIGHT",
                            f"Banda <detail> #{detail_band_count} possui height={b_height} (< 0).",
                            element="detail/band",
                        )
                    )
                elif b_height > max_detail_height:
                    errors.append(
                        JrxmlLintIssue(
                            "DETAIL_BAND_HEIGHT_EXCEEDED",
                            (
                                f"Banda <detail> #{detail_band_count} possui height={b_height}, "
                                f"ultrapassando o limite útil de {max_detail_height} px "
                                f"(pageHeight={page_height} - margins={top_margin + bottom_margin} "
                                f"- pageHeader={page_header_height} - pageFooter={page_footer_height})."
                            ),
                            element="detail/band",
                        )
                    )
                detail_element_count += _validate_band_elements_geometry(
                    band,
                    section_name=f"detail/band[{detail_band_count}]",
                    max_width=column_width,
                    max_height=max(0, b_height),
                    min_y=0,
                    errors=errors,
                )
        elif sec_name in ("pageHeader", "pageFooter"):
            band = _find_child_by_local_name(section, "band")
            if band is not None and "height" in band.attrib:
                b_height = _parse_int_attr(band, "height", 0, errors, f"{sec_name}/band")
                _validate_band_elements_geometry(
                    band,
                    section_name=f"{sec_name}/band",
                    max_width=column_width,
                    max_height=max(0, b_height),
                    min_y=-1,  # Subreports oficiais do Salutem utilizam y="-1" no header/footer
                    errors=errors,
                )

    # 4. Varredura global da árvore: UUIDs, isBlankWhenNull, ordem XSD e expressões
    text_field_count = 0
    report_element_count = 0

    for elem in root.iter():
        ename = _local_name(elem.tag)

        # Validação de ordem XSD nos 7 elementos alvo
        if ename in XSD_STRICT_SEQUENCES:
            _validate_xsd_child_order(elem, errors)

        # Validação de UUIDs
        if ename == "reportElement":
            report_element_count += 1
            _check_uuid_value(elem.attrib.get("uuid"), "reportElement", seen_uuids, errors)
        elif elem is not root and "uuid" in elem.attrib:
            _check_uuid_value(elem.attrib.get("uuid"), ename, seen_uuids, errors)

        # Validação de <textField isBlankWhenNull="true">
        if ename == "textField":
            text_field_count += 1
            tf_uuid = _get_element_uuid(elem)
            if elem.attrib.get("isBlankWhenNull") != "true":
                errors.append(
                    JrxmlLintIssue(
                        "TEXTFIELD_MISSING_BLANK_WHEN_NULL",
                        (
                            "Tag <textField> sem atributo obrigatório isBlankWhenNull=\"true\" "
                            "(risco de impressão literal da palavra 'null')."
                        ),
                        element="textField",
                        element_uuid=tf_uuid,
                    )
                )
            if elem.attrib.get("isStretchWithOverflow") == "true":
                warnings.append(
                    JrxmlLintIssue(
                        "TEXTFIELD_STRETCH_OVERFLOW",
                        (
                            "Tag <textField> utiliza isStretchWithOverflow=\"true\"; prefira alturas fixas "
                            "para evitar estouro inesperado de página."
                        ),
                        severity="warning",
                        element="textField",
                        element_uuid=tf_uuid,
                    )
                )

        # Validação de expressões (<textFieldExpression>, <printWhenExpression>, *Expression e <queryString>)
        if ename == "textFieldExpression":
            expr_text = (elem.text or "").strip()
            if "+" in expr_text and "$F{" in expr_text:
                referenced = sorted(set(_FIELD_REF_RE.findall(expr_text)))
                unguarded = [
                    fname
                    for fname in referenced
                    if not _is_field_null_guarded_in_concat(expr_text, fname)
                ]
                if unguarded:
                    errors.append(
                        JrxmlLintIssue(
                            "UNSAFE_FIELD_CONCATENATION",
                            (
                                f"Concatenação insegura com '+' envolvendo {[f'$F{{{u}}}' for u in unguarded]} "
                                "em <textFieldExpression> sem guarda ternária '!= null ?'. "
                                "Em Java, null concatenado produz a string literal 'null'."
                            ),
                            element="textFieldExpression",
                        )
                    )

        if ename == "printWhenExpression":
            expr_text = (elem.text or "").strip()
            if _UNSAFE_BOOL_PRINT_WHEN_RE.search(expr_text):
                errors.append(
                    JrxmlLintIssue(
                        "UNSAFE_PRINT_WHEN_BOOLEAN",
                        (
                            f"Comparação booleana insegura em <printWhenExpression>: '{expr_text}'. "
                            "Use Boolean.TRUE.equals($F{...}) ou Boolean.FALSE.equals($F{...}) para evitar NullPointerException."
                        ),
                        element="printWhenExpression",
                    )
                )

        if ename.endswith("Expression") or ename == "queryString":
            expr_text = elem.text or ""
            if ename != "queryString":
                for fname in _FIELD_REF_RE.findall(expr_text):
                    if fname not in declared_fields:
                        errors.append(
                            JrxmlLintIssue(
                                "UNDECLARED_FIELD",
                                f"Referência a $F{{{fname}}} em <{ename}> sem <field name=\"{fname}\"> declarado.",
                                element=ename,
                            )
                        )
            for pname in _PARAM_REF_RE.findall(expr_text):
                if pname not in allowed_params:
                    errors.append(
                        JrxmlLintIssue(
                            "UNDECLARED_PARAMETER",
                            f"Referência a $P{{{pname}}} em <{ename}> sem <parameter name=\"{pname}\"> declarado.",
                            element=ename,
                        )
                    )

    stats = {
        "page_width": page_width,
        "page_height": page_height,
        "column_width": column_width,
        "max_detail_height": max_detail_height,
        "declared_fields_count": len(declared_fields),
        "declared_parameters_count": len(declared_params),
        "detail_band_count": detail_band_count,
        "detail_element_count": detail_element_count,
        "report_element_count": report_element_count,
        "text_field_count": text_field_count,
        "unique_uuid_count": len(seen_uuids),
    }

    return JrxmlLintReport(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        stats=stats,
    )


__all__ = [
    "BUILTIN_JASPER_PARAMS",
    "XSD_STRICT_SEQUENCES",
    "JrxmlLintIssue",
    "JrxmlLintReport",
    "lint_jrxml",
]
