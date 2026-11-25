# -*- coding: utf-8 -*-
"""Descritores JSON-Schema e handlers invocáveis das ferramentas MCP/SDK do Salutem Ficha Studio."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import SKILLS_DIR
from app.mcp_tools.pdf_tools import (
    crop_pdf_region_to_png,
    extract_pdf_geometry,
    render_pdf_to_pngs,
)

_SKILL_ALIASES: dict[str, str] = {
    "extrator_ficha": "extrator_ficha",
    "extraction": "extrator_ficha",
    "extrator-ficha-clinica-salutem": "extrator_ficha",
    "gerador_jrxml": "gerador_jrxml",
    "jrxml": "gerador_jrxml",
    "gerador-layout-jrxml-salutem-v3": "gerador_jrxml",
}


def inspect_clinical_pdf(pdf_path: str) -> dict[str, Any]:
    """
    Extrai dimensões, orientação, spans de texto com fontes/coordenadas exatas e marcadores
    vetoriais (checkboxes quadrados vs rádios circulares) de um PDF clínico.
    """
    return extract_pdf_geometry(pdf_path)


def render_pdf_preview_pages(
    pdf_path: str,
    output_dir: str,
    dpi: int = 150,
    pages: list[int] | None = None,
) -> dict[str, Any]:
    """Renderiza páginas de um PDF clínico em imagens PNG para inspeção multimodal."""
    generated = render_pdf_to_pngs(pdf_path=pdf_path, output_dir=output_dir, dpi=dpi, pages=pages)
    return {
        "pdf_path": str(Path(pdf_path).resolve()),
        "output_dir": str(Path(output_dir).resolve()),
        "dpi": dpi,
        "count": len(generated),
        "png_paths": [str(p) for p in generated],
    }


def crop_pdf_feedback_region(
    pdf_path: str,
    page_number: int,
    rect: list[float] | tuple[float, float, float, float],
    output_path: str,
    dpi: int = 200,
) -> dict[str, Any]:
    """
    Recorta uma região `(x0, y0, x1, y1)` selecionada pelo usuário no preview do PDF em PNG
    de alta resolução e retorna o mapeamento exato `(detail_x, detail_y)` na banda `<detail>`
    do JasperReports Salutem (`detail_y = pdf_y - 182` no Retrato).
    """
    if len(rect) != 4:
        raise ValueError("`rect` deve conter 4 números: [x0, y0, x1, y1].")
    rect_tuple = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    cropped = crop_pdf_region_to_png(
        pdf_path=pdf_path,
        page_number=page_number,
        rect=rect_tuple,
        output_path=output_path,
        dpi=dpi,
    )
    return {
        "output_path": str(cropped),
        "page_number": cropped.page_number,
        "dpi": cropped.dpi,
        "pdf_rect": {
            "x0": cropped.pdf_rect[0],
            "y0": cropped.pdf_rect[1],
            "x1": cropped.pdf_rect[2],
            "y1": cropped.pdf_rect[3],
        },
        "detail_band": cropped.detail_coords,
    }


def get_salutem_skill(skill_name: str) -> dict[str, Any]:
    """
    Retorna o conteúdo Markdown oficial de uma skill embutida do Salutem Ficha Studio
    (`extrator_ficha` ou `gerador_jrxml`).
    """
    normalized = skill_name.strip().lower()
    canonical = _SKILL_ALIASES.get(normalized)
    if not canonical:
        valid = ", ".join(sorted({"extrator_ficha", "gerador_jrxml"}))
        raise ValueError(f"Skill desconhecida '{skill_name}'. Valores aceitos: {valid}")

    skill_file = SKILLS_DIR / canonical / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"Arquivo de skill não encontrado: {skill_file}")

    return {
        "skill_name": canonical,
        "path": str(skill_file.resolve()),
        "content": skill_file.read_text(encoding="utf-8"),
    }


STUDIO_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "inspect_clinical_pdf",
        "description": (
            "Extrai a geometria exata de um PDF clínico (dimensões, orientação Retrato/Paisagem, "
            "todos os spans de texto com fonte/tamanho/negrito/coordenadas e formas vetoriais "
            "classificando quadrados ~8-14px como checkboxes e círculos ~8-14px como rádios)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Caminho absoluto ou relativo do arquivo PDF clínico.",
                }
            },
            "required": ["pdf_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render_pdf_preview_pages",
        "description": (
            "Renderiza páginas de um PDF em arquivos PNG para inspeção visual multimodal "
            "pelo agente."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Caminho do arquivo PDF a renderizar.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Diretório onde os arquivos PNG gerados serão salvos.",
                },
                "dpi": {
                    "type": "integer",
                    "default": 150,
                    "minimum": 36,
                    "maximum": 600,
                    "description": "Resolução em DPI para renderização das páginas (padrão: 150).",
                },
                "pages": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "description": "Lista opcional de índices de páginas (base-0). Se omitido, renderiza todas.",
                },
            },
            "required": ["pdf_path", "output_dir"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crop_pdf_feedback_region",
        "description": (
            "Recorta um retângulo [x0, y0, x1, y1] selecionado no preview do PDF em PNG de alta "
            "resolução e calcula as coordenadas exatas correspondentes na banda <detail> do "
            "JasperReports Salutem (detail_y = pdf_y - 182 na ficha Retrato)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Caminho do arquivo PDF de origem.",
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Número da página (base-1, ex.: 1 para a primeira página).",
                },
                "rect": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "Coordenadas [x0, y0, x1, y1] em pontos de PDF.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Caminho completo do arquivo PNG recortado de saída.",
                },
                "dpi": {
                    "type": "integer",
                    "default": 200,
                    "minimum": 72,
                    "maximum": 600,
                    "description": "Resolução em DPI do recorte (padrão: 200).",
                },
            },
            "required": ["pdf_path", "page_number", "rect", "output_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_salutem_skill",
        "description": (
            "Carrega as instruções e regras oficiais das skills embutidas do Salutem "
            "('extrator_ficha' ou 'gerador_jrxml')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": ["extrator_ficha", "gerador_jrxml"],
                    "description": "Nome da skill desejada ('extrator_ficha' ou 'gerador_jrxml').",
                }
            },
            "required": ["skill_name"],
            "additionalProperties": False,
        },
    },
]

STUDIO_TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "inspect_clinical_pdf": inspect_clinical_pdf,
    "render_pdf_preview_pages": render_pdf_preview_pages,
    "crop_pdf_feedback_region": crop_pdf_feedback_region,
    "get_salutem_skill": get_salutem_skill,
}


def get_mcp_tool_descriptors() -> list[dict[str, Any]]:
    """Retorna cópia dos descritores JSON-Schema prontos para registro em servidor MCP."""
    return list(STUDIO_TOOL_DEFINITIONS)


def get_sdk_tool_callables() -> list[Callable[..., dict[str, Any]]]:
    """Retorna a lista de funções Python tipadas prontas para binding direto em SDKs de agentes."""
    return list(STUDIO_TOOL_HANDLERS.values())


def dispatch_studio_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa uma ferramenta do Studio pelo nome validando sua existência no registro."""
    handler = STUDIO_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        valid = ", ".join(sorted(STUDIO_TOOL_HANDLERS))
        raise KeyError(f"Ferramenta Studio desconhecida '{tool_name}'. Disponíveis: {valid}")
    kwargs = dict(arguments or {})
    return handler(**kwargs)
