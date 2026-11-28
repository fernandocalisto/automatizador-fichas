# -*- coding: utf-8 -*-
"""FastAPI router integrating Multi-Harness discovery, JRXML Scaffolder/Linter, Form Builder CRUD, and PDF Geometry."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.api.projects import (
    _raise_http_for_workspace_error,
    get_workspace_service,
)
from backend.app.core import (
    add_answer,
    add_question,
    audit_clinical_json_warnings,
    delete_answer,
    delete_question,
    format_json,
    reorder_answers,
    reorder_questions,
    update_answer,
    update_question,
)
from backend.app.harnesses import VALID_EFFORT_LEVELS, HarnessKind, get_default_registry
from backend.app.jrxml import lint_jrxml, scaffold_free_report_jrxml, scaffold_salutem_jrxml
from backend.app.mcp_tools.pdf_tools import extract_pdf_geometry
from backend.app.mcp_tools.studio_tools import get_all_mcp_tool_descriptors
from backend.app.services.workspace_service import ArtifactNotFoundError, WorkspaceService

router = APIRouter(prefix="/api", tags=["etapa1-studio-tools"])

WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


class ScaffoldJrxmlRequest(BaseModel):
    save_artifact: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class LintJrxmlRequest(BaseModel):
    jrxml: str | None = None


class QuestionMutationPayload(BaseModel):
    action: str = Field(
        ...,
        description="add_question | update_question | delete_question | reorder_questions | add_answer | update_answer | delete_answer | reorder_answers",
    )
    question_index: int | None = None
    answer_index: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    new_order: list[int] | None = None
    auto_regenerate_sql: bool = True


@router.get("/harnesses")
def list_harnesses(request: Request) -> list[dict[str, Any]]:
    """List all 4 supported AI harnesses (AGY, OpenCode, Claude Code, Codex) and live availability."""
    registry = getattr(request.app.state, "harness_registry", None) or get_default_registry()
    statuses = registry.list_statuses()
    return [
        st.model_dump(mode="json") if hasattr(st, "model_dump") else asdict(st)
        for st in statuses
    ]


@router.get("/harnesses/{harness_id}/models")
def list_harness_models(harness_id: str, request: Request) -> dict[str, Any]:
    """List available models and reasoning effort capabilities for a specific AI harness."""
    normalized_id = harness_id.strip().lower()
    registry = getattr(request.app.state, "harness_registry", None) or get_default_registry()
    try:
        harness = registry.get(normalized_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    models: list[dict[str, str]] = []
    list_fn = getattr(harness, "list_models", None)
    if callable(list_fn):
        try:
            raw_models = list_fn()
            if isinstance(raw_models, list):
                models = [
                    {
                        "id": str(item["id"]),
                        "label": str(item.get("label") or item["id"]),
                    }
                    for item in raw_models
                    if isinstance(item, dict) and item.get("id")
                ]
        except Exception:
            models = []

    is_agy = getattr(harness, "kind", None) == HarnessKind.AGY or normalized_id == "agy"
    default_model: str | None = None
    if is_agy:
        import os

        env_default = os.environ.get("AGY_DEFAULT_MODEL", "").strip()
        default_model = env_default or None

    return {
        "harness_id": normalized_id,
        "default_model": default_model,
        "models": models,
        "supports_effort": bool(is_agy),
        "effort_levels": list(VALID_EFFORT_LEVELS) if is_agy else [],
    }


@router.get("/mcp-tools")
def list_studio_mcp_tools() -> list[dict[str, Any]]:
    """Return JSON-Schema descriptors of all deterministic Studio MCP tools."""
    return get_all_mcp_tool_descriptors()


@router.get("/projects/{project_id}/json/warnings")
def get_project_json_warnings(project_id: str, service: WorkspaceSvcDep) -> dict[str, Any]:
    """Audit the project's latest clinical JSON against Salutem domain rules."""
    try:
        rev = service.get_latest_artifact(project_id, "json")
        parsed = json.loads(rev.content)
        warnings = audit_clinical_json_warnings(parsed)
        return {
            "project_id": project_id,
            "version_num": rev.version_num,
            "warnings_count": len(warnings),
            "warnings": warnings,
        }
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/projects/{project_id}/form-builder/mutate")
def mutate_project_form_builder(
    project_id: str,
    payload: QuestionMutationPayload,
    service: WorkspaceSvcDep,
) -> dict[str, Any]:
    """Execute deterministic Form Builder CRUD/reorder mutations on the project's clinical JSON."""
    try:
        rev = service.get_latest_artifact(project_id, "json")
        current_data = json.loads(rev.content)
        act = payload.action.strip().lower()

        if act == "add_question":
            updated = add_question(
                current_data,
                payload.data,
                position=payload.question_index,
            )
        elif act == "update_question":
            if payload.question_index is None:
                raise HTTPException(status_code=400, detail="question_index is required.")
            updated = update_question(current_data, payload.question_index, payload.data)
        elif act == "delete_question":
            if payload.question_index is None:
                raise HTTPException(status_code=400, detail="question_index is required.")
            updated = delete_question(current_data, payload.question_index)
        elif act == "reorder_questions":
            if payload.new_order is None:
                raise HTTPException(status_code=400, detail="new_order is required.")
            updated = reorder_questions(current_data, payload.new_order)
        elif act == "add_answer":
            if payload.question_index is None:
                raise HTTPException(status_code=400, detail="question_index is required.")
            updated = add_answer(
                current_data,
                payload.question_index,
                payload.data,
                position=payload.answer_index,
            )
        elif act == "update_answer":
            if payload.question_index is None or payload.answer_index is None:
                raise HTTPException(
                    status_code=400,
                    detail="question_index and answer_index are required.",
                )
            updated = update_answer(
                current_data,
                payload.question_index,
                payload.answer_index,
                payload.data,
            )
        elif act == "delete_answer":
            if payload.question_index is None or payload.answer_index is None:
                raise HTTPException(
                    status_code=400,
                    detail="question_index and answer_index are required.",
                )
            updated = delete_answer(current_data, payload.question_index, payload.answer_index)
        elif act == "reorder_answers":
            if payload.question_index is None or payload.new_order is None:
                raise HTTPException(
                    status_code=400,
                    detail="question_index and new_order are required.",
                )
            updated = reorder_answers(current_data, payload.question_index, payload.new_order)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported Form Builder action: '{payload.action}'.",
            )

        saved = service.save_artifact(
            project_id,
            "json",
            format_json(updated),
            summary=f"Form Builder: {act}",
            created_by="user",
            auto_regenerate_sql=payload.auto_regenerate_sql,
        )
        return {
            "saved": saved.model_dump(),
            "warnings": audit_clinical_json_warnings(updated),
        }
    except HTTPException:
        raise
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/projects/{project_id}/jrxml/scaffold")
def scaffold_project_jrxml(
    project_id: str,
    service: WorkspaceSvcDep,
    payload: ScaffoldJrxmlRequest = Body(default_factory=ScaffoldJrxmlRequest),
) -> dict[str, Any]:
    """Generate a valid base .jrxml (RETRATO or PAISAGEM) from clinical JSON or free-report starter."""
    try:
        project = service.get_project(project_id)
        try:
            rev = service.get_latest_artifact(project_id, "json")
            json_data = json.loads(rev.content)
            jrxml_text = scaffold_salutem_jrxml(json_data, options=payload.options)
            scaffold_summary = "Scaffold base Salutem .jrxml"
        except ArtifactNotFoundError:
            sql_select_text: str | None = None
            try:
                sql_select_text = service.get_latest_artifact(project_id, "sql_select").content
            except ArtifactNotFoundError:
                sql_select_text = None
            jrxml_text = scaffold_free_report_jrxml(
                title=project.name,
                report_name=project.slug,
                query_sql=sql_select_text,
                options=payload.options,
            )
            scaffold_summary = "Scaffold base relatório livre .jrxml"

        lint_report = lint_jrxml(jrxml_text)

        saved_rev = None
        if payload.save_artifact:
            save_res = service.save_artifact(
                project_id,
                "jrxml",
                jrxml_text,
                summary=scaffold_summary,
                created_by="system",
            )
            saved_rev = save_res.artifact.model_dump()

        return {
            "project_id": project_id,
            "jrxml": jrxml_text,
            "lint": lint_report.to_dict(),
            "saved_revision": saved_rev,
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/projects/{project_id}/jrxml/lint")
def lint_project_jrxml(
    project_id: str,
    service: WorkspaceSvcDep,
    payload: LintJrxmlRequest = Body(default_factory=LintJrxmlRequest),
) -> dict[str, Any]:
    """Run Phase 4 strict XSD, UUID, expression, and geometry linter on inline or stored .jrxml."""
    try:
        if payload.jrxml is not None:
            service.get_project(project_id)
            xml_text = payload.jrxml
        else:
            rev = service.get_latest_artifact(project_id, "jrxml")
            xml_text = rev.content
        report = lint_jrxml(xml_text)
        return report.to_dict()
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/projects/{project_id}/pdf/geometry")
def inspect_project_pdf_geometry(project_id: str, service: WorkspaceSvcDep) -> dict[str, Any]:
    """Extract exact text coordinates, page dimensions, and checkbox/radio candidates from source.pdf."""
    try:
        pdf_path = service.get_pdf_path(project_id)
        return extract_pdf_geometry(pdf_path)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise
