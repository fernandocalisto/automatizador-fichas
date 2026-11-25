# -*- coding: utf-8 -*-
"""FastAPI router for system health, studio settings persistence, and embedded skills discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Body, Depends, Request

from backend.app.config import (
    APP_NAME,
    APP_VERSION,
    BUILTIN_SUBREPORTS_DIR,
    FRONTEND_DIST_DIR,
    SKILLS_DIR,
    get_custom_subreports_dir,
    get_data_dir,
    get_db_path,
)
from backend.app.db.schemas import HealthResponse, SkillInfo
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.subreport_service import SubreportService

router = APIRouter(prefix="/api", tags=["system"])


def get_store(request: Request) -> SQLiteStore:
    store = getattr(request.app.state, "store", None)
    if isinstance(store, SQLiteStore):
        return store
    return SQLiteStore()


def get_subreport_service(request: Request) -> SubreportService:
    svc = getattr(request.app.state, "subreport_service", None)
    if isinstance(svc, SubreportService):
        return svc
    return SubreportService()


StoreDep = Annotated[SQLiteStore, Depends(get_store)]
SubreportSvcDep = Annotated[SubreportService, Depends(get_subreport_service)]


def _parse_skill_frontmatter(skill_md_path: Path) -> tuple[str, str]:
    """Extract `name` and `description` from a SKILL.md YAML frontmatter block."""
    raw = skill_md_path.read_text(encoding="utf-8-sig")
    fallback_name = skill_md_path.parent.name
    if not raw.startswith("---"):
        return fallback_name, ""

    parts = raw.split("---", 2)
    if len(parts) < 3:
        return fallback_name, ""

    try:
        meta = yaml.safe_load(parts[1]) or {}
        if isinstance(meta, dict):
            name = str(meta.get("name") or fallback_name).strip()
            description = str(meta.get("description") or "").strip()
            return name, description
    except yaml.YAMLError:
        pass
    return fallback_name, ""


def discover_embedded_skills(skills_root: Path | None = None) -> list[SkillInfo]:
    """List all embedded skills containing a `SKILL.md` under `SKILLS_DIR`."""
    root = skills_root or SKILLS_DIR
    if not root.is_dir():
        return []

    skills: list[SkillInfo] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        name, description = _parse_skill_frontmatter(skill_md)
        skills.append(
            SkillInfo(
                id=child.name,
                name=name,
                description=description,
                path=str(skill_md),
            )
        )
    return skills


@router.get("/health", response_model=HealthResponse)
def get_health(store: StoreDep, subreports: SubreportSvcDep) -> HealthResponse:
    """Return studio health check, paths, subreports count, and SQLite status."""
    db_health = store.check_health()
    effective = subreports.list_subreports()
    frontend_built = (FRONTEND_DIST_DIR / "index.html").is_file()

    return HealthResponse(
        status="ok",
        app_name=APP_NAME,
        version=APP_VERSION,
        database=db_health,
        paths={
            "data_dir": str(get_data_dir()),
            "db_path": str(get_db_path()),
            "builtin_subreports_dir": str(BUILTIN_SUBREPORTS_DIR),
            "custom_subreports_dir": str(get_custom_subreports_dir()),
            "skills_dir": str(SKILLS_DIR),
            "frontend_dist_dir": str(FRONTEND_DIST_DIR),
        },
        builtin_subreports_count=subreports.count_builtin_subreports(),
        custom_subreports_count=subreports.count_custom_subreports(),
        effective_subreports_count=len(effective),
        frontend_built=frontend_built,
    )


@router.get("/settings")
def get_settings(store: StoreDep) -> dict[str, Any]:
    """Retrieve all persisted application settings."""
    return store.get_all_settings()


@router.put("/settings")
def update_settings(
    store: StoreDep,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Persist or update studio settings key-value pairs."""
    return store.set_settings(payload)


@router.get("/skills", response_model=list[SkillInfo])
def list_skills() -> list[SkillInfo]:
    """List available embedded clinical extraction and JRXML layout skills."""
    return discover_embedded_skills()
