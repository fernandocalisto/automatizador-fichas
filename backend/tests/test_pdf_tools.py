# -*- coding: utf-8 -*-
"""Testes unitários de extração geométrica PyMuPDF, renderização PNG, recorte `<detail>` e Studio Tools."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

import pytest

from app.mcp_tools import (
    SALUTEM_RETRATO_DETAIL_ORIGIN_Y,
    CroppedRegionPath,
    crop_pdf_region_to_png,
    dispatch_studio_tool,
    extract_pdf_geometry,
    get_mcp_tool_descriptors,
    get_sdk_tool_callables,
    map_pdf_rect_to_detail_band,
    render_pdf_to_pngs,
)


@pytest.fixture
def synthetic_clinical_pdf(tmp_path: Path) -> Path:
    """
    Gera um PDF clínico sintético A4 Retrato (595x842) em tempo real com PyMuPDF contendo:
      - Texto de cabeçalho em negrito (y < 182, zona pageHeader);
      - Linha horizontal divisória;
      - Quadrado 10x10 px em (x=30, y=210) -> candidato a checkbox (`detail_x=10, detail_y=28`);
      - Círculo 10x10 px centrado em (155, 215), raio 5 -> candidato a rádio (`150..160, 210..220`);
      - Caixa grande de observações 535x90 px (NÃO deve ser classificada como checkbox);
      - Campos multi-linha e observação em itálico.
    """
    pdf_file = tmp_path / "ficha_avaliacao_sintetica.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # 1. Cabeçalho em negrito (dentro da área do pageHeader < 182)
    page.insert_text(
        fitz.Point(180, 68),
        "FICHA DE AVALIACAO CLINICA",
        fontname="hebo",
        fontsize=12,
    )

    # 2. Linha divisória horizontal (deve ser classificada como 'line', sem candidate_marker)
    page.draw_line(fitz.Point(20, 180), fitz.Point(575, 180), color=(0, 0, 0), width=1.0)

    # 3. Marcador quadrado 10x10 (checkbox) + rótulo
    page.draw_rect(fitz.Rect(30, 210, 40, 220), color=(0, 0, 0), width=0.75)
    page.insert_text(fitz.Point(45, 218), "Hipertensao Arterial", fontname="helv", fontsize=9)

    # 4. Marcador circular 10x10 (radio) + rótulo
    page.draw_circle(fitz.Point(185, 215), 5.0, color=(0, 0, 0), width=0.75)
    page.insert_text(fitz.Point(195, 218), "Tabagista: Sim", fontname="helv", fontsize=9)

    # 5. Campos multi-linha e observação em itálico na banda <detail>
    page.insert_textbox(
        fitz.Rect(30, 250, 540, 295),
        "Queixa Principal e Historia da Molestia Atual:\nPaciente relata cefaleia frontal ha 3 dias.",
        fontname="helv",
        fontsize=9,
    )
    page.insert_text(
        fitz.Point(30, 315),
        "Observacao obrigatoria em caso de alergia medicamentosa.",
        fontname="heit",
        fontsize=8,
    )

    # 6. Retângulo grande de texto livre (deve ser 'rectangle' com candidate_marker=None)
    page.draw_rect(fitz.Rect(30, 330, 565, 420), color=(0, 0, 0), width=0.5)

    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_extract_pdf_geometry_text_spans_and_boolean_markers(
    synthetic_clinical_pdf: Path,
) -> None:
    geo = extract_pdf_geometry(synthetic_clinical_pdf)

    assert geo["page_count"] == 1
    assert geo["width"] == 595.0
    assert geo["height"] == 842.0
    assert geo["orientation"] == "RETRATO"
    assert geo["is_portrait"] is True

    page0 = geo["pages"][0]
    assert page0["max_detail_height"] == 623.0
    assert page0["detail_origin_y"] == SALUTEM_RETRATO_DETAIL_ORIGIN_Y == 182.0

    spans = page0["text_spans"]
    header_span = next(s for s in spans if "FICHA DE AVALIACAO CLINICA" in s["text"])
    assert header_span["bold"] is True
    assert header_span["size"] == 12.0
    assert header_span["detail_y"] < 0  # Acima do início da banda <detail> (182px)

    italic_span = next(s for s in spans if "alergia medicamentosa" in s["text"])
    assert italic_span["italic"] is True
    assert italic_span["detail_y"] > 0

    multiline_spans = [s for s in spans if "Queixa Principal" in s["text"] or "cefaleia" in s["text"]]
    assert len(multiline_spans) >= 2

    # Verifica classificação vetorial de checkbox (10x10 quadrado) vs radio (10x10 círculo)
    markers = page0["candidate_markers"]
    checkboxes = [m for m in markers if m["candidate_marker"] == "checkbox"]
    radios = [m for m in markers if m["candidate_marker"] == "radio"]

    assert len(checkboxes) == 1
    assert checkboxes[0]["shape_type"] == "rectangle"
    assert checkboxes[0]["x"] == pytest.approx(30.0, abs=0.5)
    assert checkboxes[0]["y"] == pytest.approx(210.0, abs=0.5)
    assert checkboxes[0]["width"] == pytest.approx(10.0, abs=0.5)
    assert checkboxes[0]["height"] == pytest.approx(10.0, abs=0.5)
    assert checkboxes[0]["detail_x"] == pytest.approx(10.0, abs=0.5)
    assert checkboxes[0]["detail_y"] == pytest.approx(28.0, abs=0.5)  # 210 - 182 = 28

    assert len(radios) == 1
    assert radios[0]["shape_type"] == "circle"
    assert radios[0]["x"] == pytest.approx(180.0, abs=0.5)
    assert radios[0]["y"] == pytest.approx(210.0, abs=0.5)
    assert radios[0]["width"] == pytest.approx(10.0, abs=0.5)
    assert radios[0]["height"] == pytest.approx(10.0, abs=0.5)

    # Garante que a linha divisória e o retângulo grande NÃO viraram candidatos booleanos
    all_shapes = page0["shapes"]
    assert any(s["shape_type"] == "line" and s["candidate_marker"] is None for s in all_shapes)
    assert any(
        s["shape_type"] == "rectangle" and s["width"] > 500 and s["candidate_marker"] is None
        for s in all_shapes
    )
    assert geo["summary"]["checkbox_candidates"] == 1
    assert geo["summary"]["radio_candidates"] == 1


def test_extract_pdf_geometry_detects_landscape(tmp_path: Path) -> None:
    landscape_pdf = tmp_path / "ficha_paisagem.pdf"
    doc = fitz.open()
    doc.new_page(width=842, height=595)
    doc.save(str(landscape_pdf))
    doc.close()

    geo = extract_pdf_geometry(landscape_pdf)
    assert geo["orientation"] == "PAISAGEM"
    assert geo["is_portrait"] is False


def test_render_pdf_to_pngs_creates_valid_images(
    synthetic_clinical_pdf: Path,
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "previews"
    png_paths = render_pdf_to_pngs(synthetic_clinical_pdf, out_dir, dpi=150)

    assert len(png_paths) == 1
    png_file = png_paths[0]
    assert png_file.is_file()
    assert png_file.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    with Image.open(png_file) as img:
        # 595 * 150 / 72 ≈ 1240 px; 842 * 150 / 72 ≈ 1754 px
        assert 1235 <= img.width <= 1245
        assert 1750 <= img.height <= 1760


def test_crop_pdf_region_to_png_and_detail_band_y_mapping(
    synthetic_clinical_pdf: Path,
    tmp_path: Path,
) -> None:
    crop_out = tmp_path / "crops" / "regiao_feedback.png"
    # Seleção na banda <detail>: x0=30, y0=232 -> detail_x = 10, detail_y = 232 - 182 = 50!
    cropped = crop_pdf_region_to_png(
        synthetic_clinical_pdf,
        page_number=1,
        rect=(30.0, 232.0, 230.0, 282.0),
        output_path=crop_out,
        dpi=200,
    )

    assert isinstance(cropped, Path)
    assert isinstance(cropped, CroppedRegionPath)
    assert cropped.is_file()

    assert cropped.detail_x == 10.0
    assert cropped.detail_y == 50.0  # 232 - 20 (topMargin) - 162 (pageHeaderHeight) = 50
    assert cropped.detail_width == 200.0
    assert cropped.detail_height == 50.0
    assert cropped.detail_coords["in_detail_band"] is True
    assert cropped.detail_coords["in_page_header"] is False

    with Image.open(cropped) as img:
        assert 550 <= img.width <= 560  # 200pt * 200dpi / 72 ≈ 556 px
        assert 135 <= img.height <= 145  # 50pt * 200dpi / 72 ≈ 139 px

    # Verifica também mapeamento de coordenada dentro do cabeçalho (< 182)
    header_map = map_pdf_rect_to_detail_band((20.0, 60.0, 400.0, 90.0))
    assert header_map["detail_y"] == -122.0
    assert header_map["in_page_header"] is True
    assert header_map["in_detail_band"] is False


def test_studio_tools_descriptors_and_dispatch(
    synthetic_clinical_pdf: Path,
    tmp_path: Path,
) -> None:
    descriptors = get_mcp_tool_descriptors()
    assert [d["name"] for d in descriptors] == [
        "inspect_clinical_pdf",
        "render_pdf_preview_pages",
        "crop_pdf_feedback_region",
        "get_salutem_skill",
    ]
    assert len(get_sdk_tool_callables()) == 4

    geo_res = dispatch_studio_tool(
        "inspect_clinical_pdf",
        {"pdf_path": str(synthetic_clinical_pdf)},
    )
    assert geo_res["page_count"] == 1

    preview_res = dispatch_studio_tool(
        "render_pdf_preview_pages",
        {
            "pdf_path": str(synthetic_clinical_pdf),
            "output_dir": str(tmp_path / "mcp_previews"),
            "dpi": 100,
        },
    )
    assert preview_res["count"] == 1

    crop_res = dispatch_studio_tool(
        "crop_pdf_feedback_region",
        {
            "pdf_path": str(synthetic_clinical_pdf),
            "page_number": 1,
            "rect": [40.0, 200.0, 140.0, 240.0],
            "output_path": str(tmp_path / "mcp_crop.png"),
        },
    )
    assert crop_res["detail_band"]["detail_x"] == 20.0
    assert crop_res["detail_band"]["detail_y"] == 18.0  # 200 - 182 = 18

    skill_res = dispatch_studio_tool("get_salutem_skill", {"skill_name": "gerador_jrxml"})
    assert skill_res["skill_name"] == "gerador_jrxml"
    assert "cabecalho_retrato.jasper" in skill_res["content"]
