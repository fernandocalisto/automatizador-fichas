# -*- coding: utf-8 -*-
"""
Página de Configurações de Regex e Limpeza OCR (src/gui/settings/pages/regex_page.py).

Configura uso de expressões regulares customizadas (`use_custom_regex`) e caminho
do arquivo de regras (`custom_regex_path`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import AppConfig


class RegexPage(QWidget):
    """Página 'Regex' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações de Regex e OCR")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Higienização OCR e Regras Regex", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        grp = QGroupBox("Regras Customizadas de Substituição", self)
        form = QFormLayout(grp)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(10)

        self.chk_custom_regex = QCheckBox(
            "Habilitar arquivo externo de regras Regex customizadas", grp
        )
        self.chk_custom_regex.setAccessibleName("Usar Regex Customizado")
        form.addRow(self.chk_custom_regex)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.edt_regex_path = QLineEdit(grp)
        self.edt_regex_path.setPlaceholderText("Selecione um arquivo .json com regras de regex...")
        self.edt_regex_path.setAccessibleName("Caminho do Arquivo Regex")
        self.edt_regex_path.setMaximumWidth(320)
        path_row.addWidget(self.edt_regex_path)

        self.btn_browse = QPushButton("Procurar…", grp)
        self.btn_browse.setAccessibleName("Procurar arquivo Regex")
        self.btn_browse.setToolTip("Selecionar arquivo JSON de regras Regex")
        self.btn_browse.clicked.connect(self._browse_file)
        path_row.addWidget(self.btn_browse)
        path_row.addStretch(1)

        form.addRow("Arquivo de Regras:", path_row)

        layout.addWidget(grp)
        layout.addStretch(1)

    def _browse_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Regras Regex",
            "",
            "Arquivos JSON (*.json);;Todos os arquivos (*.*)",
        )
        if file_path:
            self.edt_regex_path.setText(file_path)

    def load_from_config(self, config: AppConfig) -> None:
        """Carrega os parâmetros de regex de `AppConfig`."""
        self.chk_custom_regex.setChecked(bool(config.use_custom_regex))
        self.edt_regex_path.setText(str(config.custom_regex_path or ""))

    def apply_to_config(self, config: AppConfig) -> None:
        """Salva os parâmetros de regex em `AppConfig`."""
        config.use_custom_regex = bool(self.chk_custom_regex.isChecked())
        config.custom_regex_path = self.edt_regex_path.text().strip()
