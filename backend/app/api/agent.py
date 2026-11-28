# -*- coding: utf-8 -*-
"""FastAPI router para orquestração de agentes de IA com streaming SSE e WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import HTTPConnection

from backend.app.db.schemas import AgentSessionRead, ChatMessageRead, ChatPhase, GateApprovalRead
from backend.app.harnesses import (
    VALID_EFFORT_LEVELS,
    EventType,
    HarnessEvent,
    PhaseKind,
    get_default_registry,
)
from backend.app.services.agent_orchestrator import (
    AgentOrchestratorService,
    UnknownHarnessError,
)
from backend.app.services.workspace_service import (
    ProjectNotFoundError,
    WorkspaceService,
    WorkspaceValidationError,
)

router = APIRouter(prefix="/api/projects", tags=["agent"])


# -----------------------------------------------------------------------------
# Schemas Pydantic
# -----------------------------------------------------------------------------


def _normalize_optional_model(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _validate_optional_effort(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    if cleaned not in VALID_EFFORT_LEVELS:
        raise ValueError(
            f"Nível de esforço inválido '{value}'. Esperado: {', '.join(VALID_EFFORT_LEVELS)}."
        )
    return cleaned


class AgentStreamRequest(BaseModel):
    """Payload de disparo de um turno de agente via SSE ou WebSocket."""

    model_config = ConfigDict(extra="ignore")

    phase: PhaseKind
    prompt: str = Field(..., min_length=1)
    harness_id: str | None = None
    model: str | None = None
    effort: str | None = None
    gate_authorized: bool = False
    timeout_seconds: float = Field(default=300.0, gt=0.0, le=3600.0)

    @field_validator("model", mode="before")
    @classmethod
    def _clean_model(cls, value: Any) -> str | None:
        return _normalize_optional_model(value)

    @field_validator("effort", mode="before")
    @classmethod
    def _clean_effort(cls, value: Any) -> str | None:
        return _validate_optional_effort(value)


AgentRunPayload = AgentStreamRequest


class AgentWarmupRequest(BaseModel):
    """Payload opcional para pré-aquecimento de sessão persistente do agente (ex.: AGY)."""

    model_config = ConfigDict(extra="ignore")

    phase: PhaseKind = "jrxml"
    harness: str | None = None
    harness_id: str | None = None
    model: str | None = None
    effort: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _clean_model(cls, value: Any) -> str | None:
        return _normalize_optional_model(value)

    @field_validator("effort", mode="before")
    @classmethod
    def _clean_effort(cls, value: Any) -> str | None:
        return _validate_optional_effort(value)


class AuthorizeGateRequest(BaseModel):
    """Payload para aprovação explícita do gate da fase (`extraction` ou `jrxml`)."""

    model_config = ConfigDict(extra="ignore")

    phase: PhaseKind
    notes: str = ""


class AuthorizeGateResponse(BaseModel):
    """Resposta da aprovação de gate com registro atualizado e mensagem de chat."""

    ok: bool = True
    gate: GateApprovalRead
    message: ChatMessageRead


class CancelAgentResponse(BaseModel):
    """Resposta do pedido de cancelamento de turno ativo do agente."""

    ok: bool = True
    cancelled: bool


# -----------------------------------------------------------------------------
# Dependência Injetável (compatível com HTTP e WebSocket)
# -----------------------------------------------------------------------------


def get_agent_orchestrator(request: HTTPConnection) -> AgentOrchestratorService:
    """
    Resolve a instância compartilhada de `AgentOrchestratorService` em `app.state.agent_orchestrator`,
    permitindo fácil injeção em produção (`main.py`) ou override em testes.
    """
    existing = getattr(request.app.state, "agent_orchestrator", None)
    if isinstance(existing, AgentOrchestratorService):
        return existing

    workspace_service = getattr(request.app.state, "workspace_service", None)
    if not isinstance(workspace_service, WorkspaceService):
        workspace_service = WorkspaceService()
        request.app.state.workspace_service = workspace_service

    harness_registry = getattr(request.app.state, "harness_registry", None)
    if harness_registry is None:
        harness_registry = get_default_registry()

    orchestrator = AgentOrchestratorService(
        workspace_service=workspace_service,
        harness_registry=harness_registry,
    )
    request.app.state.agent_orchestrator = orchestrator
    return orchestrator


AgentOrchestratorDep = Annotated[AgentOrchestratorService, Depends(get_agent_orchestrator)]


def _raise_http_for_agent_error(exc: Exception) -> None:
    if isinstance(exc, ProjectNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, (UnknownHarnessError, WorkspaceValidationError)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise exc


# -----------------------------------------------------------------------------
# Endpoints REST & SSE
# -----------------------------------------------------------------------------


@router.get("/{project_id}/agent/status")
def get_project_agent_status(
    project_id: str,
    orchestrator: AgentOrchestratorDep,
) -> dict[str, Any]:
    """Retorna status do agente, harnesses instalados, gates e feedbacks visuais pendentes."""
    try:
        return orchestrator.get_agent_status(project_id)
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


@router.post("/{project_id}/agent/stream")
async def stream_project_agent(
    project_id: str,
    payload: AgentStreamRequest,
    orchestrator: AgentOrchestratorDep,
) -> StreamingResponse:
    """Executa um turno de agente e faz streaming de eventos normalizados via Server-Sent Events."""
    try:
        orchestrator.validate_turn_request(
            project_id,
            phase=payload.phase,
            harness_id=payload.harness_id,
        )
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise

    async def _sse_generator() -> AsyncIterator[str]:
        async for event in orchestrator.stream_turn(
            project_id,
            phase=payload.phase,
            prompt=payload.prompt,
            harness_id=payload.harness_id,
            model=payload.model,
            effort=payload.effort,
            explicit_gate_authorized=payload.gate_authorized,
            timeout_seconds=payload.timeout_seconds,
        ):
            yield event.to_sse()

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{project_id}/agent/authorize-gate", response_model=AuthorizeGateResponse)
def authorize_project_agent_gate(
    project_id: str,
    payload: AuthorizeGateRequest,
    orchestrator: AgentOrchestratorDep,
) -> AuthorizeGateResponse:
    """Aprova explicitamente o gate da fase (`gate1_json` ou `gate3_jrxml`) e registra no chat."""
    try:
        result = orchestrator.authorize_gate(
            project_id,
            phase=payload.phase,
            notes=payload.notes,
        )
        return AuthorizeGateResponse(**result)
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


@router.post("/{project_id}/agent/cancel", response_model=CancelAgentResponse)
def cancel_project_agent(
    project_id: str,
    orchestrator: AgentOrchestratorDep,
) -> CancelAgentResponse:
    """Cancela a execução ativa do agente para o projeto informado."""
    try:
        cancelled = orchestrator.cancel_run(project_id)
        return CancelAgentResponse(ok=True, cancelled=cancelled)
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


@router.get("/{project_id}/agent/sessions", response_model=list[AgentSessionRead])
def list_project_agent_sessions(
    project_id: str,
    orchestrator: AgentOrchestratorDep,
) -> list[AgentSessionRead]:
    """Lista todas as sessões persistidas dos harnesses de IA para o projeto."""
    try:
        return orchestrator.list_sessions(project_id)
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


@router.post("/{project_id}/agent/warmup")
async def warmup_project_agent(
    project_id: str,
    orchestrator: AgentOrchestratorDep,
    payload: AgentWarmupRequest = Body(default_factory=AgentWarmupRequest),
) -> dict[str, Any]:
    """Pré-aquece o subprocesso persistente do agente (ex.: AGY) em background para eliminar latência inicial."""
    requested_harness = payload.harness_id or payload.harness
    try:
        return await orchestrator.warmup_agent(
            project_id,
            phase=payload.phase,
            harness_id=requested_harness,
            model=payload.model,
            effort=payload.effort,
        )
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


@router.delete("/{project_id}/agent/session")
async def reset_project_agent_session(
    project_id: str,
    orchestrator: AgentOrchestratorDep,
    phase: ChatPhase | None = Query(default=None),
    harness_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Remove sessão(ões) persistida(s) e encerra processos persistentes aquecidos para iniciar conversa limpa."""
    try:
        deleted = orchestrator.reset_session(
            project_id,
            phase=phase,
            harness_id=harness_id,
        )
        closed_warm = await orchestrator.close_warm_sessions(
            project_id,
            harness_id=harness_id,
        )
        return {
            "ok": True,
            "project_id": project_id,
            "phase": phase,
            "harness_id": harness_id,
            "deleted": deleted,
            "closed_warm_sessions": closed_warm,
        }
    except Exception as exc:
        _raise_http_for_agent_error(exc)
        raise


# -----------------------------------------------------------------------------
# Endpoint WebSocket Bidirecional
# -----------------------------------------------------------------------------


@router.websocket("/{project_id}/agent/ws")
async def project_agent_websocket(
    websocket: WebSocket,
    project_id: str,
    orchestrator: AgentOrchestratorDep,
) -> None:
    """
    Canal WebSocket bidirecional para o painel de chat do agente:
    - `{type: "send_message", phase, prompt, harness_id?, model?, gate_authorized?, timeout_seconds?}`
    - `{type: "authorize_gate", phase, notes?}`
    - `{type: "cancel"}`
    Envia cada `HarnessEvent.model_dump(mode="json")` em tempo real.
    """
    await websocket.accept()

    send_lock = asyncio.Lock()

    async def _safe_send_json(data: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(data)

    try:
        orchestrator.workspace_service.get_project(project_id)
    except ProjectNotFoundError as exc:
        await _safe_send_json(
            HarnessEvent(
                type=EventType.ERROR,
                content=str(exc),
                metadata={"status_code": 404},
            ).model_dump(mode="json")
        )
        await websocket.close(code=4404, reason="Project not found")
        return

    active_stream_task: asyncio.Task[None] | None = None

    async def _run_ws_turn(msg: dict[str, Any]) -> None:
        try:
            req = AgentStreamRequest.model_validate(msg)
            orchestrator.validate_turn_request(
                project_id,
                phase=req.phase,
                harness_id=req.harness_id,
            )
        except Exception as exc:
            status_code = 404 if isinstance(exc, ProjectNotFoundError) else 400
            await _safe_send_json(
                HarnessEvent(
                    type=EventType.ERROR,
                    content=str(exc),
                    metadata={"status_code": status_code},
                ).model_dump(mode="json")
            )
            await _safe_send_json(
                HarnessEvent(
                    type=EventType.DONE,
                    metadata={"had_error": True},
                ).model_dump(mode="json")
            )
            return

        try:
            async for event in orchestrator.stream_turn(
                project_id,
                phase=req.phase,
                prompt=req.prompt,
                harness_id=req.harness_id,
                model=req.model,
                effort=req.effort,
                explicit_gate_authorized=req.gate_authorized,
                timeout_seconds=req.timeout_seconds,
            ):
                await _safe_send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            orchestrator.cancel_run(project_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await _safe_send_json(
                    HarnessEvent(
                        type=EventType.ERROR,
                        content=str(exc),
                    ).model_dump(mode="json")
                )

    try:
        while True:
            raw_msg = await websocket.receive_json()
            if not isinstance(raw_msg, dict):
                await _safe_send_json(
                    HarnessEvent(
                        type=EventType.ERROR,
                        content="Mensagem WebSocket deve ser um objeto JSON.",
                    ).model_dump(mode="json")
                )
                continue

            msg_type = str(raw_msg.get("type") or "").strip().lower()

            if msg_type == "send_message":
                if active_stream_task is not None and not active_stream_task.done():
                    orchestrator.cancel_run(project_id)
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await active_stream_task
                active_stream_task = asyncio.create_task(_run_ws_turn(raw_msg))

            elif msg_type == "authorize_gate":
                try:
                    gate_req = AuthorizeGateRequest.model_validate(raw_msg)
                    res = orchestrator.authorize_gate(
                        project_id,
                        phase=gate_req.phase,
                        notes=gate_req.notes,
                    )
                    await _safe_send_json(
                        {
                            "type": "gate_authorized",
                            "ok": True,
                            "gate": res["gate"].model_dump(mode="json"),
                            "message": res["message"].model_dump(mode="json"),
                        }
                    )
                except Exception as exc:
                    status_code = 404 if isinstance(exc, ProjectNotFoundError) else 400
                    await _safe_send_json(
                        HarnessEvent(
                            type=EventType.ERROR,
                            content=str(exc),
                            metadata={"status_code": status_code},
                        ).model_dump(mode="json")
                    )

            elif msg_type == "cancel":
                cancelled = orchestrator.cancel_run(project_id)
                await _safe_send_json(
                    {
                        "type": "cancelled",
                        "ok": True,
                        "cancelled": cancelled,
                    }
                )

            else:
                await _safe_send_json(
                    HarnessEvent(
                        type=EventType.ERROR,
                        content=f"Tipo de mensagem WebSocket desconhecido: '{msg_type}'.",
                    ).model_dump(mode="json")
                )
    except WebSocketDisconnect:
        if active_stream_task is not None and not active_stream_task.done():
            orchestrator.cancel_run(project_id)
            active_stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active_stream_task
    finally:
        if active_stream_task is not None and not active_stream_task.done():
            orchestrator.cancel_run(project_id)
            active_stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active_stream_task
