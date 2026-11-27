# -*- coding: utf-8 -*-
"""Ferramentas determinísticas, inspeção geométrica/visual de PDFs clínicos, descritores MCP/SDK e servidor stdio."""

from __future__ import annotations

from .artifact_tools import (
    extract_pdf_geometry,
    render_preview_images,
    save_validated_json,
    validate_and_compile_jrxml,
)
from .db_tools import (
    DB_TOOL_DEFINITIONS,
    DB_TOOL_HANDLERS,
    describe_db_table,
    list_db_tables,
    preview_db_select,
)
from .pdf_tools import (
    SALUTEM_BOTTOM_MARGIN,
    SALUTEM_LEFT_MARGIN,
    SALUTEM_RETRATO_DETAIL_ORIGIN_Y,
    SALUTEM_RETRATO_FOOTER_HEIGHT,
    SALUTEM_RETRATO_HEADER_HEIGHT,
    SALUTEM_RIGHT_MARGIN,
    SALUTEM_TOP_MARGIN,
    CroppedRegionPath,
    crop_pdf_region_to_png,
    map_pdf_rect_to_detail_band,
    render_pdf_to_pngs,
)
from .studio_tools import (
    LEGACY_STUDIO_TOOL_NAMES,
    STUDIO_TOOL_DEFINITIONS,
    STUDIO_TOOL_HANDLERS,
    crop_pdf_feedback_region,
    dispatch_studio_tool,
    get_all_mcp_tool_descriptors,
    get_all_sdk_tool_callables,
    get_mcp_tool_descriptors,
    get_salutem_skill,
    get_sdk_tool_callables,
    inspect_clinical_pdf,
    render_pdf_preview_pages,
)

__all__ = [
    "CroppedRegionPath",
    "DB_TOOL_DEFINITIONS",
    "DB_TOOL_HANDLERS",
    "LEGACY_STUDIO_TOOL_NAMES",
    "SALUTEM_BOTTOM_MARGIN",
    "SALUTEM_LEFT_MARGIN",
    "SALUTEM_RETRATO_DETAIL_ORIGIN_Y",
    "SALUTEM_RETRATO_FOOTER_HEIGHT",
    "SALUTEM_RETRATO_HEADER_HEIGHT",
    "SALUTEM_RIGHT_MARGIN",
    "SALUTEM_TOP_MARGIN",
    "STUDIO_TOOL_DEFINITIONS",
    "STUDIO_TOOL_HANDLERS",
    "StudioMcpServer",
    "crop_pdf_feedback_region",
    "crop_pdf_region_to_png",
    "describe_db_table",
    "dispatch_studio_tool",
    "extract_pdf_geometry",
    "get_all_mcp_tool_descriptors",
    "get_all_sdk_tool_callables",
    "get_mcp_tool_descriptors",
    "get_salutem_skill",
    "get_sdk_tool_callables",
    "inspect_clinical_pdf",
    "list_db_tables",
    "map_pdf_rect_to_detail_band",
    "preview_db_select",
    "render_pdf_preview_pages",
    "render_pdf_to_pngs",
    "render_preview_images",
    "save_validated_json",
    "validate_and_compile_jrxml",
]


def __getattr__(name: str):
    if name == "StudioMcpServer":
        from .mcp_server import StudioMcpServer

        return StudioMcpServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
