# -*- coding: utf-8 -*-
"""
Página de Configurações de Conexões PostgreSQL (src/gui/settings/pages/connections_page.py).

Página estrutural para gerenciamento de perfis de conexão PostgreSQL (Spec 03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class ConnectionsPage(QWidget):
    """Página 'Conexões' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações de Conexões")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Conexões de Banco de Dados (PostgreSQL)", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        grp = QGroupBox("Perfis Cadastrados", self)
        grp_layout = QVBoxLayout(grp)
        grp_layout.setContentsMargins(12, 16, 12, 12)
        grp_layout.setSpacing(10)

        self.lst_connections = QListWidget(grp)
        self.lst_connections.setAccessibleName("Lista de Perfis de Conexão")
        self.lst_connections.addItem("Localhost — PostgreSQL (Desconectado)")
        grp_layout.addWidget(self.lst_connections, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_add = QPushButton("Nova Conexão", grp)
        self.btn_add.setProperty("variant", "primary")
        self.btn_add.setToolTip("Adicionar novo perfil de conexão PostgreSQL")
        self.btn_test = QPushButton("Testar Selecionada", grp)
        self.btn_test.setToolTip("Testar conectividade com o banco selecionado")
        self.btn_remove = QPushButton("Remover", grp)
        self.btn_remove.setToolTip("Remover perfil selecionado")

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(self.btn_remove)
        btn_row.addStretch(1)
        grp_layout.addLayout(btn_row)

        layout.addWidget(grp, 1)

    def load_from_config(self, config: AppConfig) -> None:
        """Sincroniza estado de conexões (gerenciado separadamente)."""

    def apply_to_config(self, config: AppConfig) -> None:
        """Persiste alterações de conexões."""
