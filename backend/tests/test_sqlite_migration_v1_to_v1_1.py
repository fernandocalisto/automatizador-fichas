# -*- coding: utf-8 -*-
"""Tests idempotent SQLite migration from a real v1.0.0 database to v1.1 schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.workspace_service import WorkspaceService


V1_0_SCHEMA_SQL = """
CREATE TABLE projects (
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

CREATE TABLE artifact_revisions (
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

CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN ('extraction', 'jrxml')),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE gate_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    gate_name TEXT NOT NULL CHECK (gate_name IN ('gate1_json', 'gate2_sql_insert', 'gate3_jrxml')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by TEXT NULL,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, gate_name)
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def test_sqlite_migration_v1_0_to_v1_1_preserves_data_and_enables_new_modes(tmp_path: Path) -> None:
    db_path = tmp_path / "studio_v1_legacy.db"
    ws_dir = tmp_path / "legacy_ws"
    ws_dir.mkdir(parents=True, exist_ok=True)

    # Seed a genuine v1.0.0 SQLite database with related child records
    raw_conn = sqlite3.connect(str(db_path))
    raw_conn.execute("PRAGMA foreign_keys = ON;")
    raw_conn.executescript(V1_0_SCHEMA_SQL)
    raw_conn.execute(
        """
        INSERT INTO projects (
            id, slug, name, description, current_stage, entry_mode,
            preferred_harness, template_db_id, workspace_dir, created_at, updated_at
        ) VALUES (
            'proj-v1', 'ficha_legada', 'Ficha Legada v1.0', 'Desc v1',
            'jrxml_design', 'pdf', 'agy', 77, ?, '2026-11-25T10:00:00+00:00', '2026-11-25T10:00:00+00:00'
        )
        """,
        (str(ws_dir),),
    )
    raw_conn.execute(
        """
        INSERT INTO artifact_revisions (project_id, artifact_type, version_num, content, summary, created_by, created_at)
        VALUES ('proj-v1', 'json', 1, '{"template":{"nome":"X"},"perguntas":[]}', 'v1', 'user', '2026-11-25T10:00:00+00:00')
        """
    )
    raw_conn.execute(
        """
        INSERT INTO gate_approvals (project_id, gate_name, status, decided_by, notes, updated_at)
        VALUES ('proj-v1', 'gate1_json', 'approved', 'user', 'ok', '2026-11-25T10:00:00+00:00')
        """
    )
    raw_conn.execute(
        """
        INSERT INTO chat_messages (project_id, phase, role, content, metadata_json, created_at)
        VALUES ('proj-v1', 'extraction', 'user', 'Oi', '{}', '2026-11-25T10:00:00+00:00')
        """
    )
    raw_conn.commit()
    raw_conn.close()

    # Open with v1.1 SQLiteStore and verify migration + idempotency
    store = SQLiteStore(db_path=db_path)
    store.init_db()
    store.init_db()  # second call must be a clean no-op

    legacy = store.get_project("proj-v1")
    assert legacy is not None
    assert legacy["name"] == "Ficha Legada v1.0"
    assert legacy["project_kind"] == "clinical_form"
    assert legacy["source_origin"] == {}
    assert legacy["default_db_profile_id"] is None
    assert legacy["client_system_id"] is None

    # Child rows survived intact with foreign keys valid
    assert len(store.list_artifact_revisions("proj-v1")) == 1
    assert len(store.list_gates("proj-v1")) == 1
    assert len(store.list_chat_messages("proj-v1")) == 1

    # Creating v1.1 free_report project with new entry_mode succeeds
    ws = WorkspaceService(store=store, data_dir=tmp_path / "data")
    free_proj = ws.create_project(
        ProjectCreate(
            name="Relatório Financeiro Livre",
            entry_mode="blank_report",
            default_db_profile_id="db-1",
            source_origin={"provider": "jasperserver", "uri": "/reports/fin"},
        )
    )
    assert free_proj.project_kind == "free_report"
    assert free_proj.entry_mode == "blank_report"
    assert free_proj.current_stage == "jrxml_design"
    assert free_proj.default_db_profile_id == "db-1"
    assert free_proj.source_origin == {"provider": "jasperserver", "uri": "/reports/fin"}

    # Agent sessions table works and cascades on project delete
    sess = store.upsert_agent_session(free_proj.id, "jrxml", "agy", "conv-123")
    assert sess["external_session_id"] == "conv-123"
    assert store.get_agent_session(free_proj.id, "jrxml", "agy")["external_session_id"] == "conv-123"
    assert store.delete_agent_session(free_proj.id, phase="jrxml", harness_id="agy") == 1
    assert store.get_agent_session(free_proj.id, "jrxml", "agy") is None
