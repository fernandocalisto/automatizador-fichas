# -*- coding: utf-8 -*-
"""
Página de Configurações do Editor (src/gui/settings/pages/editor_page.py).

Configura tamanho de tabulação (`tab_size`), numeração de linhas (`show_line_numbers`),
exibição de espaços em branco (`show_whitespace`), code folding (`enable_folding`)
e atraso do autocompletar (`autocomplete_delay_ms`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class EditorPage(QWidget):
    """Página 'Editor SQL / JSON' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações do Editor")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Editor de Código (JSON & SQL)", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        grp_ed = QGroupBox("Comportamento e Exibição", self)
        form = QFormLayout(grp_ed)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(10)

        self.spn_tab_size = QSpinBox(grp_ed)
        self.spn_tab_size.setRange(2, 8)
        self.spn_tab_size.setSuffix(" espaços")
        self.spn_tab_size.setAccessibleName("Tamanho da Tabulação")
        self.spn_tab_size.setToolTip("Quantidade de espaços por nível de indentação")
        form.addRow("Tamanho do Tab:", self.spn_tab_size)

        self.spn_autocomplete_delay = QSpinBox(grp_ed)
        self.spn_autocomplete_delay.setRange(50, 2000)
        self.spn_autocomplete_delay.setSingleStep(50)
        self.spn_autocomplete_delay.setSuffix(" ms")
        self.spn_autocomplete_delay.setAccessibleName("Atraso do Autocompletar")
        self.spn_autocomplete_delay.setToolTip("Tempo em milissegundos antes de exibir sugestões")
        form.addRow("Delay Autocomplete:", self.spn_autocomplete_delay)

        self.chk_line_numbers = QCheckBox("Exibir numeração de linhas", grp_ed)
        self.chk_line_numbers.setAccessibleName("Exibir numeração de linhas")
        form.addRow("", self.chk_line_numbers)

        self.chk_whitespace = QCheckBox("Exibir caracteres de espaço em branco", grp_ed)
        self.chk_whitespace.setAccessibleName("Exibir espaços em branco")
        form.addRow("", self.chk_whitespace)

        self.chk_folding = QCheckBox("Habilitar recolhimento de blocos (Code Folding)", grp_ed)
        self.chk_folding.setAccessibleName("Habilitar Code Folding")
        form.addRow("", self.chk_folding)

        layout.addWidget(grp_ed)
        layout.addStretch(1)

    def load_from_config(self, config: AppConfig) -> None:
        """Carrega os parâmetros do editor a partir de `AppConfig`."""
        self.spn_tab_size.setValue(int(config.tab_size))
        self.spn_autocomplete_delay.setValue(int(config.autocomplete_delay_ms))
        self.chk_line_numbers.setChecked(bool(config.show_line_numbers))
        self.chk_whitespace.setChecked(bool(config.show_whitespace))
        self.chk_folding.setChecked(bool(config.enable_folding))

    def apply_to_config(self, config: AppConfig) -> None:
        """Grava os parâmetros do editor em `AppConfig`."""
        config.tab_size = int(self.spn_tab_size.value())
        config.autocomplete_delay_ms = int(self.spn_autocomplete_delay.value())
        config.show_line_numbers = bool(self.chk_line_numbers.isChecked())
        config.show_whitespace = bool(self.chk_whitespace.isChecked())
        config.enable_folding = bool(self.chk_folding.isChecked())
