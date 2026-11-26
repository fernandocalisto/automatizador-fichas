# -*- coding: utf-8 -*-
"""
Ferramentas determinísticas de artefatos do Salutem Ficha Studio (`backend/app/mcp_tools/artifact_tools.py`).

Fornece 4 operações determinísticas prontas para agentes IA e servidor MCP:
1. `extract_pdf_geometry`: extrai geometria completa via PyMuPDF a partir de `pdf_path` ou `project_id`.
2. `save_validated_json`: valida JSON clínico, audita warnings e salva revisão imutável + SQLs.
3. `validate_and_compile_jrxml`: executa linter Fase 4, salva revisão bem-formada e compila no JasperDaemon.
4. `render_preview_images`: gera PDF fictício (offline/híbrido) e renderiza todas as páginas em PNG.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from backend.app.config import get_data_dir
    from backend.app.core.json_utils import (
        audit_clinical_json_warnings,
        parse_and_validate_clinical_json,
    )
    from backend.app.jrxml.linter import lint_jrxml
    from backend.app.jrxml.mock_data import (
        VALID_SCENARIOS,
        build_offline_mock_subreports_jrxml,
        generate_fictitious_row,
        prepare_preview_jrxml,
    )
    from backend.app.services.subreport_service import SubreportService
    from backend.app.services.workspace_service import (
        ArtifactNotFoundError,
        WorkspaceService,
        WorkspaceValidationError,
        validate_jrxml_content,
    )
except ModuleNotFoundError:  # pragma: no cover
    from app.config import get_data_dir  # type: ignore[no-redef]
    from app.core.json_utils import (  # type: ignore[no-redef]
        audit_clinical_json_warnings,
        parse_and_validate_clinical_json,
    )
    from app.jrxml.linter import lint_jrxml  # type: ignore[no-redef]
    from app.jrxml.mock_data import (  # type: ignore[no-redef]
        VALID_SCENARIOS,
        build_offline_mock_subreports_jrxml,
        generate_fictitious_row,
        prepare_preview_jrxml,
    )
    from app.services.subreport_service import SubreportService  # type: ignore[no-redef]
    from app.services.workspace_service import (  # type: ignore[no-redef]
        ArtifactNotFoundError,
        WorkspaceService,
        WorkspaceValidationError,
        validate_jrxml_content,
    )

from .pdf_tools import (
    extract_pdf_geometry as _extract_pdf_geometry_from_path,
    render_pdf_to_pngs,
)

# Cache em memória para evitar recompilar os 4 subreports offline mock para o mesmo daemon/hash
_COMPILED_MOCK_SUBREPORT_CACHE: set[tuple[int, str, str, str]] = set()


def _resolve_jasper_daemon(jasper_daemon: Any | None) -> Any:
    if jasper_daemon is not None:
        return jasper_daemon
    try:
        from backend.app.services.jasper_daemon import get_jasper_daemon
    except ModuleNotFoundError:  # pragma: no cover
        from app.services.jasper_daemon import get_jasper_daemon  # type: ignore[no-redef]
    return get_jasper_daemon()


def _is_daemon_success(daemon_res: Any) -> bool:
    if not isinstance(daemon_res, dict):
        return True
    if daemon_res.get("ok") is False:
        return False
    status_val = str(daemon_res.get("status") or "").strip().upper()
    if status_val == "ERROR":
        return False
    return True


def _format_daemon_exception(exc: Exception) -> dict[str, Any]:
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        data = dict(to_dict())
        data["ok"] = False
        return data
    return {
        "ok": False,
        "status": "ERROR",
        "error_type": type(exc).__name__,
        "message": str(exc),
    }


def _ensure_offline_mock_subreports_compiled(
    jasper_daemon: Any,
    *,
    unit_name: str = "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO",
) -> Path:
    """
    Materializa e compila uma única vez os 4 subreports offline mock em
    `get_data_dir() / "mock_subreports_runtime"`, reutilizando os `.jasper` já compilados.
    """
    runtime_dir = get_data_dir() / "mock_subreports_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    jrxml_map = build_offline_mock_subreports_jrxml(unit_name=unit_name)
    daemon_key = id(jasper_daemon)
    dir_key = str(runtime_dir.resolve())

    for jrxml_filename, jrxml_source in jrxml_map.items():
        stem = Path(jrxml_filename).stem
        jrxml_path = runtime_dir / f"{stem}.jrxml"
        jasper_path = runtime_dir / f"{stem}.jasper"
        src_bytes = jrxml_source.encode("utf-8")
        src_hash = hashlib.sha256(src_bytes).hexdigest()
        cache_token = (daemon_key, dir_key, stem, src_hash)

        source_changed = True
        if jrxml_path.is_file():
            existing_hash = hashlib.sha256(jrxml_path.read_bytes()).hexdigest()
            source_changed = existing_hash != src_hash

        if source_changed:
            jrxml_path.write_bytes(src_bytes)

        already_compiled = (not source_changed) and (
            jasper_path.is_file() or cache_token in _COMPILED_MOCK_SUBREPORT_CACHE
        )
        if not already_compiled:
            res = jasper_daemon.compile(str(jrxml_path), str(jasper_path))
            if not _is_daemon_success(res):
                detail = res.get("message") or res.get("error") or res
                raise RuntimeError(
                    f"Falha ao compilar subreport mock '{jrxml_filename}': {detail}"
                )
            _COMPILED_MOCK_SUBREPORT_CACHE.add(cache_token)

    return runtime_dir


def _load_optional_project_json(
    workspace_service: WorkspaceService,
    project_id: str,
) -> dict[str, Any] | None:
    try:
        rev = workspace_service.get_latest_artifact(project_id, "json")
        parsed = json.loads(rev.content)
        return parsed if isinstance(parsed, dict) else None
    except (ArtifactNotFoundError, ValueError, TypeError):
        return None


def _resolve_preview_mode_and_db(
    *,
    requested_mode: str,
    db_profile_id: str | None,
    requested_atendimento_id: int | None,
    postgres_service: Any | None,
) -> tuple[str, dict[str, Any] | None, int, str | None]:
    if requested_mode not in ("auto", "offline", "db_hybrid"):
        raise ValueError(
            f"Modo de preview inválido '{requested_mode}': esperado 'offline', 'auto' ou 'db_hybrid'."
        )

    default_atend_id = int(requested_atendimento_id) if requested_atendimento_id is not None else 10042

    if requested_mode == "offline":
        return "offline", None, default_atend_id, None

    if requested_mode == "db_hybrid":
        if not db_profile_id:
            raise ValueError("O parâmetro 'db_profile_id' é obrigatório quando mode='db_hybrid'.")
        if postgres_service is None:
            raise RuntimeError("PostgresService indisponível para execução em modo 'db_hybrid'.")
        creds = postgres_service.get_jdbc_credentials(db_profile_id)
        if not isinstance(creds, dict) or not creds.get("db_url"):
            raise ValueError(f"Perfil PostgreSQL '{db_profile_id}' sem 'db_url' válido.")
        if requested_atendimento_id is not None:
            atend_id = int(requested_atendimento_id)
        else:
            sample = postgres_service.find_sample_atendimento_id(db_profile_id)
            atend_id = int(sample) if sample is not None else 10042
        return "db_hybrid", creds, atend_id, None

    # requested_mode == "auto"
    if not db_profile_id:
        return "offline", None, default_atend_id, None
    if postgres_service is None:
        return (
            "offline",
            None,
            default_atend_id,
            "PostgresService indisponível; utilizando modo offline automaticamente.",
        )

    try:
        creds = postgres_service.get_jdbc_credentials(db_profile_id)
        if not isinstance(creds, dict) or not creds.get("db_url"):
            return (
                "offline",
                None,
                default_atend_id,
                f"Perfil '{db_profile_id}' sem credenciais JDBC válidas; fallback para offline.",
            )
        if requested_atendimento_id is not None:
            atend_id = int(requested_atendimento_id)
        else:
            sample = postgres_service.find_sample_atendimento_id(db_profile_id)
            atend_id = int(sample) if sample is not None else 10042
        return "db_hybrid", creds, atend_id, None
    except Exception as exc:
        return (
            "offline",
            None,
            default_atend_id,
            f"Conexão PostgreSQL indisponível ({exc}); fallback automático para modo offline.",
        )


# =============================================================================
# 4 Ferramentas Determinísticas de Artefatos
# =============================================================================


def extract_pdf_geometry(
    pdf_path: str | Path | None = None,
    project_id: str | None = None,
    *,
    workspace_service: WorkspaceService | None = None,
) -> dict[str, Any]:
    """
    Extrai a geometria exata (dimensões, orientação, spans de texto e checkboxes/rádios)
    de um PDF clínico a partir de `pdf_path` direto ou resolvendo `uploads/source.pdf`
    do projeto informado em `project_id` via `WorkspaceService`.
    """
    has_pdf_path = pdf_path is not None and str(pdf_path).strip() != ""
    has_project_id = project_id is not None and str(project_id).strip() != ""

    if not has_pdf_path and not has_project_id:
        raise ValueError(
            "Informe 'pdf_path' ou 'project_id' para extrair a geometria do PDF clínico."
        )

    if has_pdf_path:
        assert pdf_path is not None
        geo = _extract_pdf_geometry_from_path(pdf_path)
        if has_project_id:
            geo = {**geo, "project_id": str(project_id).strip()}
        return geo

    assert project_id is not None
    pid = project_id.strip()
    ws = workspace_service or WorkspaceService()
    resolved_pdf = ws.get_pdf_path(pid)
    geo = _extract_pdf_geometry_from_path(resolved_pdf)
    return {**geo, "project_id": pid}


def save_validated_json(
    project_id: str,
    json_content: str | dict[str, Any],
    summary: str = "JSON salvo pelo agente",
    auto_regenerate_sql: bool = True,
    apply_uppercase: bool = True,
    workspace_service: WorkspaceService | None = None,
) -> dict[str, Any]:
    """
    Valida estritamente o JSON clínico Salutem (`parse_and_validate_clinical_json` +
    `audit_clinical_json_warnings`), salva nova revisão imutável (`created_by="agent"`)
    via `WorkspaceService` e retorna contagens e versões de SQL regeneradas.
    """
    if isinstance(json_content, dict):
        raw_text = json.dumps(json_content, ensure_ascii=False)
    elif isinstance(json_content, str):
        raw_text = json_content
    else:
        raise ValueError("'json_content' deve ser uma string JSON válida ou um objeto (dict).")

    parsed = parse_and_validate_clinical_json(
        raw_text,
        require_clinical_structure=True,
        apply_uppercase=apply_uppercase,
    )
    warnings = audit_clinical_json_warnings(parsed)

    ws = workspace_service or WorkspaceService()
    saved = ws.save_artifact(
        project_id,
        "json",
        raw_text,
        summary=summary or "JSON salvo pelo agente",
        created_by="agent",
        auto_regenerate_sql=auto_regenerate_sql,
        apply_uppercase=apply_uppercase,
    )

    template = parsed.get("template") if isinstance(parsed.get("template"), dict) else {}
    template_name = str(template.get("nome") or "")
    perguntas = parsed.get("perguntas") if isinstance(parsed.get("perguntas"), list) else []

    sections_count = 0
    questions_count = 0
    answers_count = 0
    for item in perguntas:
        if not isinstance(item, dict):
            continue
        if bool(item.get("titulo", False)):
            sections_count += 1
        else:
            questions_count += 1
        respostas = item.get("respostas")
        if isinstance(respostas, list):
            answers_count += len(respostas)

    return {
        "ok": True,
        "project_id": project_id,
        "version_num": saved.artifact.version_num,
        "template_name": template_name,
        "sections_count": sections_count,
        "questions_count": questions_count,
        "answers_count": answers_count,
        "warnings": warnings,
        "sql_insert_version": (
            saved.generated_sql_insert.version_num
            if saved.generated_sql_insert is not None
            else None
        ),
        "sql_select_version": (
            saved.generated_sql_select.version_num
            if saved.generated_sql_select is not None
            else None
        ),
    }


def validate_and_compile_jrxml(
    project_id: str,
    jrxml_content: str | None = None,
    save_artifact: bool = True,
    summary: str = "JRXML validado pelo agente",
    workspace_service: WorkspaceService | None = None,
    jasper_daemon: Any | None = None,
) -> dict[str, Any]:
    """
    Carrega ou recebe um `.jrxml`, executa `lint_jrxml` (todas as travas da Fase 4),
    salva nova revisão `jrxml` (`created_by="agent"`) quando `save_artifact=True` e o XML
    é bem-formado, e compila via `JasperDaemonService.compile(...)`.
    """
    ws = workspace_service or WorkspaceService()
    project = ws.get_project(project_id)

    supplied_inline = jrxml_content is not None
    if supplied_inline:
        jrxml_text = str(jrxml_content)
    else:
        latest_rev = ws.get_latest_artifact(project_id, "jrxml")
        jrxml_text = latest_rev.content

    lint_report = lint_jrxml(jrxml_text).to_dict()

    # Verifica se o XML é bem-formado com raiz <jasperReport>
    well_formed_xml = False
    cleaned_xml = jrxml_text
    try:
        cleaned_xml = validate_jrxml_content(jrxml_text)
        well_formed_xml = True
    except WorkspaceValidationError:
        well_formed_xml = False

    saved_version: int | None = None
    if save_artifact and well_formed_xml and supplied_inline:
        saved_resp = ws.save_artifact(
            project_id,
            "jrxml",
            cleaned_xml,
            summary=summary or "JRXML validado pelo agente",
            created_by="agent",
        )
        saved_version = saved_resp.artifact.version_num

    if not well_formed_xml:
        return {
            "ok": False,
            "project_id": project.id,
            "compiled": False,
            "lint": lint_report,
            "daemon": {
                "ok": False,
                "skipped": True,
                "reason": "XML mal-formado ou elemento raiz diferente de <jasperReport>.",
            },
            "saved_version": saved_version,
        }

    build_dir = Path(project.workspace_dir) / "exports" / "_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    src_jrxml_path = build_dir / f"{project.slug}.jrxml"
    out_jasper_path = build_dir / f"{project.slug}.jasper"
    src_jrxml_path.write_text(cleaned_xml, encoding="utf-8")

    daemon = _resolve_jasper_daemon(jasper_daemon)
    try:
        daemon_res = daemon.compile(str(src_jrxml_path), str(out_jasper_path))
        compiled = _is_daemon_success(daemon_res)
        daemon_payload = (
            dict(daemon_res) if isinstance(daemon_res, dict) else {"result": daemon_res}
        )
    except Exception as exc:
        compiled = False
        daemon_payload = _format_daemon_exception(exc)

    ok = bool(lint_report.get("is_valid")) and compiled
    return {
        "ok": ok,
        "project_id": project.id,
        "compiled": compiled,
        "lint": lint_report,
        "daemon": daemon_payload,
        "saved_version": saved_version,
    }


def render_preview_images(
    project_id: str,
    scenario: str = "full",
    mode: str = "offline",
    dpi: int = 150,
    inline_jrxml: str | None = None,
    workspace_service: WorkspaceService | None = None,
    subreport_service: SubreportService | None = None,
    jasper_daemon: Any | None = None,
    postgres_service: Any | None = None,
    *,
    db_profile_id: str | None = None,
    atendimento_id: int | None = None,
    unit_name: str = "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO",
) -> dict[str, Any]:
    """
    Gera PDF fictício (`full`, `stress` ou `blank`) usando `generate_fictitious_row`,
    `prepare_preview_jrxml` e `jasper_daemon.export_pdf` (compilando subreports mock
    automaticamente em modo `offline`) e renderiza todas as páginas em PNG via PyMuPDF.
    """
    if scenario not in VALID_SCENARIOS:
        raise ValueError(
            f"Cenário inválido '{scenario}': valores aceitos são {VALID_SCENARIOS}."
        )
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi < 36 or dpi > 600:
        raise ValueError(f"DPI inválido '{dpi}': esperado inteiro entre 36 e 600.")

    ws = workspace_service or WorkspaceService()
    project = ws.get_project(project_id)

    if inline_jrxml is not None and inline_jrxml.strip():
        jrxml_text = validate_jrxml_content(inline_jrxml)
    else:
        latest_rev = ws.get_latest_artifact(project_id, "jrxml")
        jrxml_text = validate_jrxml_content(latest_rev.content)

    json_data = _load_optional_project_json(ws, project_id)
    lint_report = lint_jrxml(jrxml_text).to_dict()

    effective_mode, db_creds, effective_atendimento_id, fallback_reason = (
        _resolve_preview_mode_and_db(
            requested_mode=mode,
            db_profile_id=db_profile_id,
            requested_atendimento_id=atendimento_id,
            postgres_service=postgres_service,
        )
    )

    mock_row = generate_fictitious_row(
        jrxml_text,
        json_data=json_data,
        scenario=scenario,  # type: ignore[arg-type]
        atendimento_id=effective_atendimento_id,
    )
    rewritten_jrxml = prepare_preview_jrxml(
        jrxml_text,
        mode=effective_mode,  # type: ignore[arg-type]
        mock_row=mock_row,
    )

    ws_dir = Path(project.workspace_dir)
    exports_dir = ws_dir / "exports"
    build_dir = exports_dir / "_build"
    pages_dir = exports_dir / f"pages_{scenario}"
    for directory in (exports_dir, build_dir, pages_dir):
        directory.mkdir(parents=True, exist_ok=True)

    preview_jrxml_path = build_dir / f"preview_{scenario}_{effective_mode}.jrxml"
    preview_jrxml_path.write_text(rewritten_jrxml, encoding="utf-8")

    daemon = _resolve_jasper_daemon(jasper_daemon)

    if effective_mode == "offline":
        mock_runtime_dir = _ensure_offline_mock_subreports_compiled(
            daemon,
            unit_name=unit_name,
        )
        subreport_dir = str(mock_runtime_dir.resolve())
        caminho_relatorio = mock_runtime_dir.resolve().as_posix().rstrip("/") + "/"
    else:
        subreports = subreport_service or SubreportService()
        real_runtime_dir = subreports.materialize_runtime_dir()
        subreport_dir = str(real_runtime_dir.resolve())
        caminho_relatorio = subreports.get_caminho_relatorio()

    pdf_output_path = exports_dir / f"preview_{scenario}.pdf"
    params: dict[str, Any] = {
        "id": int(effective_atendimento_id),
        "caminho_relatorio": caminho_relatorio,
    }

    if effective_mode == "offline":
        daemon_res = daemon.export_pdf(
            str(preview_jrxml_path),
            str(pdf_output_path),
            params=params,
            mock_rows=[mock_row],
            subreport_dir=subreport_dir,
            db_url=None,
            db_user=None,
            db_pass=None,
        )
    else:
        assert db_creds is not None
        daemon_res = daemon.export_pdf(
            str(preview_jrxml_path),
            str(pdf_output_path),
            params=params,
            mock_rows=None,
            subreport_dir=subreport_dir,
            db_url=db_creds["db_url"],
            db_user=db_creds.get("db_user"),
            db_pass=db_creds.get("db_pass"),
        )

    if not _is_daemon_success(daemon_res):
        detail = (
            daemon_res.get("message") or daemon_res.get("error") or daemon_res
            if isinstance(daemon_res, dict)
            else daemon_res
        )
        raise RuntimeError(f"JasperDaemon reportou erro na exportação de PDF: {detail}")

    if not pdf_output_path.is_file():
        raise RuntimeError(
            f"O JasperDaemon concluiu sem gerar o arquivo esperado em '{pdf_output_path}'."
        )

    for old_png in pages_dir.glob("*.png"):
        old_png.unlink(missing_ok=True)

    rendered_pngs = render_pdf_to_pngs(pdf_output_path, pages_dir, dpi=dpi)
    page_urls = [
        f"/api/projects/{project.id}/jasper/preview/pages/{idx}?scenario={scenario}"
        for idx in range(1, len(rendered_pngs) + 1)
    ]

    latest_meta = {
        "scenario": scenario,
        "effective_mode": effective_mode,
        "dpi": dpi,
        "page_count": len(rendered_pngs),
        "pdf_path": str(pdf_output_path.resolve()),
    }
    (exports_dir / "latest_preview.json").write_text(
        json.dumps(latest_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "project_id": project.id,
        "scenario": scenario,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "page_count": len(rendered_pngs),
        "single_page_ok": len(rendered_pngs) == 1,
        "pdf_path": str(pdf_output_path.resolve()),
        "png_paths": [str(p.resolve()) for p in rendered_pngs],
        "page_urls": page_urls,
        "dpi": dpi,
        "lint": lint_report,
    }


__all__ = [
    "extract_pdf_geometry",
    "render_preview_images",
    "save_validated_json",
    "validate_and_compile_jrxml",
]
