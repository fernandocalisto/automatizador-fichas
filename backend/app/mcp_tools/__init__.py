# -*- coding: utf-8 -*-
"""Ferramentas de inspeção geométrica/visual de PDFs clínicos e descritores MCP/SDK do Studio."""

from __future__ import annotations

from app.mcp_tools.pdf_tools import (
    SALUTEM_BOTTOM_MARGIN,
    SALUTEM_LEFT_MARGIN,
    SALUTEM_RETRATO_DETAIL_ORIGIN_Y,
    SALUTEM_RETRATO_FOOTER_HEIGHT,
    SALUTEM_RETRATO_HEADER_HEIGHT,
    SALUTEM_RIGHT_MARGIN,
    SALUTEM_TOP_MARGIN,
    CroppedRegionPath,
    crop_pdf_region_to_png,
    extract_pdf_geometry,
    map_pdf_rect_to_detail_band,
    render_pdf_to_pngs,
)
from app.mcp_tools.studio_tools import (
    STUDIO_TOOL_DEFINITIONS,
    STUDIO_TOOL_HANDLERS,
    crop_pdf_feedback_region,
    dispatch_studio_tool,
    get_mcp_tool_descriptors,
    get_salutem_skill,
    get_sdk_tool_callables,
    inspect_clinical_pdf,
    render_pdf_preview_pages,
)

__all__ = [
    "CroppedRegionPath",
    "SALUTEM_BOTTOM_MARGIN",
    "SALUTEM_LEFT_MARGIN",
    "SALUTEM_RETRATO_DETAIL_ORIGIN_Y",
    "SALUTEM_RETRATO_FOOTER_HEIGHT",
    "SALUTEM_RETRATO_HEADER_HEIGHT",
    "SALUTEM_RIGHT_MARGIN",
    "SALUTEM_TOP_MARGIN",
    "STUDIO_TOOL_DEFINITIONS",
    "STUDIO_TOOL_HANDLERS",
    "crop_pdf_feedback_region",
    "crop_pdf_region_to_png",
    "dispatch_studio_tool",
    "extract_pdf_geometry",
    "get_mcp_tool_descriptors",
    "get_salutem_skill",
    "get_sdk_tool_callables",
    "inspect_clinical_pdf",
    "map_pdf_rect_to_detail_band",
    "render_pdf_preview_pages",
    "render_pdf_to_pngs",
]
