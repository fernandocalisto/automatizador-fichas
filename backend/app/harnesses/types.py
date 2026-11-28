# -*- coding: utf-8 -*-
"""Tipos unificados, eventos de streaming e contratos de execução dos Harnesses de IA."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HarnessKind(str, Enum):
    """Identificadores canônicos dos 4 harnesses de agentes suportados pelo Studio."""

    AGY = "agy"
    OPENCODE = "opencode"
    CLAUDE = "claude"
    CODEX = "codex"


class EventType(str, Enum):
    """Tipos de eventos normalizados emitidos em tempo real por qualquer harness."""

    TEXT_DELTA = "text_delta"
    THOUGHT_DELTA = "thought_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    GATE_REQUEST = "gate_request"
    ERROR = "error"
    DONE = "done"


PhaseKind = Literal["extraction", "jrxml"]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
VALID_EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


class HarnessEvent(BaseModel):
    """Evento individual do stream unificado (compatível com serialização SSE JSON)."""

    model_config = ConfigDict(extra="ignore")

    type: EventType
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_output: Any = None
    harness: HarnessKind | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        """Formata o evento no padrão Server-Sent Events (`event: <type>\\ndata: <json>\\n\\n`)."""
        payload = self.model_dump_json(exclude_none=True)
        return f"event: {self.type.value}\ndata: {payload}\n\n"


class HarnessStatus(BaseModel):
    """Diagnóstico de instalação, capacidades e autenticação de um harness local."""

    model_config = ConfigDict(extra="ignore")

    id: HarnessKind
    display_name: str
    installed: bool
    executable_path: str | None = None
    sdk_available: bool = False
    version: str | None = None
    auth_hint: str = ""
    supports_vision: bool = True
    supports_mcp: bool = True

    @property
    def is_available(self) -> bool:
        """Indica se o harness está pronto para uso (via CLI/servidor instalado ou SDK Python)."""
        return bool(self.installed or self.sdk_available)


class HarnessRunRequest(BaseModel):
    """Requisição de execução de turno para uma fase do Salutem Ficha Studio."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace_dir: Path
    phase: PhaseKind
    prompt: str
    gate_authorized: bool = False
    model: str | None = None
    effort: str | None = None
    image_paths: list[Path] = Field(default_factory=list)
    extra_context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 300.0
    system_prompt_override: str | None = None
    resume_session_id: str | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _normalize_model(cls, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("effort", mode="before")
    @classmethod
    def _validate_effort(cls, value: Any) -> str | None:
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
