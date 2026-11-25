# -*- coding: utf-8 -*-
"""
Construtor de alto nível para bandas `<detail>` e componentes gráficos do JasperReports
(`backend/app/jrxml/builder.py`).

Todos os elementos emitidos obedecem 100% às regras das Fases 3 e 4 (`gerador_jrxml/SKILL.md`):
- `isBlankWhenNull="true"` obrigatório em todo `<textField>`, sem `isStretchWithOverflow="true"`
- Ordem estrita de filhos exigida pelo `jasperreport.xsd`
- UUIDs v4 reais e únicos por `<reportElement>`
- Marcadores booleanos oficiais Salutem:
  - Checkbox: `<rectangle>` externo `10x10` (`lineWidth="0.75"`) + interno condicional `6x6` (`#000000`)
  - Rádio: `<ellipse>` externo `10x10` (`lineWidth="0.75"`) + interno condicional `6x6` (`#000000`)
- Expressões `<printWhenExpression>` null-safe com `Boolean.TRUE.equals($F{...})` / `Boolean.FALSE.equals($F{...})`
- Frases com lacunas via `markup="styled"` com ternário null-safe e escape de `&` e `<`
- Injeção e extração limpa de `<detail>...</detail>` preservando blocos `<![CDATA[...]]>` intactos.
"""

from __future__ import annotations

import math
import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any

_GAP_TOKEN_RE = re.compile(r"(?:\$F\{([A-Za-z0-9_.\-]+)\}|\{([A-Za-z0-9_.\-]+)(?::([^{}]*))?\})")
_DETAIL_BLOCK_RE = re.compile(r"(<detail\b[^>]*>.*?</detail>)", re.DOTALL)


def _safe_cdata(text: str) -> str:
    return text.replace("]]>", "]]]]><![CDATA[>")


def _xml_attr(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _java_string_literal(text: str) -> str:
    """Converte string Python em literal Java seguro entre aspas duplas."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _escape_styled_static_text(text: str) -> str:
    """Escapa `&` e `<` em trechos estáticos de `markup="styled"`."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def estimate_text_width(
    text: str,
    *,
    bold: bool = False,
    font_size: int = 8,
    padding: int = 4,
) -> int:
    """
    Calcula largura recomendada em pixels conforme heurística de `gerador_jrxml/SKILL.md`:
    - Rótulo negrito tamanho 9 ≈ 5.5 px/caractere
    - Opção normal tamanho 8 ≈ 4.5 px/caractere
    """
    if not text:
        return max(10, padding)
    base_px = 5.5 * (font_size / 9.0) if bold else 4.5 * (font_size / 8.0)
    longest_line = max((len(line) for line in str(text).splitlines()), default=len(str(text)))
    return int(math.ceil(longest_line * base_px)) + padding


def _indent_block(xml_block: str, tabs: int) -> str:
    prefix = "\t" * tabs
    return "\n".join(
        f"{prefix}{line}" if line.strip() else ""
        for line in xml_block.splitlines()
    )


def _resolve_print_when(
    print_when_field: str | None = None,
    print_when_expression: str | None = None,
    *,
    negate_print_when: bool = False,
) -> str | None:
    if print_when_expression is not None:
        return print_when_expression.strip()
    if print_when_field is not None:
        bool_const = "Boolean.FALSE" if negate_print_when else "Boolean.TRUE"
        return f"{bool_const}.equals($F{{{print_when_field.strip()}}})"
    return None


def _render_report_element(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    mode: str | None = None,
    forecolor: str | None = None,
    backcolor: str | None = None,
    print_when_expr: str | None = None,
    properties: dict[str, str] | None = None,
    element_uuid: str | None = None,
) -> str:
    uid = element_uuid or str(uuid.uuid4())
    attrs: list[str] = []
    if mode:
        attrs.append(f'mode="{_xml_attr(mode)}"')
    attrs.append(f'x="{int(x)}"')
    attrs.append(f'y="{int(y)}"')
    attrs.append(f'width="{int(width)}"')
    attrs.append(f'height="{int(height)}"')
    if forecolor:
        attrs.append(f'forecolor="{_xml_attr(forecolor)}"')
    if backcolor:
        attrs.append(f'backcolor="{_xml_attr(backcolor)}"')
    attrs.append(f'uuid="{_xml_attr(uid)}"')
    attr_str = " ".join(attrs)

    children: list[str] = []
    # Ordem estrita jasperreport.xsd dentro de <reportElement>:
    # <property> (1º) -> <propertyExpression> -> <printWhenExpression> (último)
    if properties:
        for k, v in properties.items():
            children.append(
                f'\t<property name="{_xml_attr(k)}" value="{_xml_attr(v)}"/>'
            )
    if print_when_expr:
        children.append(
            f"\t<printWhenExpression><![CDATA[{_safe_cdata(print_when_expr)}]]></printWhenExpression>"
        )

    if not children:
        return f"<reportElement {attr_str}/>"
    inner = "\n".join(children)
    return f"<reportElement {attr_str}>\n{inner}\n</reportElement>"


def _render_box(
    box: bool | float | int | str | dict[str, Any] | None = None,
    *,
    top_padding: int | None = None,
    left_padding: int | None = None,
    bottom_padding: int | None = None,
    right_padding: int | None = None,
) -> str | None:
    """
    Renderiza `<box>` respeitando a ordem XSD estrita:
    `<pen>` -> `<topPen>` -> `<leftPen>` -> `<bottomPen>` -> `<rightPen>`.
    """
    box_attrs: list[str] = []
    pen_cfg: dict[str, Any] = {}

    if isinstance(box, dict):
        top_padding = box.get("top_padding", top_padding)
        left_padding = box.get("left_padding", left_padding)
        bottom_padding = box.get("bottom_padding", bottom_padding)
        right_padding = box.get("right_padding", right_padding)
        pen_cfg = dict(box)
    elif box is True:
        pen_cfg = {"pen": 0.5}
    elif isinstance(box, (int, float)) and not isinstance(box, bool):
        pen_cfg = {"pen": float(box)}
    elif isinstance(box, str):
        preset = box.strip().lower()
        if preset == "underline":
            pen_cfg = {"bottom": 0.5}
        elif preset in ("box", "all", "solid"):
            pen_cfg = {"pen": 0.5}
        elif preset == "header_band":
            pen_cfg = {"pen": 0.25, "top": 1.0, "left": 0.0, "bottom": 1.0, "right": 0.0}

    if top_padding is not None:
        box_attrs.append(f'topPadding="{int(top_padding)}"')
    if left_padding is not None:
        box_attrs.append(f'leftPadding="{int(left_padding)}"')
    if bottom_padding is not None:
        box_attrs.append(f'bottomPadding="{int(bottom_padding)}"')
    if right_padding is not None:
        box_attrs.append(f'rightPadding="{int(right_padding)}"')

    color = str(pen_cfg.get("color", "#000000"))
    style = str(pen_cfg.get("style", "Solid"))

    children: list[str] = []
    if "pen" in pen_cfg and pen_cfg["pen"] is not None:
        children.append(
            f'\t<pen lineWidth="{float(pen_cfg["pen"])}" lineStyle="{_xml_attr(style)}" lineColor="{_xml_attr(color)}"/>'
        )
    for key, tag in (
        ("top", "topPen"),
        ("left", "leftPen"),
        ("bottom", "bottomPen"),
        ("right", "rightPen"),
    ):
        if key in pen_cfg and pen_cfg[key] is not None:
            children.append(
                f'\t<{tag} lineWidth="{float(pen_cfg[key])}" lineStyle="{_xml_attr(style)}" lineColor="{_xml_attr(color)}"/>'
            )

    if not box_attrs and not children:
        return None

    attr_suffix = (" " + " ".join(box_attrs)) if box_attrs else ""
    if not children:
        return f"<box{attr_suffix}/>"
    inner = "\n".join(children)
    return f"<box{attr_suffix}>\n{inner}\n</box>"


def _render_text_element(
    *,
    font_name: str | None = "SansSerif",
    font_size: int = 8,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    h_align: str | None = None,
    v_align: str | None = "Middle",
    markup: str | None = None,
    line_spacing: str | None = None,
) -> str:
    """
    Renderiza `<textElement>` respeitando a ordem XSD estrita:
    `<font>` -> `<paragraph>`.
    """
    te_attrs: list[str] = []
    if h_align:
        te_attrs.append(f'textAlignment="{_xml_attr(h_align)}"')
    if v_align:
        te_attrs.append(f'verticalAlignment="{_xml_attr(v_align)}"')
    if markup:
        te_attrs.append(f'markup="{_xml_attr(markup)}"')

    font_attrs: list[str] = []
    if font_name:
        font_attrs.append(f'fontName="{_xml_attr(font_name)}"')
    font_attrs.append(f'size="{int(font_size)}"')
    if bold:
        font_attrs.append('isBold="true"')
    if italic:
        font_attrs.append('isItalic="true"')
    if underline:
        font_attrs.append('isUnderline="true"')

    children = [f'\t<font {" ".join(font_attrs)}/>']
    if line_spacing:
        children.append(f'\t<paragraph lineSpacing="{_xml_attr(line_spacing)}"/>')

    te_attr_str = (" " + " ".join(te_attrs)) if te_attrs else ""
    inner = "\n".join(children)
    return f"<textElement{te_attr_str}>\n{inner}\n</textElement>"


def make_static_text(
    x: int,
    y: int,
    width: int,
    height: int,
    text: str,
    *,
    font_size: int = 9,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    font_name: str | None = "SansSerif",
    h_align: str | None = None,
    v_align: str | None = "Middle",
    box: bool | float | int | str | dict[str, Any] | None = None,
    left_padding: int | None = None,
    right_padding: int | None = None,
    mode: str | None = None,
    forecolor: str | None = None,
    backcolor: str | None = None,
    print_when_field: str | None = None,
    print_when_expression: str | None = None,
    negate_print_when: bool = False,
    element_uuid: str | None = None,
) -> str:
    """
    Cria um `<staticText>` válido segundo `jasperreport.xsd`:
    `reportElement` -> `box` -> `textElement` -> `text`.
    """
    pwe = _resolve_print_when(
        print_when_field=print_when_field,
        print_when_expression=print_when_expression,
        negate_print_when=negate_print_when,
    )
    rep_xml = _render_report_element(
        x=x,
        y=y,
        width=width,
        height=height,
        mode=mode,
        forecolor=forecolor,
        backcolor=backcolor,
        print_when_expr=pwe,
        element_uuid=element_uuid,
    )
    box_xml = _render_box(box, left_padding=left_padding, right_padding=right_padding)
    te_xml = _render_text_element(
        font_name=font_name,
        font_size=font_size,
        bold=bold,
        italic=italic,
        underline=underline,
        h_align=h_align,
        v_align=v_align,
    )

    parts = ["<staticText>", _indent_block(rep_xml, 1)]
    if box_xml:
        parts.append(_indent_block(box_xml, 1))
    parts.append(_indent_block(te_xml, 1))
    parts.append(f"\t<text><![CDATA[{_safe_cdata(str(text))}]]></text>")
    parts.append("</staticText>")
    return "\n".join(parts)


def make_text_field(
    x: int,
    y: int,
    width: int,
    height: int,
    field_name: str | None = None,
    *,
    expression: str | None = None,
    font_size: int = 8,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    font_name: str | None = "SansSerif",
    h_align: str | None = None,
    v_align: str | None = "Middle",
    markup: str | None = None,
    pattern: str | None = None,
    box: bool | float | int | str | dict[str, Any] | None = None,
    left_padding: int | None = None,
    right_padding: int | None = None,
    mode: str | None = None,
    forecolor: str | None = None,
    backcolor: str | None = None,
    print_when_field: str | None = None,
    print_when_expression: str | None = None,
    negate_print_when: bool = False,
    element_uuid: str | None = None,
) -> str:
    """
    Cria um `<textField isBlankWhenNull="true">` válido segundo `jasperreport.xsd`:
    `reportElement` -> `box` -> `textElement` -> `textFieldExpression`.
    """
    if expression is None:
        if not field_name or not str(field_name).strip():
            raise ValueError(
                "Informe 'field_name' ou 'expression' para construir um <textField>."
            )
        expr_final = f"$F{{{field_name.strip()}}}"
    else:
        expr_final = expression.strip()

    pwe = _resolve_print_when(
        print_when_field=print_when_field,
        print_when_expression=print_when_expression,
        negate_print_when=negate_print_when,
    )
    rep_xml = _render_report_element(
        x=x,
        y=y,
        width=width,
        height=height,
        mode=mode,
        forecolor=forecolor,
        backcolor=backcolor,
        print_when_expr=pwe,
        element_uuid=element_uuid,
    )
    box_xml = _render_box(box, left_padding=left_padding, right_padding=right_padding)
    te_xml = _render_text_element(
        font_name=font_name,
        font_size=font_size,
        bold=bold,
        italic=italic,
        underline=underline,
        h_align=h_align,
        v_align=v_align,
        markup=markup,
    )

    tf_attrs = ['isBlankWhenNull="true"']
    if pattern:
        tf_attrs.append(f'pattern="{_xml_attr(pattern)}"')

    parts = [f'<textField {" ".join(tf_attrs)}>', _indent_block(rep_xml, 1)]
    if box_xml:
        parts.append(_indent_block(box_xml, 1))
    parts.append(_indent_block(te_xml, 1))
    parts.append(f"\t<textFieldExpression><![CDATA[{_safe_cdata(expr_final)}]]></textFieldExpression>")
    parts.append("</textField>")
    return "\n".join(parts)


def _make_boolean_shape(
    shape_tag: str,
    x: int,
    y: int,
    field_name: str,
    *,
    label: str | None = None,
    negate: bool = False,
    outer_size: int = 10,
    inner_size: int = 6,
    label_width: int | None = None,
    label_height: int = 12,
    label_gap: int = 4,
    font_size: int = 8,
    bold: bool = False,
    outer_uuid: str | None = None,
    inner_uuid: str | None = None,
    label_uuid: str | None = None,
) -> str:
    if not field_name or not field_name.strip():
        raise ValueError(f"'field_name' é obrigatório para construir <{shape_tag}> booleano.")

    offset = (int(outer_size) - int(inner_size)) // 2
    pwe = _resolve_print_when(print_when_field=field_name.strip(), negate_print_when=negate)

    outer_rep = _render_report_element(
        x=x,
        y=y,
        width=outer_size,
        height=outer_size,
        element_uuid=outer_uuid,
    )
    inner_rep = _render_report_element(
        x=x + offset,
        y=y + offset,
        width=inner_size,
        height=inner_size,
        mode="Opaque",
        backcolor="#000000",
        print_when_expr=pwe,
        element_uuid=inner_uuid,
    )

    blocks = [
        "\n".join(
            [
                f"<{shape_tag}>",
                _indent_block(outer_rep, 1),
                "\t<graphicElement>",
                '\t\t<pen lineWidth="0.75"/>',
                "\t</graphicElement>",
                f"</{shape_tag}>",
            ]
        ),
        "\n".join(
            [
                f"<{shape_tag}>",
                _indent_block(inner_rep, 1),
                "\t<graphicElement>",
                '\t\t<pen lineWidth="0.0"/>',
                "\t</graphicElement>",
                f"</{shape_tag}>",
            ]
        ),
    ]

    if label is not None:
        calc_width = (
            label_width
            if label_width is not None
            else estimate_text_width(label, bold=bold, font_size=font_size)
        )
        blocks.append(
            make_static_text(
                x=x + outer_size + label_gap,
                y=y,
                width=calc_width,
                height=max(outer_size, label_height),
                text=label,
                font_size=font_size,
                bold=bold,
                v_align="Middle",
                element_uuid=label_uuid,
            )
        )

    return "\n".join(blocks)


def make_checkbox(
    x: int,
    y: int,
    field_name: str,
    *,
    label: str | None = None,
    negate: bool = False,
    outer_size: int = 10,
    inner_size: int = 6,
    label_width: int | None = None,
    label_height: int = 12,
    label_gap: int = 4,
    font_size: int = 8,
    bold: bool = False,
    outer_uuid: str | None = None,
    inner_uuid: str | None = None,
    label_uuid: str | None = None,
) -> str:
    """
    Cria um marcador quadrado Salutem (`<rectangle>` externo `10x10` + interno condicional `6x6` `#000000`),
    com `<staticText>` opcional ao lado caso `label` seja informado.
    """
    return _make_boolean_shape(
        "rectangle",
        x=x,
        y=y,
        field_name=field_name,
        label=label,
        negate=negate,
        outer_size=outer_size,
        inner_size=inner_size,
        label_width=label_width,
        label_height=label_height,
        label_gap=label_gap,
        font_size=font_size,
        bold=bold,
        outer_uuid=outer_uuid,
        inner_uuid=inner_uuid,
        label_uuid=label_uuid,
    )


def make_radio_circle(
    x: int,
    y: int,
    field_name: str,
    *,
    label: str | None = None,
    negate: bool = False,
    outer_size: int = 10,
    inner_size: int = 6,
    label_width: int | None = None,
    label_height: int = 12,
    label_gap: int = 4,
    font_size: int = 8,
    bold: bool = False,
    outer_uuid: str | None = None,
    inner_uuid: str | None = None,
    label_uuid: str | None = None,
) -> str:
    """
    Cria um marcador circular de rádio Salutem (`<ellipse>` externo `10x10` + interno condicional `6x6` `#000000`),
    com `<staticText>` opcional ao lado caso `label` seja informado.
    """
    return _make_boolean_shape(
        "ellipse",
        x=x,
        y=y,
        field_name=field_name,
        label=label,
        negate=negate,
        outer_size=outer_size,
        inner_size=inner_size,
        label_width=label_width,
        label_height=label_height,
        label_gap=label_gap,
        font_size=font_size,
        bold=bold,
        outer_uuid=outer_uuid,
        inner_uuid=inner_uuid,
        label_uuid=label_uuid,
    )


def make_styled_gap_text(
    x: int,
    y: int,
    width: int,
    height: int,
    template: str,
    *,
    placeholder: str = "____________",
    bold_values: bool = True,
    font_size: int = 9,
    font_name: str | None = "SansSerif",
    h_align: str | None = None,
    v_align: str | None = "Middle",
    box: bool | float | int | str | dict[str, Any] | None = None,
    left_padding: int | None = None,
    right_padding: int | None = None,
    element_uuid: str | None = None,
) -> str:
    """
    Cria um `<textField isBlankWhenNull="true">` com `<textElement markup="styled">`
    para frases corridas com lacunas embutidas (ex.: `"Encaminhamos {pac_nome} para {destino}."`).

    Substitui nulos por `placeholder`, destaca valores preenchidos em negrito e escapa `&` e `<`
    para proteger o parser de styled text do JasperReports.
    """
    if not isinstance(template, str) or not template:
        raise ValueError("'template' não pode ser vazio em make_styled_gap_text.")

    expr_parts: list[str] = []
    pos = 0

    for match in _GAP_TOKEN_RE.finditer(template):
        if match.start() > pos:
            static_chunk = _escape_styled_static_text(template[pos : match.start()])
            expr_parts.append(_java_string_literal(static_chunk))

        fname = (match.group(1) or match.group(2) or "").strip()
        custom_ph = match.group(3)
        ph_text = _escape_styled_static_text(
            custom_ph if custom_ph is not None and custom_ph != "" else placeholder
        )
        safe_val = (
            f'String.valueOf($F{{{fname}}}).replace("&", "&amp;").replace("<", "&lt;")'
        )
        if bold_values:
            filled_expr = f'"<style isBold=\\"true\\">" + {safe_val} + "</style>"'
        else:
            filled_expr = safe_val

        expr_parts.append(
            f"($F{{{fname}}} != null ? {filled_expr} : {_java_string_literal(ph_text)})"
        )
        pos = match.end()

    if pos < len(template):
        tail_chunk = _escape_styled_static_text(template[pos:])
        expr_parts.append(_java_string_literal(tail_chunk))

    java_expr = " + ".join(expr_parts) if expr_parts else _java_string_literal("")

    return make_text_field(
        x=x,
        y=y,
        width=width,
        height=height,
        expression=java_expr,
        font_size=font_size,
        font_name=font_name,
        h_align=h_align,
        v_align=v_align,
        markup="styled",
        box=box,
        left_padding=left_padding,
        right_padding=right_padding,
        element_uuid=element_uuid,
    )


class DetailBandBuilder:
    """Construtor fluente de uma `<band>` da seção `<detail>` compatível com o linter estrito."""

    def __init__(
        self,
        height: int = 100,
        *,
        column_width: int = 555,
        max_height: int = 623,
        split_type: str | None = "Stretch",
    ) -> None:
        if height < 0 or height > max_height:
            raise ValueError(
                f"Altura da banda detail ({height} px) fora do intervalo permitido (0..{max_height} px)."
            )
        self.height = int(height)
        self.column_width = int(column_width)
        self.max_height = int(max_height)
        self.split_type = split_type
        self._elements: list[str] = []

    def _validate_bounds(self, x: int, y: int, width: int, height: int, label: str) -> None:
        if x < 0 or y < 0:
            raise ValueError(f"Coordenada negativa em {label}: (x={x}, y={y}).")
        if width < 0 or height < 0:
            raise ValueError(f"Dimensão negativa em {label}: (width={width}, height={height}).")
        if x + width > self.column_width:
            raise ValueError(
                f"{label} excede columnWidth ({x} + {width} = {x + width} > {self.column_width})."
            )
        if y + height > self.height:
            raise ValueError(
                f"{label} excede altura da banda ({y} + {height} = {y + height} > {self.height})."
            )

    def add_raw(self, xml_fragment: str) -> DetailBandBuilder:
        if xml_fragment and xml_fragment.strip():
            self._elements.append(xml_fragment.strip("\n"))
        return self

    def add_static_text(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str,
        **kwargs: Any,
    ) -> DetailBandBuilder:
        self._validate_bounds(x, y, width, height, "staticText")
        self._elements.append(make_static_text(x, y, width, height, text, **kwargs))
        return self

    def add_section_header(
        self,
        y: int,
        title: str,
        *,
        x: int = 0,
        width: int | None = None,
        height: int = 16,
        backcolor: str = "#E5E7EB",
        font_size: int = 9,
    ) -> DetailBandBuilder:
        w = self.column_width - x if width is None else width
        self._validate_bounds(x, y, w, height, "sectionHeader")
        self._elements.append(
            make_static_text(
                x=x,
                y=y,
                width=w,
                height=height,
                text=title,
                font_size=font_size,
                bold=True,
                h_align="Center",
                v_align="Middle",
                mode="Opaque",
                backcolor=backcolor,
                box=0.5,
            )
        )
        return self

    def add_text_field(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        field_name: str | None = None,
        **kwargs: Any,
    ) -> DetailBandBuilder:
        self._validate_bounds(x, y, width, height, "textField")
        self._elements.append(make_text_field(x, y, width, height, field_name, **kwargs))
        return self

    def add_checkbox(
        self,
        x: int,
        y: int,
        field_name: str,
        **kwargs: Any,
    ) -> DetailBandBuilder:
        outer_size = int(kwargs.get("outer_size", 10))
        self._validate_bounds(x, y, outer_size, outer_size, "checkbox")
        label = kwargs.get("label")
        if label is not None:
            gap = int(kwargs.get("label_gap", 4))
            lw = kwargs.get("label_width")
            if lw is None:
                lw = estimate_text_width(
                    str(label),
                    bold=bool(kwargs.get("bold", False)),
                    font_size=int(kwargs.get("font_size", 8)),
                )
            lh = max(outer_size, int(kwargs.get("label_height", 12)))
            self._validate_bounds(x + outer_size + gap, y, int(lw), lh, "checkbox label")
        self._elements.append(make_checkbox(x, y, field_name, **kwargs))
        return self

    def add_radio_circle(
        self,
        x: int,
        y: int,
        field_name: str,
        **kwargs: Any,
    ) -> DetailBandBuilder:
        outer_size = int(kwargs.get("outer_size", 10))
        self._validate_bounds(x, y, outer_size, outer_size, "radioCircle")
        label = kwargs.get("label")
        if label is not None:
            gap = int(kwargs.get("label_gap", 4))
            lw = kwargs.get("label_width")
            if lw is None:
                lw = estimate_text_width(
                    str(label),
                    bold=bool(kwargs.get("bold", False)),
                    font_size=int(kwargs.get("font_size", 8)),
                )
            lh = max(outer_size, int(kwargs.get("label_height", 12)))
            self._validate_bounds(x + outer_size + gap, y, int(lw), lh, "radioCircle label")
        self._elements.append(make_radio_circle(x, y, field_name, **kwargs))
        return self

    def add_styled_gap_text(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        template: str,
        **kwargs: Any,
    ) -> DetailBandBuilder:
        self._validate_bounds(x, y, width, height, "styledGapText")
        self._elements.append(
            make_styled_gap_text(x, y, width, height, template, **kwargs)
        )
        return self

    def build(self) -> str:
        split_attr = f' splitType="{_xml_attr(self.split_type)}"' if self.split_type else ""
        if not self._elements:
            return f'<band height="{self.height}"{split_attr}/>'
        body = "\n".join(_indent_block(el, 1) for el in self._elements)
        return f'<band height="{self.height}"{split_attr}>\n{body}\n</band>'

    to_xml = build


def _normalize_band_xml(item: str | DetailBandBuilder) -> str:
    if isinstance(item, DetailBandBuilder):
        return item.build()
    if isinstance(item, str):
        stripped = item.strip()
        if not stripped:
            raise ValueError("Banda XML vazia não pode ser injetada em <detail>.")
        if stripped.startswith("<detail"):
            m = re.match(r"^<detail\b[^>]*>(.*)</detail>$", stripped, re.DOTALL)
            if not m:
                raise ValueError("Bloco <detail> malformado ao injetar bandas.")
            return m.group(1).strip()
        if not stripped.startswith("<band"):
            raise ValueError(
                "Cada item injetado em <detail> deve ser um DetailBandBuilder ou tag <band ...>."
            )
        return stripped
    raise TypeError(f"Tipo inválido para banda detail: {type(item)!r}")


def inject_detail_bands(
    jrxml_text: str,
    bands: list[str | DetailBandBuilder] | tuple[str | DetailBandBuilder, ...] | str | DetailBandBuilder,
) -> str:
    """
    Substitui o bloco `<detail>...</detail>` de um `.jrxml` existente pelas bandas fornecidas,
    preservando integralmente `<![CDATA[...]]>`, declaração XML e namespaces do documento.
    """
    if not isinstance(jrxml_text, str) or not jrxml_text.strip():
        raise ValueError("O conteúdo JRXML de entrada está vazio.")

    try:
        ET.fromstring(jrxml_text)
    except ET.ParseError as exc:
        raise ValueError(f"JRXML base malformado antes da injeção de <detail>: {exc}") from exc

    if isinstance(bands, (list, tuple)):
        band_items = list(bands)
    else:
        band_items = [bands]

    if not band_items:
        detail_block = "<detail/>"
    else:
        rendered_bands = [
            _indent_block(_normalize_band_xml(b), 2)
            for b in band_items
        ]
        detail_block = "<detail>\n" + "\n".join(rendered_bands) + "\n\t</detail>"

    if _DETAIL_BLOCK_RE.search(jrxml_text):
        updated = _DETAIL_BLOCK_RE.sub(lambda _: detail_block, jrxml_text, count=1)
    elif re.search(r"<detail\s*/>", jrxml_text):
        updated = re.sub(r"<detail\s*/>", lambda _: detail_block, jrxml_text, count=1)
    else:
        raise ValueError("Bloco <detail> não encontrado no documento JRXML informado.")

    # Garante que o resultado continua bem-formado
    try:
        ET.fromstring(updated)
    except ET.ParseError as exc:
        raise ValueError(f"XML resultante inválido após injeção de <detail>: {exc}") from exc

    return updated


def extract_detail_xml(jrxml_text: str) -> str:
    """
    Extrai apenas o bloco `<detail>...</detail>` de um `.jrxml` válido
    (padrão de entrega compacta `detail_<nome_da_ficha>.xml`).
    """
    if not isinstance(jrxml_text, str) or not jrxml_text.strip():
        raise ValueError("O conteúdo JRXML está vazio.")

    try:
        ET.fromstring(jrxml_text)
    except ET.ParseError as exc:
        raise ValueError(f"JRXML malformado ao extrair <detail>: {exc}") from exc

    match = _DETAIL_BLOCK_RE.search(jrxml_text)
    if match:
        return re.sub(r"^\t", "", match.group(1), flags=re.MULTILINE).strip() + "\n"

    empty_match = re.search(r"<detail\s*/>", jrxml_text)
    if empty_match:
        return "<detail/>\n"

    raise ValueError("Bloco <detail> não encontrado no documento JRXML.")


__all__ = [
    "DetailBandBuilder",
    "estimate_text_width",
    "extract_detail_xml",
    "inject_detail_bands",
    "make_checkbox",
    "make_radio_circle",
    "make_static_text",
    "make_styled_gap_text",
    "make_text_field",
]
