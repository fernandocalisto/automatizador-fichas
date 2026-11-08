# -*- coding: utf-8 -*-
"""
Página 3 do Wizard — SqlInsertPage (src/gui/wizard/sql_insert_page.py).

Implementa a interface PySide6 para geração do script SQL PostgreSQL de inserção
(`template_ficha_clinica`, `pergunta_template_ficha_clinica`, `resposta_template_ficha_clinica`)
conforme `spec_sql_perguntas.md` e Spec 00:
- Botões: "Gerar SQL INSERT", "Validar Sintaxe", "Copiar para Área de Transferência",
  "Salvar como .sql", "Voltar à Tela Inicial"
- Editor `QPlainTextEdit` com `PostgresSyntaxHighlighter` e integração com `ThemeService`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.sql_insert import (
    POSTGRES_FUNCTIONS,
    POSTGRES_KEYWORDS,
    generate_insert_sql,
    validate_postgres_syntax,
)

if TYPE_CHECKING:
    from src.services.theme_service import ThemeService

logger = logging.getLogger("sql_insert")


class PostgresSyntaxHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe PostgreSQL para `QPlainTextEdit`."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.fmt_keyword = QTextCharFormat()
        self.fmt_keyword.setForeground(QColor("#1d4ed8"))
        self.fmt_keyword.setFontWeight(QFont.Weight.Bold)

        self.fmt_function = QTextCharFormat()
        self.fmt_function.setForeground(QColor("#7c3aed"))

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor("#15803d"))

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor("#b45309"))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor("#64748b"))
        self.fmt_comment.setFontItalic(True)

        kw_pattern = "|".join(re.escape(k) for k in sorted(POSTGRES_KEYWORDS, key=len, reverse=True))
        fn_pattern = "|".join(re.escape(f) for f in sorted(POSTGRES_FUNCTIONS, key=len, reverse=True))

        self._re_kw = re.compile(rf"\b(?:{kw_pattern})\b", re.IGNORECASE)
        self._re_fn = re.compile(rf"\b(?:{fn_pattern})\b", re.IGNORECASE)
        self._re_num = re.compile(r"\b\d+(?:\.\d+)?\b")
        self._re_str_or_comment = re.compile(r"('(?:''|[^'])*')|(--[^\n]*)")

    def apply_palette(self, styles: dict[str, Any]) -> None:
        kw = styles.get("keyword", {}).get("fore")
        fn = styles.get("function", {}).get("fore")
        st = styles.get("string", {}).get("fore")
        nm = styles.get("number", {}).get("fore")
        cm = styles.get("comment", {}).get("fore")

        if kw:
            self.fmt_keyword.setForeground(QColor(kw))
        if fn:
            self.fmt_function.setForeground(QColor(fn))
        if st:
            self.fmt_string.setForeground(QColor(st))
        if nm:
            self.fmt_number.setForeground(QColor(nm))
        if cm:
            self.fmt_comment.setForeground(QColor(cm))
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not text:
            return

        protected: list[tuple[int, int]] = []
        for m in self._re_str_or_comment.finditer(text):
            s_idx, e_idx = m.start(), m.end()
            protected.append((s_idx, e_idx))
            if m.group(1) is not None:
                self.setFormat(s_idx, e_idx - s_idx, self.fmt_string)
            else:
                self.setFormat(s_idx, e_idx - s_idx, self.fmt_comment)

        def _is_protected(start: int, end: int) -> bool:
            return any(start < p_end and end > p_start for p_start, p_end in protected)

        for m in self._re_kw.finditer(text):
            if not _is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_keyword)

        for m in self._re_fn.finditer(text):
            if not _is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_function)

        for m in self._re_num.finditer(text):
            if not _is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)


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


class SqlInsertPage(QWidget):
    """
    Página 3 do Wizard: Geração e validação do script SQL INSERT PostgreSQL.

    Signals:
        sql_generated (str): Emitido quando o SQL INSERT é gerado com sucesso.
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
        theme_service: ThemeService | None = None,
    ) -> None:
        super().__init__(parent)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_sql_generated = on_sql_generated
        self.on_back_to_landing = on_back_to_landing
        self._theme_service = theme_service

        self.generated_sql: str = ""
        self.current_sql_file: Path | None = None
        self.generation_options: dict[str, Any] = {
            "include_comments": True,
            "use_generate_series": True,
            "use_unnest": True,
            "clean_ocr": True,
            "force_uppercase": True,
        }

        self.setAccessibleName("Gerar SQL INSERT")
        self._build_ui()

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

        self.btn_generate = _StatefulButton("Gerar SQL INSERT", self)
        self.btn_generate.setProperty("variant", "primary")
        self.btn_generate.setAccessibleName("Gerar SQL INSERT")
        self.btn_generate.clicked.connect(lambda: self.generate_sql(True))
        toolbar.addWidget(self.btn_generate)

        self.btn_validate = _StatefulButton("Validar Sintaxe", self)
        self.btn_validate.setAccessibleName("Validar Sintaxe PostgreSQL")
        self.btn_validate.clicked.connect(lambda: self.validate_syntax(False))
        toolbar.addWidget(self.btn_validate)

        self.btn_copy = _StatefulButton("Copiar para Área de Transferência", self)
        self.btn_copy.setAccessibleName("Copiar SQL INSERT")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        toolbar.addWidget(self.btn_copy)

        self.btn_save = _StatefulButton("Salvar como .sql", self)
        self.btn_save.setAccessibleName("Salvar SQL INSERT como arquivo")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_as_sql_dialog)
        toolbar.addWidget(self.btn_save)

        toolbar.addStretch(1)

        self.btn_back = _StatefulButton("Voltar à Tela Inicial", self)
        self.btn_back.setAccessibleName("Voltar à Tela Inicial")
        self.btn_back.clicked.connect(self._handle_back_to_landing)
        toolbar.addWidget(self.btn_back)

        root_layout.addLayout(toolbar)

        self.preview_text = QPlainTextEdit(self)
        self.preview_text.setAccessibleName("Editor SQL INSERT")
        self.preview_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("JetBrains Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.preview_text.setFont(font)

        self.highlighter = PostgresSyntaxHighlighter(self.preview_text.document())

        self.preview_text.textChanged.connect(self._on_text_edited)
        self.preview_text.cursorPositionChanged.connect(self._on_cursor_changed)
        root_layout.addWidget(self.preview_text, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.lbl_status = QLabel(
            "Clique em 'Gerar SQL INSERT' para gerar o script SQL a partir do JSON carregado.",
            self,
        )
        self.lbl_status.setAccessibleName("Status do SQL INSERT")
        status_row.addWidget(self.lbl_status, 1)

        self.lbl_counts = QLabel("Linhas: 0 | Caracteres: 0", self)
        self.lbl_counts.setAccessibleName("Contagem de Linhas e Caracteres SQL INSERT")
        status_row.addWidget(self.lbl_counts)

        root_layout.addLayout(status_row)

    def apply_theme_from_service(self, theme_service: ThemeService) -> None:
        theme_service.apply_editor_theme(self.preview_text)
        theme_data = theme_service.get_editor_theme_data()
        styles = theme_data.get("styles", {})
        if isinstance(styles, dict):
            self.highlighter.apply_palette(styles)

    def _on_cursor_changed(self) -> None:
        cursor = self.preview_text.textCursor()
        self.cursor_position_changed.emit(cursor.blockNumber() + 1, cursor.columnNumber() + 1)

    def _update_counts(self, sql_text: str) -> None:
        num_chars = len(sql_text)
        num_lines = sql_text.count("\n") + 1 if sql_text else 0
        self.lbl_counts.setText(f"Linhas: {num_lines} | Caracteres: {num_chars}")

    def _on_text_edited(self) -> None:
        current = self.get_preview_text()
        self.generated_sql = current
        self._update_counts(current)
        has_content = bool(current.strip())
        self.btn_copy.setEnabled(has_content)
        self.btn_save.setEnabled(has_content)

    def get_preview_text(self) -> str:
        return self.preview_text.toPlainText()

    def set_preview_text(self, sql_text: str) -> None:
        self.preview_text.blockSignals(True)
        self.preview_text.setPlainText(sql_text)
        self.preview_text.blockSignals(False)
        self.highlighter.rehighlight()
        self._update_counts(sql_text)

    def clear_preview(self) -> None:
        self.generated_sql = ""
        self.set_preview_text("")
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.lbl_status.setText(
            "Clique em 'Gerar SQL INSERT' para gerar o script SQL a partir do JSON carregado."
        )

    def generate_sql(self, show_error_dialog: bool = True) -> bool:
        if not self.shared_json or not isinstance(self.shared_json, dict):
            msg = "Erro: Nenhum JSON carregado para gerar o SQL."
            self.lbl_status.setText(msg)
            logger.warning(msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Gerar SQL", msg)
            return False

        try:
            sql_script = generate_insert_sql(
                self.shared_json,
                options=self.generation_options,
            )
        except ValueError as exc:
            err_msg = str(exc)
            self.lbl_status.setText(f"Erro: {err_msg}")
            logger.error("Erro de validação ao gerar SQL INSERT: %s", err_msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Erro de Validação SQL", err_msg)
            return False
        except Exception as exc:
            err_msg = f"Erro inesperado ao gerar SQL: {exc}"
            self.lbl_status.setText(err_msg)
            logger.exception("Erro inesperado ao gerar SQL INSERT")
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Gerar SQL", err_msg)
            return False

        self.generated_sql = sql_script
        self.set_preview_text(sql_script)
        self.btn_copy.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.lbl_status.setText("SQL gerado com sucesso")
        logger.info("SQL INSERT gerado com sucesso (%d caracteres).", len(sql_script))

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
            self.lbl_status.setText("Aviso: Nenhum SQL gerado para copiar.")
            return False

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(sql_text)
        self.lbl_status.setText("SQL copiado para a área de transferência!")
        return True

    def save_sql_to_path(self, file_path: str | Path) -> bool:
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.lbl_status.setText("Aviso: Nenhum SQL gerado para salvar.")
            return False

        path = Path(file_path)
        try:
            path.write_text(sql_text, encoding="utf-8")
            self.current_sql_file = path
            self.lbl_status.setText(f"Arquivo SQL salvo com sucesso em: {path.name}")
            logger.info("SQL INSERT salvo em '%s'", path)
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
            self.lbl_status.setText("Aviso: Gere o SQL antes de salvar.")
            return False

        initial_name = (
            self.current_sql_file.name
            if self.current_sql_file is not None
            else "insert_ficha_clinica.sql"
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
