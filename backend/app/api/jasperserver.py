# -*- coding: utf-8 -*-
"""FastAPI router for JasperReports Server REST v2 profiles, repository browsing, import, and deploy."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.schemas import ProjectRead
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.jasperserver_service import (
    JasperServerCompileError,
    JasperServerDeployPreview,
    JasperServerDeployResult,
    JasperServerDeployTokenError,
    JasperServerError,
    JasperServerHttpError,
    JasperServerProfileCreate,
    JasperServerProfileNotFoundError,
    JasperServerProfileRead,
    JasperServerProfileUpdate,
    JasperServerReportUnitDetail,
    JasperServerResourceItem,
    JasperServerService,
    JasperServerTestResult,
    JasperServerValidationError,
    ReadOnlyJasperServerProfileError,
)
from backend.app.services.workspace_service import (
    ArtifactNotFoundError,
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)

router = APIRouter(prefix="/api", tags=["jasperserver"])


# =============================================================================
# Request Schemas
# =============================================================================


class JasperServerImportRequest(BaseModel):
    """Payload to import a JasperReports Server Report Unit into a new free_report project."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    resource_uri: str = Field(..., min_length=1)
    project_name: str | None = Field(default=None, max_length=200)
    db_profile_id: str | None = Field(default=None, max_length=128)
    sync_subreports: bool = True


class JasperServerDeployPrepareRequest(BaseModel):
    """Step-1 payload to validate, compile, diff, and issue a single-use JasperServer deploy token."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    mode: Literal["update", "create"] = "update"
    target_uri: str = Field(..., min_length=1)
    main_jrxml_uri: str | None = None
    label: str | None = Field(default=None, max_length=200)
    datasource_uri: str | None = None


class JasperServerDeployExecuteRequest(BaseModel):
    """Step-2 payload to execute a previously prepared JasperServer deploy."""

    model_config = ConfigDict(extra="forbid")

    deploy_token: str = Field(..., min_length=1)


# =============================================================================
# Dependencies & Error Handling
# =============================================================================


def get_jasperserver_service(request: Request) -> JasperServerService:
    """Resolve `JasperServerService` attached to FastAPI `app.state`."""
    svc = getattr(request.app.state, "jasperserver_service", None)
    if isinstance(svc, JasperServerService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    svc = JasperServerService(store=resolved_store)
    request.app.state.jasperserver_service = svc
    return svc


def get_workspace_service(request: Request) -> WorkspaceService:
    """Resolve `WorkspaceService` attached to FastAPI `app.state`."""
    svc = getattr(request.app.state, "workspace_service", None)
    if isinstance(svc, WorkspaceService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    svc = WorkspaceService(store=resolved_store)
    request.app.state.workspace_service = svc
    return svc


def get_jasper_daemon_dep(request: Request) -> Any:
    """Resolve `JasperDaemonService` from `app.state` or lazy singleton."""
    override = getattr(request.app.state, "jasper_daemon", None)
    if override is not None:
        return override
    try:
        from backend.app.services import jasper_daemon as _jd

        return _jd.get_jasper_daemon()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Serviço JasperDaemon indisponível: {exc}",
        ) from exc


JasperServerSvcDep = Annotated[JasperServerService, Depends(get_jasperserver_service)]
WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
JasperDaemonDep = Annotated[Any, Depends(get_jasper_daemon_dep)]


def _raise_http_for_js_error(exc: Exception) -> None:
    if isinstance(
        exc,
        (JasperServerProfileNotFoundError, ProjectNotFoundError, ArtifactNotFoundError),
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ReadOnlyJasperServerProfileError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            JasperServerValidationError,
            JasperServerDeployTokenError,
            JasperServerCompileError,
            WorkspaceValidationError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, JasperServerHttpError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if isinstance(exc, JasperServerError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


# =============================================================================
# Profile Endpoints
# =============================================================================


@router.get("/jasperserver/profiles", response_model=list[JasperServerProfileRead])
def list_jasperserver_profiles(
    service: JasperServerSvcDep,
) -> list[JasperServerProfileRead]:
    """List all configured JasperReports Server profiles (passwords redacted)."""
    return service.list_profiles()


@router.post(
    "/jasperserver/profiles",
    response_model=JasperServerProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_jasperserver_profile(
    payload: JasperServerProfileCreate,
    service: JasperServerSvcDep,
) -> JasperServerProfileRead:
    """Create a new JasperReports Server profile."""
    try:
        return service.create_profile(payload)
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.get("/jasperserver/profiles/{profile_id}", response_model=JasperServerProfileRead)
def get_jasperserver_profile(
    profile_id: str,
    service: JasperServerSvcDep,
) -> JasperServerProfileRead:
    """Get a single JasperReports Server profile by ID."""
    try:
        return service.get_profile(profile_id)
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.put("/jasperserver/profiles/{profile_id}", response_model=JasperServerProfileRead)
@router.patch("/jasperserver/profiles/{profile_id}", response_model=JasperServerProfileRead)
def update_jasperserver_profile(
    profile_id: str,
    payload: JasperServerProfileUpdate,
    service: JasperServerSvcDep,
) -> JasperServerProfileRead:
    """Update a JasperReports Server profile."""
    try:
        return service.update_profile(profile_id, payload)
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.delete("/jasperserver/profiles/{profile_id}")
def delete_jasperserver_profile(
    profile_id: str,
    service: JasperServerSvcDep,
) -> dict[str, Any]:
    """Delete a JasperReports Server profile and its vault password."""
    try:
        service.delete_profile(profile_id)
        return {"status": "ok", "deleted": profile_id}
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.post("/jasperserver/profiles/{profile_id}/test", response_model=JasperServerTestResult)
def test_jasperserver_profile(
    profile_id: str,
    service: JasperServerSvcDep,
) -> JasperServerTestResult:
    """Test connectivity and retrieve JasperReports Server version/edition/build."""
    try:
        return service.test_connection(profile_id)
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


# =============================================================================
# Repository Browse, Inspection & Import Endpoints
# =============================================================================


@router.get(
    "/jasperserver/profiles/{profile_id}/resources",
    response_model=list[JasperServerResourceItem],
)
def list_jasperserver_resources(
    profile_id: str,
    service: JasperServerSvcDep,
    folder_uri: str = Query(default="/"),
    q: str | None = Query(default=None),
    recursive: bool = Query(default=False),
    types: list[str] | None = Query(default=None),
) -> list[JasperServerResourceItem]:
    """List or search repository resources on a JasperReports Server."""
    flattened_types: list[str] | None = None
    if types:
        flattened_types = [
            part.strip()
            for raw in types
            for part in raw.split(",")
            if part.strip()
        ]
    try:
        return service.list_resources(
            profile_id,
            folder_uri=folder_uri,
            q=q,
            recursive=recursive,
            types=flattened_types,
        )
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.get(
    "/jasperserver/profiles/{profile_id}/report-unit",
    response_model=JasperServerReportUnitDetail,
)
def inspect_jasperserver_report_unit(
    profile_id: str,
    service: JasperServerSvcDep,
    uri: str = Query(..., min_length=1),
) -> JasperServerReportUnitDetail:
    """Inspect a JasperReports Server Report Unit descriptor."""
    try:
        return service.inspect_report_unit(profile_id, uri)
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.post(
    "/jasperserver/import",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def import_jasperserver_report(
    payload: JasperServerImportRequest,
    service: JasperServerSvcDep,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
) -> ProjectRead:
    """Import a Report Unit from JasperReports Server into a new `free_report` project."""
    try:
        return service.import_report_to_project(
            payload.profile_id,
            payload.resource_uri,
            workspace_service,
            jasper_daemon,
            project_name=payload.project_name,
            db_profile_id=payload.db_profile_id,
            sync_subreports=payload.sync_subreports,
        )
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


# =============================================================================
# 2-Step Safe Deploy Endpoints
# =============================================================================


@router.post(
    "/projects/{project_id}/deploy/jasperserver/prepare",
    response_model=JasperServerDeployPreview,
)
def prepare_jasperserver_deploy(
    project_id: str,
    payload: JasperServerDeployPrepareRequest,
    service: JasperServerSvcDep,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
) -> JasperServerDeployPreview:
    """Validate JVM compile, diff against remote JRXML, and issue a single-use deploy token."""
    try:
        return service.prepare_deploy_preview(
            project_id,
            payload.profile_id,
            workspace_service,
            jasper_daemon,
            mode=payload.mode,
            target_uri=payload.target_uri,
            main_jrxml_uri=payload.main_jrxml_uri,
            label=payload.label,
            datasource_uri=payload.datasource_uri,
        )
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise


@router.post(
    "/projects/{project_id}/deploy/jasperserver/execute",
    response_model=JasperServerDeployResult,
)
def execute_jasperserver_deploy(
    project_id: str,
    payload: JasperServerDeployExecuteRequest,
    service: JasperServerSvcDep,
    workspace_service: WorkspaceSvcDep,
) -> JasperServerDeployResult:
    """Consume single-use deploy token, save local backup (on update), and PUT to JasperServer."""
    try:
        return service.execute_deploy(
            project_id,
            payload.deploy_token,
            workspace_service,
        )
    except Exception as exc:
        _raise_http_for_js_error(exc)
        raise
