# -*- coding: utf-8 -*-
"""
FastAPI router para compilação JasperReports, pré-visualização híbrida/offline em PDF e PNG,
e empacotamento final do bundle de entrega Salutem (`backend/app/api/jasper_preview.py`).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.config import get_data_dir
from backend.app.core.json_utils import parse_and_validate_clinical_json
from backend.app.core.sql_insert import generate_insert_sql
from backend.app.jrxml.linter import lint_jrxml
from backend.app.jrxml.mock_data import (
    ScenarioType,
    build_offline_mock_subreports_jrxml,
    generate_fictitious_row,
    prepare_preview_jrxml,
)
from backend.app.mcp_tools.pdf_tools import render_pdf_to_pngs
from backend.app.services.subreport_service import SubreportService
from backend.app.services.workspace_service import (
    ArtifactNotFoundError,
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
    validate_jrxml_content,
)

router = APIRouter(prefix="/api/projects", tags=["jasper-preview"])

# Cache em memória para evitar recompilar subreports mock quando o daemon fake em testes não grava .jasper
_COMPILED_MOCK_SUBREPORT_CACHE: set[tuple[int, str, str, str]] = set()


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------


class JasperCompileRequest(BaseModel):
    """Payload opcional para compilação de `.jrxml` (salvo no workspace ou inline)."""

    model_config = ConfigDict(extra="ignore")

    inline_jrxml: str | None = None
    run_linter: bool = True


class JasperPreviewRequest(BaseModel):
    """Payload de geração de pré-visualização PDF + páginas PNG."""

    model_config = ConfigDict(extra="ignore")

    scenario: ScenarioType = "full"
    mode: Literal["auto", "offline", "db_hybrid"] = "auto"
    db_profile_id: str | None = None
    atendimento_id: int | None = None
    inline_jrxml: str | None = None
    dpi: int = Field(default=150, ge=36, le=600)
    unit_name: str = "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO"


class PreviewPageInfo(BaseModel):
    """Metadados de uma página PNG renderizada do PDF de preview."""

    page_number: int
    url: str
    filename: str
    size_bytes: int


# -----------------------------------------------------------------------------
# FastAPI Dependencies (com lazy imports para permitir injeção de fakes em testes)
# -----------------------------------------------------------------------------


def get_workspace_service(request: Request) -> WorkspaceService:
    """Resolve `WorkspaceService` anexado ao estado da aplicação FastAPI."""
    svc = getattr(request.app.state, "workspace_service", None)
    if isinstance(svc, WorkspaceService):
        return svc
    return WorkspaceService()


def get_subreport_service(request: Request) -> SubreportService:
    """Resolve `SubreportService` anexado ao estado da aplicação FastAPI."""
    svc = getattr(request.app.state, "subreport_service", None)
    if isinstance(svc, SubreportService):
        return svc
    return SubreportService()


def get_jasper_daemon_dep(request: Request) -> Any:
    """
    Resolve `JasperDaemonService` via `app.state.jasper_daemon` ou lazy import
    de `backend.app.services.jasper_daemon.get_jasper_daemon()`.
    """
    override_svc = getattr(request.app.state, "jasper_daemon", None)
    if override_svc is not None:
        return override_svc
    try:
        from backend.app.services import jasper_daemon as _jasper_daemon_mod

        return _jasper_daemon_mod.get_jasper_daemon()
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Serviço JasperDaemon indisponível neste ambiente: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha ao inicializar JasperDaemonService: {exc}",
        ) from exc


def get_postgres_service_dep(request: Request) -> Any | None:
    """
    Resolve `PostgresService` via `app.state.postgres_service` ou lazy import
    de `backend.app.services.postgres_service.PostgresService`.
    Retorna `None` caso o módulo não esteja disponível (permitindo fallback para `offline` em modo `auto`).
    """
    override_svc = getattr(request.app.state, "postgres_service", None)
    if override_svc is not None:
        return override_svc
    try:
        from backend.app.services.postgres_service import PostgresService
    except ModuleNotFoundError:
        return None

    store = getattr(request.app.state, "store", None)
    if store is not None:
        try:
            return PostgresService(store=store)
        except TypeError:
            pass
    return PostgresService()


# Aliases amigáveis para dependency_overrides nos testes e integração
get_jasper_daemon = get_jasper_daemon_dep
get_postgres_service = get_postgres_service_dep

WorkspaceSvcDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
SubreportSvcDep = Annotated[SubreportService, Depends(get_subreport_service)]
JasperDaemonDep = Annotated[Any, Depends(get_jasper_daemon_dep)]
PostgresSvcDep = Annotated[Any | None, Depends(get_postgres_service_dep)]


# -----------------------------------------------------------------------------
# Helpers Internos
# -----------------------------------------------------------------------------


def _raise_http_for_workspace_error(exc: Exception) -> None:
    if isinstance(exc, ProjectNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ArtifactNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, WorkspaceValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


def _resolve_jrxml_source(
    workspace_service: WorkspaceService,
    project_id: str,
    inline_jrxml: str | None = None,
) -> str:
    """Obtém e valida o XML `.jrxml` (inline ou última revisão salva do projeto)."""
    if inline_jrxml is not None and inline_jrxml.strip():
        return validate_jrxml_content(inline_jrxml)
    rev = workspace_service.get_latest_artifact(project_id, "jrxml")
    return validate_jrxml_content(rev.content)


def _load_optional_project_json(
    workspace_service: WorkspaceService,
    project_id: str,
) -> dict[str, Any] | None:
    """Carrega o JSON clínico do projeto quando disponível (projetos JRXML-only podem não tê-lo)."""
    try:
        rev = workspace_service.get_latest_artifact(project_id, "json")
        parsed = json.loads(rev.content)
        return parsed if isinstance(parsed, dict) else None
    except (ArtifactNotFoundError, ValueError, TypeError):
        return None


def _ensure_offline_mock_subreports_compiled(
    jasper_daemon: Any,
    *,
    unit_name: str = "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO",
) -> Path:
    """
    Materializa e compila uma única vez os 4 subreports offline mock em
    `get_data_dir() / "mock_subreports_runtime"`, reutilizando os `.jasper` compilados
    nas execuções subsequentes.
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
            if isinstance(res, dict) and res.get("ok") is False:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Falha ao compilar subreport mock '{jrxml_filename}': {res.get('error') or res}",
                )
            _COMPILED_MOCK_SUBREPORT_CACHE.add(cache_token)

    return runtime_dir


def _resolve_preview_mode_and_db(
    *,
    requested_mode: Literal["auto", "offline", "db_hybrid"],
    db_profile_id: str | None,
    requested_atendimento_id: int | None,
    postgres_service: Any | None,
) -> tuple[Literal["offline", "db_hybrid"], dict[str, Any] | None, int, str | None]:
    """
    Determina o modo efetivo (`"offline"` vs `"db_hybrid"`), credenciais JDBC, `atendimento_id`
    e eventual motivo de fallback quando `requested_mode == "auto"`.
    """
    default_atend_id = requested_atendimento_id if requested_atendimento_id is not None else 10042

    if requested_mode == "offline":
        return "offline", None, default_atend_id, None

    if requested_mode == "db_hybrid":
        if not db_profile_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O parâmetro 'db_profile_id' é obrigatório quando mode='db_hybrid'.",
            )
        if postgres_service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PostgresService indisponível para execução em modo 'db_hybrid'.",
            )
        try:
            creds = postgres_service.get_jdbc_credentials(db_profile_id)
            if not isinstance(creds, dict) or not creds.get("db_url"):
                raise ValueError(f"Perfil PostgreSQL '{db_profile_id}' sem 'db_url' válido.")
            if requested_atendimento_id is not None:
                atend_id = int(requested_atendimento_id)
            else:
                sample = postgres_service.find_sample_atendimento_id(db_profile_id)
                atend_id = int(sample) if sample is not None else 10042
            return "db_hybrid", creds, atend_id, None
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Falha ao obter credenciais PostgreSQL para modo 'db_hybrid': {exc}",
            ) from exc

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


def _execute_preview_pipeline(
    *,
    project_id: str,
    payload: JasperPreviewRequest,
    workspace_service: WorkspaceService,
    subreport_service: SubreportService,
    jasper_daemon: Any,
    postgres_service: Any | None,
) -> dict[str, Any]:
    """Executa o fluxo completo de preview híbrido/offline sem mutar o `.jrxml` original."""
    project = workspace_service.get_project(project_id)
    jrxml_text = _resolve_jrxml_source(workspace_service, project_id, payload.inline_jrxml)
    json_data = _load_optional_project_json(workspace_service, project_id)
    lint_report = lint_jrxml(jrxml_text).to_dict()

    effective_mode, db_creds, effective_atendimento_id, fallback_reason = (
        _resolve_preview_mode_and_db(
            requested_mode=payload.mode,
            db_profile_id=payload.db_profile_id,
            requested_atendimento_id=payload.atendimento_id,
            postgres_service=postgres_service,
        )
    )

    mock_row = generate_fictitious_row(
        jrxml_text,
        json_data=json_data,
        scenario=payload.scenario,
        atendimento_id=effective_atendimento_id,
    )
    rewritten_jrxml = prepare_preview_jrxml(
        jrxml_text,
        mode=effective_mode,
        mock_row=mock_row,
    )

    ws_dir = Path(project.workspace_dir)
    exports_dir = ws_dir / "exports"
    build_dir = exports_dir / "_build"
    pages_dir = exports_dir / f"pages_{payload.scenario}"
    for d in (exports_dir, build_dir, pages_dir):
        d.mkdir(parents=True, exist_ok=True)

    preview_jrxml_path = build_dir / f"preview_{payload.scenario}_{effective_mode}.jrxml"
    preview_jrxml_path.write_text(rewritten_jrxml, encoding="utf-8")

    if effective_mode == "offline":
        mock_runtime_dir = _ensure_offline_mock_subreports_compiled(
            jasper_daemon,
            unit_name=payload.unit_name,
        )
        subreport_dir = str(mock_runtime_dir.resolve())
        caminho_relatorio = mock_runtime_dir.resolve().as_posix().rstrip("/") + "/"
    else:
        real_runtime_dir = subreport_service.materialize_runtime_dir()
        subreport_dir = str(real_runtime_dir.resolve())
        caminho_relatorio = subreport_service.get_caminho_relatorio()

    pdf_output_path = exports_dir / f"preview_{payload.scenario}.pdf"
    params: dict[str, Any] = {
        "id": int(effective_atendimento_id),
        "caminho_relatorio": caminho_relatorio,
    }

    try:
        if effective_mode == "offline":
            daemon_res = jasper_daemon.export_pdf(
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
            daemon_res = jasper_daemon.export_pdf(
                str(preview_jrxml_path),
                str(pdf_output_path),
                params=params,
                mock_rows=None,
                subreport_dir=subreport_dir,
                db_url=db_creds["db_url"],
                db_user=db_creds.get("db_user"),
                db_pass=db_creds.get("db_pass"),
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Falha ao exportar PDF de preview no JasperDaemon: {exc}",
        ) from exc

    if isinstance(daemon_res, dict) and daemon_res.get("ok") is False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"JasperDaemon reportou erro na exportação de PDF: {daemon_res.get('error') or daemon_res}",
        )

    if not pdf_output_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"O JasperDaemon concluiu sem gerar o arquivo esperado em '{pdf_output_path}'.",
        )

    # Limpa PNGs antigos do mesmo cenário antes de re-renderizar
    for old_png in pages_dir.glob("*.png"):
        old_png.unlink(missing_ok=True)

    rendered_pngs = render_pdf_to_pngs(pdf_output_path, pages_dir, dpi=payload.dpi)

    pdf_url = f"/api/projects/{project.id}/jasper/preview/pdf?scenario={payload.scenario}"
    page_urls = [
        f"/api/projects/{project.id}/jasper/preview/pages/{idx}?scenario={payload.scenario}"
        for idx in range(1, len(rendered_pngs) + 1)
    ]
    pages_meta = [
        PreviewPageInfo(
            page_number=idx + 1,
            url=page_urls[idx],
            filename=png_file.name,
            size_bytes=png_file.stat().st_size,
        ).model_dump()
        for idx, png_file in enumerate(rendered_pngs)
    ]

    latest_meta = {
        "scenario": payload.scenario,
        "effective_mode": effective_mode,
        "dpi": payload.dpi,
        "page_count": len(rendered_pngs),
        "pdf_path": str(pdf_output_path),
    }
    (exports_dir / "latest_preview.json").write_text(
        json.dumps(latest_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "project_id": project.id,
        "slug": project.slug,
        "scenario": payload.scenario,
        "requested_mode": payload.mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "atendimento_id": effective_atendimento_id,
        "dpi": payload.dpi,
        "page_count": len(rendered_pngs),
        "single_page_ok": len(rendered_pngs) == 1,
        "pdf_path": str(pdf_output_path),
        "pdf_size_bytes": pdf_output_path.stat().st_size,
        "pdf_url": pdf_url,
        "page_urls": page_urls,
        "pages": pages_meta,
        "subreport_dir": subreport_dir,
        "lint": lint_report,
        "daemon": daemon_res if isinstance(daemon_res, dict) else {"result": daemon_res},
    }


def _resolve_active_scenario(exports_dir: Path, scenario: ScenarioType | None) -> ScenarioType:
    """Determina o cenário alvo para streaming de PDF/PNG (explícito ou último preview gerado)."""
    if scenario is not None:
        return scenario
    meta_path = exports_dir / "latest_preview.json"
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            cand = data.get("scenario")
            if cand in ("full", "stress", "blank"):
                return cand  # type: ignore[return-value]
        except Exception:
            pass
    for fallback in ("full", "stress", "blank"):
        if (exports_dir / f"preview_{fallback}.pdf").is_file():
            return fallback  # type: ignore[return-value]
    return "full"


# -----------------------------------------------------------------------------
# Rotas FastAPI
# -----------------------------------------------------------------------------


@router.post("/{project_id}/jasper/compile")
def compile_project_jasper(
    project_id: str,
    workspace_service: WorkspaceSvcDep,
    jasper_daemon: JasperDaemonDep,
    payload: JasperCompileRequest = Body(default_factory=JasperCompileRequest),
) -> dict[str, Any]:
    """Compila o `.jrxml` do projeto (ou `inline_jrxml`) para `.jasper` sem alterar os artefatos salvos."""
    try:
        project = workspace_service.get_project(project_id)
        jrxml_text = _resolve_jrxml_source(workspace_service, project_id, payload.inline_jrxml)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise

    lint_dict = lint_jrxml(jrxml_text).to_dict() if payload.run_linter else None

    build_dir = Path(project.workspace_dir) / "exports" / "_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    src_jrxml_path = build_dir / f"{project.slug}.jrxml"
    out_jasper_path = build_dir / f"{project.slug}.jasper"
    src_jrxml_path.write_text(jrxml_text, encoding="utf-8")

    try:
        daemon_res = jasper_daemon.compile(str(src_jrxml_path), str(out_jasper_path))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Erro de compilação JasperReports: {exc}",
        ) from exc

    is_ok = True
    if isinstance(daemon_res, dict):
        if daemon_res.get("ok") is False or daemon_res.get("status") == "error":
            is_ok = False

    return {
        "ok": is_ok,
        "compiled": is_ok,
        "project_id": project.id,
        "slug": project.slug,
        "jrxml_path": str(src_jrxml_path),
        "jasper_path": str(out_jasper_path),
        "lint": lint_dict,
        "daemon": daemon_res if isinstance(daemon_res, dict) else {"result": daemon_res},
    }


@router.post("/{project_id}/jasper/preview")
def generate_project_jasper_preview(
    project_id: str,
    workspace_service: WorkspaceSvcDep,
    subreport_service: SubreportSvcDep,
    jasper_daemon: JasperDaemonDep,
    postgres_service: PostgresSvcDep,
    payload: JasperPreviewRequest = Body(default_factory=JasperPreviewRequest),
) -> dict[str, Any]:
    """
    Gera PDF fictício (`full`, `stress` ou `blank`) em modo `offline`, `db_hybrid` ou `auto`,
    renderiza as páginas PNG via PyMuPDF e retorna URLs + métricas de paginação e linter.
    """
    try:
        return _execute_preview_pipeline(
            project_id=project_id,
            payload=payload,
            workspace_service=workspace_service,
            subreport_service=subreport_service,
            jasper_daemon=jasper_daemon,
            postgres_service=postgres_service,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise


@router.get("/{project_id}/jasper/preview/pdf")
def stream_project_preview_pdf(
    project_id: str,
    workspace_service: WorkspaceSvcDep,
    scenario: ScenarioType | None = Query(default=None),
) -> FileResponse:
    """Retorna o arquivo PDF gerado no preview (`preview_<scenario>.pdf`)."""
    try:
        project = workspace_service.get_project(project_id)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise

    exports_dir = Path(project.workspace_dir) / "exports"
    resolved_scenario = _resolve_active_scenario(exports_dir, scenario)
    pdf_path = exports_dir / f"preview_{resolved_scenario}.pdf"
    if not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Nenhum PDF de preview encontrado para o cenário '{resolved_scenario}' "
                f"no projeto '{project_id}'."
            ),
        )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{project.slug}_preview_{resolved_scenario}.pdf",
        content_disposition_type="inline",
    )


@router.get("/{project_id}/jasper/preview/pages/{page_num}")
def stream_project_preview_page_png(
    project_id: str,
    workspace_service: WorkspaceSvcDep,
    page_num: int = PathParam(..., ge=1),
    scenario: ScenarioType | None = Query(default=None),
) -> FileResponse:
    """Retorna a imagem PNG renderizada de uma página específica do PDF de preview."""
    try:
        project = workspace_service.get_project(project_id)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise

    exports_dir = Path(project.workspace_dir) / "exports"
    resolved_scenario = _resolve_active_scenario(exports_dir, scenario)
    png_path = (
        exports_dir
        / f"pages_{resolved_scenario}"
        / f"preview_{resolved_scenario}_page_{page_num}.png"
    )
    if not png_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Página PNG #{page_num} não encontrada para o cenário '{resolved_scenario}' "
                f"no projeto '{project_id}'."
            ),
        )

    return FileResponse(
        path=str(png_path),
        media_type="image/png",
        filename=png_path.name,
        content_disposition_type="inline",
    )


@router.get("/{project_id}/jasper/export-bundle")
def export_salutem_delivery_bundle(
    project_id: str,
    workspace_service: WorkspaceSvcDep,
    subreport_service: SubreportSvcDep,
    jasper_daemon: JasperDaemonDep,
    postgres_service: PostgresSvcDep,
    scenario: ScenarioType = Query(default="full"),
    mode: Literal["auto", "offline", "db_hybrid"] = Query(default="auto"),
    db_profile_id: str | None = Query(default=None),
) -> FileResponse:
    """
    Gera e transmite o pacote final `<slug>_entrega_salutem.zip` contendo:
      1. `<slug>.jrxml` (limpo, com `$P{REPORT_CONNECTION}` e `<queryString>` originais intactos)
      2. `<slug>_relatorio_ficticio.pdf`
      3. `<slug>_insert_template.sql`
    """
    try:
        project = workspace_service.get_project(project_id)
        clean_jrxml = workspace_service.get_latest_artifact(project_id, "jrxml").content

        try:
            sql_insert_content = workspace_service.get_latest_artifact(
                project_id, "sql_insert"
            ).content
        except ArtifactNotFoundError:
            json_rev = workspace_service.get_latest_artifact(project_id, "json")
            parsed_json = parse_and_validate_clinical_json(
                json_rev.content,
                require_clinical_structure=True,
                apply_uppercase=True,
            )
            sql_insert_content = generate_insert_sql(parsed_json)
    except Exception as exc:
        _raise_http_for_workspace_error(exc)
        raise

    exports_dir = Path(project.workspace_dir) / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = exports_dir / f"preview_{scenario}.pdf"

    if not pdf_path.is_file():
        _execute_preview_pipeline(
            project_id=project_id,
            payload=JasperPreviewRequest(
                scenario=scenario,
                mode=mode,
                db_profile_id=db_profile_id,
            ),
            workspace_service=workspace_service,
            subreport_service=subreport_service,
            jasper_daemon=jasper_daemon,
            postgres_service=postgres_service,
        )

    slug = project.slug
    bundle_filename = f"{slug}_entrega_salutem.zip"
    bundle_path = exports_dir / bundle_filename

    jrxml_entry = clean_jrxml if clean_jrxml.endswith("\n") else clean_jrxml + "\n"
    sql_entry = (
        sql_insert_content
        if sql_insert_content.endswith("\n")
        else sql_insert_content + "\n"
    )

    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}.jrxml", jrxml_entry.encode("utf-8"))
        zf.writestr(f"{slug}_relatorio_ficticio.pdf", pdf_path.read_bytes())
        zf.writestr(f"{slug}_insert_template.sql", sql_entry.encode("utf-8"))

    return FileResponse(
        path=str(bundle_path),
        media_type="application/zip",
        filename=bundle_filename,
        content_disposition_type="attachment",
    )


__all__ = [
    "JasperCompileRequest",
    "JasperPreviewRequest",
    "PreviewPageInfo",
    "get_jasper_daemon",
    "get_jasper_daemon_dep",
    "get_postgres_service",
    "get_postgres_service_dep",
    "get_subreport_service",
    "get_workspace_service",
    "router",
]
