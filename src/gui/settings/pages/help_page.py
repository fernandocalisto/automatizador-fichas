# -*- coding: utf-8 -*-
"""
Página de Ajuda e Atalhos no Diálogo de Configurações (src/gui/settings/pages/help_page.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from src.services.help_service import DEFAULT_SHORTCUTS, HelpService

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class HelpPage(QWidget):
    """Página 'Ajuda' do diálogo de configurações."""

    def __init__(
        self,
        help_service: HelpService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._help_service = help_service or HelpService()
        self.setAccessibleName("Ajuda e Atalhos")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Ajuda, Documentação e Atalhos", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        grp_shortcuts = QGroupBox("Atalhos de Teclado", self)
        v_short = QVBoxLayout(grp_shortcuts)
        v_short.setContentsMargins(12, 16, 12, 12)

        shortcuts = self._help_service.get_shortcuts() or DEFAULT_SHORTCUTS
        self.tbl_shortcuts = QTableWidget(len(shortcuts), 2, grp_shortcuts)
        self.tbl_shortcuts.setHorizontalHeaderLabels(["Atalho", "Ação"])
        self.tbl_shortcuts.verticalHeader().setVisible(False)
        self.tbl_shortcuts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_shortcuts.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tbl_shortcuts.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        for row_idx, (key, desc) in enumerate(shortcuts):
            self.tbl_shortcuts.setItem(row_idx, 0, QTableWidgetItem(key))
            self.tbl_shortcuts.setItem(row_idx, 1, QTableWidgetItem(desc))

        v_short.addWidget(self.tbl_shortcuts)
        layout.addWidget(grp_shortcuts, 1)

        self.btn_open_github = QPushButton("Abrir Repositório no GitHub", self)
        self.btn_open_github.setToolTip("Abre a documentação oficial no navegador")
        self.btn_open_github.clicked.connect(self._help_service.open_github_repository)
        layout.addWidget(self.btn_open_github)

    def load_from_config(self, config: AppConfig) -> None:
        """Compatibilidade de ciclo de vida com `SettingsDialog`."""

    def apply_to_config(self, config: AppConfig) -> None:
        """Compatibilidade de ciclo de vida com `SettingsDialog`."""
