# -*- coding: utf-8 -*-
"""FastAPI router for local default credentials per connection type (`postgres`, `sftp`, `jasperserver`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.default_credentials_service import (
    CredentialKind,
    DefaultCredentialRead,
    DefaultCredentialsService,
    DefaultCredentialUpdate,
)
from backend.app.services.secret_vault import SecretVaultError, SecretVaultService

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def get_default_credentials_service(request: Request) -> DefaultCredentialsService:
    svc = getattr(request.app.state, "default_credentials_service", None)
    if isinstance(svc, DefaultCredentialsService):
        return svc
    store = getattr(request.app.state, "store", None)
    resolved_store = store if isinstance(store, SQLiteStore) else SQLiteStore()
    vault = getattr(request.app.state, "secret_vault", None)
    resolved_vault = vault if isinstance(vault, SecretVaultService) else SecretVaultService()
    svc = DefaultCredentialsService(store=resolved_store, vault=resolved_vault)
    request.app.state.default_credentials_service = svc
    return svc


DefaultCredsDep = Annotated[DefaultCredentialsService, Depends(get_default_credentials_service)]


@router.get("/defaults", response_model=dict[str, DefaultCredentialRead])
def list_default_credentials(service: DefaultCredsDep) -> dict[str, DefaultCredentialRead]:
    """Return redacted local default credentials metadata for postgres, sftp, and jasperserver."""
    try:
        return service.get_all_defaults()
    except SecretVaultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/defaults/{kind}", response_model=DefaultCredentialRead)
def get_default_credential(kind: CredentialKind, service: DefaultCredsDep) -> DefaultCredentialRead:
    """Return redacted local default credential metadata for a single connection type."""
    try:
        return service.get_default(kind)
    except SecretVaultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/defaults/{kind}", response_model=DefaultCredentialRead)
def update_default_credential(
    kind: CredentialKind,
    payload: DefaultCredentialUpdate,
    service: DefaultCredsDep,
) -> DefaultCredentialRead:
    """Save or update local default credentials in SQLite settings + SecretVault."""
    try:
        return service.update_default(kind, payload)
    except (SecretVaultError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/defaults/{kind}", response_model=DefaultCredentialRead)
def delete_default_credential(kind: CredentialKind, service: DefaultCredsDep) -> DefaultCredentialRead:
    """Clear local default credentials and erase secrets from the vault for `kind`."""
    try:
        return service.clear_default(kind)
    except SecretVaultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
