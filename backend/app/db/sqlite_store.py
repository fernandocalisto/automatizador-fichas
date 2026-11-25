# -*- coding: utf-8 -*-
"""SQLite persistence layer for Salutem Ficha Studio workspaces, revisions, gates, chat, and settings."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import get_db_path
from backend.app.db.schemas import (
    ALL_GATES,
    ArtifactType,
    ChatPhase,
    ChatRole,
    CreatedBy,
    EntryMode,
    GateName,
    GateStatus,
    ProjectStage,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    current_stage TEXT NOT NULL DEFAULT 'landing'
        CHECK (current_stage IN ('landing', 'extraction', 'form_builder', 'sql_db', 'jrxml_design', 'completed')),
    entry_mode TEXT NOT NULL DEFAULT 'pdf'
        CHECK (entry_mode IN ('pdf', 'json', 'jrxml')),
    preferred_harness TEXT NOT NULL DEFAULT 'agy',
    template_db_id INTEGER NULL,
    workspace_dir TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC);

CREATE TABLE IF NOT EXISTS artifact_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL
        CHECK (artifact_type IN ('json', 'sql_insert', 'sql_select', 'jrxml')),
    version_num INTEGER NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'user'
        CHECK (created_by IN ('user', 'agent', 'system')),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, artifact_type, version_num)
);

CREATE INDEX IF NOT EXISTS idx_artifact_revisions_lookup
    ON artifact_revisions(project_id, artifact_type, version_num DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase TEXT NOT NULL
        CHECK (phase IN ('extraction', 'jrxml')),
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_lookup
    ON chat_messages(project_id, phase, id ASC);

CREATE TABLE IF NOT EXISTS gate_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    gate_name TEXT NOT NULL
        CHECK (gate_name IN ('gate1_json', 'gate2_sql_insert', 'gate3_jrxml')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by TEXT NULL,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, gate_name)
);

CREATE INDEX IF NOT EXISTS idx_gate_approvals_project
    ON gate_approvals(project_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    """Thread-safe, Windows-friendly SQLite store with WAL mode and foreign keys enabled."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._explicit_db_path = Path(db_path).resolve() if db_path is not None else None
        self._initialized_paths: set[Path] = set()

    @property
    def db_path(self) -> Path:
        """Resolve active SQLite database path dynamically (honoring env overrides)."""
        if self._explicit_db_path is not None:
            self._explicit_db_path.parent.mkdir(parents=True, exist_ok=True)
            return self._explicit_db_path
        return get_db_path()

    def _open_raw_connection(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def init_db(self) -> None:
        """Initialize database tables and indexes idempotently."""
        target = self.db_path
        conn = self._open_raw_connection(target)
        try:
            with conn:
                conn.executescript(SCHEMA_SQL)
            self._initialized_paths.add(target)
        finally:
            conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a transactional SQLite connection and always close file handles on exit."""
        target = self.db_path
        if target not in self._initialized_paths or not target.exists():
            self.init_db()

        conn = self._open_raw_connection(target)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def check_health(self) -> dict[str, Any]:
        """Verify SQLite connectivity, WAL mode, and row counts."""
        with self.connection() as conn:
            journal_mode = str(conn.execute("PRAGMA journal_mode;").fetchone()[0])
            foreign_keys = int(conn.execute("PRAGMA foreign_keys;").fetchone()[0])
            projects_count = int(conn.execute("SELECT COUNT(*) FROM projects;").fetchone()[0])
        return {
            "status": "ok",
            "path": str(self.db_path),
            "journal_mode": journal_mode,
            "foreign_keys": bool(foreign_keys),
            "projects_count": projects_count,
        }

    # -------------------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------------------

    def create_project(
        self,
        *,
        project_id: str,
        slug: str,
        name: str,
        workspace_dir: str | Path,
        description: str = "",
        current_stage: ProjectStage = "landing",
        entry_mode: EntryMode = "pdf",
        preferred_harness: str = "agy",
        template_db_id: int | None = None,
    ) -> dict[str, Any]:
        """Insert a new project row and seed its 3 approval gates in 'pending' status."""
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, slug, name, description, current_stage, entry_mode,
                    preferred_harness, template_db_id, workspace_dir, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    slug,
                    name,
                    description,
                    current_stage,
                    entry_mode,
                    preferred_harness,
                    template_db_id,
                    str(workspace_dir),
                    now,
                    now,
                ),
            )
            for gate_name in ALL_GATES:
                conn.execute(
                    """
                    INSERT INTO gate_approvals (
                        project_id, gate_name, status, decided_by, notes, updated_at
                    ) VALUES (?, ?, 'pending', NULL, '', ?)
                    """,
                    (project_id, gate_name, now),
                )
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Fetch a single project row by ID."""
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_projects(self) -> list[dict[str, Any]]:
        """Return all projects ordered by most recently updated first."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_project(self, project_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update allowed mutable columns on a project and refresh updated_at."""
        allowed = {
            "slug",
            "name",
            "description",
            "current_stage",
            "entry_mode",
            "preferred_harness",
            "template_db_id",
            "workspace_dir",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        with self.connection() as conn:
            existing = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if existing is None:
                return None

            if updates:
                updates["updated_at"] = utc_now_iso()
                assignments = ", ".join(f"{col} = ?" for col in updates)
                params = [*updates.values(), project_id]
                conn.execute(f"UPDATE projects SET {assignments} WHERE id = ?", params)

            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row is not None else None

    def delete_project(self, project_id: str) -> bool:
        """Delete project and cascade-remove its revisions, gates, and chat messages."""
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Artifact Revisions
    # -------------------------------------------------------------------------

    def add_artifact_revision(
        self,
        project_id: str,
        artifact_type: ArtifactType,
        content: str,
        *,
        summary: str = "",
        created_by: CreatedBy = "user",
    ) -> dict[str, Any]:
        """Append a new sequential revision for (project_id, artifact_type) and touch project."""
        now = utc_now_iso()
        with self.connection() as conn:
            next_ver_row = conn.execute(
                """
                SELECT COALESCE(MAX(version_num), 0) + 1 AS next_ver
                FROM artifact_revisions
                WHERE project_id = ? AND artifact_type = ?
                """,
                (project_id, artifact_type),
            ).fetchone()
            version_num = int(next_ver_row["next_ver"])

            cursor = conn.execute(
                """
                INSERT INTO artifact_revisions (
                    project_id, artifact_type, version_num, content, summary, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, artifact_type, version_num, content, summary, created_by, now),
            )
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            row = conn.execute(
                "SELECT * FROM artifact_revisions WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row)

    def get_latest_artifact(
        self,
        project_id: str,
        artifact_type: ArtifactType,
    ) -> dict[str, Any] | None:
        """Return the highest version_num revision for (project_id, artifact_type)."""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM artifact_revisions
                WHERE project_id = ? AND artifact_type = ?
                ORDER BY version_num DESC
                LIMIT 1
                """,
                (project_id, artifact_type),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_artifact_revision(
        self,
        project_id: str,
        artifact_type: ArtifactType | None = None,
        *,
        version_num: int | None = None,
        revision_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a specific artifact revision either by revision_id or by (artifact_type, version_num)."""
        with self.connection() as conn:
            if revision_id is not None:
                if artifact_type is not None:
                    row = conn.execute(
                        """
                        SELECT * FROM artifact_revisions
                        WHERE id = ? AND project_id = ? AND artifact_type = ?
                        """,
                        (revision_id, project_id, artifact_type),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM artifact_revisions WHERE id = ? AND project_id = ?",
                        (revision_id, project_id),
                    ).fetchone()
            elif artifact_type is not None and version_num is not None:
                row = conn.execute(
                    """
                    SELECT * FROM artifact_revisions
                    WHERE project_id = ? AND artifact_type = ? AND version_num = ?
                    """,
                    (project_id, artifact_type, version_num),
                ).fetchone()
            else:
                return None
        return dict(row) if row is not None else None

    def list_artifact_revisions(
        self,
        project_id: str,
        artifact_type: ArtifactType | None = None,
    ) -> list[dict[str, Any]]:
        """List artifact revisions for a project (newest first), optionally filtered by type."""
        with self.connection() as conn:
            if artifact_type is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM artifact_revisions
                    WHERE project_id = ? AND artifact_type = ?
                    ORDER BY version_num DESC, id DESC
                    """,
                    (project_id, artifact_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM artifact_revisions
                    WHERE project_id = ?
                    ORDER BY id DESC
                    """,
                    (project_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_artifact_versions_map(self, project_id: str) -> dict[str, int]:
        """Return mapping of artifact_type -> max(version_num) for a project."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT artifact_type, MAX(version_num) AS max_ver
                FROM artifact_revisions
                WHERE project_id = ?
                GROUP BY artifact_type
                """,
                (project_id,),
            ).fetchall()
        return {str(r["artifact_type"]): int(r["max_ver"]) for r in rows}

    # -------------------------------------------------------------------------
    # Approval Gates
    # -------------------------------------------------------------------------

    def list_gates(self, project_id: str) -> list[dict[str, Any]]:
        """Return all 3 approval gates for a project in canonical gate order."""
        order_map = {name: idx for idx, name in enumerate(ALL_GATES)}
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM gate_approvals WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        items = [dict(r) for r in rows]
        items.sort(key=lambda r: order_map.get(r["gate_name"], 99))
        return items

    def upsert_gate(
        self,
        project_id: str,
        gate_name: GateName,
        status: GateStatus,
        *,
        decided_by: str | None = "user",
        notes: str = "",
    ) -> dict[str, Any]:
        """Insert or update one of the 3 approval gates for a project."""
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO gate_approvals (
                    project_id, gate_name, status, decided_by, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, gate_name) DO UPDATE SET
                    status = excluded.status,
                    decided_by = excluded.decided_by,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (project_id, gate_name, status, decided_by, notes, now),
            )
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            row = conn.execute(
                "SELECT * FROM gate_approvals WHERE project_id = ? AND gate_name = ?",
                (project_id, gate_name),
            ).fetchone()
        return dict(row)

    # -------------------------------------------------------------------------
    # Chat Messages
    # -------------------------------------------------------------------------

    def add_chat_message(
        self,
        project_id: str,
        phase: ChatPhase,
        role: ChatRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a chat message to a project's phase log."""
        now = utc_now_iso()
        metadata_dict = metadata or {}
        metadata_json = json.dumps(metadata_dict, ensure_ascii=False)
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_messages (
                    project_id, phase, role, content, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, phase, role, content, metadata_json, now),
            )
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._deserialize_chat_row(row)

    def list_chat_messages(
        self,
        project_id: str,
        phase: ChatPhase | None = None,
    ) -> list[dict[str, Any]]:
        """List chat messages chronologically for a project (optionally filtered by phase)."""
        with self.connection() as conn:
            if phase is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE project_id = ? AND phase = ?
                    ORDER BY id ASC
                    """,
                    (project_id, phase),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE project_id = ?
                    ORDER BY id ASC
                    """,
                    (project_id,),
                ).fetchall()
        return [self._deserialize_chat_row(r) for r in rows]

    @staticmethod
    def _deserialize_chat_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        raw_meta = data.get("metadata_json") or "{}"
        try:
            parsed_meta = json.loads(raw_meta)
            data["metadata"] = parsed_meta if isinstance(parsed_meta, dict) else {}
        except (TypeError, ValueError):
            data["metadata"] = {}
        return data

    # -------------------------------------------------------------------------
    # App Settings
    # -------------------------------------------------------------------------

    def get_all_settings(self) -> dict[str, Any]:
        """Return all persisted application settings decoded from JSON."""
        with self.connection() as conn:
            rows = conn.execute("SELECT key, value_json FROM app_settings ORDER BY key ASC").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[str(row["key"])] = json.loads(row["value_json"])
            except (TypeError, ValueError):
                result[str(row["key"])] = row["value_json"]
        return result

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a single setting value or return default if unset."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value_json"])
        except (TypeError, ValueError):
            return row["value_json"]

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        """Upsert multiple key-value settings atomically (removing keys whose value is None if desired)."""
        now = utc_now_iso()
        with self.connection() as conn:
            for key, val in values.items():
                encoded = json.dumps(val, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), encoded, now),
                )
        return self.get_all_settings()

    def delete_setting(self, key: str) -> bool:
        """Delete a persisted setting by key."""
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            return cursor.rowcount > 0
