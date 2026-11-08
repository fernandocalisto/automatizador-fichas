# -*- coding: utf-8 -*-
"""
Serviço de Ajuda e Documentação Contextual (src/services/help_service.py).

Placeholder para Spec 00 (Foundation) com suporte a tópicos básicos, atalhos
de teclado e abertura de documentação.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

logger = logging.getLogger("services.help_service")

DEFAULT_SHORTCUTS: list[tuple[str, str]] = [
    ("Ctrl+N", "Novo JSON"),
    ("Ctrl+O", "Abrir arquivo JSON"),
    ("Ctrl+S", "Salvar arquivo JSON"),
    ("Ctrl+Z", "Desfazer"),
    ("Ctrl+Y", "Refazer"),
    ("Ctrl+F", "Buscar"),
    ("Ctrl+H", "Substituir"),
    ("Ctrl+,", "Abrir Configurações"),
    ("F1", "Como Usar / Ajuda Contextual"),
]


class HelpService:
    """Serviço de suporte à documentação, atalhos e ajuda contextual (placeholder v0.2.0)."""

    GITHUB_URL = "https://github.com/FernandoCalisto/Automatizador-de-Fichas"

    def __init__(self) -> None:
        self._topics: dict[str, str] = {
            "getting_started": (
                "1. Baixe a SKILL.md na Tela Inicial e envie junto com o PDF para a IA.\n"
                "2. Carregue ou cole o JSON estruturado na ferramenta.\n"
                "3. Revise as Perguntas & Respostas e gere os scripts SQL INSERT e SELECT Jasper."
            ),
            "shortcuts": "\n".join(f"{key}: {desc}" for key, desc in DEFAULT_SHORTCUTS),
        }

    def get_topic(self, topic_id: str) -> str:
        """Retorna o texto de ajuda para um tópico específico."""
        return self._topics.get(topic_id, "Tópico de ajuda não encontrado.")

    def get_shortcuts(self) -> list[tuple[str, str]]:
        """Retorna a lista de atalhos de teclado `(atalho, descrição)`."""
        return list(DEFAULT_SHORTCUTS)

    def open_github_repository(self) -> bool:
        """Abre a página do repositório no navegador padrão do sistema."""
        logger.info("Abrindo repositório GitHub: %s", self.GITHUB_URL)
        return QDesktopServices.openUrl(QUrl(self.GITHUB_URL))

    def show_context_help(self, context_key: str = "getting_started") -> dict[str, Any]:
        """Retorna metadados de ajuda contextual para exibição pela UI."""
        return {
            "key": context_key,
            "content": self.get_topic(context_key),
            "shortcuts": self.get_shortcuts(),
        }
