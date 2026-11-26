# -*- coding: utf-8 -*-
"""Testes unitários abrangentes do motor JRXML: Scaffolder, Detail Builder e Linter Estrito."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from backend.app.jrxml import (
    STANDARD_SALUTEM_FIELDS,
    DetailBandBuilder,
    estimate_text_width,
    extract_detail_xml,
    get_page_metrics,
    inject_detail_bands,
    lint_jrxml,
    make_checkbox,
    make_radio_circle,
    make_static_text,
    make_styled_gap_text,
    make_text_field,
    scaffold_salutem_jrxml,
)

JR_NS = {"jr": "http://jasperreports.sourceforge.net/jasperreports"}


def _clinical_fixture(orientacao: str = "RETRATO") -> dict[str, Any]:
    return {
        "template": {
            "nome": "Avaliação de Alta Hospital Dia",
            "descricao": "Ficha de alta",
            "layout": "ficha-clinica",
            "orientacao": orientacao,
            "quantidade_pagina": 1,
        },
        "perguntas": [
            {
                "nome": "Condições de Alta",
                "titulo": False,
                "respostas": [
                    {"label": "Orientado", "tipo_campo": "BOOLEANO", "observacao": True},
                    {"label": "Deambulando", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "Cadeira de Rodas", "tipo_campo": "BOOLEANO_RADIO"},
                    {"label": "Temperatura", "tipo_campo": "NUMERICO"},
                    {"label": "Especialidade Destino", "tipo_campo": "TEXTO"},
                ],
            }
        ],
    }


# =============================================================================
# 1. Scaffolder RETRATO & PAISAGEM
# =============================================================================


def test_scaffolder_retrato_default_empty_and_with_questions() -> None:
    empty_doc: dict[str, Any] = {"template": {}, "perguntas": []}
    empty_xml = scaffold_salutem_jrxml(empty_doc)

    report_empty = lint_jrxml(empty_xml)
    assert report_empty.is_valid is True, report_empty.to_dict()
    assert report_empty.errors == []
    assert report_empty.warnings == []
    assert report_empty.stats["page_width"] == 595
    assert report_empty.stats["page_height"] == 842
    assert report_empty.stats["column_width"] == 555
    assert report_empty.stats["max_detail_height"] == 623
    assert report_empty.stats["declared_fields_count"] == len(STANDARD_SALUTEM_FIELDS)

    root_empty = ET.fromstring(empty_xml)
    assert root_empty.attrib["name"] == "ficha_padrao"
    assert "orientation" not in root_empty.attrib
    assert "cabecalho_retrato.jasper" in empty_xml
    assert "dados_paciente.jasper" in empty_xml
    assert "rodape_retrato.jasper" in empty_xml
    assert "fc.id = $P{id}" in empty_xml

    # Com perguntas dinâmicas posicionadas exatamente após data_criacao e antes de pac_id
    doc = _clinical_fixture("RETRATO")
    xml_retrato = scaffold_salutem_jrxml(doc)
    rep = lint_jrxml(xml_retrato)
    assert rep.is_valid is True, rep.to_dict()

    root = ET.fromstring(xml_retrato)
    assert root.attrib["name"] == "avaliacao_de_alta_hospital_dia"
    assert "AVALIAÇÃO DE ALTA HOSPITAL DIA" in xml_retrato

    field_elems = root.findall("jr:field", JR_NS)
    field_names = [f.attrib["name"] for f in field_elems]
    field_classes = {f.attrib["name"]: f.attrib["class"] for f in field_elems}

    idx_data_criacao = field_names.index("data_criacao")
    idx_pac_id = field_names.index("pac_id")
    dynamic_slice = field_names[idx_data_criacao + 1 : idx_pac_id]
    assert dynamic_slice == [
        "orientado",
        "orientado_obs",
        "deambulando",
        "cadeira_de_rodas",
        "temperatura",
        "especialidade_destino",
    ]
    assert field_classes["orientado"] == "java.lang.Boolean"
    assert field_classes["orientado_obs"] == "java.lang.String"
    assert field_classes["temperatura"] == "java.lang.Double"
    assert field_classes["especialidade_destino"] == "java.lang.String"


def test_scaffolder_paisagem_metrics_and_subreports() -> None:
    metrics = get_page_metrics("PAISAGEM")
    assert metrics["max_detail_height"] == 376
    assert metrics["column_width"] == 802

    doc = _clinical_fixture("PAISAGEM")
    xml_paisagem = scaffold_salutem_jrxml(doc)

    rep = lint_jrxml(xml_paisagem)
    assert rep.is_valid is True, rep.to_dict()
    assert rep.stats["page_width"] == 842
    assert rep.stats["page_height"] == 595
    assert rep.stats["column_width"] == 802
    assert rep.stats["max_detail_height"] == 376

    root = ET.fromstring(xml_paisagem)
    assert root.attrib.get("orientation") == "Landscape"
    assert "cabecalho_paisagem.jasper" in xml_paisagem
    assert 'width="802"' in xml_paisagem

    # Dois scaffolds consecutivos geram UUIDs distintos
    xml_paisagem_2 = scaffold_salutem_jrxml(doc)
    assert ET.fromstring(xml_paisagem).attrib["uuid"] != ET.fromstring(xml_paisagem_2).attrib["uuid"]


# =============================================================================
# 2. DetailBandBuilder, Componentes Gráficos e Injeção/Extração
# =============================================================================


def test_detail_builder_and_injection_produce_100_percent_linter_compliant_jrxml() -> None:
    doc = _clinical_fixture("RETRATO")
    base_jrxml = scaffold_salutem_jrxml(doc)

    band1 = (
        DetailBandBuilder(height=160, column_width=555, max_height=623)
        .add_section_header(y=0, title="1. CONDIÇÕES CLÍNICAS DE ALTA")
        .add_checkbox(x=8, y=24, field_name="orientado", label="ORIENTADO:", label_width=80, bold=True)
        .add_text_field(
            x=96,
            y=22,
            width=450,
            height=14,
            field_name="orientado_obs",
            box="underline",
            print_when_field="orientado",
        )
        .add_radio_circle(x=8, y=46, field_name="deambulando", label="DEAMBULANDO", label_width=95)
        .add_radio_circle(x=130, y=46, field_name="cadeira_de_rodas", label="CADEIRA DE RODAS", label_width=120)
        .add_static_text(x=280, y=45, width=90, height=14, text="TEMPERATURA:", bold=True)
        .add_text_field(
            x=375,
            y=45,
            width=60,
            height=14,
            field_name="temperatura",
            pattern="#,##0.0",
            box=0.5,
            h_align="Center",
        )
        .add_styled_gap_text(
            x=8,
            y=72,
            width=539,
            height=32,
            template="Encaminhamos o(a) paciente {pac_nome} para acompanhamento em {especialidade_destino:________________} (Risco < 5% & estável).",
        )
    )

    band2 = DetailBandBuilder(height=40, column_width=555, max_height=623).add_static_text(
        x=0,
        y=10,
        width=555,
        height=20,
        text="ASSINATURA E CARIMBO DO MÉDICO RESPONSÁVEL",
        h_align="Center",
        box={"top": 0.75},
    )

    merged_jrxml = inject_detail_bands(base_jrxml, [band1, band2])

    # Verifica preservação de CDATA na queryString e conformidade 100% no linter
    assert "<![CDATA[select" in merged_jrxml
    lint_res = lint_jrxml(merged_jrxml)
    assert lint_res.is_valid is True, lint_res.to_dict()
    assert lint_res.errors == []
    assert lint_res.warnings == []
    assert lint_res.stats["detail_band_count"] == 2
    assert lint_res.stats["text_field_count"] == 3

    detail_only = extract_detail_xml(merged_jrxml)
    assert detail_only.startswith("<detail>")
    assert detail_only.strip().endswith("</detail>")
    assert 'markup="styled"' in detail_only
    assert "Boolean.TRUE.equals($F{orientado})" in detail_only

    # Verifica make_checkbox com negate=True -> Boolean.FALSE.equals
    neg_cb = make_checkbox(0, 0, "orientado", negate=True)
    assert "Boolean.FALSE.equals($F{orientado})" in neg_cb

    assert estimate_text_width("TEMPERATURA:", bold=True, font_size=9) > estimate_text_width(
        "TEMPERATURA:", bold=False, font_size=8
    )


def test_detail_builder_rejects_out_of_bounds_coordinates() -> None:
    with pytest.raises(ValueError, match="fora do intervalo"):
        DetailBandBuilder(height=624, max_height=623)

    b = DetailBandBuilder(height=50, column_width=555, max_height=623)
    with pytest.raises(ValueError, match="columnWidth"):
        b.add_static_text(x=500, y=0, width=60, height=12, text="Estouro X")
    with pytest.raises(ValueError, match="altura da banda"):
        b.add_static_text(x=0, y=40, width=100, height=15, text="Estouro Y")
    with pytest.raises(ValueError, match="Coordenada negativa"):
        b.add_static_text(x=-1, y=0, width=100, height=15, text="Negativo")


# =============================================================================
# 3. Linter Estrito — Todas as 7 Regras (Casos Inválidos Deliberados)
# =============================================================================


def test_linter_rule1_malformed_and_empty_xml() -> None:
    r_empty = lint_jrxml("")
    assert r_empty.is_valid is False
    assert r_empty.errors[0].code == "XML_EMPTY"

    r_bad = lint_jrxml("<jasperReport><unclosed></jasperReport>")
    assert r_bad.is_valid is False
    assert r_bad.errors[0]["code"] == "XML_PARSE_ERROR"

    r_root = lint_jrxml("<detail><band height='20'/></detail>")
    assert r_root.is_valid is False
    assert r_root.errors[0].code == "INVALID_ROOT_TAG"


def test_linter_rule2_and_rule3_textfield_null_and_expression_guards() -> None:
    base = scaffold_salutem_jrxml(_clinical_fixture("RETRATO"))

    # Caso 1: textField sem isBlankWhenNull="true" + concatenação insegura + printWhen == true + stretch warning
    bad_band = f"""<band height="80">
        <textField isStretchWithOverflow="true">
            <reportElement x="0" y="0" width="200" height="15" uuid="{uuid.uuid4()}">
                <printWhenExpression><![CDATA[$F{{orientado}} == true]]></printWhenExpression>
            </reportElement>
            <textElement><font size="8"/></textElement>
            <textFieldExpression><![CDATA[$F{{pac_nome}} + " - " + $F{{orientado_obs}}]]></textFieldExpression>
        </textField>
    </band>"""

    mutated = inject_detail_bands(base, bad_band)
    rep = lint_jrxml(mutated)
    assert rep.is_valid is False
    err_codes = {e.code for e in rep.errors}
    warn_codes = {w.code for w in rep.warnings}

    assert "TEXTFIELD_MISSING_BLANK_WHEN_NULL" in err_codes
    assert "UNSAFE_FIELD_CONCATENATION" in err_codes
    assert "UNSAFE_PRINT_WHEN_BOOLEAN" in err_codes
    assert "TEXTFIELD_STRETCH_OVERFLOW" in warn_codes


def test_linter_rule4_invalid_missing_and_duplicate_uuids() -> None:
    base = scaffold_salutem_jrxml(_clinical_fixture("RETRATO"))
    dup_uid = str(uuid.uuid4())

    bad_uuid_band = f"""<band height="60">
        <staticText>
            <reportElement x="0" y="0" width="100" height="15" uuid="titulo_invalido_1"/>
            <text><![CDATA[A]]></text>
        </staticText>
        <staticText>
            <reportElement x="0" y="16" width="100" height="15"/>
            <text><![CDATA[B]]></text>
        </staticText>
        <staticText>
            <reportElement x="0" y="32" width="100" height="15" uuid="{dup_uid}"/>
            <text><![CDATA[C]]></text>
        </staticText>
        <staticText>
            <reportElement x="110" y="32" width="100" height="15" uuid="{dup_uid}"/>
            <text><![CDATA[D]]></text>
        </staticText>
    </band>"""

    rep = lint_jrxml(inject_detail_bands(base, bad_uuid_band))
    assert rep.is_valid is False
    codes = {e.code for e in rep.errors}
    assert "INVALID_UUID" in codes
    assert "MISSING_UUID" in codes
    assert "DUPLICATE_UUID" in codes


def test_linter_rule5_undeclared_fields_and_parameters() -> None:
    base = scaffold_salutem_jrxml(_clinical_fixture("RETRATO"))
    bad_refs_band = f"""<band height="40">
        <textField isBlankWhenNull="true">
            <reportElement x="0" y="0" width="200" height="15" uuid="{uuid.uuid4()}">
                <printWhenExpression><![CDATA[$P{{parametro_fantasma}} != null && $P{{REPORT_LOCALE}} != null]]></printWhenExpression>
            </reportElement>
            <textFieldExpression><![CDATA[$F{{campo_inexistente}}]]></textFieldExpression>
        </textField>
    </band>"""

    rep = lint_jrxml(inject_detail_bands(base, bad_refs_band))
    assert rep.is_valid is False
    codes = {e.code for e in rep.errors}
    assert "UNDECLARED_FIELD" in codes
    assert "UNDECLARED_PARAMETER" in codes
    # REPORT_LOCALE é built-in do Jasper e NÃO deve ser listado como erro
    assert not any("REPORT_LOCALE" in e.message for e in rep.errors)


def test_linter_rule6_band_height_and_element_geometry_retrato_and_paisagem() -> None:
    base_retrato = scaffold_salutem_jrxml(_clinical_fixture("RETRATO"))
    overflow_retrato_band = f"""<band height="624">
        <staticText>
            <reportElement x="-2" y="-1" width="560" height="630" uuid="{uuid.uuid4()}"/>
            <text><![CDATA[Estouro Total]]></text>
        </staticText>
    </band>"""

    rep_r = lint_jrxml(inject_detail_bands(base_retrato, overflow_retrato_band))
    assert rep_r.is_valid is False
    codes_r = {e.code for e in rep_r.errors}
    assert "DETAIL_BAND_HEIGHT_EXCEEDED" in codes_r
    assert "ELEMENT_NEGATIVE_X" in codes_r
    assert "ELEMENT_NEGATIVE_Y" in codes_r
    assert "ELEMENT_EXCEEDS_COLUMN_WIDTH" in codes_r
    assert "ELEMENT_EXCEEDS_BAND_HEIGHT" in codes_r

    # Em PAISAGEM o limite de detail é 376 px (377 deve falhar)
    base_paisagem = scaffold_salutem_jrxml(_clinical_fixture("PAISAGEM"))
    rep_p = lint_jrxml(inject_detail_bands(base_paisagem, '<band height="377"/>'))
    assert rep_p.is_valid is False
    assert any(e.code == "DETAIL_BAND_HEIGHT_EXCEEDED" for e in rep_p.errors)


@pytest.mark.parametrize(
    ("label", "broken_element_xml"),
    [
        (
            "reportElement_order",
            lambda: f"""<staticText>
                <reportElement x="0" y="0" width="100" height="15" uuid="{uuid.uuid4()}">
                    <printWhenExpression><![CDATA[Boolean.TRUE.equals($F{{orientado}})]]></printWhenExpression>
                    <property name="com.jaspersoft.studio.unit.width" value="px"/>
                </reportElement>
                <text><![CDATA[Ordem errada em reportElement]]></text>
            </staticText>""",
        ),
        (
            "staticText_order",
            lambda: f"""<staticText>
                <reportElement x="0" y="0" width="100" height="15" uuid="{uuid.uuid4()}"/>
                <textElement><font size="8"/></textElement>
                <box><pen lineWidth="0.5"/></box>
                <text><![CDATA[box depois de textElement]]></text>
            </staticText>""",
        ),
        (
            "textField_order",
            lambda: f"""<textField isBlankWhenNull="true">
                <reportElement x="0" y="0" width="100" height="15" uuid="{uuid.uuid4()}"/>
                <textFieldExpression><![CDATA[$F{{pac_nome}}]]></textFieldExpression>
                <textElement><font size="8"/></textElement>
            </textField>""",
        ),
        (
            "ellipse_order",
            lambda: f"""<ellipse>
                <graphicElement><pen lineWidth="0.75"/></graphicElement>
                <reportElement x="0" y="0" width="10" height="10" uuid="{uuid.uuid4()}"/>
            </ellipse>""",
        ),
        (
            "rectangle_order",
            lambda: f"""<rectangle>
                <graphicElement><pen lineWidth="0.75"/></graphicElement>
                <reportElement x="0" y="0" width="10" height="10" uuid="{uuid.uuid4()}"/>
            </rectangle>""",
        ),
        (
            "box_order",
            lambda: f"""<staticText>
                <reportElement x="0" y="0" width="100" height="15" uuid="{uuid.uuid4()}"/>
                <box>
                    <bottomPen lineWidth="1.0"/>
                    <topPen lineWidth="1.0"/>
                </box>
                <text><![CDATA[bottomPen antes de topPen]]></text>
            </staticText>""",
        ),
        (
            "textElement_order",
            lambda: f"""<staticText>
                <reportElement x="0" y="0" width="100" height="15" uuid="{uuid.uuid4()}"/>
                <textElement>
                    <paragraph lineSpacing="Single"/>
                    <font size="8"/>
                </textElement>
                <text><![CDATA[paragraph antes de font]]></text>
            </staticText>""",
        ),
    ],
)
def test_linter_rule7_strict_xsd_child_order_all_7_elements(
    label: str,
    broken_element_xml: Any,
) -> None:
    base = scaffold_salutem_jrxml(_clinical_fixture("RETRATO"))
    band_xml = f'<band height="40">\n{broken_element_xml()}\n</band>'
    rep = lint_jrxml(inject_detail_bands(base, band_xml))
    assert rep.is_valid is False, f"Deveria falhar para {label}"
    assert any(e.code == "XSD_CHILD_ORDER_INVALID" for e in rep.errors), (
        f"Esperado XSD_CHILD_ORDER_INVALID em {label}, obteve: {rep.to_dict()}"
    )
