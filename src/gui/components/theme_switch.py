# -*- coding: utf-8 -*-
"""
Componente de Alternância de Tema (src/gui/components/theme_switch.py).

Implementa `ThemeSwitch(QToolButton)` para a barra de ferramentas com menu popup
contendo as opções Claro (`light`), Escuro (`dark`) e Sistema (`system`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

if TYPE_CHECKING:
    from src.services.theme_service import ThemeService

THEME_LABELS: dict[str, str] = {
    "light": "Claro",
    "dark": "Escuro",
    "system": "Sistema",
}


class ThemeSwitch(QToolButton):
    """
    Botão de barra de ferramentas com menu popup para troca rápida de tema
    (`Claro`, `Escuro`, `Sistema`).

    Signals:
        theme_selected (str): Emitido quando o usuário seleciona um tema (`light`, `dark`, `system`).
    """

    theme_selected = Signal(str)

    def __init__(
        self,
        theme_service: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_service = theme_service
        self.setAccessibleName("Alternar Tema da Aplicação")
        self.setToolTip("Alternar tema da aplicação (Claro / Escuro / Sistema)")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._menu = QMenu(self)
        self._action_group = QActionGroup(self)
        self._action_group.setExclusive(True)
        self._actions: dict[str, QAction] = {}

        for key, label in THEME_LABELS.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(key)
            action.triggered.connect(lambda checked=False, k=key: self._on_theme_triggered(k))
            self._action_group.addAction(action)
            self._menu.addAction(action)
            self._actions[key] = action

        self.setMenu(self._menu)

        initial_theme = (
            self._theme_service.current_app_theme()
            if self._theme_service is not None
            else "system"
        )
        self.set_current_theme(initial_theme)

        if self._theme_service is not None:
            self._theme_service.app_theme_changed.connect(self.set_current_theme)

    def _on_theme_triggered(self, theme_key: str) -> None:
        """Aplica o tema selecionado no `ThemeService` e emite `theme_selected`."""
        self.set_current_theme(theme_key)
        if self._theme_service is not None:
            self._theme_service.apply_app_theme(theme_key)
        self.theme_selected.emit(theme_key)

    def set_current_theme(self, theme_key: str) -> None:
        """Atualiza o estado marcado do menu e o texto do botão."""
        normalized = theme_key.strip().lower()
        if normalized not in self._actions:
            normalized = "system"

        action = self._actions[normalized]
        action.setChecked(True)
        label = THEME_LABELS.get(normalized, "Sistema")
        self.setText(f"Tema: {label}")
