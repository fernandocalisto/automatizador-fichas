# -*- coding: utf-8 -*-
"""Extração geométrica de PDFs clínicos, renderização PNG e recorte com mapeamento `<detail>` via PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

# Constantes oficiais de paginação da ficha Salutem (conforme gerador_jrxml/SKILL.md)
SALUTEM_TOP_MARGIN: float = 20.0
SALUTEM_BOTTOM_MARGIN: float = 20.0
SALUTEM_LEFT_MARGIN: float = 20.0
SALUTEM_RIGHT_MARGIN: float = 20.0
SALUTEM_RETRATO_HEADER_HEIGHT: float = 162.0
SALUTEM_RETRATO_FOOTER_HEIGHT: float = 17.0
SALUTEM_RETRATO_DETAIL_ORIGIN_Y: float = SALUTEM_TOP_MARGIN + SALUTEM_RETRATO_HEADER_HEIGHT  # 182.0

# Faixa dimensional (em pontos/px de PDF) para classificação de checkboxes/rádios (~8–14px com margem de traço)
MARKER_MIN_SIZE: float = 6.0
MARKER_MAX_SIZE: float = 16.0
MARKER_MAX_ASPECT_DIFF: float = 3.0

_BOLD_FONT_HINTS = ("bold", "black", "heavy", "demi", "semibold", "hebo", "tibo", "cobo")
_ITALIC_FONT_HINTS = (
    "italic",
    "oblique",
    "slant",
    "heit",
    "tiit",
    "coit",
    "hebi",
    "tibi",
    "cobi",
)


class CroppedRegionPath(Path):
    """
    Subclasse compatível de `pathlib.Path` retornada por `crop_pdf_region_to_png`.

    Preserva 100% da semântica de `Path` (`isinstance(p, Path) is True`) e expõe diretamente
    as coordenadas mapeadas para a banda `<detail>` do JasperReports (`detail_x`, `detail_y`,
    `detail_coords`), onde `detail_y = pdf_y - 182` na ficha Retrato do Salutem.
    """

    page_number: int
    dpi: int
    pdf_rect: tuple[float, float, float, float]
    detail_x: float
    detail_y: float
    detail_width: float
    detail_height: float
    detail_coords: dict[str, Any]

    @classmethod
    def with_metadata(
        cls,
        target: Path,
        *,
        page_number: int,
        dpi: int,
        pdf_rect: tuple[float, float, float, float],
        detail_coords: dict[str, Any],
    ) -> CroppedRegionPath:
        instance = cls(target)
        instance.page_number = page_number
        instance.dpi = dpi
        instance.pdf_rect = pdf_rect
        instance.detail_x = float(detail_coords["detail_x"])
        instance.detail_y = float(detail_coords["detail_y"])
        instance.detail_width = float(detail_coords["width"])
        instance.detail_height = float(detail_coords["height"])
        instance.detail_coords = detail_coords
        return instance


def _int_color_to_hex(color_int: int | None) -> str:
    if color_int is None:
        return "#000000"
    val = int(color_int) & 0xFFFFFF
    return f"#{val:06X}"


def _rgb_tuple_to_hex(rgb: tuple[float, ...] | list[float] | None) -> str | None:
    if not rgb or len(rgb) < 3:
        return None
    r = max(0, min(255, round(float(rgb[0]) * 255)))
    g = max(0, min(255, round(float(rgb[1]) * 255)))
    b = max(0, min(255, round(float(rgb[2]) * 255)))
    return f"#{r:02X}{g:02X}{b:02X}"


def map_pdf_rect_to_detail_band(
    rect: tuple[float, float, float, float],
    *,
    page_width: float = 595.0,
    page_height: float = 842.0,
    top_margin: float = SALUTEM_TOP_MARGIN,
    bottom_margin: float = SALUTEM_BOTTOM_MARGIN,
    left_margin: float = SALUTEM_LEFT_MARGIN,
    page_header_height: float = SALUTEM_RETRATO_HEADER_HEIGHT,
    page_footer_height: float = SALUTEM_RETRATO_FOOTER_HEIGHT,
) -> dict[str, Any]:
    """
    Converte um retângulo `(x0, y0, x1, y1)` em coordenadas absolutas do PDF para as coordenadas
    internas da banda `<detail>` do template Salutem:
      - `detail_x = pdf_x - leftMargin` (`pdf_x - 20`)
      - `detail_y = pdf_y - topMargin - pageHeaderHeight` (`pdf_y - 182` no Retrato!)
    """
    x0, y0, x1, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    width = round(x1 - x0, 2)
    height = round(y1 - y0, 2)
    is_portrait = page_height >= page_width
    orientation = "RETRATO" if is_portrait else "PAISAGEM"

    header_offset_y = round(top_margin + page_header_height, 2)
    footer_start_y = round(page_height - bottom_margin - page_footer_height, 2)
    max_detail_height = round(
        page_height - top_margin - bottom_margin - page_header_height - page_footer_height,
        2,
    )

    detail_x = round(x0 - left_margin, 2)
    detail_y = round(y0 - header_offset_y, 2)

    return {
        "x": detail_x,
        "y": detail_y,
        "detail_x": detail_x,
        "detail_y": detail_y,
        "width": width,
        "height": height,
        "pdf_x": round(x0, 2),
        "pdf_y": round(y0, 2),
        "header_offset_y": header_offset_y,
        "left_margin": round(left_margin, 2),
        "max_detail_height": max_detail_height,
        "orientation": orientation,
        "in_page_header": y0 < header_offset_y,
        "in_detail_band": header_offset_y <= y0 <= footer_start_y,
    }


def _classify_drawing(drawing: dict[str, Any]) -> tuple[str, str | None]:
    """
    Classifica uma primitiva vetorial do PyMuPDF (`page.get_drawings()`) em:
      - `shape_type`: `'rectangle'`, `'circle'`, `'ellipse'`, `'curve'`, `'line'` ou `'path'`
      - `candidate_marker`: `'checkbox'` (quadrado ~8–14px), `'radio'` (círculo ~8–14px) ou `None`
    """
    rect = drawing.get("rect")
    if rect is None:
        return "path", None

    w = float(rect.width)
    h = float(rect.height)
    items = drawing.get("items") or []
    ops = [item[0] for item in items if isinstance(item, tuple) and item]

    is_marker_sized = (
        MARKER_MIN_SIZE <= w <= MARKER_MAX_SIZE
        and MARKER_MIN_SIZE <= h <= MARKER_MAX_SIZE
        and abs(w - h) <= MARKER_MAX_ASPECT_DIFF
    )

    has_rect_op = "re" in ops or "qu" in ops
    has_curve_op = "c" in ops
    only_lines = bool(ops) and set(ops) == {"l"}

    # Círculo / Elipse / Curva Bézier (ex.: page.draw_circle / page.draw_oval)
    if has_curve_op and not has_rect_op:
        aspect = (min(w, h) / max(w, h)) if max(w, h) > 0 else 0.0
        if aspect >= 0.75:
            return "circle", ("radio" if is_marker_sized else None)
        if aspect >= 0.4:
            return "ellipse", None
        return "curve", None

    # Retângulo explícito ('re'/'qu') ou caixa fechada de 4 linhas ortogonais
    if has_rect_op or (only_lines and len(ops) == 4 and w > 1.5 and h > 1.5):
        if w <= 1.5 or h <= 1.5:
            return "line", None
        return "rectangle", ("checkbox" if is_marker_sized else None)

    if only_lines:
        return "line", None

    return "path", None


def extract_pdf_geometry(pdf_path: str | Path) -> dict[str, Any]:
    """
    Extrai a geometria completa de um PDF clínico usando PyMuPDF:
      - Contagem de páginas, largura/altura e orientação (`RETRATO` vs `PAISAGEM`);
      - Todos os spans de texto com bounding box exato `(x, y, width, height)`, coordenadas
        relativas à banda `<detail>`, nome/tamanho da fonte e flags `bold`/`italic`;
      - Formas vetoriais (`rectangle`, `line`, `circle`, `ellipse`, `curve`), classificando
        quadrados vs círculos de ~8–14px como candidatos a `checkbox` ou `radio` para a Fase 1
        do `gerador_jrxml`.
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {path}")

    pages_out: list[dict[str, Any]] = []
    total_spans = 0
    total_shapes = 0
    total_checkboxes = 0
    total_radios = 0

    with fitz.open(str(path)) as doc:
        page_count = doc.page_count

        for page_idx in range(page_count):
            page = doc.load_page(page_idx)
            p_width = round(float(page.rect.width), 2)
            p_height = round(float(page.rect.height), 2)
            is_portrait = p_height >= p_width
            orientation = "RETRATO" if is_portrait else "PAISAGEM"
            header_offset_y = SALUTEM_RETRATO_DETAIL_ORIGIN_Y
            max_detail_height = round(
                p_height
                - SALUTEM_TOP_MARGIN
                - SALUTEM_BOTTOM_MARGIN
                - SALUTEM_RETRATO_HEADER_HEIGHT
                - SALUTEM_RETRATO_FOOTER_HEIGHT,
                2,
            )

            # 1. Extração de spans de texto
            text_spans: list[dict[str, Any]] = []
            text_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        raw_text = str(span.get("text") or "")
                        if not raw_text.strip():
                            continue
                        bbox = span.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                        x0, y0, x1, y1 = (
                            float(bbox[0]),
                            float(bbox[1]),
                            float(bbox[2]),
                            float(bbox[3]),
                        )
                        font_name = str(span.get("font") or "")
                        font_lower = font_name.lower()
                        flags = int(span.get("flags") or 0)

                        is_bold = bool(flags & 16) or any(h in font_lower for h in _BOLD_FONT_HINTS)
                        is_italic = bool(flags & 2) or any(
                            h in font_lower for h in _ITALIC_FONT_HINTS
                        )

                        span_entry = {
                            "text": raw_text,
                            "x": round(x0, 2),
                            "y": round(y0, 2),
                            "width": round(x1 - x0, 2),
                            "height": round(y1 - y0, 2),
                            "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                            "detail_x": round(x0 - SALUTEM_LEFT_MARGIN, 2),
                            "detail_y": round(y0 - header_offset_y, 2),
                            "font": font_name,
                            "size": round(float(span.get("size") or 0.0), 2),
                            "bold": is_bold,
                            "italic": is_italic,
                            "flags": flags,
                            "color": _int_color_to_hex(span.get("color")),
                        }
                        text_spans.append(span_entry)

            # 2. Extração de formas vetoriais / desenhos
            shapes: list[dict[str, Any]] = []
            candidate_markers: list[dict[str, Any]] = []
            for drawing in page.get_drawings():
                d_rect = drawing.get("rect")
                if d_rect is None:
                    continue
                x0, y0, x1, y1 = (
                    float(d_rect.x0),
                    float(d_rect.y0),
                    float(d_rect.x1),
                    float(d_rect.y1),
                )
                shape_type, candidate_marker = _classify_drawing(drawing)
                stroke_width = drawing.get("width")

                shape_entry = {
                    "shape_type": shape_type,
                    "candidate_marker": candidate_marker,
                    "x": round(x0, 2),
                    "y": round(y0, 2),
                    "width": round(x1 - x0, 2),
                    "height": round(y1 - y0, 2),
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "detail_x": round(x0 - SALUTEM_LEFT_MARGIN, 2),
                    "detail_y": round(y0 - header_offset_y, 2),
                    "stroke_width": round(float(stroke_width), 2)
                    if stroke_width is not None
                    else None,
                    "stroke_color": _rgb_tuple_to_hex(drawing.get("color")),
                    "fill_color": _rgb_tuple_to_hex(drawing.get("fill")),
                }
                shapes.append(shape_entry)
                if candidate_marker is not None:
                    candidate_markers.append(shape_entry)
                    if candidate_marker == "checkbox":
                        total_checkboxes += 1
                    elif candidate_marker == "radio":
                        total_radios += 1

            total_spans += len(text_spans)
            total_shapes += len(shapes)

            pages_out.append(
                {
                    "page_number": page_idx + 1,
                    "page_index": page_idx,
                    "width": p_width,
                    "height": p_height,
                    "orientation": orientation,
                    "is_portrait": is_portrait,
                    "detail_origin_x": SALUTEM_LEFT_MARGIN,
                    "detail_origin_y": header_offset_y,
                    "max_detail_height": max_detail_height,
                    "text_spans": text_spans,
                    "shapes": shapes,
                    "candidate_markers": candidate_markers,
                }
            )

    first_page = pages_out[0] if pages_out else None
    return {
        "pdf_path": str(path),
        "page_count": page_count,
        "width": first_page["width"] if first_page else 0.0,
        "height": first_page["height"] if first_page else 0.0,
        "orientation": first_page["orientation"] if first_page else "RETRATO",
        "is_portrait": first_page["is_portrait"] if first_page else True,
        "pages": pages_out,
        "summary": {
            "total_text_spans": total_spans,
            "total_shapes": total_shapes,
            "checkbox_candidates": total_checkboxes,
            "radio_candidates": total_radios,
        },
    }


def render_pdf_to_pngs(
    pdf_path: str | Path,
    output_dir: str | Path,
    dpi: int = 150,
    pages: list[int] | None = None,
) -> list[Path]:
    """
    Renderiza as páginas de um PDF em arquivos de imagem PNG para inspeção visual multimodal.

    `pages` aceita índices base-0 (`[0, 1]`). Caso receba numeração base-1 inequívoca
    (ex.: `[1]` em PDF de 1 página), normaliza automaticamente.
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {path}")
    if dpi <= 0:
        raise ValueError(f"DPI deve ser positivo, recebido: {dpi}")

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered_paths: list[Path] = []
    with fitz.open(str(path)) as doc:
        total = doc.page_count
        if pages is None:
            target_indices = list(range(total))
        else:
            if (
                pages
                and 0 not in pages
                and all(1 <= p <= total for p in pages)
                and any(p == total for p in pages)
            ):
                target_indices = [p - 1 for p in pages]
            else:
                target_indices = list(pages)

        for idx in target_indices:
            if idx < 0 or idx >= total:
                raise ValueError(
                    f"Índice de página fora do intervalo válido (0..{total - 1}): {idx}"
                )
            page = doc.load_page(idx)
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            out_file = out_dir / f"{path.stem}_page_{idx + 1}.png"
            pix.save(str(out_file))
            rendered_paths.append(out_file)

    return rendered_paths


def crop_pdf_region_to_png(
    pdf_path: str | Path,
    page_number: int,
    rect: tuple[float, float, float, float],
    output_path: str | Path,
    dpi: int = 200,
) -> CroppedRegionPath:
    """
    Recorta um retângulo `(x0, y0, x1, y1)` selecionado pelo usuário em alta resolução PNG
    e mapeia as coordenadas para a banda `<detail>` do Salutem (`detail_y = pdf_y - 182` no Retrato).

    `page_number` usa base-1 (`1` = primeira página), aceitando também `0` como alias seguro
    para a primeira página. Retorna `CroppedRegionPath` (subclasse de `pathlib.Path` com
    `.detail_x`, `.detail_y` e `.detail_coords`).
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {path}")
    if dpi <= 0:
        raise ValueError(f"DPI deve ser positivo, recebido: {dpi}")
    if len(rect) != 4:
        raise ValueError("O retângulo `rect` deve conter exatamente 4 coordenadas (x0, y0, x1, y1).")

    x0, y0, x1, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Retângulo de recorte inválido (x1 <= x0 ou y1 <= y0): {rect}")

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(path)) as doc:
        total = doc.page_count
        if page_number == 0:
            page_idx = 0
        elif page_number >= 1:
            page_idx = page_number - 1
        else:
            raise ValueError(f"Número de página inválido: {page_number}")

        if page_idx >= total:
            raise ValueError(
                f"Página {page_number} inexistente no PDF (total de páginas: {total})."
            )

        page = doc.load_page(page_idx)
        clip_rect = fitz.Rect(x0, y0, x1, y1) & page.rect
        if clip_rect.is_empty or clip_rect.width <= 0 or clip_rect.height <= 0:
            raise ValueError(
                f"O retângulo {rect} está fora dos limites da página ({page.rect.width}x{page.rect.height})."
            )

        pix = page.get_pixmap(dpi=dpi, clip=clip_rect, alpha=False)
        pix.save(str(out_file))

        detail_coords = map_pdf_rect_to_detail_band(
            (clip_rect.x0, clip_rect.y0, clip_rect.x1, clip_rect.y1),
            page_width=float(page.rect.width),
            page_height=float(page.rect.height),
        )

    return CroppedRegionPath.with_metadata(
        out_file,
        page_number=page_idx + 1,
        dpi=dpi,
        pdf_rect=(round(clip_rect.x0, 2), round(clip_rect.y0, 2), round(clip_rect.x1, 2), round(clip_rect.y1, 2)),
        detail_coords=detail_coords,
    )
