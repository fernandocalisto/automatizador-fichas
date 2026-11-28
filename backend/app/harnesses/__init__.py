# -*- coding: utf-8 -*-
"""Pacote unificado de Harnesses de IA do Salutem Ficha Studio."""

from __future__ import annotations

from backend.app.harnesses.agy_harness import (
    AgyHarness,
    AgyPersistentSessionPool,
    get_agy_session_pool,
)
from backend.app.harnesses.base import (
    AgentHarness,
    BaseSubprocessHarness,
    SubprocessChunk,
    SubprocessRunner,
    compose_delta_system_prompt,
    compose_phase_system_prompt,
    compose_user_prompt_with_context,
    default_subprocess_runner,
    load_phase_skill_markdown,
)
from backend.app.harnesses.claude_harness import ClaudeCodeHarness
from backend.app.harnesses.codex_harness import CodexHarness
from backend.app.harnesses.opencode_harness import OpenCodeHarness
from backend.app.harnesses.registry import HarnessRegistry, get_default_registry
from backend.app.harnesses.types import (
    VALID_EFFORT_LEVELS,
    EffortLevel,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
    PhaseKind,
)

__all__ = [
    "AgentHarness",
    "AgyHarness",
    "AgyPersistentSessionPool",
    "BaseSubprocessHarness",
    "ClaudeCodeHarness",
    "CodexHarness",
    "EffortLevel",
    "EventType",
    "HarnessEvent",
    "HarnessKind",
    "HarnessRegistry",
    "HarnessRunRequest",
    "HarnessStatus",
    "OpenCodeHarness",
    "PhaseKind",
    "SubprocessChunk",
    "SubprocessRunner",
    "VALID_EFFORT_LEVELS",
    "compose_delta_system_prompt",
    "compose_phase_system_prompt",
    "compose_user_prompt_with_context",
    "default_subprocess_runner",
    "get_agy_session_pool",
    "get_default_registry",
    "load_phase_skill_markdown",
]
