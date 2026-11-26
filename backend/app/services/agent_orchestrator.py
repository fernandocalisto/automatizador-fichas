# -*- coding: utf-8 -*-
"""Serviço Orquestrador de Agentes de IA com controle estrito de 2 Gates e sincronização de artefatos."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.json_utils import parse_and_validate_clinical_json
from backend.app.db.schemas import (
    ArtifactType,
    ChatMessageCreate,
    ChatMessageRead,
    GateApprovalRead,
    GateApprovalUpdate,
    GateName,
    ProjectRead,
)
from backend.app.harnesses import (
    AgentHarness,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRegistry,
    HarnessRunRequest,
    PhaseKind,
    get_default_registry,
)
from backend.app.mcp_tools.studio_tools import get_all_mcp_tool_descriptors
from backend.app.services.workspace_service import (
    WorkspaceService,
    WorkspaceValidationError,
    validate_jrxml_content,
)

PHASE_GATE_MAP: dict[PhaseKind, GateName] = {
    "extraction": "gate1_json",
    "jrxml": "gate3_jrxml",
}

PHASE_ARTIFACT_MAP: dict[PhaseKind, ArtifactType] = {
    "extraction": "json",
    "jrxml": "jrxml",
}

PHASE_EXTENSION_MAP: dict[PhaseKind, str] = {
    "extraction": ".json",
    "jrxml": ".jrxml",
}

_EXCLUDED_SCAN_DIRS: frozenset[str] = frozenset(
    {
        "exports",
        "uploads",
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
    }
)

_EXCLUDED_SCAN_FILES: frozenset[str] = frozenset(
    {
        "opencode.json",
        "mcp_config.json",
        "plugin.json",
        "studio_mcp_config.json",
        "package.json",
        "tsconfig.json",
    }
)

_MAX_RECENT_CHAT_MESSAGES = 12
_MAX_PREVIEW_IMAGES = 12

# Padrões de negação explícita que invalidam detecção automática de confirmação de Gate 2
_NEGATION_RE = re.compile(
    r"\b(?:nao|nunca|jamais|ainda\s+nao|sem)\s+(?:esta\s+|estou\s+)?"
    r"(?:autorizad[oa]|autorizo|aprovad[oa]|aprovo|confirmad[oa]|confirmo|"
    r"pode\s+(?:gerar|criar|prosseguir|salvar|avancar)|gerar|gere|criar|crie)\b"
)

# Mensagens curtas de aprovação direta (ex.: "Autorizado", "Sim, aprovado!", "Ok, pode gerar")
_DIRECT_APPROVAL_RE = re.compile(
    r"^(?:(?:sim|ok|okay|blz|beleza|perfeito|otimo|certo|tudo\s+(?:certo|ok|bem)|"
    r"combinado|fechado|concordo|de\s+acordo)[,!.;:\s-]*)*"
    r"(?:autorizad[oa]|autorizo|aprovad[oa]|aprovo|confirmad[oa]|confirmo|"
    r"authorized|approved|pode\s+(?:gerar|criar|prosseguir|avancar|salvar|fazer|montar))"
    r"(?:[!.,;\s]*$|[,!.;:\s-]+.{0,140}$)"
)

# Comandos explícitos de geração dentro de uma frase afirmativa (não interrogativa)
_EXPLICIT_GENERATE_CMD_RE = re.compile(
    r"\b(?:pode\s+(?:gerar|criar|prosseguir|avancar|salvar|exportar|escrever)|"
    r"autorizo\s+(?:a\s+)?(?:geracao|gerar|criar|prosseguir|avancar|salvar)|"
    r"aprovo\s+(?:a\s+)?(?:geracao|gerar|estrutura|layout|proposta)|"
    r"gerar\s+(?:o\s+)?(?:json|jrxml|arquivo|artefato|layout)\s*(?:agora|final)?)\b"
)


class AgentOrchestratorError(Exception):
    """Erro base da camada de orquestração de agentes."""


class UnknownHarnessError(AgentOrchestratorError):
    """Levantado quando o identificador de harness informado não existe no catálogo."""


@dataclass(slots=True)
class _FileFingerprint:
    """Assinatura de arquivo no workspace usada para detectar criação/atualização pelo agente."""

    mtime_ns: int
    sha256: str


@dataclass(slots=True)
class _ActiveRun:
    """Controle de execução concorrente e cancelamento por projeto."""

    cancel_event: asyncio.Event
    phase: PhaseKind
    harness_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _normalize_text(raw: str) -> str:
    """Remove acentos, converte para minúsculas e colapsa espaços para análise de intenção."""
    nfkd = unicodedata.normalize("NFKD", raw.strip().lower())
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip()


def is_gate_confirmation_message(prompt: str) -> bool:
    """
    Detecta se a mensagem do usuário representa uma confirmação/autorização expressa
    para avançar do Gate 1 ao Gate 2 (`"autorizado"`, `"aprovado"`, `"pode gerar"`, etc.),
    rejeitando negações explícitas e perguntas.
    """
    if not prompt or not prompt.strip():
        return False

    normalized = _normalize_text(prompt)
    if not normalized:
        return False

    if _NEGATION_RE.search(normalized):
        return False

    if _DIRECT_APPROVAL_RE.match(normalized):
        # Evita falso positivo se a continuação for uma pergunta ("aprovado? ...")
        if "?" in normalized:
            return False
        return True

    if "?" in normalized:
        return False

    return bool(_EXPLICIT_GENERATE_CMD_RE.search(normalized))


def _event_type_value(event: HarnessEvent) -> str:
    """Extrai o valor string do `EventType` de forma resiliente a múltiplos caminhos de import."""
    raw = event.type
    return str(raw.value) if hasattr(raw, "value") else str(raw)


def _resolve_harness_kind(harness: AgentHarness, fallback_id: str) -> HarnessKind:
    """Obtém o `HarnessKind` canônico de um adaptador."""
    raw = getattr(harness, "kind", fallback_id)
    if isinstance(raw, HarnessKind):
        return raw
    raw_val = raw.value if hasattr(raw, "value") else str(raw)
    return HarnessKind(raw_val)


def _sha256_file(path: Path) -> str:
    """Calcula SHA-256 de um arquivo de texto/binário do workspace."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _is_excluded_workspace_path(rel_path: Path) -> bool:
    """Ignora subpastas de exports/uploads/caches e configs de harness ao procurar artefatos finais."""
    if rel_path.name.lower() in _EXCLUDED_SCAN_FILES:
        return True
    return any(
        part in _EXCLUDED_SCAN_DIRS or part.startswith(".")
        for part in rel_path.parts[:-1]
    )


def _snapshot_workspace_artifacts(workspace_dir: Path) -> dict[Path, _FileFingerprint]:
    """Captura snapshot `(mtime_ns, sha256)` de todos os `*.json` e `*.jrxml` relevantes."""
    snapshot: dict[Path, _FileFingerprint] = {}
    if not workspace_dir.is_dir():
        return snapshot

    for pattern in ("*.json", "*.jrxml"):
        for file_path in workspace_dir.rglob(pattern):
            if not file_path.is_file():
                continue
            try:
                rel = file_path.relative_to(workspace_dir)
            except ValueError:
                continue
            if _is_excluded_workspace_path(rel):
                continue
            try:
                stat = file_path.stat()
                snapshot[file_path.resolve()] = _FileFingerprint(
                    mtime_ns=stat.st_mtime_ns,
                    sha256=_sha256_file(file_path),
                )
            except OSError:
                continue
    return snapshot


def _collect_preview_image_paths(workspace_dir: Path, phase: PhaseKind) -> list[Path]:
    """
    Na fase `jrxml`, localiza PNGs recentes em `exports/pages_*/*.png` para envio multimodal
    ao agente, priorizando o cenário registrado em `exports/latest_preview.json`.
    """
    if phase != "jrxml":
        return []

    exports_dir = workspace_dir / "exports"
    if not exports_dir.is_dir():
        return []

    candidate_dirs: list[Path] = []
    seen_dirs: set[Path] = set()

    latest_meta_path = exports_dir / "latest_preview.json"
    if latest_meta_path.is_file():
        try:
            meta = json.loads(latest_meta_path.read_text(encoding="utf-8"))
            scenario = meta.get("scenario")
            if isinstance(scenario, str) and scenario.strip():
                preferred_dir = (exports_dir / f"pages_{scenario.strip()}").resolve()
                if preferred_dir.is_dir():
                    candidate_dirs.append(preferred_dir)
                    seen_dirs.add(preferred_dir)
        except Exception:
            pass

    other_dirs = [
        d.resolve()
        for d in exports_dir.glob("pages_*")
        if d.is_dir() and d.resolve() not in seen_dirs
    ]
    other_dirs.sort(key=lambda d: d.stat().st_mtime_ns, reverse=True)
    candidate_dirs.extend(other_dirs)

    images: list[Path] = []
    seen_files: set[Path] = set()
    for page_dir in candidate_dirs:
        pngs = sorted(
            (p.resolve() for p in page_dir.glob("*.png") if p.is_file()),
            key=lambda p: p.name,
        )
        for png in pngs:
            if png not in seen_files:
                seen_files.add(png)
                images.append(png)
                if len(images) >= _MAX_PREVIEW_IMAGES:
                    return images

    return images


class AgentOrchestratorService:
    """
    Orquestra turnos de agentes de IA (AGY, OpenCode, Claude Code, Codex) com:
    - Trava estrita de 2 Gates (`gate1_json` na fase `extraction`, `gate3_jrxml` na fase `jrxml`);
    - Montagem rica de contexto do projeto, histórico recente de chat, anotações visuais
      `visual_region_feedback` do Jasper Studio, ferramentas MCP disponíveis e PNGs de preview;
    - Streaming assíncrono de `HarnessEvent` com suporte a cancelamento por projeto;
    - Sincronização automática de `.json` e `.jrxml` gravados no workspace em Gate 2 para novas
      revisões versionadas no `WorkspaceService` (com auto-regeneração de SQL para JSON);
    - Persistência completa de mensagens do usuário e do assistente (thoughts, tool calls, gate).
    """

    def __init__(
        self,
        workspace_service: WorkspaceService,
        harness_registry: HarnessRegistry | None = None,
    ) -> None:
        self.workspace_service = workspace_service
        self.harness_registry = harness_registry or get_default_registry()
        self._active_runs: dict[str, _ActiveRun] = {}

    # -------------------------------------------------------------------------
    # Validação & Resolução de Fase / Gate / Harness
    # -------------------------------------------------------------------------

    @staticmethod
    def get_gate_for_phase(phase: PhaseKind) -> GateName:
        """Retorna o gate obrigatório da fase (`extraction` -> `gate1_json`, `jrxml` -> `gate3_jrxml`)."""
        gate_name = PHASE_GATE_MAP.get(phase)
        if gate_name is None:
            raise WorkspaceValidationError(
                f"Fase inválida '{phase}'. Esperado: 'extraction' ou 'jrxml'."
            )
        return gate_name

    def _resolve_harness(
        self,
        project: ProjectRead,
        harness_id: str | None = None,
    ) -> tuple[AgentHarness, HarnessKind]:
        """Resolve o harness solicitado (ou `project.preferred_harness`) validando existência."""
        requested_id = (harness_id or project.preferred_harness or "agy").strip().lower()
        try:
            harness = self.harness_registry.get(requested_id)
        except KeyError as exc:
            raise UnknownHarnessError(str(exc)) from exc
        kind = _resolve_harness_kind(harness, requested_id)
        return harness, kind

    def validate_turn_request(
        self,
        project_id: str,
        *,
        phase: PhaseKind,
        harness_id: str | None = None,
    ) -> tuple[ProjectRead, AgentHarness, HarnessKind, GateName]:
        """
        Valida sincronamente projeto, fase e harness antes de abrir o stream HTTP/WS,
        permitindo retornar códigos 404/400 determinísticos antes dos headers SSE.
        """
        gate_name = self.get_gate_for_phase(phase)
        project = self.workspace_service.get_project(project_id)
        harness, kind = self._resolve_harness(project, harness_id)
        return project, harness, kind, gate_name

    @staticmethod
    def _find_gate(project: ProjectRead, gate_name: GateName) -> GateApprovalRead | None:
        for gate in project.gates:
            if gate.gate_name == gate_name:
                return gate
        return None

    def _resolve_gate_authorization(
        self,
        project: ProjectRead,
        *,
        phase: PhaseKind,
        prompt: str,
        explicit_gate_authorized: bool = False,
    ) -> tuple[bool, GateName, ProjectRead]:
        """
        Determina se o turno está autorizado para Gate 2:
        - `explicit_gate_authorized=True`, OU
        - gate da fase já está `"approved"` no SQLite, OU
        - `prompt` contém confirmação expressa (caso em que o gate também é atualizado para `"approved"`).
        """
        gate_name = self.get_gate_for_phase(phase)
        current_gate = self._find_gate(project, gate_name)
        is_db_approved = current_gate is not None and current_gate.status == "approved"
        is_prompt_confirmed = is_gate_confirmation_message(prompt)

        if is_prompt_confirmed and not is_db_approved:
            self.workspace_service.update_gate(
                project.id,
                gate_name,
                GateApprovalUpdate(
                    status="approved",
                    decided_by="user",
                    notes=f"Autorizado via chat ({phase}): {prompt.strip()[:160]}",
                ),
            )
            project = self.workspace_service.get_project(project.id)
            is_db_approved = True

        authorized = bool(explicit_gate_authorized or is_db_approved or is_prompt_confirmed)
        return authorized, gate_name, project

    # -------------------------------------------------------------------------
    # Montagem de Contexto Rico para o Harness
    # -------------------------------------------------------------------------

    def _build_run_request(
        self,
        project: ProjectRead,
        *,
        phase: PhaseKind,
        prompt: str,
        gate_name: GateName,
        gate_authorized: bool,
        recent_messages: list[ChatMessageRead],
        model: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> HarnessRunRequest:
        workspace_dir = Path(project.workspace_dir)
        image_paths = _collect_preview_image_paths(workspace_dir, phase)

        gates_context = [g.model_dump(mode="json") for g in project.gates]
        recent_chat_context = [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at,
                "metadata": msg.metadata,
            }
            for msg in recent_messages[-_MAX_RECENT_CHAT_MESSAGES:]
        ]

        visual_feedbacks = [
            item
            for item in recent_chat_context
            if isinstance(item.get("metadata"), dict)
            and item["metadata"].get("type") == "visual_region_feedback"
        ]

        # Inclui recortes PNG de feedback visual existentes para inspeção multimodal
        seen_image_paths = {p.resolve() for p in image_paths}
        for fb in visual_feedbacks:
            crop_raw = fb.get("metadata", {}).get("crop_png_path")
            if isinstance(crop_raw, str) and crop_raw.strip():
                crop_path = Path(crop_raw)
                if crop_path.is_file() and crop_path.resolve() not in seen_image_paths:
                    image_paths.append(crop_path.resolve())
                    seen_image_paths.add(crop_path.resolve())

        available_tools = [
            {
                "name": descriptor["name"],
                "description": descriptor.get("description", ""),
                "inputSchema": descriptor.get("inputSchema", {}),
            }
            for descriptor in get_all_mcp_tool_descriptors()
        ]

        project_context: dict[str, Any] = {
            "id": project.id,
            "slug": project.slug,
            "name": project.name,
            "description": project.description,
            "current_stage": project.current_stage,
            "entry_mode": project.entry_mode,
            "preferred_harness": project.preferred_harness,
            "template_db_id": project.template_db_id,
            "has_pdf": project.has_pdf,
            "latest_artifacts": dict(project.latest_artifacts),
            "gates": gates_context,
        }
        if project.has_pdf:
            project_context["source_pdf_path"] = str(
                (workspace_dir / "uploads" / "source.pdf").resolve()
            )

        extra_context: dict[str, Any] = {
            "project": project_context,
            "phase": phase,
            "gate": {
                "name": gate_name,
                "authorized": gate_authorized,
            },
            "recent_chat": recent_chat_context,
            "available_tools": available_tools,
        }
        if visual_feedbacks:
            extra_context["visual_region_feedbacks"] = visual_feedbacks

        return HarnessRunRequest(
            workspace_dir=workspace_dir,
            phase=phase,
            prompt=prompt,
            gate_authorized=gate_authorized,
            model=model,
            image_paths=image_paths,
            extra_context=extra_context,
            timeout_seconds=timeout_seconds,
        )

    # -------------------------------------------------------------------------
    # Sincronização Automática de Artefatos do Workspace (Gate 2)
    # -------------------------------------------------------------------------

    def _sync_modified_workspace_artifacts(
        self,
        project_id: str,
        *,
        workspace_dir: Path,
        phase: PhaseKind,
        harness_id: str,
        before_snapshot: dict[Path, _FileFingerprint],
    ) -> list[dict[str, Any]]:
        """
        Detecta arquivos `.json` (fase `extraction`) ou `.jrxml` (fase `jrxml`) criados ou
        alterados durante o turno autorizado (Gate 2), valida seu conteúdo clínico/XML e
        importa automaticamente como nova revisão no `WorkspaceService`.
        """
        target_ext = PHASE_EXTENSION_MAP[phase]
        artifact_type = PHASE_ARTIFACT_MAP[phase]
        after_snapshot = _snapshot_workspace_artifacts(workspace_dir)

        changed_candidates: list[tuple[int, Path]] = []
        for path, after_fp in after_snapshot.items():
            if path.suffix.lower() != target_ext:
                continue
            before_fp = before_snapshot.get(path)
            if before_fp is None or before_fp.sha256 != after_fp.sha256:
                changed_candidates.append((after_fp.mtime_ns, path))

        if not changed_candidates:
            return []

        # Mais recentemente gravado primeiro
        changed_candidates.sort(key=lambda item: item[0], reverse=True)

        synced: list[dict[str, Any]] = []
        for _, candidate_path in changed_candidates:
            try:
                raw_text = candidate_path.read_text(encoding="utf-8")
            except OSError:
                continue

            if not raw_text.strip():
                continue

            if artifact_type == "json":
                try:
                    parse_and_validate_clinical_json(
                        raw_text,
                        require_clinical_structure=True,
                        apply_uppercase=True,
                    )
                except ValueError:
                    continue
            elif artifact_type == "jrxml":
                try:
                    validate_jrxml_content(raw_text)
                except WorkspaceValidationError:
                    continue

            try:
                rel_path = candidate_path.relative_to(workspace_dir.resolve()).as_posix()
            except ValueError:
                rel_path = candidate_path.name

            save_res = self.workspace_service.save_artifact(
                project_id,
                artifact_type,
                raw_text,
                summary=f"Sincronizado automaticamente do workspace ({rel_path}) via agente '{harness_id}'",
                created_by="agent",
                auto_regenerate_sql=(artifact_type == "json"),
            )

            sync_meta: dict[str, Any] = {
                "artifact_synced": True,
                "artifact_type": artifact_type,
                "version_num": save_res.artifact.version_num,
                "revision_id": save_res.artifact.id,
                "source_file": rel_path,
            }
            if save_res.generated_sql_insert is not None:
                sync_meta["sql_insert_version"] = save_res.generated_sql_insert.version_num
            if save_res.generated_sql_select is not None:
                sync_meta["sql_select_version"] = save_res.generated_sql_select.version_num

            synced.append(sync_meta)
            # Sincroniza o artefato válido mais recente da fase para evitar revisões duplicadas
            break

        return synced

    # -------------------------------------------------------------------------
    # Ciclo de Vida de Streaming do Turno
    # -------------------------------------------------------------------------

    async def stream_turn(
        self,
        project_id: str,
        *,
        phase: PhaseKind,
        prompt: str,
        harness_id: str | None = None,
        model: str | None = None,
        explicit_gate_authorized: bool = False,
        timeout_seconds: float = 300.0,
        persist_user_message: bool = True,
        user_message_metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """
        Executa um turno completo de streaming de agente para o projeto:
        1. Valida projeto, fase e harness;
        2. Resolve autorização de Gate 2 (explícita, DB ou frase de confirmação);
        3. Coleta histórico recente + PNGs de preview e persiste a mensagem do usuário;
        4. Registra `asyncio.Event` de cancelamento e captura snapshot de arquivos do workspace;
        5. Faz streaming dos eventos do harness acumulando texto, pensamentos e tool calls;
        6. Em Gate 2 sem erro, sincroniza `.json`/`.jrxml` alterado no workspace e emite
           `TOOL_RESULT` (`tool_name="workspace_sync"`) antes do `DONE`;
        7. Em Gate 1 sem erro, garante emissão de `GATE_REQUEST` antes do `DONE` e bloqueia sync;
        8. Persiste a resposta consolidada do assistente no SQLite.
        """
        project, harness, harness_kind, _ = self.validate_turn_request(
            project_id,
            phase=phase,
            harness_id=harness_id,
        )

        gate_authorized, gate_name, project = self._resolve_gate_authorization(
            project,
            phase=phase,
            prompt=prompt,
            explicit_gate_authorized=explicit_gate_authorized,
        )

        # Histórico anterior ao turno atual (preservando anotações visual_region_feedback)
        recent_messages = self.workspace_service.list_chat_messages(project_id, phase=phase)

        if persist_user_message:
            user_meta = dict(user_message_metadata or {})
            user_meta.setdefault("gate_authorized", gate_authorized)
            user_meta.setdefault("harness", harness_kind.value)
            self.workspace_service.add_chat_message(
                project_id,
                ChatMessageCreate(
                    phase=phase,
                    role="user",
                    content=prompt,
                    metadata=user_meta,
                ),
            )

        run_request = self._build_run_request(
            project,
            phase=phase,
            prompt=prompt,
            gate_name=gate_name,
            gate_authorized=gate_authorized,
            recent_messages=recent_messages,
            model=model,
            timeout_seconds=timeout_seconds,
        )

        workspace_dir = Path(project.workspace_dir)
        before_snapshot = _snapshot_workspace_artifacts(workspace_dir)
        before_artifact_versions = dict(project.latest_artifacts)

        cancel_event = asyncio.Event()
        active_run = _ActiveRun(
            cancel_event=cancel_event,
            phase=phase,
            harness_id=harness_kind.value,
        )
        # Se houver execução anterior pendente no mesmo projeto, sinaliza cancelamento
        prev_run = self._active_runs.get(project_id)
        if prev_run is not None:
            prev_run.cancel_event.set()
        self._active_runs[project_id] = active_run

        text_parts: list[str] = []
        thought_parts: list[str] = []
        tool_calls_log: list[dict[str, Any]] = []
        tool_results_log: list[dict[str, Any]] = []
        synced_artifacts: list[dict[str, Any]] = []
        saw_gate_request = False
        had_error = False
        cancelled = False
        buffered_done: HarnessEvent | None = None

        aiter = harness.stream(run_request).__aiter__()
        cancel_wait_task = asyncio.create_task(cancel_event.wait())

        try:
            while True:
                if cancel_event.is_set():
                    cancelled = True
                    break

                next_task = asyncio.create_task(aiter.__anext__())
                done_tasks, _ = await asyncio.wait(
                    {next_task, cancel_wait_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if cancel_wait_task in done_tasks:
                    cancelled = True
                    if not next_task.done():
                        next_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                            await next_task
                    else:
                        with contextlib.suppress(StopAsyncIteration, Exception):
                            next_task.result()
                    break

                try:
                    event = next_task.result()
                except StopAsyncIteration:
                    break
                except Exception as exc:
                    had_error = True
                    err_event = HarnessEvent(
                        type=EventType.ERROR,
                        content=f"Erro durante execução do harness '{harness_kind.value}': {exc}",
                        harness=harness_kind,
                        metadata={"exception_type": type(exc).__name__, "phase": phase},
                    )
                    yield err_event
                    break

                ev_type = _event_type_value(event)
                if event.harness is None:
                    event = event.model_copy(update={"harness": harness_kind})

                if ev_type == EventType.DONE.value:
                    buffered_done = event
                    break

                if ev_type == EventType.TEXT_DELTA.value:
                    if event.content:
                        text_parts.append(event.content)
                elif ev_type == EventType.THOUGHT_DELTA.value:
                    if event.content:
                        thought_parts.append(event.content)
                elif ev_type == EventType.TOOL_CALL.value:
                    tool_calls_log.append(
                        {
                            "tool_name": event.tool_name,
                            "tool_call_id": event.tool_call_id,
                            "tool_args": event.tool_args,
                            "status": "running",
                        }
                    )
                elif ev_type == EventType.TOOL_RESULT.value:
                    result_record = {
                        "tool_name": event.tool_name,
                        "tool_call_id": event.tool_call_id,
                        "tool_output": event.tool_output,
                        "content": event.content,
                        "metadata": dict(event.metadata),
                    }
                    tool_results_log.append(result_record)
                    self._attach_tool_result(tool_calls_log, result_record)
                elif ev_type == EventType.GATE_REQUEST.value:
                    saw_gate_request = True
                elif ev_type == EventType.ERROR.value:
                    had_error = True

                yield event

            if cancelled:
                for item in tool_calls_log:
                    if item.get("status") == "running":
                        item["status"] = "error"
                        item["result_content"] = "Execução cancelada pelo usuário."
                cancel_err = HarnessEvent(
                    type=EventType.ERROR,
                    content="Execução do agente cancelada pelo usuário.",
                    harness=harness_kind,
                    metadata={"cancelled": True, "phase": phase},
                )
                yield cancel_err
            else:
                # Nunca deixar ferramentas presas em "running" após o encerramento do turno
                unfinished_tools: list[dict[str, Any]] = []
                for item in tool_calls_log:
                    if item.get("status") == "running":
                        unfinished_tools.append(item)
                        err_msg = "Ferramenta interrompida antes de retornar resultado."
                        item["status"] = "error"
                        item["tool_output"] = err_msg
                        item["result_content"] = err_msg
                        tool_results_log.append(
                            {
                                "tool_name": item.get("tool_name"),
                                "tool_call_id": item.get("tool_call_id"),
                                "tool_output": err_msg,
                                "content": err_msg,
                                "metadata": {"error": err_msg, "interrupted": True},
                            }
                        )
                        yield HarnessEvent(
                            type=EventType.TOOL_RESULT,
                            tool_name=item.get("tool_name"),
                            tool_call_id=item.get("tool_call_id"),
                            tool_output=err_msg,
                            content=err_msg,
                            harness=harness_kind,
                            metadata={"error": err_msg, "interrupted": True},
                        )

                if not had_error and unfinished_tools and not text_parts:
                    had_error = True
                    names = ", ".join(
                        str(t.get("tool_name") or "tool") for t in unfinished_tools
                    )
                    yield HarnessEvent(
                        type=EventType.ERROR,
                        content=(
                            f"O agente encerrou sem concluir as ferramentas pendentes ({names}) "
                            "e não produziu resposta. Nenhum artefato foi alterado."
                        ),
                        harness=harness_kind,
                        metadata={"phase": phase, "unfinished_tools": names},
                    )

            if not cancelled and not had_error:
                if gate_authorized:
                    artifact_type = PHASE_ARTIFACT_MAP[phase]
                    refreshed_project = self.workspace_service.get_project(project_id)
                    prev_ver = before_artifact_versions.get(artifact_type)
                    curr_ver = refreshed_project.latest_artifacts.get(artifact_type)
                    mcp_saved_new_revision = curr_ver is not None and curr_ver != prev_ver

                    if mcp_saved_new_revision:
                        try:
                            latest_rev = self.workspace_service.get_latest_artifact(
                                project_id, artifact_type
                            )
                            mcp_sync_meta: dict[str, Any] = {
                                "artifact_synced": True,
                                "artifact_type": artifact_type,
                                "version_num": latest_rev.version_num,
                                "revision_id": latest_rev.id,
                                "source_file": "mcp_tool",
                            }
                            if artifact_type == "json":
                                if refreshed_project.latest_artifacts.get("sql_insert") is not None:
                                    mcp_sync_meta["sql_insert_version"] = (
                                        refreshed_project.latest_artifacts["sql_insert"]
                                    )
                                if refreshed_project.latest_artifacts.get("sql_select") is not None:
                                    mcp_sync_meta["sql_select_version"] = (
                                        refreshed_project.latest_artifacts["sql_select"]
                                    )
                            synced_artifacts = [mcp_sync_meta]
                        except Exception:
                            synced_artifacts = []
                    else:
                        try:
                            synced_artifacts = self._sync_modified_workspace_artifacts(
                                project_id,
                                workspace_dir=workspace_dir,
                                phase=phase,
                                harness_id=harness_kind.value,
                                before_snapshot=before_snapshot,
                            )
                        except Exception as exc:
                            had_error = True
                            yield HarnessEvent(
                                type=EventType.ERROR,
                                content=f"Falha ao sincronizar artefato do workspace: {exc}",
                                harness=harness_kind,
                                metadata={"phase": phase, "workspace_sync_error": True},
                            )

                    refreshed_after_sync = self.workspace_service.get_project(project_id)
                    latest_artifacts_map = dict(refreshed_after_sync.latest_artifacts)
                    for sync_meta in synced_artifacts:
                        sync_meta["latest_artifacts"] = latest_artifacts_map
                        sync_event = HarnessEvent(
                            type=EventType.TOOL_RESULT,
                            tool_name="workspace_sync",
                            tool_output=sync_meta,
                            content=(
                                f"Artefato '{sync_meta['artifact_type']}' sincronizado "
                                f"como revisão v{sync_meta['version_num']} ({sync_meta['source_file']})."
                            ),
                            harness=harness_kind,
                            metadata=sync_meta,
                        )
                        tool_results_log.append(
                            {
                                "tool_name": "workspace_sync",
                                "tool_call_id": None,
                                "tool_output": sync_meta,
                                "content": sync_event.content,
                                "metadata": dict(sync_meta),
                            }
                        )
                        yield sync_event
                else:
                    # Gate 1: nunca sincroniza artefatos finais e só emite gate_request se houve conteúdo útil
                    if not saw_gate_request and text_parts:
                        saw_gate_request = True
                        yield HarnessEvent(
                            type=EventType.GATE_REQUEST,
                            content=(
                                "Análise concluída em Gate 1. Aguardando autorização expressa "
                                "do usuário para gerar os artefatos finais."
                            ),
                            harness=harness_kind,
                            metadata={
                                "phase": phase,
                                "gate_name": gate_name,
                                "gate_authorized": False,
                            },
                        )

            assistant_text = "".join(text_parts).strip()
            if not assistant_text:
                if cancelled:
                    assistant_text = "Execução cancelada pelo usuário."
                elif synced_artifacts:
                    first = synced_artifacts[0]
                    assistant_text = (
                        f"Artefato '{first['artifact_type']}' sincronizado como "
                        f"revisão v{first['version_num']}."
                    )
                elif saw_gate_request:
                    assistant_text = "Análise concluída. Aguardando aprovação para prosseguir ao Gate 2."

            assistant_metadata: dict[str, Any] = {
                "harness": harness_kind.value,
                "model": model,
                "phase": phase,
                "gate_name": gate_name,
                "gate_authorized": gate_authorized,
                "thoughts": "".join(thought_parts),
                "tool_calls": tool_calls_log,
                "tool_results": tool_results_log,
                "gate_requested": saw_gate_request,
                "synced_artifacts": synced_artifacts,
                "cancelled": cancelled,
                "had_error": had_error,
            }

            saved_assistant_msg: ChatMessageRead | None = None
            if assistant_text or thought_parts or tool_calls_log or synced_artifacts or saw_gate_request:
                saved_assistant_msg = self.workspace_service.add_chat_message(
                    project_id,
                    ChatMessageCreate(
                        phase=phase,
                        role="assistant",
                        content=assistant_text,
                        metadata=assistant_metadata,
                    ),
                )

            latest_proj_state = self.workspace_service.get_project(project_id)
            final_done_meta = dict(buffered_done.metadata) if buffered_done is not None else {}
            final_done_meta.update(
                {
                    "phase": phase,
                    "gate_name": gate_name,
                    "gate_authorized": gate_authorized,
                    "gate_requested": saw_gate_request,
                    "synced_artifacts": synced_artifacts,
                    "latest_artifacts": dict(latest_proj_state.latest_artifacts),
                    "cancelled": cancelled,
                    "had_error": had_error,
                }
            )
            if saved_assistant_msg is not None:
                final_done_meta["assistant_message_id"] = saved_assistant_msg.id

            yield HarnessEvent(
                type=EventType.DONE,
                content=buffered_done.content if buffered_done is not None else "",
                harness=harness_kind,
                metadata=final_done_meta,
            )
        finally:
            if not cancel_wait_task.done():
                cancel_wait_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_wait_task
            if hasattr(aiter, "aclose"):
                with contextlib.suppress(Exception):
                    await aiter.aclose()
            if self._active_runs.get(project_id) is active_run:
                self._active_runs.pop(project_id, None)

    @staticmethod
    def _attach_tool_result(
        tool_calls_log: list[dict[str, Any]],
        result_record: dict[str, Any],
    ) -> None:
        """Associa `tool_result` ao `tool_call` correspondente (por `tool_call_id` ou último aberto)."""
        call_id = result_record.get("tool_call_id")
        tool_name = result_record.get("tool_name")
        meta = result_record.get("metadata")
        has_err = isinstance(meta, dict) and bool(meta.get("error") or meta.get("is_error"))
        final_status = "error" if has_err else "completed"

        if call_id:
            for item in reversed(tool_calls_log):
                if item.get("tool_call_id") == call_id:
                    item["tool_output"] = result_record.get("tool_output")
                    item["result_content"] = result_record.get("content", "")
                    item["status"] = final_status
                    if has_err and isinstance(meta, dict) and meta.get("error"):
                        item["error_message"] = str(meta["error"])
                    return

        for item in reversed(tool_calls_log):
            if item.get("status") == "running" and (
                not tool_name or item.get("tool_name") == tool_name
            ):
                item["tool_output"] = result_record.get("tool_output")
                item["result_content"] = result_record.get("content", "")
                item["status"] = final_status
                if has_err and isinstance(meta, dict) and meta.get("error"):
                    item["error_message"] = str(meta["error"])
                return

    # -------------------------------------------------------------------------
    # Aprovação de Gate, Cancelamento e Status do Agente
    # -------------------------------------------------------------------------

    def authorize_gate(
        self,
        project_id: str,
        phase: PhaseKind,
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Aprova explicitamente o gate da fase (`gate1_json` para `extraction`, `gate3_jrxml`
        para `jrxml`) no `WorkspaceService` e registra a decisão no histórico de chat.
        """
        gate_name = self.get_gate_for_phase(phase)
        self.workspace_service.get_project(project_id)

        clean_notes = notes.strip()
        gate = self.workspace_service.update_gate(
            project_id,
            gate_name,
            GateApprovalUpdate(
                status="approved",
                decided_by="user",
                notes=clean_notes or f"Gate '{gate_name}' autorizado para geração na fase '{phase}'.",
            ),
        )

        msg_content = f"Gate '{gate_name}' autorizado pelo usuário para prosseguir ao Gate 2."
        if clean_notes:
            msg_content = f"{msg_content} Observações: {clean_notes}"

        message = self.workspace_service.add_chat_message(
            project_id,
            ChatMessageCreate(
                phase=phase,
                role="system",
                content=msg_content,
                metadata={
                    "type": "gate_authorization",
                    "gate_name": gate_name,
                    "status": "approved",
                    "notes": clean_notes,
                },
            ),
        )

        return {
            "ok": True,
            "gate": gate,
            "message": message,
        }

    def cancel_run(self, project_id: str) -> bool:
        """Cancela a execução ativa do agente para o projeto, retornando se havia run ativo."""
        self.workspace_service.get_project(project_id)
        active = self._active_runs.get(project_id)
        if active is None or active.cancel_event.is_set():
            return False
        active.cancel_event.set()
        return True

    def _count_pending_visual_feedback(self, project_id: str) -> int:
        """
        Conta anotações `visual_region_feedback` da fase `jrxml` criadas após a última
        resposta do assistente (ou todas, caso o assistente ainda não tenha respondido).
        """
        messages = self.workspace_service.list_chat_messages(project_id, phase="jrxml")
        pending = 0
        for msg in reversed(messages):
            if msg.role == "assistant":
                break
            if isinstance(msg.metadata, dict) and msg.metadata.get("type") == "visual_region_feedback":
                pending += 1
        return pending

    def get_agent_status(self, project_id: str) -> dict[str, Any]:
        """Retorna diagnóstico completo do agente, harnesses, gates e feedbacks visuais pendentes."""
        project = self.workspace_service.get_project(project_id)
        statuses = self.harness_registry.list_statuses()
        serialized_harnesses = [
            st.model_dump(mode="json") if hasattr(st, "model_dump") else dict(st)
            for st in statuses
        ]
        serialized_gates = [g.model_dump(mode="json") for g in project.gates]

        return {
            "project_id": project.id,
            "active_run": project_id in self._active_runs,
            "preferred_harness": project.preferred_harness,
            "harnesses": serialized_harnesses,
            "gates": serialized_gates,
            "pending_visual_feedback_count": self._count_pending_visual_feedback(project_id),
        }
