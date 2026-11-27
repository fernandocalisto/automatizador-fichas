# -*- coding: utf-8 -*-
"""FastAPI application entrypoint for Salutem Ficha Studio."""

from __future__ import annotations

import html
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure repository root and backend/ are importable regardless of working directory
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
for _p in (_BACKEND_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import (
    agent,
    database,
    harnesses_and_tools,
    jasper_preview,
    projects,
    subreports,
    system,
)
from backend.app.config import APP_NAME, APP_VERSION, FRONTEND_DIST_DIR
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services.agent_orchestrator import AgentOrchestratorService
from backend.app.services.jasper_daemon import JasperDaemonService
from backend.app.services.postgres_service import PostgresService
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import WorkspaceService


def _render_dev_status_html(
    *,
    db_path: str,
    projects_count: int,
    builtin_subreports_count: int,
    custom_subreports_count: int,
) -> str:
    """Render clean, modern dark-themed status & quick-test page when frontend/dist is not yet built."""
    esc_app = html.escape(APP_NAME)
    esc_ver = html.escape(APP_VERSION)
    esc_db = html.escape(db_path)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc_app} — Backend Studio Status</title>
  <style>
    :root {{
      --bg: #0b1120;
      --panel: #111827;
      --border: #1f2937;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.12);
      --ok: #34d399;
      --text: #f3f4f6;
      --muted: #9ca3af;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(circle at top right, #1e293b 0%, var(--bg) 55%);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }}
    .card {{
      width: 100%;
      max-width: 820px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2rem 2.25rem;
      box-shadow: 0 24px 48px rgba(0, 0, 0, 0.45);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.3rem 0.75rem;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      background: rgba(52, 211, 153, 0.12);
      color: var(--ok);
      border: 1px solid rgba(52, 211, 153, 0.3);
    }}
    h1 {{
      margin: 0.85rem 0 0.35rem;
      font-size: 1.75rem;
      letter-spacing: -0.02em;
    }}
    .subtitle {{
      margin: 0 0 1.5rem;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.5;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.85rem;
      margin-bottom: 1.5rem;
    }}
    .stat {{
      background: rgba(255, 255, 255, 0.025);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.9rem 1rem;
    }}
    .stat-label {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }}
    .stat-value {{
      margin-top: 0.35rem;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text);
    }}
    .links {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }}
    a.btn {{
      display: flex;
      flex-direction: column;
      gap: 0.2rem;
      text-decoration: none;
      padding: 0.85rem 1rem;
      border-radius: 10px;
      background: var(--accent-soft);
      border: 1px solid rgba(56, 189, 248, 0.28);
      color: var(--text);
      transition: transform 0.12s ease, border-color 0.12s ease;
    }}
    a.btn:hover {{
      transform: translateY(-1px);
      border-color: var(--accent);
    }}
    a.btn strong {{
      color: var(--accent);
      font-size: 0.92rem;
    }}
    a.btn span {{
      color: var(--muted);
      font-size: 0.78rem;
    }}
    .footer {{
      margin-top: 1rem;
      padding-top: 1rem;
      border-top: 1px solid var(--border);
      font-size: 0.8rem;
      color: var(--muted);
      word-break: break-all;
    }}
    code {{
      color: #cbd5e1;
      background: rgba(255, 255, 255, 0.06);
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="badge">&#9679; API Online &middot; v{esc_ver}</div>
    <h1>{esc_app}</h1>
    <p class="subtitle">
      Workspace SQLite (WAL) e API FastAPI prontos. O bundle SPA (<code>frontend/dist</code>) ainda n&atilde;o foi compilado,
      exibindo painel r&aacute;pido de inspe&ccedil;&atilde;o para desenvolvimento.
    </p>

    <section class="stats">
      <div class="stat">
        <div class="stat-label">Projetos no Studio</div>
        <div class="stat-value">{projects_count}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Subreports Padr&atilde;o</div>
        <div class="stat-value">{builtin_subreports_count}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Subreports Custom</div>
        <div class="stat-value">{custom_subreports_count}</div>
      </div>
    </section>

    <nav class="links">
      <a class="btn" href="/docs">
        <strong>/docs</strong>
        <span>Swagger UI interativo</span>
      </a>
      <a class="btn" href="/api/health">
        <strong>/api/health</strong>
        <span>Status, paths e SQLite</span>
      </a>
      <a class="btn" href="/api/projects">
        <strong>/api/projects</strong>
        <span>Workspaces e fichas</span>
      </a>
      <a class="btn" href="/api/subreports">
        <strong>/api/subreports</strong>
        <span>Invent&aacute;rio .jasper</span>
      </a>
      <a class="btn" href="/api/harnesses">
        <strong>/api/harnesses</strong>
        <span>AGY, OpenCode, Claude, Codex</span>
      </a>
      <a class="btn" href="/api/skills">
        <strong>/api/skills</strong>
        <span>Skills Salutem embutidas</span>
      </a>
      <a class="btn" href="/api/db/profiles">
        <strong>/api/db/profiles</strong>
        <span>Perfis PostgreSQL &amp; Vault</span>
      </a>
      <a class="btn" href="/api/jasper/health">
        <strong>/api/jasper/health</strong>
        <span>Jasper Daemon JVM</span>
      </a>
    </nav>

    <div class="footer">
      SQLite DB: <code>{esc_db}</code>
    </div>
  </main>
</body>
</html>
"""


_DEFAULT_LOCAL_CORS_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def _resolve_cors_settings() -> tuple[list[str], str | None, bool]:
    """
    Resolve configurações seguras de CORS via `STUDIO_CORS_ORIGINS`.

    - Sem env definida: permite apenas origens locais (`localhost` / `127.0.0.1`).
      Requisições same-origin em rede local (`http://<LAN-IP>:8000`) não precisam de CORS.
    - Com `*` explícito: desabilita `allow_credentials` (conforme especificação Fetch/CORS).
    - Com lista separada por vírgula: restringe estritamente às origens informadas.
    """
    raw = os.environ.get("STUDIO_CORS_ORIGINS", "").strip()
    if not raw:
        return ([], _DEFAULT_LOCAL_CORS_REGEX, True)

    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if not origins:
        return ([], _DEFAULT_LOCAL_CORS_REGEX, True)
    if "*" in origins:
        return (["*"], None, False)
    return (origins, None, True)


def create_app(
    *,
    store: SQLiteStore | None = None,
    workspace_service: WorkspaceService | None = None,
    subreport_service: SubreportService | None = None,
    postgres_service: PostgresService | None = None,
    jasper_daemon: JasperDaemonService | None = None,
    agent_orchestrator: AgentOrchestratorService | None = None,
    frontend_dist_dir: Path | None = None,
) -> FastAPI:
    """Create and configure the Salutem Ficha Studio FastAPI application."""
    resolved_store = store or SQLiteStore()
    resolved_workspace = workspace_service or WorkspaceService(store=resolved_store)
    resolved_subreports = subreport_service or SubreportService()
    resolved_postgres = postgres_service or PostgresService(store=resolved_store)
    resolved_agent = agent_orchestrator or AgentOrchestratorService(
        workspace_service=resolved_workspace
    )
    dist_dir = frontend_dist_dir if frontend_dist_dir is not None else FRONTEND_DIST_DIR

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        app_instance.state.store.init_db()
        try:
            yield
        finally:
            active_daemon = getattr(app_instance.state, "jasper_daemon", None)
            if active_daemon is not None and hasattr(active_daemon, "stop"):
                try:
                    active_daemon.stop()
                except Exception:
                    pass

    app_instance = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        description="Backend API for Salutem Ficha Studio — Clinical Form Extraction, SQL Generation & JasperReports Designer.",
        lifespan=lifespan,
    )

    app_instance.state.store = resolved_store
    app_instance.state.workspace_service = resolved_workspace
    app_instance.state.subreport_service = resolved_subreports
    app_instance.state.postgres_service = resolved_postgres
    app_instance.state.agent_orchestrator = resolved_agent
    if jasper_daemon is not None:
        app_instance.state.jasper_daemon = jasper_daemon

    cors_origins, cors_origin_regex, cors_allow_credentials = _resolve_cors_settings()
    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app_instance.include_router(projects.router)
    app_instance.include_router(subreports.router)
    app_instance.include_router(system.router)
    app_instance.include_router(harnesses_and_tools.router)
    app_instance.include_router(database.router)
    app_instance.include_router(jasper_preview.router)
    app_instance.include_router(agent.router)

    if (dist_dir / "assets").is_dir():
        app_instance.mount(
            "/assets",
            StaticFiles(directory=str(dist_dir / "assets")),
            name="frontend-assets",
        )

    @app_instance.get("/", include_in_schema=False, response_model=None)
    def serve_root(request: Request) -> FileResponse | HTMLResponse:
        index_html = dist_dir / "index.html"
        if index_html.is_file():
            return FileResponse(str(index_html), media_type="text/html")

        active_store: SQLiteStore = request.app.state.store
        active_subreports: SubreportService = request.app.state.subreport_service
        db_info = active_store.check_health()
        html_body = _render_dev_status_html(
            db_path=str(db_info["path"]),
            projects_count=int(db_info["projects_count"]),
            builtin_subreports_count=active_subreports.count_builtin_subreports(),
            custom_subreports_count=active_subreports.count_custom_subreports(),
        )
        return HTMLResponse(content=html_body, status_code=200)

    if dist_dir.is_dir() and (dist_dir / "index.html").is_file():
        app_instance.mount(
            "/",
            StaticFiles(directory=str(dist_dir), html=True),
            name="frontend-spa",
        )

    return app_instance


app = create_app()
