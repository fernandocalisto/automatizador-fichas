# -*- coding: utf-8 -*-
"""FastAPI router for project workspaces, PDF streaming, artifacts, SQL tools, gates, and chat."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from backend.app.db.schemas import (
    ArtifactRevisionRead,
    ArtifactSaveRequest,
    ArtifactSaveResponse,
    ArtifactType,
    ChatMessageCreate,
    ChatMessageRead,
    ChatPhase,
    CreatedBy,
    GateApprovalRead,
    GateApprovalUpdate,
    GateName,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    SqlRegenerateRequest,
    SqlRegenerateResponse,
    SqlValidateRequest,
    SqlValidateResponse,
)
from backend.app.services.workspace_service import (
    ArtifactNotFoundError,
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class RevisionRestorePayload(BaseModel):
    """Payload to restore an artifact revision by version_num or revision_id."""

    model_config = ConfigDict(extra="forbid")

    version_num: int | None = None
    revision_id: int | None = None
    created_by: CreatedBy = "user"
    auto_regenerate_sql: bool = True


def get_workspace_service(request: Request) -> WorkspaceService:
    """Resolve WorkspaceService instance attached to FastAPI app state."""
    svc = getattr(request.app.state, "workspace_service", None)
    if isinstance(svc, WorkspaceService):
        return svc
    return WorkspaceService()


WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


def _raise_http_for_workspace_error(exc: Exception) -> None:
    if isinstance(exc, ProjectNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ArtifactNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, WorkspaceValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=list[ProjectRead])
def list_projects(service: WorkspaceSvcDep) -> list[ProjectRead]:
    """List all studio projects ordered by last update."""
    return service.list_projects()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, service: WorkspaceSvcDep) -> ProjectRead:
    """Create a new project (empty/PDF landing, direct JSON import, or direct JRXML import)."""
    try:
        return service.create_project(payload)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, service: WorkspaceSvcDep) -> ProjectRead:
    """Retrieve full metadata, gate statuses, and latest artifact versions for a project."""
    try:
        return service.get_project(project_id)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    service: WorkspaceSvcDep,
) -> ProjectRead:
    """Partially update project metadata, stage, harness preference, or template_db_id."""
    try:
        return service.update_project(project_id, payload)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.delete("/{project_id}")
def delete_project(project_id: str, service: WorkspaceSvcDep) -> dict[str, Any]:
    """Delete a project, its SQLite records, and its workspace folder."""
    try:
        service.delete_project(project_id)
        return {"status": "ok", "deleted": project_id}
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/{project_id}/pdf", response_model=ProjectRead)
async def upload_project_pdf(
    project_id: str,
    service: WorkspaceSvcDep,
    file: UploadFile = File(...),
) -> ProjectRead:
    """Upload original clinical form PDF (`source.pdf`) and move landing projects to `extraction`."""
    pdf_bytes = await file.read()
    try:
        return service.save_uploaded_pdf(project_id, pdf_bytes)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/pdf")
def stream_project_pdf(project_id: str, service: WorkspaceSvcDep) -> FileResponse:
    """Stream the project's original `source.pdf`."""
    try:
        project = service.get_project(project_id)
        pdf_path = service.get_pdf_path(project_id)
        return FileResponse(
            path=str(pdf_path),
            media_type="application/pdf",
            filename=f"{project.slug}_source.pdf",
            content_disposition_type="inline",
        )
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/artifacts/{artifact_type}", response_model=ArtifactRevisionRead)
def get_project_artifact(
    project_id: str,
    artifact_type: ArtifactType,
    service: WorkspaceSvcDep,
    version: int | None = Query(default=None, ge=1),
) -> ArtifactRevisionRead:
    """Fetch the latest revision (or a specific historical `version`) of an artifact."""
    try:
        if version is not None:
            service.get_project(project_id)
            rev = service.store.get_artifact_revision(
                project_id,
                artifact_type,
                version_num=version,
            )
            if rev is None:
                raise ArtifactNotFoundError(
                    f"Version {version} of '{artifact_type}' not found for project '{project_id}'."
                )
            return ArtifactRevisionRead(**rev)
        return service.get_latest_artifact(project_id, artifact_type)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.put("/{project_id}/artifacts/{artifact_type}", response_model=ArtifactSaveResponse)
def save_project_artifact(
    project_id: str,
    artifact_type: ArtifactType,
    payload: ArtifactSaveRequest,
    service: WorkspaceSvcDep,
) -> ArtifactSaveResponse:
    """Save a new immutable revision of `json`, `sql_insert`, `sql_select`, or `jrxml`."""
    try:
        if payload.restore_from_version is not None or payload.restore_from_revision_id is not None:
            return service.restore_revision(
                project_id,
                artifact_type,
                version_num=payload.restore_from_version,
                revision_id=payload.restore_from_revision_id,
                created_by=payload.created_by,
                auto_regenerate_sql=payload.auto_regenerate_sql,
            )
        return service.save_artifact(
            project_id,
            artifact_type,
            payload.content,
            summary=payload.summary,
            created_by=payload.created_by,
            auto_regenerate_sql=payload.auto_regenerate_sql,
            apply_uppercase=payload.apply_uppercase,
            sql_options=payload.sql_options,
        )
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/{project_id}/artifacts/{artifact_type}/restore", response_model=ArtifactSaveResponse)
def restore_project_artifact(
    project_id: str,
    artifact_type: ArtifactType,
    payload: RevisionRestorePayload,
    service: WorkspaceSvcDep,
) -> ArtifactSaveResponse:
    """Restore a previous revision of an artifact as the new latest revision."""
    try:
        return service.restore_revision(
            project_id,
            artifact_type,
            version_num=payload.version_num,
            revision_id=payload.revision_id,
            created_by=payload.created_by,
            auto_regenerate_sql=payload.auto_regenerate_sql,
        )
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/revisions", response_model=list[ArtifactRevisionRead])
def list_project_revisions(
    project_id: str,
    service: WorkspaceSvcDep,
    artifact_type: ArtifactType | None = Query(default=None),
) -> list[ArtifactRevisionRead]:
    """List revision history for a project (optionally filtered by `artifact_type`)."""
    try:
        return service.list_revisions(project_id, artifact_type=artifact_type)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/{project_id}/sql/regenerate", response_model=SqlRegenerateResponse)
def regenerate_project_sql(
    project_id: str,
    service: WorkspaceSvcDep,
    payload: SqlRegenerateRequest = Body(default_factory=SqlRegenerateRequest),
) -> SqlRegenerateResponse:
    """Regenerate both `sql_insert` and `sql_select` from the project's latest clinical JSON."""
    try:
        return service.regenerate_sql_from_json(
            project_id,
            insert_options=payload.insert_options,
            select_options=payload.select_options,
            created_by=payload.created_by,
            summary=payload.summary,
        )
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post("/{project_id}/sql/validate", response_model=SqlValidateResponse)
def validate_project_sql(
    project_id: str,
    service: WorkspaceSvcDep,
    payload: SqlValidateRequest = Body(default_factory=SqlValidateRequest),
) -> SqlValidateResponse:
    """Validate PostgreSQL syntax for inline SQL or one of the project's stored SQL artifacts."""
    try:
        return service.validate_sql(
            project_id,
            sql=payload.sql,
            artifact_type=payload.artifact_type,
        )
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/gates", response_model=list[GateApprovalRead])
def list_project_gates(project_id: str, service: WorkspaceSvcDep) -> list[GateApprovalRead]:
    """Return the 3 human approval gates (`gate1_json`, `gate2_sql_insert`, `gate3_jrxml`)."""
    try:
        return service.list_gates(project_id)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.put("/{project_id}/gates/{gate_name}", response_model=GateApprovalRead)
def update_project_gate(
    project_id: str,
    gate_name: GateName,
    payload: GateApprovalUpdate,
    service: WorkspaceSvcDep,
) -> GateApprovalRead:
    """Approve, reject, or reset a project approval gate."""
    try:
        return service.update_gate(project_id, gate_name, payload)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/chat", response_model=list[ChatMessageRead])
def list_project_chat(
    project_id: str,
    service: WorkspaceSvcDep,
    phase: ChatPhase | None = Query(default=None),
) -> list[ChatMessageRead]:
    """List persisted chat messages for a project (optionally filtered by `phase`)."""
    try:
        return service.list_chat_messages(project_id, phase=phase)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.post(
    "/{project_id}/chat",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
)
def append_project_chat(
    project_id: str,
    payload: ChatMessageCreate,
    service: WorkspaceSvcDep,
) -> ChatMessageRead:
    """Append a message to the project's `extraction` or `jrxml` chat transcript."""
    try:
        return service.add_chat_message(project_id, payload)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise
