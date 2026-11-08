# -*- coding: utf-8 -*-
"""
Página de Configurações Gerais (src/gui/settings/pages/general_page.py).

Configura idioma (`language`), verificação automática de atualizações (`auto_check_updates`),
exibição do tour inicial (`show_tour_on_startup`) e nível de log global (`log_level`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class GeneralPage(QWidget):
    """Página 'Geral' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações Gerais")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Configurações Gerais", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        # Grupo: Preferências da Aplicação
        grp_app = QGroupBox("Preferências da Aplicação", self)
        form_app = QFormLayout(grp_app)
        form_app.setContentsMargins(12, 16, 12, 12)
        form_app.setSpacing(10)

        self.cmb_language = QComboBox(grp_app)
        self.cmb_language.addItem("Português (Brasil) — pt_BR", "pt_BR")
        self.cmb_language.addItem("English (US) — en_US", "en_US")
        self.cmb_language.setAccessibleName("Idioma da Interface")
        self.cmb_language.setToolTip("Selecione o idioma da interface da aplicação")
        self.cmb_language.setMaximumWidth(240)
        form_app.addRow("Idioma:", self.cmb_language)

        self.chk_auto_updates = QCheckBox("Verificar atualizações automaticamente ao iniciar", grp_app)
        self.chk_auto_updates.setAccessibleName("Verificar atualizações automaticamente")
        self.chk_auto_updates.setToolTip("Consulta se há novas versões ao abrir o aplicativo")
        form_app.addRow(self.chk_auto_updates)

        self.chk_show_tour = QCheckBox("Exibir tour guiado de boas-vindas ao iniciar", grp_app)
        self.chk_show_tour.setAccessibleName("Exibir tour ao iniciar")
        self.chk_show_tour.setToolTip("Mostra dicas rápidas de uso na inicialização")
        form_app.addRow(self.chk_show_tour)

        layout.addWidget(grp_app)

        # Grupo: Diagnóstico e Logging
        grp_log = QGroupBox("Diagnóstico e Logging", self)
        form_log = QFormLayout(grp_log)
        form_log.setContentsMargins(12, 16, 12, 12)
        form_log.setSpacing(10)

        self.cmb_log_level = QComboBox(grp_log)
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.cmb_log_level.addItem(level, level)
        self.cmb_log_level.setAccessibleName("Nível de Log")
        self.cmb_log_level.setToolTip("Define o nível mínimo registrado em app.log e no painel inferior")
        self.cmb_log_level.setMaximumWidth(160)
        form_log.addRow("Nível de Log:", self.cmb_log_level)

        layout.addWidget(grp_log)
        layout.addStretch(1)

    def load_from_config(self, config: AppConfig) -> None:
        """Carrega os valores de `AppConfig` nos controles da página."""
        idx_lang = self.cmb_language.findData(config.language)
        self.cmb_language.setCurrentIndex(max(0, idx_lang))
        self.chk_auto_updates.setChecked(bool(config.auto_check_updates))
        self.chk_show_tour.setChecked(bool(config.show_tour_on_startup))

        idx_log = self.cmb_log_level.findData(config.log_level.upper())
        self.cmb_log_level.setCurrentIndex(max(0, idx_log))

    def apply_to_config(self, config: AppConfig) -> None:
        """Grava os valores selecionados na instância `AppConfig`."""
        config.language = str(self.cmb_language.currentData() or "pt_BR")
        config.auto_check_updates = bool(self.chk_auto_updates.isChecked())
        config.show_tour_on_startup = bool(self.chk_show_tour.isChecked())
        config.log_level = str(self.cmb_log_level.currentData() or "INFO")
