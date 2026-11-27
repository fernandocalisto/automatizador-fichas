# -*- coding: utf-8 -*-
"""FastAPI router for SSH/SFTP profiles, remote browsing, report import, and safe 2-step deployment."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.schemas import ProjectRead
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.jasper_daemon import JasperDaemonError
from backend.app.services.sftp_service import (
    ReadOnlySftpProfileError,
    SftpConnectionError,
    SftpConnectionTestResult,
    SftpDeployPreview,
    SftpDeployResult,
    SftpDeployTokenError,
    SftpListResult,
    SftpProfileCreate,
    SftpProfileNotFoundError,
    SftpProfileRead,
    SftpProfileUpdate,
    SftpPublishMode,
    SftpService,
    SftpServiceError,
    SftpValidationError,
)
from backend.app.services.workspace_service import (
    ArtifactNotFoundError,
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)

router = APIRouter(prefix="/api", tags=["sftp"])


# =============================================================================
# Request Payloads
# =============================================================================


class SftpImportRequest(BaseModel):
    """Payload to import a remote `.jrxml` or `.jasper` report via SFTP into a new project."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    remote_path: str = Field(..., min_length=1)
    project_name: str | None = None
    db_profile_id: str | None = None
    sync_subreports: bool = False


class SftpDeployPrepareRequest(BaseModel):
    """Step 1 payload: validate compilation, compute remote diff, and issue a single-use deploy token."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1)
    remote_dir: str = Field(..., min_length=1)
    base_filename: str = Field(..., min_length=1)
    publish_mode: SftpPublishMode = "jrxml_only"


class SftpDeployExecuteRequest(BaseModel):
    """Step 2 payload: consume single-use deploy token, backup existing files, and upload atomically."""

    model_config = ConfigDict(extra="forbid")

    deploy_token: str = Field(..., min_length=1)


# =============================================================================
# Dependencies & Error Mapping
# =============================================================================


def get_sftp_service(request: Request) -> SftpService:
    """Resolve `SftpService` attached to FastAPI `app.state` (lazily initializing if absent)."""
    svc = getattr(request.app.state, "sftp_service", None)
    if isinstance(svc, SftpService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    svc = SftpService(store=resolved_store)
    request.app.state.sftp_service = svc
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
        from backend.app.services import jasper_daemon as _jasper_daemon_mod

        return _jasper_daemon_mod.get_jasper_daemon()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"JasperDaemonService indisponível: {exc}",
        ) from exc


SftpSvcDep = Annotated[SftpService, Depends(get_sftp_service)]
WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
JasperDaemonDep = Annotated[Any, Depends(get_jasper_daemon_dep)]


def _raise_http_for_sftp_error(exc: Exception) -> None:
    if isinstance(exc, (SftpProfileNotFoundError, ProjectNotFoundError, ArtifactNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ReadOnlySftpProfileError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, SftpConnectionError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            SftpValidationError,
            SftpDeployTokenError,
            WorkspaceValidationError,
            JasperDaemonError,
            SftpServiceError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


# =============================================================================
# Profile Endpoints (/api/sftp/profiles)
# =============================================================================


@router.get("/sftp/profiles", response_model=list[SftpProfileRead])
def list_sftp_profiles(service: SftpSvcDep) -> list[SftpProfileRead]:
    """List all configured SSH/SFTP server profiles with redacted secret flags."""
    return service.list_profiles()


@router.post(
    "/sftp/profiles",
    response_model=SftpProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_sftp_profile(
    payload: SftpProfileCreate,
    service: SftpSvcDep,
) -> SftpProfileRead:
    """Create a new SSH/SFTP server profile and store custom credentials in SecretVault."""
    try:
        return service.create_profile(payload)
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.get("/sftp/profiles/{profile_id}", response_model=SftpProfileRead)
def get_sftp_profile(profile_id: str, service: SftpSvcDep) -> SftpProfileRead:
    """Fetch redacted metadata for a single SSH/SFTP profile."""
    try:
        return service.get_profile(profile_id)
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.put("/sftp/profiles/{profile_id}", response_model=SftpProfileRead)
@router.patch("/sftp/profiles/{profile_id}", response_model=SftpProfileRead)
def update_sftp_profile(
    profile_id: str,
    payload: SftpProfileUpdate,
    service: SftpSvcDep,
) -> SftpProfileRead:
    """Update an existing SSH/SFTP profile and optionally rotate/clear its vault secrets."""
    try:
        return service.update_profile(profile_id, payload)
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.delete("/sftp/profiles/{profile_id}")
def delete_sftp_profile(profile_id: str, service: SftpSvcDep) -> dict[str, Any]:
    """Delete an SSH/SFTP profile and remove its vault secrets."""
    try:
        service.delete_profile(profile_id)
        return {"status": "ok", "deleted": profile_id}
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.post("/sftp/profiles/{profile_id}/test", response_model=SftpConnectionTestResult)
def test_sftp_profile_connection(
    profile_id: str,
    service: SftpSvcDep,
) -> SftpConnectionTestResult:
    """Test SSH/SFTP connectivity, measure latency, and verify `remote_base_dir`."""
    try:
        return service.test_connection(profile_id)
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.get("/sftp/profiles/{profile_id}/browse", response_model=SftpListResult)
def browse_sftp_directory(
    profile_id: str,
    service: SftpSvcDep,
    path: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> SftpListResult:
    """List remote directories and `.jrxml`/`.jasper` files inside the profile's allowed base dir."""
    try:
        return service.list_directory(profile_id, remote_path=path, search=search)
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


# =============================================================================
# Import & Safe 2-Step Deploy Endpoints
# =============================================================================


@router.post(
    "/sftp/import",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def import_sftp_report(
    payload: SftpImportRequest,
    service: SftpSvcDep,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
) -> ProjectRead:
    """Import a `.jrxml` or `.jasper` (auto-decompiled) report from SFTP into a new `free_report` project."""
    try:
        return service.import_report_to_project(
            payload.profile_id,
            payload.remote_path,
            workspace_service,
            jasper_daemon,
            project_name=payload.project_name,
            db_profile_id=payload.db_profile_id,
            sync_subreports=payload.sync_subreports,
        )
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.post(
    "/projects/{project_id}/deploy/sftp/prepare",
    response_model=SftpDeployPreview,
)
def prepare_sftp_deploy(
    project_id: str,
    payload: SftpDeployPrepareRequest,
    service: SftpSvcDep,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
) -> SftpDeployPreview:
    """Step 1: validate JRXML compile, diff against remote file, and issue single-use `deploy_token`."""
    try:
        return service.prepare_deploy_preview(
            project_id,
            payload.profile_id,
            payload.remote_dir,
            payload.base_filename,
            workspace_service,
            jasper_daemon,
            publish_mode=payload.publish_mode,
        )
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise


@router.post(
    "/projects/{project_id}/deploy/sftp/execute",
    response_model=SftpDeployResult,
)
def execute_sftp_deploy(
    project_id: str,
    payload: SftpDeployExecuteRequest,
    service: SftpSvcDep,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
) -> SftpDeployResult:
    """Step 2: consume `deploy_token`, create remote `.bak` + local backup, and upload atomically."""
    try:
        return service.execute_deploy(
            project_id,
            payload.deploy_token,
            workspace_service,
            jasper_daemon,
        )
    except Exception as exc:
        _raise_http_for_sftp_error(exc)
        raise
