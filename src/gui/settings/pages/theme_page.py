# -*- coding: utf-8 -*-
"""
Página de Configurações de Tema e Tipografia (src/gui/settings/pages/theme_page.py).

Configura tema da aplicação (`app_theme`: light/dark/system), tema do editor
(`editor_theme`: vscode/monokai/dracula/github/solarized), família de fonte (`font_family`)
e tamanho de fonte (`font_size`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class ThemePage(QWidget):
    """Página 'Tema' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações de Tema")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Aparência e Tema", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        # Grupo: Tema Visual
        grp_theme = QGroupBox("Esquema de Cores", self)
        form_theme = QFormLayout(grp_theme)
        form_theme.setContentsMargins(12, 16, 12, 12)
        form_theme.setSpacing(12)
        form_theme.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_theme.setFormAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        form_theme.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.cmb_app_theme = QComboBox(grp_theme)
        self.cmb_app_theme.addItem("Sistema (Automático)", "system")
        self.cmb_app_theme.addItem("Claro (Light)", "light")
        self.cmb_app_theme.addItem("Escuro (Dark)", "dark")
        self.cmb_app_theme.setAccessibleName("Tema da Aplicação")
        self.cmb_app_theme.setToolTip("Escolha o tema geral das janelas e painéis")
        self.cmb_app_theme.setMinimumWidth(220)
        lbl_app = QLabel("Tema da Aplicação:")
        lbl_app.setStyleSheet("font-weight: 500; color: #334155;")
        form_theme.addRow(lbl_app, self.cmb_app_theme)

        self.cmb_editor_theme = QComboBox(grp_theme)
        self.cmb_editor_theme.addItem("VS Code Dark+", "vscode")
        self.cmb_editor_theme.addItem("Monokai", "monokai")
        self.cmb_editor_theme.addItem("Dracula", "dracula")
        self.cmb_editor_theme.addItem("GitHub Light", "github")
        self.cmb_editor_theme.addItem("Solarized Dark", "solarized")
        self.cmb_editor_theme.setAccessibleName("Tema do Editor")
        self.cmb_editor_theme.setToolTip("Escolha o esquema de cores dos editores JSON e SQL")
        self.cmb_editor_theme.setMinimumWidth(220)
        lbl_ed = QLabel("Tema do Editor:")
        lbl_ed.setStyleSheet("font-weight: 500; color: #334155;")
        form_theme.addRow(lbl_ed, self.cmb_editor_theme)

        layout.addWidget(grp_theme)

        # Grupo: Tipografia do Editor
        grp_font = QGroupBox("Tipografia do Editor", self)
        form_font = QFormLayout(grp_font)
        form_font.setContentsMargins(12, 16, 12, 12)
        form_font.setSpacing(12)
        form_font.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_font.setFormAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        form_font.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.cmb_font_family = QComboBox(grp_font)
        self.cmb_font_family.setEditable(True)
        for family in ("JetBrains Mono", "Consolas", "Cascadia Mono", "Courier New", "Segoe UI"):
            self.cmb_font_family.addItem(family, family)
        self.cmb_font_family.setAccessibleName("Família da Fonte do Editor")
        self.cmb_font_family.setToolTip("Fonte monoespaçada utilizada nos editores JSON e SQL")
        self.cmb_font_family.setMinimumWidth(220)
        lbl_font = QLabel("Fonte do Editor:")
        lbl_font.setStyleSheet("font-weight: 500; color: #334155;")
        form_font.addRow(lbl_font, self.cmb_font_family)

        self.spn_font_size = QSpinBox(grp_font)
        self.spn_font_size.setRange(8, 28)
        self.spn_font_size.setSuffix(" pt")
        self.spn_font_size.setAccessibleName("Tamanho da Fonte do Editor")
        self.spn_font_size.setToolTip("Tamanho da fonte em pontos (8 a 28 pt)")
        self.spn_font_size.setMinimumWidth(120)
        lbl_size = QLabel("Tamanho da Fonte:")
        lbl_size.setStyleSheet("font-weight: 500; color: #334155;")
        form_font.addRow(lbl_size, self.spn_font_size)

        layout.addWidget(grp_font)
        layout.addStretch(1)

    def load_from_config(self, config: AppConfig) -> None:
        """Carrega os valores de tema e fonte a partir de `AppConfig`."""
        idx_app = self.cmb_app_theme.findData(config.app_theme)
        self.cmb_app_theme.setCurrentIndex(max(0, idx_app))

        idx_ed = self.cmb_editor_theme.findData(config.editor_theme)
        self.cmb_editor_theme.setCurrentIndex(max(0, idx_ed))

        idx_font = self.cmb_font_family.findText(config.font_family)
        if idx_font >= 0:
            self.cmb_font_family.setCurrentIndex(idx_font)
        else:
            self.cmb_font_family.setEditText(config.font_family)

        self.spn_font_size.setValue(int(config.font_size))

    def apply_to_config(self, config: AppConfig) -> None:
        """Aplica as seleções de tema e fonte em `AppConfig`."""
        config.app_theme = str(self.cmb_app_theme.currentData() or "system")
        config.editor_theme = str(self.cmb_editor_theme.currentData() or "vscode")
        font_text = self.cmb_font_family.currentText().strip()
        config.font_family = font_text if font_text else "JetBrains Mono"
        config.font_size = int(self.spn_font_size.value())
