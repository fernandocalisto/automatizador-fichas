# -*- coding: utf-8 -*-
"""
Página de Configurações do Gerador SELECT Jasper (src/gui/settings/pages/select_page.py).

Configura estilo de booleanos (`boolean_style`), convenção de nomes de colunas
(`column_naming`), inclusão de observações (`include_observations`) e metadados
(`include_metadata`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
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


class SelectPage(QWidget):
    """Página 'SELECT Jasper' do diálogo de configurações."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Configurações de SELECT Jasper")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        title = QLabel("Opções de Geração SELECT Jasper", self)
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        layout.addWidget(title)

        grp = QGroupBox("Formatação de Projeções e Colunas", self)
        form = QFormLayout(grp)
        form.setContentsMargins(12, 16, 12, 12)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.cmb_boolean_style = QComboBox(grp)
        self.cmb_boolean_style.addItem("COALESCE(BOOL_OR(...), false)", "coalesce_bool_or")
        self.cmb_boolean_style.addItem("Marcação 'X' ou Vazio ('')", "x_empty")
        self.cmb_boolean_style.addItem("'SIM' / 'NÃO'", "sim_nao")
        self.cmb_boolean_style.addItem("Numérico (1 / 0)", "1_0")
        self.cmb_boolean_style.setAccessibleName("Estilo de Campos Booleanos")
        self.cmb_boolean_style.setToolTip("Define como campos BOOLEANO são projetados no SELECT")
        self.cmb_boolean_style.setMinimumWidth(280)
        lbl_bool = QLabel("Estilo de Booleanos:")
        lbl_bool.setStyleSheet("font-weight: 500; color: #334155;")
        form.addRow(lbl_bool, self.cmb_boolean_style)

        self.cmb_column_naming = QComboBox(grp)
        self.cmb_column_naming.addItem("Pergunta + Label", "pergunta_label")
        self.cmb_column_naming.addItem("Apenas Label (Slug)", "label_only")
        self.cmb_column_naming.addItem("Label + Sufixo de Tipo", "label_sufixo")
        self.cmb_column_naming.setAccessibleName("Nomenclatura de Colunas")
        self.cmb_column_naming.setToolTip("Convenção de geração dos aliases SQL")
        self.cmb_column_naming.setMinimumWidth(280)
        lbl_col = QLabel("Aliases de Coluna:")
        lbl_col.setStyleSheet("font-weight: 500; color: #334155;")
        form.addRow(lbl_col, self.cmb_column_naming)

        self.chk_observations = QCheckBox("Incluir colunas adicionais de observação (_obs)", grp)
        self.chk_observations.setAccessibleName("Incluir colunas de observação")
        form.addRow("", self.chk_observations)

        self.chk_metadata = QCheckBox("Incluir comentários de metadados nas perguntas", grp)
        self.chk_metadata.setAccessibleName("Incluir metadados")
        form.addRow("", self.chk_metadata)

        layout.addWidget(grp)
        layout.addStretch(1)

    def load_from_config(self, config: AppConfig) -> None:
        """Carrega as opções de SELECT Jasper a partir de `AppConfig`."""
        idx_bool = self.cmb_boolean_style.findData(config.boolean_style)
        self.cmb_boolean_style.setCurrentIndex(max(0, idx_bool))

        idx_col = self.cmb_column_naming.findData(config.column_naming)
        self.cmb_column_naming.setCurrentIndex(max(0, idx_col))

        self.chk_observations.setChecked(bool(config.include_observations))
        self.chk_metadata.setChecked(bool(config.include_metadata))

    def apply_to_config(self, config: AppConfig) -> None:
        """Aplica as opções de SELECT Jasper em `AppConfig`."""
        config.boolean_style = str(self.cmb_boolean_style.currentData() or "coalesce_bool_or")
        config.column_naming = str(self.cmb_column_naming.currentData() or "pergunta_label")
        config.include_observations = bool(self.chk_observations.isChecked())
        config.include_metadata = bool(self.chk_metadata.isChecked())
