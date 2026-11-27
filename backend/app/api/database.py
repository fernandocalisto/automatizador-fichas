# -*- coding: utf-8 -*-
"""FastAPI router for PostgreSQL connection profiles, transactional Dry-Run/Commit, and SELECT inspection."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.pg_schema_inspector import (
    PgSchemaInspector,
    SelectPreviewResult,
    TableSchemaDetail,
    TableSummary,
)
from backend.app.services.postgres_service import (
    CommitInsertResult,
    DbConnectionTestResult,
    DbProfileCreate,
    DbProfileNotFoundError,
    DbProfileRead,
    DbProfileUpdate,
    DbProfileValidationError,
    DryRunInsertResult,
    DryRunRequiredError,
    InspectSelectResult,
    PostgresConnectionError,
    PostgresExecutionError,
    PostgresService,
    PostgresServiceError,
    ReadOnlyProfileError,
)
from backend.app.services.workspace_service import (
    ArtifactNotFoundError,
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)

router = APIRouter(prefix="/api", tags=["database"])


# =============================================================================
# Request Payloads
# =============================================================================


class DryRunInsertRequest(BaseModel):
    """Payload to execute a rolled-back PostgreSQL Dry-Run for a project's SQL INSERT."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    sql_text: str | None = None
    sql: str | None = None


class CommitInsertRequest(BaseModel):
    """Payload to commit a Dry-Run-verified PostgreSQL SQL INSERT for a project."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    dry_run_token: str
    sql_text: str | None = None
    sql: str | None = None


class InspectSelectRequest(BaseModel):
    """Payload to inspect column OIDs and Java classes of a JasperReports SELECT query."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    sql_select: str | None = None
    sql: str | None = None
    sample_id: int | None = None
    lookup_sample_id: bool = False


class PreviewSelectRequest(BaseModel):
    """Payload to run a strictly READ ONLY bounded SELECT preview on a PostgreSQL profile."""

    model_config = ConfigDict(extra="forbid")

    sql_select: str | None = None
    sql: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=200)


# =============================================================================
# Dependencies & Error Mapping
# =============================================================================


def get_postgres_service(request: Request) -> PostgresService:
    """Resolve PostgresService attached to FastAPI `app.state` (lazily initializing if absent)."""
    svc = getattr(request.app.state, "postgres_service", None)
    if isinstance(svc, PostgresService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    svc = PostgresService(store=resolved_store)
    request.app.state.postgres_service = svc
    return svc


def get_workspace_service(request: Request) -> WorkspaceService:
    """Resolve WorkspaceService attached to FastAPI `app.state`."""
    svc = getattr(request.app.state, "workspace_service", None)
    if isinstance(svc, WorkspaceService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    svc = WorkspaceService(store=resolved_store)
    request.app.state.workspace_service = svc
    return svc


PostgresSvcDep = Annotated[PostgresService, Depends(get_postgres_service)]
WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


def _raise_http_for_db_error(exc: Exception) -> None:
    if isinstance(exc, (DbProfileNotFoundError, ProjectNotFoundError, ArtifactNotFoundError)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ReadOnlyProfileError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, PostgresConnectionError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if isinstance(
        exc,
        (
            DryRunRequiredError,
            DbProfileValidationError,
            WorkspaceValidationError,
            PostgresExecutionError,
            PostgresServiceError,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


# =============================================================================
# Connection Profile Endpoints (/api/db/profiles)
# =============================================================================


@router.get("/db/profiles", response_model=list[DbProfileRead])
def list_db_profiles(service: PostgresSvcDep) -> list[DbProfileRead]:
    """List all configured PostgreSQL connection profiles with redacted password status."""
    return service.list_profiles()


@router.post(
    "/db/profiles",
    response_model=DbProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_db_profile(payload: DbProfileCreate, service: PostgresSvcDep) -> DbProfileRead:
    """Create a new PostgreSQL connection profile and store its password in keyring/vault."""
    try:
        return service.create_profile(payload)
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}", response_model=DbProfileRead)
def get_db_profile(profile_id: str, service: PostgresSvcDep) -> DbProfileRead:
    """Retrieve redacted metadata for a single PostgreSQL connection profile."""
    try:
        return service.get_profile(profile_id)
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.put("/db/profiles/{profile_id}", response_model=DbProfileRead)
@router.patch("/db/profiles/{profile_id}", response_model=DbProfileRead)
def update_db_profile(
    profile_id: str,
    payload: DbProfileUpdate,
    service: PostgresSvcDep,
) -> DbProfileRead:
    """Update connection parameters, read-only flag, default flag, or password for a profile."""
    try:
        return service.update_profile(profile_id, payload)
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.delete("/db/profiles/{profile_id}")
def delete_db_profile(profile_id: str, service: PostgresSvcDep) -> dict[str, Any]:
    """Delete a PostgreSQL connection profile and erase its stored secret."""
    try:
        service.delete_profile(profile_id)
        return {"status": "ok", "deleted": profile_id}
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.post("/db/profiles/{profile_id}/test", response_model=DbConnectionTestResult)
def test_db_profile_connection(
    profile_id: str,
    service: PostgresSvcDep,
) -> DbConnectionTestResult:
    """Test connectivity, measure round-trip latency (ms), and query PostgreSQL server version."""
    try:
        return service.test_connection(profile_id)
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}/sample-atendimento")
def get_sample_atendimento_id(
    profile_id: str,
    service: PostgresSvcDep,
) -> dict[str, Any]:
    """Look up the most recent `public.atendimento.id` on the target PostgreSQL profile."""
    try:
        sample_id = service.find_sample_atendimento_id(profile_id)
        return {"profile_id": profile_id, "sample_atendimento_id": sample_id}
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}/databases")
def list_profile_databases(
    profile_id: str,
    service: PostgresSvcDep,
) -> dict[str, Any]:
    """Discover non-template databases on the PostgreSQL host in a read-only transaction."""
    try:
        databases = service.list_databases(profile_id)
        return {"profile_id": profile_id, "databases": databases}
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}/schemas")
def list_profile_schemas(
    profile_id: str,
    service: PostgresSvcDep,
) -> dict[str, Any]:
    """List user PostgreSQL schemas on the profile in a strictly READ ONLY transaction."""
    try:
        inspector = PgSchemaInspector(service)
        schemas = inspector.list_schemas(profile_id)
        return {"profile_id": profile_id, "schemas": schemas}
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}/tables", response_model=list[TableSummary])
def list_profile_tables(
    profile_id: str,
    service: PostgresSvcDep,
    schema: str = Query(default="public"),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[TableSummary]:
    """List tables and views in a schema with estimated row counts (READ ONLY)."""
    try:
        inspector = PgSchemaInspector(service)
        return inspector.list_tables(
            profile_id,
            schema=schema,
            search=search,
            limit=limit,
        )
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.get("/db/profiles/{profile_id}/tables/{table_name}", response_model=TableSchemaDetail)
def describe_profile_table(
    profile_id: str,
    table_name: str,
    service: PostgresSvcDep,
    schema: str = Query(default="public"),
) -> TableSchemaDetail:
    """Describe columns, Java classes, PKs, and FKs of a PostgreSQL table/view (READ ONLY)."""
    try:
        inspector = PgSchemaInspector(service)
        return inspector.describe_table(profile_id, schema=schema, table=table_name)
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.post("/db/profiles/{profile_id}/preview-select", response_model=SelectPreviewResult)
def preview_profile_select(
    profile_id: str,
    payload: PreviewSelectRequest,
    service: PostgresSvcDep,
) -> SelectPreviewResult:
    """Execute a strictly READ ONLY SELECT preview bounded by LIMIT (1..200)."""
    sql_text = payload.sql_select if payload.sql_select is not None else (payload.sql or "")
    try:
        inspector = PgSchemaInspector(service)
        return inspector.preview_select_query(
            profile_id,
            sql_text,
            params=payload.params,
            limit=payload.limit,
        )
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


# =============================================================================
# Project Transactional SQL Execution Endpoints (/api/projects/{project_id}/db/*)
# =============================================================================


def _resolve_sql_payload(
    *,
    explicit_primary: str | None,
    explicit_alias: str | None,
    workspace_service: WorkspaceService,
    project_id: str,
    artifact_type: str,
) -> str:
    if explicit_primary is not None:
        return explicit_primary
    if explicit_alias is not None:
        return explicit_alias
    latest = workspace_service.get_latest_artifact(project_id, artifact_type)  # type: ignore[arg-type]
    return latest.content


@router.post(
    "/projects/{project_id}/db/dry-run-insert",
    response_model=DryRunInsertResult,
)
def dry_run_project_insert(
    project_id: str,
    payload: DryRunInsertRequest,
    postgres_service: PostgresSvcDep,
    workspace_service: WorkspaceSvcDep,
) -> DryRunInsertResult:
    """Run a clinical SQL INSERT inside a rolled-back transaction and issue a SHA-256 `dry_run_token`."""
    try:
        workspace_service.get_project(project_id)
        sql_text = _resolve_sql_payload(
            explicit_primary=payload.sql_text,
            explicit_alias=payload.sql,
            workspace_service=workspace_service,
            project_id=project_id,
            artifact_type="sql_insert",
        )
        return postgres_service.dry_run_insert(
            project_id=project_id,
            profile_id=payload.profile_id,
            sql_text=sql_text,
        )
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.post(
    "/projects/{project_id}/db/commit-insert",
    response_model=CommitInsertResult,
)
def commit_project_insert(
    project_id: str,
    payload: CommitInsertRequest,
    postgres_service: PostgresSvcDep,
    workspace_service: WorkspaceSvcDep,
) -> CommitInsertResult:
    """Verify `dry_run_token` and commit the clinical SQL INSERT, updating `template_db_id` and `gate2_sql_insert`."""
    try:
        workspace_service.get_project(project_id)
        sql_text = _resolve_sql_payload(
            explicit_primary=payload.sql_text,
            explicit_alias=payload.sql,
            workspace_service=workspace_service,
            project_id=project_id,
            artifact_type="sql_insert",
        )
        return postgres_service.commit_insert(
            project_id=project_id,
            profile_id=payload.profile_id,
            sql_text=sql_text,
            dry_run_token=payload.dry_run_token,
            workspace_service=workspace_service,
        )
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise


@router.post(
    "/projects/{project_id}/db/inspect-select",
    response_model=InspectSelectResult,
)
def inspect_project_select(
    project_id: str,
    payload: InspectSelectRequest,
    postgres_service: PostgresSvcDep,
    workspace_service: WorkspaceSvcDep,
) -> InspectSelectResult:
    """Inspect a JasperReports SELECT query with `LIMIT 0` to discover column OIDs and Java classes."""
    try:
        workspace_service.get_project(project_id)
        sql_select = _resolve_sql_payload(
            explicit_primary=payload.sql_select,
            explicit_alias=payload.sql,
            workspace_service=workspace_service,
            project_id=project_id,
            artifact_type="sql_select",
        )
        discovered_sample_id: int | None = None
        if payload.sample_id is not None:
            effective_sample_id = payload.sample_id
        elif payload.lookup_sample_id:
            discovered_sample_id = postgres_service.find_sample_atendimento_id(payload.profile_id)
            effective_sample_id = discovered_sample_id if discovered_sample_id is not None else 0
        else:
            effective_sample_id = 0

        result = postgres_service.inspect_select_query(
            profile_id=payload.profile_id,
            sql_select=sql_select,
            sample_id=effective_sample_id,
        )
        if discovered_sample_id is not None:
            result = result.model_copy(update={"sample_atendimento_id": discovered_sample_id})
        return result
    except Exception as exc:
        _raise_http_for_db_error(exc)
        raise
