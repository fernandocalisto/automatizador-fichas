# -*- coding: utf-8 -*-
"""Testes de contrato para artefatos de empacotamento, Docker, launchers e documentacao v1.0.0."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_required_packaging_files_and_runtime_assets_exist() -> None:
    expected_files = [
        "Dockerfile",
        ".dockerignore",
        "docker-compose.yml",
        "scripts/start_local.ps1",
        "scripts/start_network.ps1",
        "scripts/dev.ps1",
        "README.md",
        "CHANGELOG.md",
        "resources/bin/jasper-daemon.jar",
        "resources/subreports/cabecalho_retrato.jasper",
        "resources/subreports/cabecalho_paisagem.jasper",
        "resources/subreports/dados_paciente.jasper",
        "resources/subreports/rodape_retrato.jasper",
    ]
    missing = [rel for rel in expected_files if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"Artefatos obrigatorios ausentes: {missing}"


def test_dockerfile_multistage_and_runtime_contracts() -> None:
    content = _read_text("Dockerfile")

    # Stage 1: Frontend builder
    assert "FROM node:22-alpine AS frontend-builder" in content
    assert "COPY frontend/package*.json" in content
    assert "RUN npm ci" in content
    assert "RUN npm run build" in content

    # Stage 2: Runtime Python + JRE 17 + fonts + libpq5 + curl
    assert "FROM python:3.13-slim-bookworm AS runtime" in content
    for pkg in (
        "openjdk-17-jre-headless",
        "fontconfig",
        "fonts-dejavu-core",
        "fonts-liberation",
        "curl",
        "libpq5",
    ):
        assert pkg in content, f"Pacote obrigatorio ausente no Dockerfile: {pkg}"

    assert "pip install --no-cache-dir" in content
    assert "backend/requirements.txt" in content
    assert "COPY backend/" in content
    assert "COPY resources/" in content
    assert "COPY pyproject.toml" in content
    assert "COPY --from=frontend-builder" in content
    assert "./frontend/dist" in content

    # Non-root user, persistent /data, environment, healthcheck and entrypoint
    assert "studio" in content
    assert "USER studio" in content
    assert "/data" in content
    assert "FICHA_STUDIO_DATA_DIR=/data" in content
    assert "PYTHONPATH=/app/backend:/app" in content
    assert "PYTHONUNBUFFERED=1" in content
    assert "EXPOSE 8000" in content
    assert "HEALTHCHECK" in content
    assert "http://127.0.0.1:8000/api/health" in content
    assert 'CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in content


def test_dockerignore_excludes_local_artifacts_and_preserves_runtime_assets() -> None:
    lines = [
        line.strip()
        for line in _read_text(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    required_ignores = [
        ".git",
        ".venv",
        "venv",
        "workspaces",
        "frontend/node_modules",
        "frontend/dist",
        "java-engine/target",
        "*.db*",
        "__pycache__",
        ".pytest_cache",
        "implementation_plan.md",
    ]
    for pattern in required_ignores:
        assert pattern in lines, f"Padrao obrigatorio ausente no .dockerignore: {pattern}"

    # Nao pode ignorar o diretorio resources nem os binarios Jasper necessarios em runtime
    for forbidden in ("resources", "resources/", "*.jar", "*.jasper"):
        assert forbidden not in lines, f".dockerignore nao deve ignorar {forbidden}"


def test_docker_compose_schema_and_contracts() -> None:
    data = yaml.safe_load(_read_text("docker-compose.yml"))
    assert isinstance(data, dict)
    assert "services" in data and "studio" in data["services"]

    studio = data["services"]["studio"]
    assert studio["build"]["dockerfile"] == "Dockerfile"
    assert "8000:8000" in studio["ports"]
    assert "studio_data:/data" in studio["volumes"]
    assert studio["restart"] == "unless-stopped"

    env = studio["environment"]
    if isinstance(env, dict):
        assert env.get("FICHA_STUDIO_DATA_DIR") == "/data"
        assert env.get("FICHA_STUDIO_VAULT_KEY") == "${FICHA_STUDIO_VAULT_KEY:-}"
        assert "STUDIO_CORS_ORIGINS" in env
    else:
        assert "FICHA_STUDIO_DATA_DIR=/data" in env
        assert "FICHA_STUDIO_VAULT_KEY=${FICHA_STUDIO_VAULT_KEY:-}" in env

    assert "volumes" in data and "studio_data" in data["volumes"]


def test_github_workflow_scopes_write_permission_to_release_job() -> None:
    workflow = yaml.safe_load(_read_text(".github/workflows/build.yml"))
    assert isinstance(workflow, dict)
    assert workflow.get("permissions", {}).get("contents") == "read"

    jobs = workflow.get("jobs", {})
    assert jobs["release"].get("permissions", {}).get("contents") == "write"
    for job_name in ("backend-tests", "frontend-tests", "docker-validate"):
        assert "permissions" not in jobs[job_name]


def test_cors_hardening_defaults_and_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from backend.app.main import _resolve_cors_settings, create_app

    monkeypatch.delenv("STUDIO_CORS_ORIGINS", raising=False)
    origins, regex, creds = _resolve_cors_settings()
    assert origins == []
    assert regex is not None
    assert creds is True

    app = create_app()
    client = TestClient(app)

    local_resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert local_resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    foreign_resp = client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in foreign_resp.headers

    monkeypatch.setenv("STUDIO_CORS_ORIGINS", "https://studio.salutem.local, http://10.0.0.5:8000")
    assert _resolve_cors_settings() == (
        ["https://studio.salutem.local", "http://10.0.0.5:8000"],
        None,
        True,
    )

    monkeypatch.setenv("STUDIO_CORS_ORIGINS", "*")
    assert _resolve_cors_settings() == (["*"], None, False)


def test_start_local_ps1_contracts() -> None:
    content = _read_text("scripts/start_local.ps1")

    for required_fragment in (
        "[int]$Port = 8000",
        "[switch]$RebuildFrontend",
        "[switch]$NoBrowser",
        '[string]$DataDir = ""',
        ".venv\\Scripts\\python.exe",
        "import cryptography, paramiko",
        "Test-FrontendBuildStale",
        "package.json",
        "Get-Command java",
        "dist\\index.html",
        "--prefix frontend ci",
        "--prefix frontend run build",
        "TcpListener",
        "uvicorn",
        "backend.app.main:app",
        "PYTHONPATH",
        "FICHA_STUDIO_DATA_DIR",
        "/api/health",
        "Start-Process",
        "finally",
    ):
        assert required_fragment in content, f"Fragmento ausente em scripts/start_local.ps1: {required_fragment}"

    # Compatibilidade estrita com Windows PowerShell 5.1 (sem operadores exclusivos do PS 7)
    assert " && " not in content
    assert " || " not in content
    assert " ?? " not in content


def test_start_network_ps1_contracts() -> None:
    content = _read_text("scripts/start_network.ps1")

    for required_fragment in (
        "[int]$Port = 8000",
        '[string]$BindHost = "0.0.0.0"',
        "[switch]$RebuildFrontend",
        "[switch]$NoBrowser",
        '[string]$DataDir = ""',
        ".venv\\Scripts\\python.exe",
        "import cryptography, paramiko",
        "Test-FrontendBuildStale",
        "package.json",
        "uvicorn",
        "backend.app.main:app",
        '"--host", "$BindHost"',
        "/api/health",
        "Acesso Rede",
        "finally",
    ):
        assert required_fragment in content, (
            f"Fragmento ausente em scripts/start_network.ps1: {required_fragment}"
        )

    # Compatibilidade estrita com Windows PowerShell 5.1
    assert " && " not in content
    assert " || " not in content
    assert " ?? " not in content


def test_dev_ps1_contracts() -> None:
    content = _read_text("scripts/dev.ps1")

    for required_fragment in (
        "[int]$ApiPort = 8000",
        "[int]$WebPort = 5173",
        ".venv\\Scripts\\python.exe",
        "frontend\\node_modules",
        "uvicorn",
        "backend.app.main:app",
        "--reload",
        '"--prefix", "frontend"',
        '"run", "dev"',
        '"--port", "$WebPort"',
        "Frontend Vite",
        "Backend API",
        "Swagger /docs",
        "finally",
    ):
        assert required_fragment in content, f"Fragmento ausente em scripts/dev.ps1: {required_fragment}"

    assert " && " not in content
    assert " || " not in content
    assert " ?? " not in content


@pytest.mark.skipif(sys.platform != "win32", reason="Validacao PowerShell ParseFile executa no Windows")
@pytest.mark.parametrize("script_rel", ["scripts/start_local.ps1", "scripts/start_network.ps1", "scripts/dev.ps1"])
def test_powershell_scripts_parse_with_zero_syntax_errors(script_rel: str) -> None:
    script_path = str((REPO_ROOT / script_rel).resolve()).replace("'", "''")
    ps_cmd = (
        "$tokens = $null; $errors = $null; "
        f"$null = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors); "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error ($_.Extent.StartLineNumber.ToString() + ': ' + $_.Message) }; "
        "exit 1 }"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Erro de sintaxe PowerShell em {script_rel}:\n{proc.stdout}\n{proc.stderr}"


def test_readme_v1_documentation_contracts() -> None:
    content = _read_text("README.md")

    for expected in (
        "Salutem Ficha Studio",
        "v1.0.0",
        "React",
        "FastAPI",
        "Jasper Daemon",
        "MCP",
        "Form Builder",
        "Dry-Run",
        "Commit",
        "PDF.js",
        "ZIP",
        "scripts/start_local.ps1",
        "scripts/dev.ps1",
        "docker compose",
        "pytest",
        "vitest",
    ):
        assert re.search(re.escape(expected), content, re.IGNORECASE), (
            f"Topico obrigatorio ausente no README.md: {expected}"
        )


def test_changelog_v1_documents_phases_and_preserves_history() -> None:
    content = _read_text("CHANGELOG.md")

    idx_100 = content.find("## [1.0.0] - 2026-11-25")
    idx_020 = content.find("## [0.2.0] - 2026-11-14")
    idx_010 = content.find("## [0.1.0] - 2026-11-05")

    assert idx_100 != -1, "Secao ## [1.0.0] - 2026-11-25 ausente no CHANGELOG.md"
    assert idx_020 != -1, "Historico ## [0.2.0] - 2026-11-14 foi removido do CHANGELOG.md"
    assert idx_010 != -1, "Historico ## [0.1.0] - 2026-11-05 foi removido do CHANGELOG.md"
    assert idx_100 < idx_020 < idx_010, "Ordem cronologica das versoes no CHANGELOG.md esta incorreta"

    v1_section = content[idx_100:idx_020]
    for phase in ("Fase 1", "Fase 2", "Fase 3", "Fase 4"):
        assert phase in v1_section, f"{phase} nao documentada na secao 1.0.0 do CHANGELOG.md"
