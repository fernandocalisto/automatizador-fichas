# -*- coding: utf-8 -*-
"""Pydantic v2 schemas for Salutem Ficha Studio workspace, artifacts, gates, chat, and system APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectStage = Literal[
    "landing",
    "extraction",
    "form_builder",
    "sql_db",
    "jrxml_design",
    "completed",
]
EntryMode = Literal["pdf", "json", "jrxml"]
ArtifactType = Literal["json", "sql_insert", "sql_select", "jrxml"]
CreatedBy = Literal["user", "agent", "system"]
ChatPhase = Literal["extraction", "jrxml"]
ChatRole = Literal["user", "assistant", "tool", "system"]
GateName = Literal["gate1_json", "gate2_sql_insert", "gate3_jrxml"]
GateStatus = Literal["pending", "approved", "rejected"]
SubreportSource = Literal["builtin", "custom_override", "custom_extra"]

ALL_GATES: tuple[GateName, ...] = ("gate1_json", "gate2_sql_insert", "gate3_jrxml")
ALL_ARTIFACT_TYPES: tuple[ArtifactType, ...] = ("json", "sql_insert", "sql_select", "jrxml")


class GateApprovalUpdate(BaseModel):
    """Payload to update an approval gate decision."""

    model_config = ConfigDict(extra="forbid")

    status: GateStatus
    decided_by: str | None = "user"
    notes: str = ""


class GateApprovalRead(BaseModel):
    """Persisted approval gate state for a project."""

    model_config = ConfigDict(from_attributes=True)

    project_id: str
    gate_name: GateName
    status: GateStatus
    decided_by: str | None = None
    notes: str = ""
    updated_at: str


class ProjectCreate(BaseModel):
    """Payload for creating a new clinical form studio project."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    description: str = ""
    entry_mode: EntryMode = "pdf"
    preferred_harness: str = "agy"
    template_db_id: int | None = None
    current_stage: ProjectStage | None = None
    initial_json: str | dict[str, Any] | None = None
    initial_jrxml: str | None = None


class ProjectUpdate(BaseModel):
    """Partial update payload for project metadata and workflow stage."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    current_stage: ProjectStage | None = None
    preferred_harness: str | None = None
    template_db_id: int | None = None


class ProjectRead(BaseModel):
    """Full representation of a studio project and its workspace status."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str = ""
    current_stage: ProjectStage
    entry_mode: EntryMode
    preferred_harness: str = "agy"
    template_db_id: int | None = None
    workspace_dir: str
    has_pdf: bool = False
    gates: list[GateApprovalRead] = Field(default_factory=list)
    latest_artifacts: dict[str, int] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ArtifactSaveRequest(BaseModel):
    """Payload for saving a new artifact revision (or restoring content)."""

    model_config = ConfigDict(extra="forbid")

    content: str
    summary: str = ""
    created_by: CreatedBy = "user"
    auto_regenerate_sql: bool = True
    apply_uppercase: bool = True
    sql_options: dict[str, Any] | None = None
    restore_from_version: int | None = None
    restore_from_revision_id: int | None = None


class ArtifactRevisionRead(BaseModel):
    """Single immutable revision of a project artifact."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    artifact_type: ArtifactType
    version_num: int
    content: str
    summary: str = ""
    created_by: CreatedBy
    created_at: str


class ArtifactSaveResponse(BaseModel):
    """Response returned when saving an artifact (plus auto-generated SQL revisions if triggered)."""

    artifact: ArtifactRevisionRead
    generated_sql_insert: ArtifactRevisionRead | None = None
    generated_sql_select: ArtifactRevisionRead | None = None


class SqlRegenerateRequest(BaseModel):
    """Options for regenerating INSERT and Jasper SELECT SQL scripts from current JSON."""

    model_config = ConfigDict(extra="forbid")

    insert_options: dict[str, Any] | None = None
    select_options: dict[str, Any] | None = None
    created_by: CreatedBy = "user"
    summary: str = "Regenerated SQL scripts from clinical JSON"


class SqlRegenerateResponse(BaseModel):
    """Result of regenerating both SQL scripts from the project's latest clinical JSON."""

    sql_insert: ArtifactRevisionRead
    sql_select: ArtifactRevisionRead


class SqlValidateRequest(BaseModel):
    """Request to validate either inline PostgreSQL code or one of the project's stored SQL artifacts."""

    model_config = ConfigDict(extra="forbid")

    sql: str | None = None
    artifact_type: Literal["sql_insert", "sql_select"] | None = None


class SqlValidateResponse(BaseModel):
    """PostgreSQL syntax and clinical field-type validation result."""

    valid: bool
    message: str
    artifact_type: str | None = None
    unknown_field_types: list[str] = Field(default_factory=list)


class ChatMessageCreate(BaseModel):
    """Payload to append a chat message to a project's phase conversation."""

    model_config = ConfigDict(extra="forbid")

    phase: ChatPhase = "extraction"
    role: ChatRole = "user"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessageRead(BaseModel):
    """Stored chat message in a project's conversation log."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    phase: ChatPhase
    role: ChatRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    metadata_json: str = "{}"
    created_at: str


class SubreportInfo(BaseModel):
    """Metadata for a built-in or user-uploaded compiled Jasper subreport (.jasper)."""

    filename: str
    name: str
    source: SubreportSource
    is_builtin_standard: bool
    is_overridden: bool
    size_bytes: int
    sha256: str
    path: str
    updated_at: str


class SkillInfo(BaseModel):
    """Metadata for an embedded domain skill in SKILLS_DIR."""

    id: str
    name: str
    description: str
    path: str


class HealthResponse(BaseModel):
    """System health, paths, subreports inventory, and SQLite status."""

    status: str = "ok"
    app_name: str
    version: str
    database: dict[str, Any]
    paths: dict[str, str]
    builtin_subreports_count: int
    custom_subreports_count: int
    effective_subreports_count: int
    frontend_built: bool
