# -*- coding: utf-8 -*-
"""Pacote unificado de Harnesses de IA do Salutem Ficha Studio."""

from __future__ import annotations

from app.harnesses.agy_harness import AgyHarness
from app.harnesses.base import (
    AgentHarness,
    BaseSubprocessHarness,
    SubprocessChunk,
    SubprocessRunner,
    compose_phase_system_prompt,
    compose_user_prompt_with_context,
    default_subprocess_runner,
    load_phase_skill_markdown,
)
from app.harnesses.claude_harness import ClaudeCodeHarness
from app.harnesses.codex_harness import CodexHarness
from app.harnesses.opencode_harness import OpenCodeHarness
from app.harnesses.registry import HarnessRegistry, get_default_registry
from app.harnesses.types import (
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
    "BaseSubprocessHarness",
    "ClaudeCodeHarness",
    "CodexHarness",
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
    "compose_phase_system_prompt",
    "compose_user_prompt_with_context",
    "default_subprocess_runner",
    "get_default_registry",
    "load_phase_skill_markdown",
]
