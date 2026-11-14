# -*- coding: utf-8 -*-
"""
Página 4 do Wizard — SqlSelectPage (src/gui/wizard/sql_select_page.py).

Implementa a interface PySide6 para geração da consulta SQL SELECT para Jasper Reports
(Padrão Ouro) conforme `spec_sql_select.md` e Spec 00:
- Botões: "Gerar SELECT Jasper", "Validar Sintaxe", "Copiar para Área de Transferência",
  "Salvar como .sql", "Voltar à Tela Inicial"
- Editor `SqlEditorWidget` (QScintilla) com lexer PostgreSQL + Jasper, line numbers, folding,
  brace matching, e integração com `ThemeService` (5 temas).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.sql_select import (
    MODEL_RESOURCE_NAME,
    find_unknown_field_types,
    generate_select_jasper,
    validate_postgres_syntax,
)
from src.utils.resource_path import resource_path

if TYPE_CHECKING:
    from src.services.config_service import ConfigService
    from src.services.theme_service import ThemeService

logger = logging.getLogger("sql_select")


class _LabelVarAdapter:
    """Adaptador `.get()` / `.set()` sobre `QLabel`."""

    def __init__(self, label: QLabel) -> None:
        self._label = label

    def get(self) -> str:
        return self._label.text()

    def set(self, value: str) -> None:
        self._label.setText(str(value))


class _StatefulButton(QPushButton):
    """`QPushButton` com método `cget('state')` e `invoke()` para compatibilidade."""

    def cget(self, key: str) -> str:
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        return ""

    def invoke(self) -> None:
        self.click()


class SqlSelectPage(QWidget):
    """
    Página 4 do Wizard: Geração e validação da consulta SELECT para Jasper Reports.

    Signals:
        sql_generated (str): Emitido quando o SELECT Jasper é gerado com sucesso.
        validation_finished (bool, str): Emitido após validar a sintaxe PostgreSQL.
        cursor_position_changed (int, int): Emitido quando linha/coluna do cursor muda.
        back_to_landing_requested (): Emitido ao clicar em Voltar à Tela Inicial.
    """

    sql_generated = Signal(str)
    validation_finished = Signal(bool, str)
    cursor_position_changed = Signal(int, int)
    back_to_landing_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        shared_json: dict[str, Any] | None = None,
        on_sql_generated: Callable[[str], None] | None = None,
        on_back_to_landing: Callable[[], None] | None = None,
        model_path: str | Path | None = None,
        theme_service: ThemeService | None = None,
        config_service: ConfigService | None = None,
    ) -> None:
        super().__init__(parent)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_sql_generated = on_sql_generated
        self.on_back_to_landing = on_back_to_landing
        self._theme_service = theme_service
        self._config_service = config_service
        self.model_path: Path = (
            Path(model_path)
            if model_path is not None
            else resource_path(MODEL_RESOURCE_NAME)
        )

        self.generated_sql: str = ""
        self.current_sql_file: Path | None = None
        self.generation_options: dict[str, Any] = {
            "boolean_style": "coalesce_bool_or",
            "column_naming": "label_only",
            "include_obs": True,
            "include_metadata": False,
            "include_all_blocks": True,
            "include_cabecalho": True,
            "include_paciente": True,
            "include_profissional": True,
            "include_atendimento": True,
            "only_non_title": False,
            "short_aliases": False,
            "group_by_type": False,
        }

        self.setAccessibleName("Gerar SELECT Jasper")
        self._build_ui()
        self._load_options_from_config()

        self.status_var = _LabelVarAdapter(self.lbl_status)
        self.counts_var = _LabelVarAdapter(self.lbl_counts)

        if self._theme_service is not None:
            self.apply_theme_from_service(self._theme_service)
            self._theme_service.editor_theme_changed.connect(
                lambda _: self.apply_theme_from_service(self._theme_service)  # type: ignore[arg-type]
            )

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_generate = _StatefulButton("Gerar SELECT Jasper", self)
        self.btn_generate.setProperty("variant", "primary")
        self.btn_generate.setAccessibleName("Gerar SELECT Jasper")
        self.btn_generate.clicked.connect(lambda: self.generate_sql(True))
        toolbar.addWidget(self.btn_generate)

        self.btn_validate = _StatefulButton("Validar Sintaxe", self)
        self.btn_validate.setAccessibleName("Validar Sintaxe SELECT Jasper")
        self.btn_validate.clicked.connect(lambda: self.validate_syntax(False))
        toolbar.addWidget(self.btn_validate)

        self.btn_copy = _StatefulButton("Copiar para Área de Transferência", self)
        self.btn_copy.setAccessibleName("Copiar SELECT Jasper")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        toolbar.addWidget(self.btn_copy)

        self.btn_save = _StatefulButton("Salvar como .sql", self)
        self.btn_save.setAccessibleName("Salvar SELECT Jasper como arquivo")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_as_sql_dialog)
        toolbar.addWidget(self.btn_save)

        toolbar.addStretch(1)

        self.btn_back = _StatefulButton("Voltar à Tela Inicial", self)
        self.btn_back.setAccessibleName("Voltar à Tela Inicial")
        self.btn_back.clicked.connect(self._handle_back_to_landing)
        toolbar.addWidget(self.btn_back)

        root_layout.addLayout(toolbar)

        # Seção colapsável: Opções de Consulta (antes do SQL preview)
        options_header = QHBoxLayout()
        options_header.setContentsMargins(0, 0, 0, 0)
        self.btn_toggle_options = QPushButton("▼ Opções de Consulta", self)
        self.btn_toggle_options.setCheckable(True)
        self.btn_toggle_options.setChecked(True)
        self.btn_toggle_options.setFlat(True)
        self.btn_toggle_options.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_options.setAccessibleName("Alternar Opções de Consulta")
        self.btn_toggle_options.toggled.connect(self._on_toggle_options_panel)
        options_header.addWidget(self.btn_toggle_options)
        options_header.addStretch(1)
        root_layout.addLayout(options_header)

        self.options_panel = QFrame(self)
        self.options_panel.setObjectName("QueryOptionsPanel")
        self.options_panel.setFrameShape(QFrame.Shape.StyledPanel)
        options_layout = QVBoxLayout(self.options_panel)
        options_layout.setContentsMargins(10, 8, 10, 8)
        options_layout.setSpacing(6)

        row_main_opts = QHBoxLayout()
        row_main_opts.setSpacing(12)

        row_main_opts.addWidget(QLabel("Estilo de Booleanos:", self.options_panel))
        self.cmb_boolean_style = QComboBox(self.options_panel)
        self.cmb_boolean_style.addItem("COALESCE/BOOL_OR", "coalesce_bool_or")
        self.cmb_boolean_style.addItem("'X'/''", "x_empty")
        self.cmb_boolean_style.addItem("'SIM'/'NÃO'", "sim_nao")
        self.cmb_boolean_style.addItem("1/0", "1_0")
        self.cmb_boolean_style.setAccessibleName("Estilo de Booleanos")
        self.cmb_boolean_style.setMaximumWidth(180)
        self.cmb_boolean_style.currentIndexChanged.connect(self._on_options_changed)
        row_main_opts.addWidget(self.cmb_boolean_style)

        row_main_opts.addWidget(QLabel("Nomenclatura de Colunas:", self.options_panel))
        self.cmb_column_naming = QComboBox(self.options_panel)
        self.cmb_column_naming.addItem("Pergunta+Label", "pergunta_label")
        self.cmb_column_naming.addItem("Label Only", "label_only")
        self.cmb_column_naming.addItem("Label+Sufixo", "label_sufixo")
        self.cmb_column_naming.setCurrentIndex(1)
        self.cmb_column_naming.setAccessibleName("Nomenclatura de Colunas")
        self.cmb_column_naming.setMaximumWidth(160)
        self.cmb_column_naming.currentIndexChanged.connect(self._on_options_changed)
        row_main_opts.addWidget(self.cmb_column_naming)

        self.chk_include_obs = QCheckBox("Incluir observações (_obs)", self.options_panel)
        self.chk_include_obs.setChecked(True)
        self.chk_include_obs.setAccessibleName("Incluir observações (_obs)")
        self.chk_include_obs.toggled.connect(self._on_options_changed)
        row_main_opts.addWidget(self.chk_include_obs)

        self.chk_include_metadata = QCheckBox("Incluir metadados", self.options_panel)
        self.chk_include_metadata.setChecked(False)
        self.chk_include_metadata.setAccessibleName("Incluir metadados")
        self.chk_include_metadata.toggled.connect(self._on_options_changed)
        row_main_opts.addWidget(self.chk_include_metadata)

        row_main_opts.addStretch(1)
        options_layout.addLayout(row_main_opts)

        row_blocks = QHBoxLayout()
        row_blocks.setSpacing(12)

        self.chk_include_all_blocks = QCheckBox(
            "Incluir blocos adicionais", self.options_panel
        )
        self.chk_include_all_blocks.setChecked(True)
        self.chk_include_all_blocks.setAccessibleName("Incluir blocos adicionais")
        self.chk_include_all_blocks.toggled.connect(self._on_all_blocks_toggled)
        row_blocks.addWidget(self.chk_include_all_blocks)

        self.blocks_sub_container = QWidget(self.options_panel)
        sub_layout = QHBoxLayout(self.blocks_sub_container)
        sub_layout.setContentsMargins(8, 0, 0, 0)
        sub_layout.setSpacing(10)

        self.chk_block_cabecalho = QCheckBox("Cabeçalho da Ficha", self.blocks_sub_container)
        self.chk_block_cabecalho.setChecked(True)
        self.chk_block_cabecalho.setAccessibleName("Cabeçalho da Ficha")
        self.chk_block_cabecalho.toggled.connect(self._on_options_changed)
        sub_layout.addWidget(self.chk_block_cabecalho)

        self.chk_block_paciente = QCheckBox("Dados do Paciente", self.blocks_sub_container)
        self.chk_block_paciente.setChecked(True)
        self.chk_block_paciente.setAccessibleName("Dados do Paciente")
        self.chk_block_paciente.toggled.connect(self._on_options_changed)
        sub_layout.addWidget(self.chk_block_paciente)

        self.chk_block_profissional = QCheckBox(
            "Dados do Profissional", self.blocks_sub_container
        )
        self.chk_block_profissional.setChecked(True)
        self.chk_block_profissional.setAccessibleName("Dados do Profissional")
        self.chk_block_profissional.toggled.connect(self._on_options_changed)
        sub_layout.addWidget(self.chk_block_profissional)

        self.chk_block_atendimento = QCheckBox(
            "Dados do Atendimento", self.blocks_sub_container
        )
        self.chk_block_atendimento.setChecked(True)
        self.chk_block_atendimento.setAccessibleName("Dados do Atendimento")
        self.chk_block_atendimento.toggled.connect(self._on_options_changed)
        sub_layout.addWidget(self.chk_block_atendimento)

        row_blocks.addWidget(self.blocks_sub_container)
        row_blocks.addStretch(1)
        options_layout.addLayout(row_blocks)

        root_layout.addWidget(self.options_panel)

        # SqlEditorWidget (QScintilla) com lexer PostgreSQL + Jasper
        from src.gui.components.sql_editor import SqlEditorWidget
        self.preview_text = SqlEditorWidget(
            self,
            read_only=False,
            theme_service=self._theme_service,
            config_service=self._config_service,
        )
        self.preview_text.setAccessibleName("Editor SELECT Jasper")
        self.preview_text.cursorPositionChanged.connect(self._on_cursor_changed)
        root_layout.addWidget(self.preview_text, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.lbl_status = QLabel(
            "Clique em 'Gerar SELECT Jasper' para gerar a consulta SQL a partir do JSON carregado.",
            self,
        )
        self.lbl_status.setAccessibleName("Status do SELECT Jasper")
        status_row.addWidget(self.lbl_status, 1)

        self.lbl_counts = QLabel("Linhas: 0 | Caracteres: 0", self)
        self.lbl_counts.setAccessibleName("Contagem de Linhas e Caracteres SELECT Jasper")
        status_row.addWidget(self.lbl_counts)

        root_layout.addLayout(status_row)

    def _on_toggle_options_panel(self, expanded: bool) -> None:
        self.options_panel.setVisible(expanded)
        self.btn_toggle_options.setText(
            "▼ Opções de Consulta" if expanded else "▶ Opções de Consulta"
        )

    def _on_all_blocks_toggled(self, checked: bool) -> None:
        self.blocks_sub_container.setVisible(checked)
        self._on_options_changed()

    def _sync_options_from_ui(self) -> dict[str, Any]:
        self.generation_options["boolean_style"] = (
            self.cmb_boolean_style.currentData() or "coalesce_bool_or"
        )
        self.generation_options["column_naming"] = (
            self.cmb_column_naming.currentData() or "label_only"
        )
        self.generation_options["include_obs"] = self.chk_include_obs.isChecked()
        self.generation_options["include_metadata"] = self.chk_include_metadata.isChecked()
        self.generation_options["include_all_blocks"] = (
            self.chk_include_all_blocks.isChecked()
        )
        self.generation_options["include_cabecalho"] = (
            self.chk_block_cabecalho.isChecked()
        )
        self.generation_options["include_paciente"] = (
            self.chk_block_paciente.isChecked()
        )
        self.generation_options["include_profissional"] = (
            self.chk_block_profissional.isChecked()
        )
        self.generation_options["include_atendimento"] = (
            self.chk_block_atendimento.isChecked()
        )
        return self.generation_options

    def _load_options_from_config(self) -> None:
        """Restaura as opções de geração SELECT Jasper a partir do `ConfigService`."""
        if self._config_service is None or not hasattr(
            self._config_service, "get_select_jasper_options"
        ):
            return

        saved = self._config_service.get_select_jasper_options()
        self.generation_options.update(saved)

        widgets = (
            self.cmb_boolean_style,
            self.cmb_column_naming,
            self.chk_include_obs,
            self.chk_include_metadata,
            self.chk_include_all_blocks,
            self.chk_block_cabecalho,
            self.chk_block_paciente,
            self.chk_block_profissional,
            self.chk_block_atendimento,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            idx_bool = self.cmb_boolean_style.findData(
                saved.get("boolean_style", "coalesce_bool_or")
            )
            if idx_bool >= 0:
                self.cmb_boolean_style.setCurrentIndex(idx_bool)

            idx_col = self.cmb_column_naming.findData(
                saved.get("column_naming", "label_only")
            )
            if idx_col >= 0:
                self.cmb_column_naming.setCurrentIndex(idx_col)

            self.chk_include_obs.setChecked(bool(saved.get("include_obs", True)))
            self.chk_include_metadata.setChecked(bool(saved.get("include_metadata", False)))
            all_blocks = bool(saved.get("include_all_blocks", True))
            self.chk_include_all_blocks.setChecked(all_blocks)
            self.blocks_sub_container.setVisible(all_blocks)
            self.chk_block_cabecalho.setChecked(bool(saved.get("include_cabecalho", True)))
            self.chk_block_paciente.setChecked(bool(saved.get("include_paciente", True)))
            self.chk_block_profissional.setChecked(
                bool(saved.get("include_profissional", True))
            )
            self.chk_block_atendimento.setChecked(
                bool(saved.get("include_atendimento", True))
            )
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _on_options_changed(self, *_: Any) -> None:
        self._sync_options_from_ui()
        if self._config_service is not None and hasattr(
            self._config_service, "save_select_jasper_options"
        ):
            self._config_service.save_select_jasper_options(self.generation_options)
        if self.generated_sql and self.shared_json:
            self.generate_sql(show_error_dialog=False)

    def apply_theme_from_service(self, theme_service: ThemeService) -> None:
        if hasattr(self.preview_text, "set_theme"):
            theme_name = theme_service.current_editor_theme()
            self.preview_text.set_theme(theme_name)

    def _on_cursor_changed(self, line: int, col: int) -> None:
        self.cursor_position_changed.emit(line, col)

    def _update_counts(self, sql_text: str) -> None:
        num_chars = len(sql_text)
        num_lines = sql_text.count("\n") + 1 if sql_text else 0
        self.lbl_counts.setText(f"Linhas: {num_lines} | Caracteres: {num_chars}")

    def get_preview_text(self) -> str:
        if hasattr(self.preview_text, "get_text"):
            return self.preview_text.get_text()
        return ""

    def set_preview_text(self, sql_text: str) -> None:
        if hasattr(self.preview_text, "set_text"):
            self.preview_text.blockSignals(True)
            self.preview_text.set_text(sql_text)
            self.preview_text.blockSignals(False)
        self._update_counts(sql_text)

    def clear_preview(self) -> None:
        self.generated_sql = ""
        self.set_preview_text("")
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.lbl_status.setText(
            "Clique em 'Gerar SELECT Jasper' para gerar a consulta SQL a partir do JSON carregado."
        )

    def generate_sql(self, show_error_dialog: bool = True) -> bool:
        self._sync_options_from_ui()
        if not self.shared_json or not isinstance(self.shared_json, dict):
            msg = "Erro: Nenhum JSON carregado para gerar o SELECT Jasper."
            self.lbl_status.setText(msg)
            logger.warning(msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Gerar SELECT", msg)
            return False

        model_file = self.model_path or resource_path(MODEL_RESOURCE_NAME)
        if not model_file.exists():
            err_msg = f"Erro: modelo não encontrado em '{model_file}'."
            self.lbl_status.setText(err_msg)
            logger.error(err_msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Modelo SQL Não Encontrado", err_msg)
            return False

        try:
            model_content = model_file.read_text(encoding="utf-8-sig")
            sql_script = generate_select_jasper(
                self.shared_json,
                model_sql=model_content,
                options=self.generation_options,
            )
        except ValueError as exc:
            err_msg = str(exc)
            self.lbl_status.setText(f"Erro: {err_msg}")
            logger.error("Erro ao gerar SELECT Jasper: %s", err_msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Gerar SELECT", err_msg)
            return False
        except Exception as exc:
            err_msg = f"Erro inesperado ao gerar SELECT: {exc}"
            self.lbl_status.setText(err_msg)
            logger.exception("Erro inesperado ao gerar SELECT Jasper")
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Gerar SELECT", err_msg)
            return False

        self.generated_sql = sql_script
        self.set_preview_text(sql_script)
        self.btn_copy.setEnabled(True)
        self.btn_save.setEnabled(True)

        unknown_types = find_unknown_field_types(self.shared_json)
        if unknown_types:
            self.lbl_status.setText(
                f"SELECT gerado com sucesso (Aviso: tipo_campo desconhecido usou fallback TEXTO: {', '.join(unknown_types)})"
            )
        else:
            self.lbl_status.setText("SELECT gerado com sucesso")

        logger.info("SELECT Jasper gerado com sucesso (%d caracteres).", len(sql_script))
        if self.on_sql_generated is not None:
            self.on_sql_generated(sql_script)
        self.sql_generated.emit(sql_script)
        return True

    def validate_syntax(self, show_dialog: bool = False) -> bool:
        sql_text = self.get_preview_text() or self.generated_sql
        is_valid, message = validate_postgres_syntax(sql_text)
        self.lbl_status.setText(message)
        self.validation_finished.emit(is_valid, message)

        if show_dialog:
            if is_valid:
                QMessageBox.information(self, "Validação de Sintaxe PostgreSQL", message)
            else:
                QMessageBox.critical(self, "Erro de Sintaxe PostgreSQL", message)

        return is_valid

    def copy_to_clipboard(self) -> bool:
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.lbl_status.setText("Aviso: Nenhum SELECT gerado para copiar.")
            return False

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(sql_text)
        self.lbl_status.setText("SELECT copiado para a área de transferência!")
        return True

    def save_sql_to_path(self, file_path: str | Path) -> bool:
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.lbl_status.setText("Aviso: Nenhum SELECT gerado para salvar.")
            return False

        path = Path(file_path)
        try:
            path.write_text(sql_text, encoding="utf-8")
            self.current_sql_file = path
            self.lbl_status.setText(f"Arquivo SQL salvo com sucesso em: {path.name}")
            logger.info("SELECT Jasper salvo em '%s'", path)
            return True
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Erro ao Salvar SQL",
                f"Não foi possível gravar o arquivo:\n{path}\n\nDetalhes: {exc}",
            )
            self.lbl_status.setText("Erro ao gravar arquivo .sql no disco.")
            return False

    def save_as_sql_dialog(self) -> bool:
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.lbl_status.setText("Aviso: Gere o SELECT antes de salvar.")
            return False

        initial_name = (
            self.current_sql_file.name
            if self.current_sql_file is not None
            else "select_ficha_clinica_jasper.sql"
        )
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar como .sql",
            initial_name,
            "SQL (*.sql);;Todos os arquivos (*.*)",
        )
        if not save_path:
            return False
        return self.save_sql_to_path(save_path)

    def _handle_back_to_landing(self) -> None:
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
        self.back_to_landing_requested.emit()
