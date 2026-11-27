# -*- coding: utf-8 -*-
"""
Scaffolder oficial de relatórios JasperReports (`.jrxml`) do sistema Salutem
(`backend/app/jrxml/scaffolder.py`).

Baseado estritamente em `ficha_padrao_vazia.jrxml` (`backend/app/skills/gerador_jrxml/SKILL.md`):
- Suporta `RETRATO` (595x842, `columnWidth=555`, `max_detail_height=623`)
  e `PAISAGEM` (842x595, `orientation="Landscape"`, `columnWidth=802`, `max_detail_height=376`).
- Emite os parâmetros padrão (`id`, `caminho_relatorio`), `<queryString>` sincronizada com `$P{id}`,
  todos os `<field>` padrão da ficha Salutem e os `<field>` dinâmicos das perguntas logo após `data_criacao`.
- Gera UUIDs v4 únicos em `<jasperReport>` e em todos os `<reportElement>`.
"""

from __future__ import annotations

import uuid
from typing import Any

try:
    from backend.app.core.sql_insert import limpar_ocr_texto
    from backend.app.core.sql_select import (
        extract_select_fields_metadata,
        generate_select_jasper,
        normalizar_slug,
    )
except ModuleNotFoundError:  # pragma: no cover
    from app.core.sql_insert import limpar_ocr_texto  # type: ignore[no-redef]
    from app.core.sql_select import (  # type: ignore[no-redef]
        extract_select_fields_metadata,
        generate_select_jasper,
        normalizar_slug,
    )

# 3 campos padrão do bloco ----- CABEÇALHO -----
STANDARD_HEADER_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("solicitante_cnes", "java.lang.String", None),
    ("solicitante", "java.lang.String", None),
    ("data_criacao", "java.lang.String", None),
)

# Campos padrão dos blocos ----- PACIENTE ) ----- e ----- PROFISSIONAL -----
STANDARD_TAIL_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("pac_id", "java.lang.Long", None),
    ("pac_nome", "java.lang.String", None),
    ("pac_nasc", "java.sql.Date", None),
    ("pac_resp", "java.lang.String", None),
    ("pac_mae", "java.lang.String", None),
    ("pac_idade_a", "java.lang.Double", None),
    ("pac_idade_m", "java.lang.Double", None),
    ("pac_idade_d", "java.lang.Double", None),
    ("pac_sexo", "java.lang.String", None),
    ("pac_raca", "java.lang.String", None),
    ("pac_etnia", "java.lang.String", None),
    ("pac_cns", "java.lang.String", None),
    ("pac_pront", "java.lang.Long", None),
    ("pac_cpf", "java.lang.String", None),
    ("pac_rg", "java.lang.String", None),
    ("pac_tel", "java.lang.String", None),
    ("pac_cel", "java.lang.String", None),
    ("pac_log", "java.lang.String", None),
    ("pac_compl", "java.lang.String", None),
    ("pac_mun", "java.lang.String", None),
    ("pac_idmun", "java.lang.Long", None),
    ("pac_uf", "java.lang.String", None),
    ("pac_cep", "java.lang.String", None),
    ("codigo_cross", "java.lang.String", "paciente"),
    ("assinatura", "java.lang.String", None),
    ("responsavel_assinatura", "java.lang.String", None),
    ("rg_reponsavel", "java.lang.String", None),
    ("solicitanteid", "java.lang.Long", None),
    ("prof_nome", "java.lang.String", None),
    ("prof_cns", "java.lang.String", None),
    ("prof_org", "java.lang.String", None),
    ("prof_crm", "java.lang.String", None),
    ("prof_doc", "java.lang.String", None),
    ("data_atendimento", "java.sql.Date", "agenda"),
    ("atendimento_id", "java.lang.Long", "atendimento"),
    ("descricao_ficha", "java.lang.String", "template_ficha_clinica"),
)

STANDARD_SALUTEM_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    STANDARD_HEADER_FIELDS + STANDARD_TAIL_FIELDS
)


def get_page_metrics(orientacao: str | None = "RETRATO") -> dict[str, Any]:
    """
    Retorna as métricas oficiais de página, margens, subreports e limite útil de `<detail>`
    para `RETRATO` (padrão) ou `PAISAGEM`.
    """
    norm = str(orientacao or "RETRATO").strip().upper()
    if norm == "PAISAGEM":
        page_width = 842
        page_height = 595
        column_width = 802
        is_landscape = True
        header_subreport = "cabecalho_paisagem.jasper"
    else:
        page_width = 595
        page_height = 842
        column_width = 555
        is_landscape = False
        header_subreport = "cabecalho_retrato.jasper"

    top_margin = 20
    bottom_margin = 20
    left_margin = 20
    right_margin = 20
    page_header_height = 162
    page_footer_height = 17
    max_detail_height = (
        page_height
        - top_margin
        - bottom_margin
        - page_header_height
        - page_footer_height
    )

    return {
        "orientacao": "PAISAGEM" if is_landscape else "RETRATO",
        "is_landscape": is_landscape,
        "page_width": page_width,
        "page_height": page_height,
        "column_width": column_width,
        "left_margin": left_margin,
        "right_margin": right_margin,
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
        "page_header_height": page_header_height,
        "page_footer_height": page_footer_height,
        "max_detail_height": max_detail_height,
        "header_subreport": header_subreport,
        "patient_subreport": "dados_paciente.jasper",
        "footer_subreport": "rodape_retrato.jasper",
    }


def _safe_cdata(text: str) -> str:
    """Protege eventual sequência `]]>` dentro de blocos CDATA."""
    return text.replace("]]>", "]]]]><![CDATA[>")


def _xml_attr_escape(value: str) -> str:
    """Escapa caracteres especiais em valores de atributos XML."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_field_xml(
    name: str,
    java_class: str,
    tree_path: str | None = None,
) -> str:
    esc_name = _xml_attr_escape(name)
    esc_class = _xml_attr_escape(java_class)
    lines = [
        f'\t<field name="{esc_name}" class="{esc_class}">',
        f'\t\t<property name="com.jaspersoft.studio.field.name" value="{esc_name}"/>',
        f'\t\t<property name="com.jaspersoft.studio.field.label" value="{esc_name}"/>',
    ]
    if tree_path:
        esc_tree = _xml_attr_escape(tree_path)
        lines.append(
            f'\t\t<property name="com.jaspersoft.studio.field.tree.path" value="{esc_tree}"/>'
        )
    lines.append("\t</field>")
    return "\n".join(lines)


def scaffold_salutem_jrxml(
    json_data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str:
    """
    Gera o arquivo `.jrxml` base completo do Salutem (em `RETRATO` ou `PAISAGEM`),
    sincronizando `<queryString>` e `<field>` com o JSON clínico fornecido.

    Opções suportadas em `options`:
    - `orientacao`: sobrescreve `template.orientacao` (`"RETRATO"` ou `"PAISAGEM"`)
    - `detail_band_height`: altura inicial da banda `<detail>` vazia (padrão `50`)
    - `data_adapter`: nome do data adapter no Jaspersoft Studio (padrão `"(192) AME Barradas"`)
    - demais opções de `generate_select_jasper` (`column_naming`, `include_obs`, etc.),
      mantendo `param_syntax="jasper"` e `boolean_style="coalesce_bool_or"` por padrão.
    """
    if not isinstance(json_data, dict) or not json_data:
        raise ValueError(
            "JSON inválido ou vazio: esperado um objeto contendo 'template' e 'perguntas'."
        )
    if "template" not in json_data or not isinstance(json_data.get("template"), dict):
        raise ValueError(
            "Estrutura JSON inválida: a chave 'template' (objeto) é obrigatória."
        )
    if "perguntas" not in json_data or not isinstance(json_data.get("perguntas"), list):
        raise ValueError(
            "Estrutura JSON inválida: a chave 'perguntas' (lista) é obrigatória."
        )

    opts = dict(options or {})
    template = json_data.get("template", {})

    raw_nome = str(template.get("nome") or "").strip()
    if raw_nome:
        slug = normalizar_slug(raw_nome)
        report_name = slug if slug and slug != "campo" else "ficha_padrao"
        titulo_ficha = limpar_ocr_texto(raw_nome, forcar_maiusculo=True, aplicar_ocr=True)
    else:
        report_name = "ficha_padrao"
        titulo_ficha = "TÍTULO DA FICHA CLÍNICA"

    orientacao = str(
        opts.get("orientacao") or template.get("orientacao") or "RETRATO"
    ).strip().upper()
    metrics = get_page_metrics(orientacao)

    detail_band_height = int(opts.get("detail_band_height", 50))
    if detail_band_height < 0 or detail_band_height > metrics["max_detail_height"]:
        raise ValueError(
            f"detail_band_height={detail_band_height} excede o limite máximo "
            f"de {metrics['max_detail_height']} px para orientação {metrics['orientacao']}."
        )

    data_adapter = str(opts.get("data_adapter", "(192) AME Barradas"))

    sql_opts = dict(opts)
    sql_opts["param_syntax"] = "jasper"
    sql_opts.setdefault("boolean_style", "coalesce_bool_or")

    query_sql = generate_select_jasper(json_data, options=sql_opts)
    dynamic_fields = extract_select_fields_metadata(json_data, options=sql_opts)

    standard_names = {name for name, _, _ in STANDARD_SALUTEM_FIELDS}
    field_blocks: list[str] = []

    # 1. Campos padrão do CABEÇALHO (solicitante_cnes, solicitante, data_criacao)
    for f_name, f_class, f_tree in STANDARD_HEADER_FIELDS:
        field_blocks.append(_render_field_xml(f_name, f_class, f_tree))

    # 2. Campos dinâmicos das PERGUNTAS (exatamente na mesma posição da SQL!)
    emitted_names = {f_name for f_name, _, _ in STANDARD_HEADER_FIELDS}
    for dyn in dynamic_fields:
        d_name = str(dyn["name"])
        if d_name in emitted_names or d_name in standard_names:
            continue
        emitted_names.add(d_name)
        field_blocks.append(_render_field_xml(d_name, str(dyn["java_class"]), None))

    # 3. Campos padrão de PACIENTE, PROFISSIONAL e ATENDIMENTO
    for f_name, f_class, f_tree in STANDARD_TAIL_FIELDS:
        if f_name not in emitted_names:
            emitted_names.add(f_name)
            field_blocks.append(_render_field_xml(f_name, f_class, f_tree))

    fields_xml = "\n".join(field_blocks)

    orientation_attr = ' orientation="Landscape"' if metrics["is_landscape"] else ""
    col_w = metrics["column_width"]
    page_w = metrics["page_width"]
    page_h = metrics["page_height"]
    header_h = metrics["page_header_height"]
    footer_h = metrics["page_footer_height"]
    header_sub = metrics["header_subreport"]
    patient_sub = metrics["patient_subreport"]
    footer_sub = metrics["footer_subreport"]

    report_uuid = str(uuid.uuid4())
    title_uuid = str(uuid.uuid4())
    sub_header_uuid = str(uuid.uuid4())
    sub_patient_uuid = str(uuid.uuid4())
    sub_footer_uuid = str(uuid.uuid4())

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports '
            'http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" '
            f'name="{_xml_attr_escape(report_name)}"{orientation_attr} '
            f'pageWidth="{page_w}" pageHeight="{page_h}" columnWidth="{col_w}" '
            f'leftMargin="{metrics["left_margin"]}" rightMargin="{metrics["right_margin"]}" '
            f'topMargin="{metrics["top_margin"]}" bottomMargin="{metrics["bottom_margin"]}" '
            f'uuid="{report_uuid}">'
        ),
        '\t<property name="com.jaspersoft.studio.data.sql.tables" value=""/>',
        f'\t<property name="com.jaspersoft.studio.data.defaultdataadapter" value="{_xml_attr_escape(data_adapter)}"/>',
        '\t<parameter name="id" class="java.lang.Long"/>',
        '\t<parameter name="caminho_relatorio" class="java.lang.String"/>',
        "\t<queryString>",
        f"\t\t<![CDATA[{_safe_cdata(query_sql)}]]>",
        "\t</queryString>",
        fields_xml,
        "\t<title>",
        '\t\t<band splitType="Stretch">',
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t</band>",
        "\t</title>",
        "\t<pageHeader>",
        f'\t\t<band height="{header_h}" splitType="Stretch">',
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="0" y="47" width="{col_w}" height="34" uuid="{title_uuid}"/>',
        "\t\t\t\t<box>",
        '\t\t\t\t\t<pen lineWidth="0.25"/>',
        '\t\t\t\t\t<topPen lineWidth="1.0" lineStyle="Solid" lineColor="#000000"/>',
        '\t\t\t\t\t<leftPen lineWidth="0.0" lineStyle="Solid" lineColor="#000000"/>',
        '\t\t\t\t\t<bottomPen lineWidth="1.0" lineStyle="Solid" lineColor="#000000"/>',
        '\t\t\t\t\t<rightPen lineWidth="0.0" lineStyle="Solid" lineColor="#000000"/>',
        "\t\t\t\t</box>",
        '\t\t\t\t<textElement textAlignment="Center" verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="12" isBold="true"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{_safe_cdata(titulo_ficha)}]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<subreport>",
        f'\t\t\t\t<reportElement x="0" y="-1" width="{col_w}" height="45" uuid="{sub_header_uuid}"/>',
        '\t\t\t\t<subreportParameter name="caminho_relatorio">',
        "\t\t\t\t\t<subreportParameterExpression><![CDATA[$P{caminho_relatorio}]]></subreportParameterExpression>",
        "\t\t\t\t</subreportParameter>",
        "\t\t\t\t<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>",
        f'\t\t\t\t<subreportExpression><![CDATA[$P{{caminho_relatorio}} + "{header_sub}"]]></subreportExpression>',
        "\t\t\t</subreport>",
        "\t\t\t<subreport>",
        f'\t\t\t\t<reportElement x="0" y="82" width="{col_w}" height="77" uuid="{sub_patient_uuid}"/>',
        '\t\t\t\t<subreportParameter name="atendimento_id">',
        "\t\t\t\t\t<subreportParameterExpression><![CDATA[$F{atendimento_id}]]></subreportParameterExpression>",
        "\t\t\t\t</subreportParameter>",
        "\t\t\t\t<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>",
        f'\t\t\t\t<subreportExpression><![CDATA[$P{{caminho_relatorio}} + "{patient_sub}"]]></subreportExpression>',
        "\t\t\t</subreport>",
        "\t\t</band>",
        "\t</pageHeader>",
        "\t<columnHeader>",
        "\t\t<band>",
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t</band>",
        "\t</columnHeader>",
        "\t<detail>",
        f'\t\t<band height="{detail_band_height}"/>',
        "\t</detail>",
        "\t<columnFooter>",
        "\t\t<band>",
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t</band>",
        "\t</columnFooter>",
        "\t<pageFooter>",
        f'\t\t<band height="{footer_h}" splitType="Stretch">',
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t\t<subreport>",
        f'\t\t\t\t<reportElement x="0" y="-1" width="{col_w}" height="{footer_h}" uuid="{sub_footer_uuid}"/>',
        '\t\t\t\t<subreportParameter name="caminho_relatorio">',
        "\t\t\t\t\t<subreportParameterExpression><![CDATA[$P{caminho_relatorio}]]></subreportParameterExpression>",
        "\t\t\t\t</subreportParameter>",
        "\t\t\t\t<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>",
        f'\t\t\t\t<subreportExpression><![CDATA[$P{{caminho_relatorio}} + "{footer_sub}"]]></subreportExpression>',
        "\t\t\t</subreport>",
        "\t\t</band>",
        "\t</pageFooter>",
        "\t<summary>",
        '\t\t<band splitType="Stretch">',
        '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        "\t\t</band>",
        "\t</summary>",
        "</jasperReport>",
    ]

    return "\n".join(xml_lines) + "\n"


def scaffold_free_report_jrxml(
    title: str | None = None,
    *,
    report_name: str | None = None,
    query_sql: str | None = None,
    orientacao: str | None = "RETRATO",
    options: dict[str, Any] | None = None,
) -> str:
    """
    Gera um `.jrxml` limpo e pronto para compilação/preview para Relatórios Livres
    (sem dependência de `ficha.json` nem de subreports clínicos).

    Suporta `RETRATO`/`PORTRAIT` (595x842) e `PAISAGEM`/`LANDSCAPE` (842x595).
    Quando `query_sql` não é informada, gera a consulta starter `SELECT 1 AS exemplo`
    com o `<field name="exemplo" class="java.lang.Integer">` correspondente.
    """
    opts = dict(options or {})
    raw_orient = str(
        opts.get("orientacao") or opts.get("orientation") or orientacao or "RETRATO"
    ).strip().upper()
    if raw_orient in ("LANDSCAPE", "PAISAGEM"):
        norm_orient = "PAISAGEM"
    else:
        norm_orient = "RETRATO"

    metrics = get_page_metrics(norm_orient)
    col_w = metrics["column_width"]
    page_w = metrics["page_width"]
    page_h = metrics["page_height"]
    orientation_attr = ' orientation="Landscape"' if metrics["is_landscape"] else ""

    clean_title = str(title or opts.get("title") or "").strip() or "Relatório Livre"
    raw_name = str(report_name or opts.get("report_name") or clean_title).strip()
    slug = normalizar_slug(raw_name)
    safe_report_name = slug if slug and slug != "campo" else "relatorio_livre"

    custom_sql = str(query_sql if query_sql is not None else opts.get("query_sql") or "").strip()
    using_default_query = not custom_sql
    effective_sql = custom_sql if custom_sql else "SELECT 1 AS exemplo"

    report_uuid = str(uuid.uuid4())
    title_uuid = str(uuid.uuid4())
    detail_label_uuid = str(uuid.uuid4())
    detail_value_uuid = str(uuid.uuid4())

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports '
            'http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" '
            f'name="{_xml_attr_escape(safe_report_name)}"{orientation_attr} '
            f'pageWidth="{page_w}" pageHeight="{page_h}" columnWidth="{col_w}" '
            f'leftMargin="{metrics["left_margin"]}" rightMargin="{metrics["right_margin"]}" '
            f'topMargin="{metrics["top_margin"]}" bottomMargin="{metrics["bottom_margin"]}" '
            f'uuid="{report_uuid}">'
        ),
        '\t<property name="com.jaspersoft.studio.data.sql.tables" value=""/>',
        '\t<queryString language="SQL">',
        f"\t\t<![CDATA[{_safe_cdata(effective_sql)}]]>",
        "\t</queryString>",
    ]

    if using_default_query:
        xml_lines.append(_render_field_xml("exemplo", "java.lang.Integer", None))

    xml_lines.extend(
        [
            "\t<title>",
            '\t\t<band height="36" splitType="Stretch">',
            '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
            "\t\t\t<staticText>",
            f'\t\t\t\t<reportElement x="0" y="0" width="{col_w}" height="30" uuid="{title_uuid}"/>',
            "\t\t\t\t<box>",
            '\t\t\t\t\t<bottomPen lineWidth="1.0" lineStyle="Solid" lineColor="#000000"/>',
            "\t\t\t\t</box>",
            '\t\t\t\t<textElement textAlignment="Left" verticalAlignment="Middle">',
            '\t\t\t\t\t<font size="13" isBold="true"/>',
            "\t\t\t\t</textElement>",
            f"\t\t\t\t<text><![CDATA[{_safe_cdata(clean_title)}]]></text>",
            "\t\t\t</staticText>",
            "\t\t</band>",
            "\t</title>",
            "\t<detail>",
            '\t\t<band height="24" splitType="Stretch">',
            '\t\t\t<property name="com.jaspersoft.studio.unit.height" value="px"/>',
        ]
    )

    if using_default_query:
        xml_lines.extend(
            [
                "\t\t\t<staticText>",
                f'\t\t\t\t<reportElement x="0" y="2" width="80" height="18" uuid="{detail_label_uuid}"/>',
                '\t\t\t\t<textElement verticalAlignment="Middle">',
                '\t\t\t\t\t<font size="9" isBold="true"/>',
                "\t\t\t\t</textElement>",
                "\t\t\t\t<text><![CDATA[Exemplo:]]></text>",
                "\t\t\t</staticText>",
                '\t\t\t<textField isBlankWhenNull="true">',
                f'\t\t\t\t<reportElement x="84" y="2" width="160" height="18" uuid="{detail_value_uuid}"/>',
                '\t\t\t\t<textElement verticalAlignment="Middle">',
                '\t\t\t\t\t<font size="9"/>',
                "\t\t\t\t</textElement>",
                "\t\t\t\t<textFieldExpression><![CDATA[$F{exemplo}]]></textFieldExpression>",
                "\t\t\t</textField>",
            ]
        )
    else:
        xml_lines.extend(
            [
                "\t\t\t<staticText>",
                f'\t\t\t\t<reportElement x="0" y="2" width="{col_w}" height="18" uuid="{detail_label_uuid}"/>',
                '\t\t\t\t<textElement verticalAlignment="Middle">',
                '\t\t\t\t\t<font size="9"/>',
                "\t\t\t\t</textElement>",
                "\t\t\t\t<text><![CDATA[Estrutura inicial gerada. Adicione campos ($F{...}) conforme a consulta SQL.]]></text>",
                "\t\t\t</staticText>",
            ]
        )

    xml_lines.extend(
        [
            "\t\t</band>",
            "\t</detail>",
            "</jasperReport>",
        ]
    )

    return "\n".join(xml_lines) + "\n"


__all__ = [
    "STANDARD_HEADER_FIELDS",
    "STANDARD_SALUTEM_FIELDS",
    "STANDARD_TAIL_FIELDS",
    "get_page_metrics",
    "scaffold_free_report_jrxml",
    "scaffold_salutem_jrxml",
]
