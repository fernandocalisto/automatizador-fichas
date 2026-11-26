# -*- coding: utf-8 -*-
"""Registro central dos 4 Harnesses suportados pelo Salutem Ficha Studio."""

from __future__ import annotations

from collections.abc import Sequence

from app.harnesses.agy_harness import AgyHarness
from app.harnesses.base import AgentHarness
from app.harnesses.claude_harness import ClaudeCodeHarness
from app.harnesses.codex_harness import CodexHarness
from app.harnesses.opencode_harness import OpenCodeHarness
from app.harnesses.types import HarnessKind, HarnessStatus


class HarnessRegistry:
    """
    Catálogo unificado dos 4 adaptadores de agentes (`agy`, `opencode`, `claude`, `codex`),
    responsável por listar diagnósticos de instalação e resolver o harness ativo.
    """

    def __init__(self, harnesses: Sequence[AgentHarness] | None = None) -> None:
        self._harnesses: dict[HarnessKind, AgentHarness] = {}
        initial = (
            list(harnesses)
            if harnesses is not None
            else [
                AgyHarness(),
                OpenCodeHarness(),
                ClaudeCodeHarness(),
                CodexHarness(),
            ]
        )
        for harness in initial:
            self.register(harness)

    def register(self, harness: AgentHarness) -> None:
        """Registra ou substitui um adaptador no catálogo."""
        self._harnesses[HarnessKind(harness.kind)] = harness

    def list_ids(self) -> list[HarnessKind]:
        """Retorna a lista ordenada dos identificadores registrados."""
        return list(self._harnesses.keys())

    def get(self, harness_id: str | HarnessKind) -> AgentHarness:
        """Obtém o adaptador correspondente a `harness_id` ou levanta `KeyError`."""
        try:
            kind = HarnessKind(harness_id)
        except ValueError as exc:
            valid = ", ".join(k.value for k in self._harnesses)
            raise KeyError(
                f"Harness desconhecido '{harness_id}'. Opções válidas: {valid}"
            ) from exc

        if kind not in self._harnesses:
            raise KeyError(f"Harness '{kind.value}' não está registrado neste catálogo.")
        return self._harnesses[kind]

    def list_statuses(self) -> list[HarnessStatus]:
        """Consulta e retorna o `HarnessStatus` atualizado de todos os harnesses registrados."""
        return [harness.check_status() for harness in self._harnesses.values()]

    def get_default_available(self) -> AgentHarness | None:
        """
        Retorna o primeiro harness disponível na ordem de prioridade
        (`agy` -> `opencode` -> `claude` -> `codex`), ou `None` se nenhum estiver instalado.
        """
        for harness in self._harnesses.values():
            status = harness.check_status()
            if status.installed or status.sdk_available:
                return harness
        return None


_DEFAULT_REGISTRY: HarnessRegistry | None = None


def get_default_registry() -> HarnessRegistry:
    """Retorna a instância padrão compartilhada do `HarnessRegistry`."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = HarnessRegistry()
    return _DEFAULT_REGISTRY
