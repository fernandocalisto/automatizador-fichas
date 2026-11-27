# -*- coding: utf-8 -*-
"""FastAPI router for multi-system Clients Hub CRUD and local authenticated portal sync."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.schemas import EnvironmentKind
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.client_catalog_service import (
    ClientCatalogError,
    ClientCatalogService,
    ClientCatalogValidationError,
    ClientSyncApplyResponse,
    ClientSyncPreviewResponse,
    ClientSyncSnippetResponse,
    ClientSystemCreate,
    ClientSystemNotFoundError,
    ClientSystemRead,
    ClientSystemType,
    ClientSystemUpdate,
    ClientUnitCreate,
    ClientUnitEntry,
    ClientUnitNotFoundError,
    ClientUnitRead,
    ClientUnitUpdate,
    SyncSourceFormat,
)
from backend.app.services.default_credentials_service import DefaultCredentialsService
from backend.app.services.postgres_service import PostgresService
from backend.app.services.secret_vault import SecretVaultService

router = APIRouter(prefix="/api/clients", tags=["clients"])


def get_client_catalog_service(request: Request) -> ClientCatalogService:
    """Resolve or lazily initialize `ClientCatalogService` on FastAPI `app.state`."""
    svc = getattr(request.app.state, "client_catalog_service", None)
    if isinstance(svc, ClientCatalogService):
        return svc

    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    vault = getattr(request.app.state, "secret_vault", None)
    resolved_vault = vault if isinstance(vault, SecretVaultService) else SecretVaultService()
    defaults_svc = getattr(request.app.state, "default_credentials_service", None)
    resolved_defaults = (
        defaults_svc
        if isinstance(defaults_svc, DefaultCredentialsService)
        else DefaultCredentialsService(store=resolved_store, vault=resolved_vault)
    )
    pg_svc = getattr(request.app.state, "postgres_service", None)
    resolved_pg = (
        pg_svc
        if isinstance(pg_svc, PostgresService)
        else PostgresService(
            store=resolved_store,
            vault=resolved_vault,
            default_credentials_service=resolved_defaults,
        )
    )
    svc = ClientCatalogService(
        store=resolved_store,
        vault=resolved_vault,
        postgres_service=resolved_pg,
        default_credentials_service=resolved_defaults,
    )
    request.app.state.client_catalog_service = svc
    return svc


CatalogDep = Annotated[ClientCatalogService, Depends(get_client_catalog_service)]


class SyncConfigUpdatePayload(BaseModel):
    """Payload to locally configure or clear the management portal URL."""

    model_config = ConfigDict(extra="forbid")

    management_portal_url: str = Field(default="", max_length=1000)


class SyncPreviewRequestPayload(BaseModel):
    """Payload for dry-run sync preview from normalized JSON, portal JSON, or portal HTML."""

    model_config = ConfigDict(extra="forbid")

    raw_payload: str | dict[str, Any] | list[Any]
    source_format: SyncSourceFormat = "auto"


class SyncApplyRequestPayload(BaseModel):
    """Payload to apply client sync from either normalized `units` or original `raw_payload`."""

    model_config = ConfigDict(extra="forbid")

    units: list[ClientUnitEntry] | None = None
    raw_payload: str | dict[str, Any] | list[Any] | None = None
    source_format: SyncSourceFormat = "auto"
    import_ssh_passwords: bool = False


# =============================================================================
# Sync Endpoints (declared before `/{unit_id}` to avoid path parameter collisions)
# =============================================================================


@router.get("/sync/snippet", response_model=ClientSyncSnippetResponse)
def get_sync_snippet(service: CatalogDep) -> ClientSyncSnippetResponse:
    """Return local portal URL, console collector snippet, bookmarklet, and instructions."""
    return service.get_collector_snippet()


@router.put("/sync/config", response_model=dict[str, str])
def update_sync_config(
    payload: SyncConfigUpdatePayload,
    service: CatalogDep,
) -> dict[str, str]:
    """Save or clear the local management portal URL in `app_settings`."""
    try:
        saved = service.set_portal_url(payload.management_portal_url)
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"management_portal_url": saved}


@router.post("/sync/preview", response_model=ClientSyncPreviewResponse)
def preview_client_sync(
    payload: SyncPreviewRequestPayload,
    service: CatalogDep,
) -> ClientSyncPreviewResponse:
    """Parse supplied JSON/HTML and return a non-destructive diff preview."""
    try:
        return service.preview_sync(payload.raw_payload, source_format=payload.source_format)
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ClientCatalogError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/sync/apply", response_model=ClientSyncApplyResponse)
def apply_client_sync(
    payload: SyncApplyRequestPayload,
    service: CatalogDep,
) -> ClientSyncApplyResponse:
    """Idempotently upsert clients, systems, and linked PG/SFTP/JasperServer profiles."""
    try:
        if payload.raw_payload is not None:
            catalog, parse_warnings = service.parse_payload(
                payload.raw_payload,
                source_format=payload.source_format,
            )
            result = service.apply_sync(
                catalog.units,
                import_ssh_passwords=payload.import_ssh_passwords,
            )
            if parse_warnings:
                result.warnings = [*parse_warnings, *result.warnings]
            return result

        if payload.units is not None:
            return service.apply_sync(
                payload.units,
                import_ssh_passwords=payload.import_ssh_passwords,
            )

        raise ClientCatalogValidationError(
            "Informe 'units' ou 'raw_payload' para aplicar a sincronização."
        )
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ClientCatalogError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# =============================================================================
# Client Units CRUD
# =============================================================================


@router.get("", response_model=list[ClientUnitRead])
def list_clients(
    service: CatalogDep,
    search: str | None = Query(default=None),
    system_type: ClientSystemType | None = Query(default=None),
    environment: EnvironmentKind | None = Query(default=None),
) -> list[ClientUnitRead]:
    """List clients with optional search, system type, and environment filters."""
    return service.list_clients(
        search=search,
        system_type=system_type,
        environment=environment,
    )


@router.post("", response_model=ClientUnitRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientUnitCreate,
    service: CatalogDep,
) -> ClientUnitRead:
    """Create a new client unit manually."""
    try:
        return service.create_client(payload)
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{unit_id}", response_model=ClientUnitRead)
def get_client(unit_id: str, service: CatalogDep) -> ClientUnitRead:
    """Fetch a single client unit and its systems."""
    try:
        return service.get_client(unit_id)
    except ClientUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{unit_id}", response_model=ClientUnitRead)
def update_client(
    unit_id: str,
    payload: ClientUnitUpdate,
    service: CatalogDep,
) -> ClientUnitRead:
    """Partially update a client unit."""
    try:
        return service.update_client(unit_id, payload)
    except ClientUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{unit_id}", response_model=dict[str, str])
def delete_client(unit_id: str, service: CatalogDep) -> dict[str, str]:
    """Delete a client unit and its systems."""
    try:
        service.delete_client(unit_id)
    except ClientUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "ok", "deleted": unit_id}


# =============================================================================
# Client Systems CRUD
# =============================================================================


@router.post("/{unit_id}/systems", response_model=ClientSystemRead, status_code=status.HTTP_201_CREATED)
def create_or_upsert_client_system(
    unit_id: str,
    payload: ClientSystemCreate,
    service: CatalogDep,
) -> ClientSystemRead:
    """Add or upsert a system under a client unit."""
    try:
        return service.upsert_system(unit_id, payload)
    except ClientUnitNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{unit_id}/systems/{system_id}", response_model=ClientSystemRead)
def update_client_system(
    unit_id: str,
    system_id: str,
    payload: ClientSystemUpdate,
    service: CatalogDep,
) -> ClientSystemRead:
    """Partially update a client system."""
    try:
        return service.update_system(unit_id, system_id, payload)
    except (ClientUnitNotFoundError, ClientSystemNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ClientCatalogValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{unit_id}/systems/{system_id}", response_model=dict[str, str])
def delete_client_system(
    unit_id: str,
    system_id: str,
    service: CatalogDep,
) -> dict[str, str]:
    """Delete a system from a client unit."""
    try:
        service.delete_system(unit_id, system_id)
    except (ClientUnitNotFoundError, ClientSystemNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "ok", "deleted": system_id}
