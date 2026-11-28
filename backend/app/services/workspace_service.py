# -*- coding: utf-8 -*-
"""Workspace & lifecycle service for clinical form projects, revisions, SQL generation, and gates."""

from __future__ import annotations

import json
import re
import shutil
import sys
import types
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal

from backend.app.config import SQL_TEMPLATES_DIR, get_data_dir
from backend.app.core import sql_insert as _core_sql_insert
from backend.app.core.json_utils import format_json, parse_and_validate_clinical_json
from backend.app.core.sql_insert import generate_insert_sql, validate_postgres_syntax
from backend.app.db.schemas import (
    ALL_GATES,
    ArtifactRevisionRead,
    ArtifactSaveResponse,
    ArtifactType,
    ChatMessageCreate,
    ChatMessageRead,
    ChatPhase,
    CreatedBy,
    EntryMode,
    GateApprovalRead,
    GateApprovalUpdate,
    GateName,
    ProjectCreate,
    ProjectKind,
    ProjectRead,
    ProjectStage,
    ProjectUpdate,
    SqlRegenerateResponse,
    SqlValidateResponse,
)
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.jrxml.scaffolder import scaffold_free_report_jrxml


class WorkspaceError(Exception):
    """Base error for project workspace operations."""


class ProjectNotFoundError(WorkspaceError):
    """Raised when a project ID does not exist in the studio store."""


class ArtifactNotFoundError(WorkspaceError):
    """Raised when a requested artifact or PDF does not exist for a project."""


class WorkspaceValidationError(WorkspaceError):
    """Raised when clinical JSON, JRXML, PDF, or SQL validation fails."""


def _load_sql_select_helpers() -> tuple[Any, Any]:
    """
    Import `generate_select_jasper` and `find_unknown_field_types` from `backend.app.core.sql_select`.
    Provides a transparent `src.*` module alias fallback if running standalone before core imports merge.
    """
    try:
        from backend.app.core.sql_select import (
            find_unknown_field_types,
            generate_select_jasper,
        )

        return generate_select_jasper, find_unknown_field_types
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "src" or exc.name.startswith("src.")):
            src_pkg = sys.modules.setdefault("src", types.ModuleType("src"))
            src_core = sys.modules.setdefault("src.core", types.ModuleType("src.core"))
            src_pkg.core = src_core  # type: ignore[attr-defined]
            sys.modules["src.core.sql_insert"] = _core_sql_insert

            src_utils = sys.modules.setdefault("src.utils", types.ModuleType("src.utils"))
            src_pkg.utils = src_utils  # type: ignore[attr-defined]
            rp_mod = types.ModuleType("src.utils.resource_path")
            rp_mod.resource_path = lambda name: SQL_TEMPLATES_DIR / str(name)  # type: ignore[attr-defined]
            sys.modules["src.utils.resource_path"] = rp_mod

            from backend.app.core.sql_select import (
                find_unknown_field_types,
                generate_select_jasper,
            )

            return generate_select_jasper, find_unknown_field_types
        raise


def slugify_project_name(raw: str | None) -> str:
    """Normalize arbitrary clinical form name into a clean snake_case filesystem/JRXML slug."""
    if not raw or not raw.strip():
        return "ficha_clinica"
    nfkd = unicodedata.normalize("NFKD", raw.strip())
    ascii_text = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        return "ficha_clinica"
    if slug[0].isdigit():
        slug = f"ficha_{slug}"
    return slug[:80]


def validate_jrxml_content(raw_xml: str) -> str:
    """Validate that JRXML text is non-empty, well-formed XML rooted at `<jasperReport>`."""
    cleaned = raw_xml.strip() if isinstance(raw_xml, str) else ""
    if not cleaned:
        raise WorkspaceValidationError("JRXML content cannot be empty.")

    # Optional future hook if `backend.app.jrxml` exposes an enhanced validator after merge
    try:
        jrxml_pkg = __import__("backend.app.jrxml", fromlist=["validate_jrxml"])
        custom_validator = getattr(jrxml_pkg, "validate_jrxml", None)
        if callable(custom_validator):
            res = custom_validator(cleaned)
            if isinstance(res, tuple) and len(res) == 2 and not res[0]:
                raise WorkspaceValidationError(str(res[1]))
    except ImportError:
        pass

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as exc:
        raise WorkspaceValidationError(f"Invalid JRXML/XML syntax: {exc}") from exc

    local_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if local_tag != "jasperReport":
        raise WorkspaceValidationError(
            f"Invalid JRXML root element '<{local_tag}>': expected '<jasperReport>'."
        )
    return cleaned


class WorkspaceService:
    """Coordinates project workspace directories on disk with SQLite revisions, gates, and chat."""

    def __init__(
        self,
        store: SQLiteStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or SQLiteStore()
        self._explicit_data_dir = data_dir.resolve() if data_dir is not None else None

    @property
    def data_dir(self) -> Path:
        if self._explicit_data_dir is not None:
            self._explicit_data_dir.mkdir(parents=True, exist_ok=True)
            return self._explicit_data_dir
        return get_data_dir()

    def _ensure_workspace_subdirs(self, workspace_dir: Path) -> dict[str, Path]:
        uploads = workspace_dir / "uploads"
        artifacts = workspace_dir / "artifacts"
        exports = workspace_dir / "exports"
        for sub in (uploads, artifacts, exports):
            sub.mkdir(parents=True, exist_ok=True)
        return {"uploads": uploads, "artifacts": artifacts, "exports": exports}

    def _artifact_disk_filename(self, slug: str, artifact_type: ArtifactType) -> str:
        mapping: dict[ArtifactType, str] = {
            "json": "ficha.json",
            "sql_insert": "insert.sql",
            "sql_select": "select_jasper.sql",
            "jrxml": f"{slug}.jrxml",
        }
        return mapping[artifact_type]

    def _write_artifact_file(
        self,
        workspace_dir: Path,
        slug: str,
        artifact_type: ArtifactType,
        content: str,
    ) -> Path:
        subdirs = self._ensure_workspace_subdirs(workspace_dir)
        target = subdirs["artifacts"] / self._artifact_disk_filename(slug, artifact_type)
        target.write_text(
            content if content.endswith("\n") else content + "\n",
            encoding="utf-8",
        )
        return target

    def _require_project_row(self, project_id: str) -> dict[str, Any]:
        row = self.store.get_project(project_id)
        if row is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")
        return row

    def _enrich_project(self, row: dict[str, Any]) -> ProjectRead:
        project_id = str(row["id"])
        ws_dir = Path(str(row["workspace_dir"]))
        pdf_path = ws_dir / "uploads" / "source.pdf"
        gates = [GateApprovalRead(**g) for g in self.store.list_gates(project_id)]
        latest_artifacts = self.store.get_latest_artifact_versions_map(project_id)
        return ProjectRead(
            id=project_id,
            slug=row["slug"],
            name=row["name"],
            description=row.get("description") or "",
            project_kind=row.get("project_kind") or "clinical_form",
            current_stage=row["current_stage"],
            entry_mode=row["entry_mode"],
            preferred_harness=row.get("preferred_harness") or "agy",
            template_db_id=row.get("template_db_id"),
            default_db_profile_id=row.get("default_db_profile_id"),
            client_system_id=row.get("client_system_id"),
            source_origin=row.get("source_origin") if isinstance(row.get("source_origin"), dict) else {},
            workspace_dir=str(ws_dir),
            has_pdf=pdf_path.is_file(),
            gates=gates,
            latest_artifacts=latest_artifacts,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # Project Lifecycle & 3 Entry Modes
    # -------------------------------------------------------------------------

    def create_project(
        self,
        payload: ProjectCreate,
        *,
        pdf_bytes: bytes | None = None,
    ) -> ProjectRead:
        """
        Create a new project workspace in one of 3 entry modes:
        1. `pdf` (empty landing or immediate `source.pdf` -> `extraction`)
        2. `json` (`ficha.json` validated + `insert.sql` & `select_jasper.sql` auto-generated -> `form_builder`)
        3. `jrxml` (`<slug>.jrxml` validated -> `jrxml_design`)
        """
        project_id = str(uuid.uuid4())
        slug = slugify_project_name(payload.slug or payload.name)

        entry_mode: EntryMode = payload.entry_mode
        if payload.initial_json is not None and payload.entry_mode == "pdf":
            entry_mode = "json"
        elif payload.initial_jrxml is not None and payload.entry_mode == "pdf":
            entry_mode = "jrxml"

        if payload.project_kind is not None:
            project_kind: ProjectKind = payload.project_kind
        elif entry_mode in ("blank_report", "sftp_import", "jasperserver_import"):
            project_kind = "free_report"
        else:
            project_kind = "clinical_form"

        # Pre-validate initial artifacts BEFORE creating DB rows or leaving orphan folders
        normalized_json_str: str | None = None
        parsed_json_dict: dict[str, Any] | None = None
        generated_insert: str | None = None
        generated_select: str | None = None
        validated_jrxml_str: str | None = None

        if pdf_bytes is not None:
            self._validate_pdf_bytes(pdf_bytes)

        if payload.initial_json is not None:
            raw_json = (
                json.dumps(payload.initial_json, ensure_ascii=False)
                if isinstance(payload.initial_json, dict)
                else str(payload.initial_json)
            )
            try:
                parsed_json_dict = parse_and_validate_clinical_json(
                    raw_json,
                    require_clinical_structure=True,
                    apply_uppercase=True,
                )
                normalized_json_str = format_json(parsed_json_dict)
                generated_insert, generated_select = self._build_sql_pair(parsed_json_dict)
            except (ValueError, FileNotFoundError) as exc:
                raise WorkspaceValidationError(str(exc)) from exc

        if payload.initial_jrxml is not None:
            validated_jrxml_str = validate_jrxml_content(payload.initial_jrxml)

        if payload.current_stage is not None:
            initial_stage: ProjectStage = payload.current_stage
        elif entry_mode == "json":
            initial_stage = "form_builder"
        elif entry_mode in ("jrxml", "blank_report", "sftp_import", "jasperserver_import"):
            initial_stage = "jrxml_design"
        elif project_kind == "free_report":
            initial_stage = "jrxml_design"
        elif pdf_bytes is not None:
            initial_stage = "extraction"
        else:
            initial_stage = "landing"

        workspace_dir = self.data_dir / f"{slug}_{project_id[:8]}"
        subdirs = self._ensure_workspace_subdirs(workspace_dir)

        try:
            row = self.store.create_project(
                project_id=project_id,
                slug=slug,
                name=payload.name.strip(),
                description=payload.description.strip(),
                project_kind=project_kind,
                current_stage=initial_stage,
                entry_mode=entry_mode,
                preferred_harness=payload.preferred_harness or "agy",
                template_db_id=payload.template_db_id,
                default_db_profile_id=payload.default_db_profile_id,
                client_system_id=payload.client_system_id,
                source_origin=payload.source_origin,
                workspace_dir=workspace_dir,
            )

            if pdf_bytes is not None:
                (subdirs["uploads"] / "source.pdf").write_bytes(pdf_bytes)

            if normalized_json_str is not None and generated_insert is not None and generated_select is not None:
                self._write_artifact_file(workspace_dir, slug, "json", normalized_json_str)
                self.store.add_artifact_revision(
                    project_id,
                    "json",
                    normalized_json_str,
                    summary="Initial clinical JSON import",
                    created_by="user",
                )
                self._write_artifact_file(workspace_dir, slug, "sql_insert", generated_insert)
                self.store.add_artifact_revision(
                    project_id,
                    "sql_insert",
                    generated_insert,
                    summary="Auto-generated INSERT SQL from initial JSON",
                    created_by="system",
                )
                self._write_artifact_file(workspace_dir, slug, "sql_select", generated_select)
                self.store.add_artifact_revision(
                    project_id,
                    "sql_select",
                    generated_select,
                    summary="Auto-generated Jasper SELECT SQL from initial JSON",
                    created_by="system",
                )

            if validated_jrxml_str is not None:
                self._write_artifact_file(workspace_dir, slug, "jrxml", validated_jrxml_str)
                self.store.add_artifact_revision(
                    project_id,
                    "jrxml",
                    validated_jrxml_str,
                    summary="Initial JRXML import",
                    created_by="user",
                )
            elif entry_mode == "blank_report":
                starter_jrxml = scaffold_free_report_jrxml(
                    title=payload.name.strip(),
                    report_name=slug,
                )
                self._write_artifact_file(workspace_dir, slug, "jrxml", starter_jrxml)
                self.store.add_artifact_revision(
                    project_id,
                    "jrxml",
                    starter_jrxml,
                    summary="Starter free-report .jrxml",
                    created_by="system",
                )

            refreshed = self._require_project_row(project_id)
            return self._enrich_project(refreshed)
        except Exception:
            self.store.delete_project(project_id)
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise

    def list_projects(self) -> list[ProjectRead]:
        """Return all studio projects enriched with gate status and artifact version summaries."""
        return [self._enrich_project(row) for row in self.store.list_projects()]

    def get_project(self, project_id: str) -> ProjectRead:
        """Return a single enriched project or raise ProjectNotFoundError."""
        row = self._require_project_row(project_id)
        return self._enrich_project(row)

    def update_project(self, project_id: str, payload: ProjectUpdate) -> ProjectRead:
        """Apply partial updates to a project's metadata or stage."""
        self._require_project_row(project_id)
        fields = payload.model_dump(exclude_unset=True)
        if "name" in fields and fields["name"] is not None:
            fields["name"] = fields["name"].strip()
        updated = self.store.update_project(project_id, **fields)
        if updated is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")
        return self._enrich_project(updated)

    def delete_project(self, project_id: str, *, delete_files: bool = True) -> None:
        """Delete a project from SQLite and remove its workspace directory on disk."""
        row = self._require_project_row(project_id)
        ws_dir = Path(str(row["workspace_dir"]))
        self.store.delete_project(project_id)
        if delete_files and ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # PDF Upload & Streaming Support
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_pdf_bytes(pdf_bytes: bytes) -> None:
        if not pdf_bytes:
            raise WorkspaceValidationError("Uploaded PDF file is empty.")
        if not pdf_bytes.lstrip().startswith(b"%PDF"):
            raise WorkspaceValidationError("Invalid PDF file: missing '%PDF' header.")

    def save_uploaded_pdf(self, project_id: str, pdf_bytes: bytes) -> ProjectRead:
        """Validate and persist `uploads/source.pdf`, advancing stage from `landing` to `extraction`."""
        row = self._require_project_row(project_id)
        self._validate_pdf_bytes(pdf_bytes)

        ws_dir = Path(str(row["workspace_dir"]))
        subdirs = self._ensure_workspace_subdirs(ws_dir)
        pdf_target = subdirs["uploads"] / "source.pdf"
        pdf_target.write_bytes(pdf_bytes)

        next_stage = "extraction" if row["current_stage"] == "landing" else row["current_stage"]
        updated = self.store.update_project(project_id, current_stage=next_stage)
        assert updated is not None
        return self._enrich_project(updated)

    def get_pdf_path(self, project_id: str) -> Path:
        """Return path to `uploads/source.pdf` for streaming, or raise ArtifactNotFoundError."""
        row = self._require_project_row(project_id)
        pdf_path = Path(str(row["workspace_dir"])) / "uploads" / "source.pdf"
        if not pdf_path.is_file():
            raise ArtifactNotFoundError(f"Project '{project_id}' does not have an uploaded source.pdf.")
        return pdf_path

    # -------------------------------------------------------------------------
    # Artifacts, Revisions & SQL Auto-Generation
    # -------------------------------------------------------------------------

    def _build_sql_pair(
        self,
        parsed_json: dict[str, Any],
        *,
        insert_options: dict[str, Any] | None = None,
        select_options: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        generate_select_jasper, _ = _load_sql_select_helpers()
        model_sql_path = SQL_TEMPLATES_DIR / "select_padrao_ouro_jasper.sql"
        sql_ins = generate_insert_sql(parsed_json, options=insert_options)
        sql_sel = generate_select_jasper(
            parsed_json,
            model_sql=model_sql_path,
            options=select_options,
        )
        return sql_ins, sql_sel

    def get_latest_artifact(
        self,
        project_id: str,
        artifact_type: ArtifactType,
    ) -> ArtifactRevisionRead:
        """Fetch latest revision for `artifact_type` or raise ArtifactNotFoundError."""
        self._require_project_row(project_id)
        rev = self.store.get_latest_artifact(project_id, artifact_type)
        if rev is None:
            raise ArtifactNotFoundError(
                f"No '{artifact_type}' artifact exists yet for project '{project_id}'."
            )
        return ArtifactRevisionRead(**rev)

    def list_revisions(
        self,
        project_id: str,
        artifact_type: ArtifactType | None = None,
    ) -> list[ArtifactRevisionRead]:
        """List immutable revision history for a project (optionally filtered by artifact_type)."""
        self._require_project_row(project_id)
        rows = self.store.list_artifact_revisions(project_id, artifact_type=artifact_type)
        return [ArtifactRevisionRead(**r) for r in rows]

    def save_artifact(
        self,
        project_id: str,
        artifact_type: ArtifactType,
        content: str,
        *,
        summary: str = "",
        created_by: CreatedBy = "user",
        auto_regenerate_sql: bool = True,
        apply_uppercase: bool = True,
        sql_options: dict[str, Any] | None = None,
    ) -> ArtifactSaveResponse:
        """
        Save a new revision of `json`, `sql_insert`, `sql_select`, or `jrxml`, writing the file to disk.
        When `artifact_type == 'json'` and `auto_regenerate_sql` is True, automatically regenerates
        and versions both `sql_insert` and `sql_select`.
        """
        row = self._require_project_row(project_id)
        ws_dir = Path(str(row["workspace_dir"]))
        slug = str(row["slug"])

        generated_ins_rev: ArtifactRevisionRead | None = None
        generated_sel_rev: ArtifactRevisionRead | None = None

        if artifact_type == "json":
            try:
                parsed = parse_and_validate_clinical_json(
                    content,
                    require_clinical_structure=True,
                    apply_uppercase=apply_uppercase,
                )
            except ValueError as exc:
                raise WorkspaceValidationError(str(exc)) from exc

            final_content = format_json(parsed)
            sql_pair: tuple[str, str] | None = None
            if auto_regenerate_sql:
                try:
                    ins_opts = (sql_options or {}).get("insert_options") if sql_options else None
                    sel_opts = (sql_options or {}).get("select_options") if sql_options else None
                    sql_pair = self._build_sql_pair(
                        parsed,
                        insert_options=ins_opts,
                        select_options=sel_opts,
                    )
                except (ValueError, FileNotFoundError) as exc:
                    raise WorkspaceValidationError(str(exc)) from exc

            self._write_artifact_file(ws_dir, slug, "json", final_content)
            saved_json = self.store.add_artifact_revision(
                project_id,
                "json",
                final_content,
                summary=summary or "Updated clinical JSON",
                created_by=created_by,
            )

            if sql_pair is not None:
                sql_ins, sql_sel = sql_pair
                auto_summary = f"Auto-generated from JSON v{saved_json['version_num']}"
                self._write_artifact_file(ws_dir, slug, "sql_insert", sql_ins)
                ins_row = self.store.add_artifact_revision(
                    project_id,
                    "sql_insert",
                    sql_ins,
                    summary=auto_summary,
                    created_by="system",
                )
                self._write_artifact_file(ws_dir, slug, "sql_select", sql_sel)
                sel_row = self.store.add_artifact_revision(
                    project_id,
                    "sql_select",
                    sql_sel,
                    summary=auto_summary,
                    created_by="system",
                )
                generated_ins_rev = ArtifactRevisionRead(**ins_row)
                generated_sel_rev = ArtifactRevisionRead(**sel_row)

            return ArtifactSaveResponse(
                artifact=ArtifactRevisionRead(**saved_json),
                generated_sql_insert=generated_ins_rev,
                generated_sql_select=generated_sel_rev,
            )

        if artifact_type == "jrxml":
            final_content = validate_jrxml_content(content)
        else:
            if not isinstance(content, str) or not content.strip():
                raise WorkspaceValidationError(f"Artifact '{artifact_type}' content cannot be empty.")
            final_content = content

        self._write_artifact_file(ws_dir, slug, artifact_type, final_content)
        saved_row = self.store.add_artifact_revision(
            project_id,
            artifact_type,
            final_content,
            summary=summary or f"Updated {artifact_type}",
            created_by=created_by,
        )
        if artifact_type == "jrxml":
            latest_preview_path = ws_dir / "exports" / "latest_preview.json"
            if latest_preview_path.is_file():
                try:
                    meta = json.loads(latest_preview_path.read_text(encoding="utf-8"))
                    if isinstance(meta, dict):
                        meta["stale"] = True
                        meta["latest_jrxml_version"] = saved_row["version_num"]
                        latest_preview_path.write_text(
                            json.dumps(meta, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                except Exception:
                    pass
        return ArtifactSaveResponse(artifact=ArtifactRevisionRead(**saved_row))

    def restore_revision(
        self,
        project_id: str,
        artifact_type: ArtifactType,
        *,
        version_num: int | None = None,
        revision_id: int | None = None,
        created_by: CreatedBy = "user",
        auto_regenerate_sql: bool = True,
    ) -> ArtifactSaveResponse:
        """Restore a historical artifact revision as a new head revision and sync disk files."""
        self._require_project_row(project_id)
        if version_num is None and revision_id is None:
            raise WorkspaceValidationError(
                "Either 'version_num' or 'revision_id' must be provided to restore a revision."
            )
        target = self.store.get_artifact_revision(
            project_id,
            artifact_type,
            version_num=version_num,
            revision_id=revision_id,
        )
        if target is None:
            raise ArtifactNotFoundError(
                f"Revision not found for project '{project_id}' ({artifact_type})."
            )
        return self.save_artifact(
            project_id,
            artifact_type,
            str(target["content"]),
            summary=f"Restored from {artifact_type} v{target['version_num']}",
            created_by=created_by,
            auto_regenerate_sql=auto_regenerate_sql,
        )

    def regenerate_sql_from_json(
        self,
        project_id: str,
        *,
        insert_options: dict[str, Any] | None = None,
        select_options: dict[str, Any] | None = None,
        created_by: CreatedBy = "user",
        summary: str = "Regenerated SQL scripts from clinical JSON",
    ) -> SqlRegenerateResponse:
        """Explicitly regenerate both `sql_insert` and `sql_select` from the latest `json` revision."""
        row = self._require_project_row(project_id)
        latest_json = self.store.get_latest_artifact(project_id, "json")
        if latest_json is None:
            raise ArtifactNotFoundError(
                f"Cannot regenerate SQL: project '{project_id}' has no 'json' artifact yet."
            )

        try:
            parsed = parse_and_validate_clinical_json(
                str(latest_json["content"]),
                require_clinical_structure=True,
                apply_uppercase=True,
            )
            sql_ins, sql_sel = self._build_sql_pair(
                parsed,
                insert_options=insert_options,
                select_options=select_options,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise WorkspaceValidationError(str(exc)) from exc

        ws_dir = Path(str(row["workspace_dir"]))
        slug = str(row["slug"])

        self._write_artifact_file(ws_dir, slug, "sql_insert", sql_ins)
        ins_rev = self.store.add_artifact_revision(
            project_id,
            "sql_insert",
            sql_ins,
            summary=summary,
            created_by=created_by,
        )

        self._write_artifact_file(ws_dir, slug, "sql_select", sql_sel)
        sel_rev = self.store.add_artifact_revision(
            project_id,
            "sql_select",
            sql_sel,
            summary=summary,
            created_by=created_by,
        )

        return SqlRegenerateResponse(
            sql_insert=ArtifactRevisionRead(**ins_rev),
            sql_select=ArtifactRevisionRead(**sel_rev),
        )

    def validate_sql(
        self,
        project_id: str,
        *,
        sql: str | None = None,
        artifact_type: Literal["sql_insert", "sql_select"] | None = None,
    ) -> SqlValidateResponse:
        """Validate PostgreSQL syntax for inline SQL or a stored SQL artifact, plus JSON field types."""
        self._require_project_row(project_id)
        resolved_type = artifact_type

        if sql is not None:
            sql_to_check = sql
        else:
            resolved_type = artifact_type or "sql_insert"
            latest = self.store.get_latest_artifact(project_id, resolved_type)
            if latest is None:
                raise ArtifactNotFoundError(
                    f"Project '{project_id}' does not have a '{resolved_type}' artifact to validate."
                )
            sql_to_check = str(latest["content"])

        valid, message = validate_postgres_syntax(sql_to_check)

        unknown_types: list[str] = []
        latest_json = self.store.get_latest_artifact(project_id, "json")
        if latest_json is not None:
            try:
                _, find_unknown_field_types = _load_sql_select_helpers()
                parsed = json.loads(str(latest_json["content"]))
                unknown_types = find_unknown_field_types(parsed)
            except Exception:
                unknown_types = []

        return SqlValidateResponse(
            valid=valid,
            message=message,
            artifact_type=resolved_type,
            unknown_field_types=unknown_types,
        )

    # -------------------------------------------------------------------------
    # Approval Gates & Chat
    # -------------------------------------------------------------------------

    def list_gates(self, project_id: str) -> list[GateApprovalRead]:
        """List all 3 human-in-the-loop approval gates (`gate1_json`, `gate2_sql_insert`, `gate3_jrxml`)."""
        self._require_project_row(project_id)
        return [GateApprovalRead(**g) for g in self.store.list_gates(project_id)]

    def update_gate(
        self,
        project_id: str,
        gate_name: GateName,
        payload: GateApprovalUpdate,
    ) -> GateApprovalRead:
        """Update status, approver, and notes for one of the 3 approval gates."""
        self._require_project_row(project_id)
        if gate_name not in ALL_GATES:
            raise WorkspaceValidationError(
                f"Invalid gate_name '{gate_name}'. Expected one of {ALL_GATES}."
            )
        updated = self.store.upsert_gate(
            project_id,
            gate_name,
            payload.status,
            decided_by=payload.decided_by,
            notes=payload.notes,
        )
        return GateApprovalRead(**updated)

    def list_chat_messages(
        self,
        project_id: str,
        phase: ChatPhase | None = None,
    ) -> list[ChatMessageRead]:
        """List chat messages for a project (optionally filtered by `extraction` or `jrxml` phase)."""
        self._require_project_row(project_id)
        return [ChatMessageRead(**m) for m in self.store.list_chat_messages(project_id, phase=phase)]

    def add_chat_message(
        self,
        project_id: str,
        payload: ChatMessageCreate,
    ) -> ChatMessageRead:
        """Append a chat message to the project's conversation history."""
        self._require_project_row(project_id)
        saved = self.store.add_chat_message(
            project_id,
            phase=payload.phase,
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
        )
        return ChatMessageRead(**saved)

    def update_chat_message_metadata(
        self,
        project_id: str,
        message_id: int,
        metadata: dict[str, Any],
    ) -> ChatMessageRead | None:
        """Update `metadata_json` on an existing chat message for the project."""
        self._require_project_row(project_id)
        updated = self.store.update_chat_message_metadata(project_id, message_id, metadata)
        return ChatMessageRead(**updated) if updated is not None else None

    def resolve_visual_feedback_messages(
        self,
        project_id: str,
        *,
        message_ids: list[int] | None = None,
        resolved_by_jrxml_version: int | None = None,
    ) -> list[int]:
        """Mark pending `visual_region_feedback` messages as resolved in SQLite."""
        self._require_project_row(project_id)
        return self.store.resolve_visual_feedback_messages(
            project_id,
            message_ids=message_ids,
            resolved_by_jrxml_version=resolved_by_jrxml_version,
        )
