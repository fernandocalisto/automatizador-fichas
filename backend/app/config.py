# -*- coding: utf-8 -*-
"""Configuração central de diretórios e constantes do Salutem Ficha Studio."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Salutem Ficha Studio"
APP_VERSION = "1.1.1"

# backend/app/config.py -> backend/app -> backend -> PROJECT_ROOT
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

RESOURCES_DIR = PROJECT_ROOT / "resources"
BUILTIN_SUBREPORTS_DIR = RESOURCES_DIR / "subreports"
JASPER_BIN_DIR = RESOURCES_DIR / "bin"
JASPER_DAEMON_JAR = JASPER_BIN_DIR / "jasper-daemon.jar"
JAVA_ENGINE_DIR = PROJECT_ROOT / "java-engine"
SQL_TEMPLATES_DIR = RESOURCES_DIR / "sql"
BRANDING_DIR = RESOURCES_DIR / "branding"
SKILLS_DIR = APP_DIR / "skills"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"


def get_data_dir() -> Path:
    """Retorna o diretório persistente de dados e workspaces (configurável via env)."""
    override = os.environ.get("FICHA_STUDIO_DATA_DIR")
    if override:
        path = Path(override).resolve()
    else:
        path = PROJECT_ROOT / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """Retorna o caminho do banco SQLite de projetos/workspaces."""
    override = os.environ.get("FICHA_STUDIO_DB_PATH")
    if override:
        path = Path(override).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return get_data_dir() / "studio.db"


def get_custom_subreports_dir() -> Path:
    """Retorna o diretório onde subreports customizados enviados pelo usuário ficam salvos."""
    d = get_data_dir() / "custom_subreports"
    d.mkdir(parents=True, exist_ok=True)
    return d
