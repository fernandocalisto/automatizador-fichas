# -*- coding: utf-8 -*-
"""FastAPI router for managing built-in and custom JasperReports `.jasper` subreports."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from backend.app.db.schemas import SubreportInfo
from backend.app.services.subreport_service import (
    SubreportNotFoundError,
    SubreportService,
    SubreportValidationError,
)

router = APIRouter(prefix="/api/subreports", tags=["subreports"])


def get_subreport_service(request: Request) -> SubreportService:
    """Resolve SubreportService attached to FastAPI app state."""
    svc = getattr(request.app.state, "subreport_service", None)
    if isinstance(svc, SubreportService):
        return svc
    return SubreportService()


SubreportSvcDep = Annotated[SubreportService, Depends(get_subreport_service)]


@router.get("", response_model=list[SubreportInfo])
def list_subreports(service: SubreportSvcDep) -> list[SubreportInfo]:
    """List all effective `.jasper` subreports (built-in standards, custom overrides, and extras)."""
    return service.list_subreports()


@router.post("", response_model=SubreportInfo, status_code=status.HTTP_201_CREATED)
async def upload_subreport(
    service: SubreportSvcDep,
    file: UploadFile = File(...),
    filename: str | None = Form(default=None),
) -> SubreportInfo:
    """Upload a custom `.jasper` file (overriding a built-in subreport or adding a new unit subreport)."""
    target_name = filename.strip() if filename and filename.strip() else (file.filename or "")
    content = await file.read()
    try:
        return service.save_custom_subreport(target_name, content)
    except SubreportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{filename}")
def delete_subreport(filename: str, service: SubreportSvcDep) -> dict[str, Any]:
    """Delete a custom `.jasper` subreport (resetting back to built-in if it was overriding one)."""
    try:
        return service.delete_custom_subreport(filename)
    except SubreportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SubreportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/materialize")
def materialize_subreports_runtime_dir(service: SubreportSvcDep) -> dict[str, Any]:
    """Materialize merged runtime subreport directory and return `$P{caminho_relatorio}` with trailing slash."""
    runtime_dir = service.materialize_runtime_dir()
    caminho_relatorio = service.get_caminho_relatorio()
    files = sorted(p.name for p in runtime_dir.glob("*.jasper"))
    return {
        "runtime_dir": str(runtime_dir),
        "caminho_relatorio": caminho_relatorio,
        "files": files,
        "count": len(files),
    }
