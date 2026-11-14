# -*- coding: utf-8 -*-
"""
Página 1 do Wizard — JsonEditorPage (src/gui/wizard/json_editor_page.py).

Implementa o editor JSON em PySide6 (`QPlainTextEdit` + `QSyntaxHighlighter`):
- Botões: "Validar & Formatar", "Salvar JSON como…", "Redefinir", "Voltar à Tela Inicial"
- Realce de sintaxe JSON configurável via `ThemeService`
- Suporte a Drag-and-Drop de arquivos `.json`
- Sincronização in-place com `shared_json` e conversão automática para UPPERCASE
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.json_utils import (
    format_json,
    save_json_file,
    update_shared_dict_in_place,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)

if TYPE_CHECKING:
    from src.services.config_service import ConfigService
    from src.services.theme_service import ThemeService

logger = logging.getLogger("gui.wizard.json_editor")


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe para JSON em `QTextDocument`."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.enabled: bool = True

        self.fmt_key = QTextCharFormat()
        self.fmt_key.setForeground(QColor("#0369a1"))
        self.fmt_key.setFontWeight(QFont.Weight.DemiBold)

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor("#15803d"))

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor("#b45309"))

        self.fmt_boolean = QTextCharFormat()
        self.fmt_boolean.setForeground(QColor("#7c3aed"))
        self.fmt_boolean.setFontWeight(QFont.Weight.Bold)

        self.fmt_null = QTextCharFormat()
        self.fmt_null.setForeground(QColor("#64748b"))

        self._re_key = re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)')
        self._re_string = re.compile(r':\s*("(?:\\.|[^"\\])*")')
        self._re_bool = re.compile(r"\b(true|false)\b")
        self._re_null = re.compile(r"\b(null)\b")
        self._re_num = re.compile(r"(?<=:\s)(-?\d+(?:\.\d+)?)")

    def apply_palette(self, styles: dict[str, Any]) -> None:
        """Atualiza cores do realce a partir de um dicionário de tema do editor."""
        kw = styles.get("keyword", {}).get("fore")
        st = styles.get("string", {}).get("fore")
        nm = styles.get("number", {}).get("fore")
        fn = styles.get("function", {}).get("fore")
        cm = styles.get("comment", {}).get("fore")

        if kw:
            self.fmt_key.setForeground(QColor(kw))
        if st:
            self.fmt_string.setForeground(QColor(st))
        if nm:
            self.fmt_number.setForeground(QColor(nm))
        if fn:
            self.fmt_boolean.setForeground(QColor(fn))
        if cm:
            self.fmt_null.setForeground(QColor(cm))
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not self.enabled or not text:
            return

        for m in self._re_key.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_key)

        for m in self._re_string.finditer(text):
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.fmt_string)

        for m in self._re_bool.finditer(text):
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.fmt_boolean)

        for m in self._re_null.finditer(text):
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.fmt_null)

        for m in self._re_num.finditer(text):
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.fmt_number)


class _LabelVarAdapter:
    """Adaptador de leitura/escrita `.get()` / `.set()` sobre `QLabel`."""

    def __init__(self, label: QLabel) -> None:
        self._label = label

    def get(self) -> str:
        return self._label.text()

    def set(self, value: str) -> None:
        self._label.setText(str(value))


class JsonEditorPage(QWidget):
    """
    Página 1 do Wizard: Editor de JSON com validação, formatação UPPERCASE e salvamento.

    Signals:
        json_changed (dict): Emitido quando o JSON compartilhado é validado/atualizado.
        cursor_position_changed (int, int): Emitido quando linha/coluna do cursor muda.
        back_to_landing_requested (): Emitido quando o usuário clica em Voltar à Tela Inicial.
    """

    json_changed = Signal(dict)
    cursor_position_changed = Signal(int, int)
    back_to_landing_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        shared_json: dict[str, Any] | None = None,
        on_json_changed: Callable[[dict[str, Any]], None] | None = None,
        on_back_to_landing: Callable[[], None] | None = None,
        theme_service: ThemeService | None = None,
        config_service: ConfigService | None = None,
    ) -> None:
        super().__init__(parent)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_json_changed = on_json_changed
        self.on_back_to_landing = on_back_to_landing
        self._theme_service = theme_service
        self._config_service = config_service
        self._config_tokens: list[int] = []

        self.current_file: Path | None = None
        self.original_data: dict[str, Any] | None = (
            copy.deepcopy(self.shared_json) if self.shared_json else None
        )

        self.setAcceptDrops(True)
        self.setAccessibleName("Editor de JSON")
        self._build_ui()

        self.status_var = _LabelVarAdapter(self.lbl_status)
        self.counts_var = _LabelVarAdapter(self.lbl_counts)

        if self._theme_service is not None:
            self.apply_theme_from_service(self._theme_service)
            self._theme_service.editor_theme_changed.connect(
                lambda _: self.apply_theme_from_service(self._theme_service)  # type: ignore[arg-type]
            )

        self._apply_editor_config()
        self._bind_config_service()
        self.destroyed.connect(self._cleanup_config_subscriptions)

        if self.shared_json:
            self.refresh_from_shared()
        else:
            self._update_counts()

    def _bind_config_service(self) -> None:
        if self._config_service is None or not hasattr(self._config_service, "subscribe"):
            return
        for key in ("tab_size", "show_whitespace", "font_family", "font_size"):
            token = self._config_service.subscribe(key, lambda _v: self._on_editor_config_changed())
            self._config_tokens.append(token)

    def _cleanup_config_subscriptions(self) -> None:
        if self._config_service is not None and hasattr(self._config_service, "unsubscribe"):
            for token in self._config_tokens:
                try:
                    self._config_service.unsubscribe(token)
                except Exception:
                    pass
        self._config_tokens.clear()

    def _on_editor_config_changed(self) -> None:
        try:
            self._apply_editor_config()
        except RuntimeError:
            self._cleanup_config_subscriptions()

    def _apply_editor_config(self) -> None:
        if self._config_service is None or not hasattr(self._config_service, "config"):
            return
        cfg = self._config_service.config
        font_family = str(getattr(cfg, "font_family", "JetBrains Mono") or "JetBrains Mono")
        font_size = int(getattr(cfg, "font_size", 11) or 11)
        font = QFont(font_family, font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_area.setFont(font)

        tab_size = max(1, int(getattr(cfg, "tab_size", 4) or 4))
        space_width = max(1, self.text_area.fontMetrics().horizontalAdvance(" "))
        self.text_area.setTabStopDistance(float(tab_size * space_width))

        option = self.text_area.document().defaultTextOption()
        flags = option.flags()
        if bool(getattr(cfg, "show_whitespace", False)):
            flags |= QTextOption.Flag.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(flags)
        self.text_area.document().setDefaultTextOption(option)

    @property
    def json_data(self) -> dict[str, Any] | None:
        """Retorna o dicionário compartilhado ativo (ou `None` se vazio)."""
        return self.shared_json if self.shared_json else None

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(8)

        # Barra de ferramentas interna da página
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_validate_format = QPushButton("Validar & Formatar", self)
        self.btn_validate_format.setProperty("variant", "primary")
        self.btn_validate_format.setAccessibleName("Validar e Formatar JSON")
        self.btn_validate_format.setToolTip(
            "Valida a sintaxe e estrutura do JSON, aplica UPPERCASE nos textos e sincroniza as páginas"
        )
        self.btn_validate_format.clicked.connect(lambda: self.validate_and_format(False))
        toolbar.addWidget(self.btn_validate_format)

        self.btn_save_as = QPushButton("Salvar JSON como…", self)
        self.btn_save_as.setAccessibleName("Salvar JSON como")
        self.btn_save_as.setToolTip("Salvar o JSON formatado em um arquivo no disco (Ctrl+S)")
        self.btn_save_as.clicked.connect(self.save_json_as_dialog)
        toolbar.addWidget(self.btn_save_as)

        self.btn_reset = QPushButton("Redefinir", self)
        self.btn_reset.setAccessibleName("Redefinir JSON")
        self.btn_reset.setToolTip("Restaura o JSON original carregado nesta sessão")
        self.btn_reset.clicked.connect(self.reset_json)
        toolbar.addWidget(self.btn_reset)

        toolbar.addStretch(1)

        self.chk_highlight = QCheckBox("Realce de sintaxe", self)
        self.chk_highlight.setChecked(True)
        self.chk_highlight.setAccessibleName("Ativar realce de sintaxe JSON")
        self.chk_highlight.setToolTip("Liga ou desliga a colorização de chaves e valores JSON")
        self.chk_highlight.toggled.connect(self._on_highlight_toggled)
        toolbar.addWidget(self.chk_highlight)

        self.btn_back = QPushButton("Voltar à Tela Inicial", self)
        self.btn_back.setAccessibleName("Voltar à Tela Inicial")
        self.btn_back.setToolTip("Descarta a sessão atual e retorna à Tela Inicial")
        self.btn_back.clicked.connect(self._handle_back_to_landing)
        toolbar.addWidget(self.btn_back)

        root_layout.addLayout(toolbar)

        # Editor de Texto Monoespaçado
        self.text_area = QPlainTextEdit(self)
        self.text_area.setAccessibleName("Área de Edição JSON")
        self.text_area.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("JetBrains Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_area.setFont(font)

        self.highlighter = JsonSyntaxHighlighter(self.text_area.document())

        self.text_area.textChanged.connect(self._on_text_modified)
        self.text_area.cursorPositionChanged.connect(self._on_cursor_changed)
        root_layout.addWidget(self.text_area, 1)

        # Barra de status inferior
        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.lbl_status = QLabel(
            "Edite o JSON abaixo e clique em 'Validar & Formatar' para aplicar UPPERCASE e atualizar as abas.",
            self,
        )
        self.lbl_status.setAccessibleName("Status do Editor JSON")
        status_row.addWidget(self.lbl_status, 1)

        self.lbl_counts = QLabel("Linhas: 1 | Caracteres: 0", self)
        self.lbl_counts.setAccessibleName("Contagem de Linhas e Caracteres")
        status_row.addWidget(self.lbl_counts)

        root_layout.addLayout(status_row)

    def apply_theme_from_service(self, theme_service: ThemeService) -> None:
        """Aplica as cores e fonte do `ThemeService` ao editor e realçador."""
        theme_service.apply_editor_theme(self.text_area)
        theme_data = theme_service.get_editor_theme_data()
        styles = theme_data.get("styles", {})
        if isinstance(styles, dict):
            self.highlighter.apply_palette(styles)

    def _on_highlight_toggled(self, checked: bool) -> None:
        self.highlighter.enabled = bool(checked)
        self.highlighter.rehighlight()

    def _on_text_modified(self) -> None:
        self._update_counts()

    def _on_cursor_changed(self) -> None:
        cursor = self.text_area.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursor_position_changed.emit(line, col)

    def _update_counts(self) -> None:
        conteudo = self.text_area.toPlainText()
        num_chars = len(conteudo)
        num_lines = conteudo.count("\n") + 1 if conteudo else 1
        self.lbl_counts.setText(f"Linhas: {num_lines} | Caracteres: {num_chars}")

    # -------------------------------------------------------------------------
    # Drag-and-Drop
    # -------------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            local_file = urls[0].toLocalFile()
            if local_file:
                self.handle_dropped_file(local_file)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def handle_dropped_file(
        self, file_path: str | Path, show_error_dialog: bool = True
    ) -> bool:
        """Processa um arquivo arrastado para dentro do editor."""
        path = Path(str(file_path).strip().strip('"'))
        if path.suffix.lower() != ".json":
            msg = f"Apenas arquivos .json são suportados.\nArquivo recebido: {path.name}"
            self.lbl_status.setText(f"Erro: arquivo '{path.name}' não é um .json.")
            if show_error_dialog:
                QMessageBox.critical(self, "Arquivo Inválido", msg)
            return False
        return self.load_file(path, show_error_dialog=show_error_dialog)

    # -------------------------------------------------------------------------
    # Manipulação do Texto e Sincronização com `shared_json`
    # -------------------------------------------------------------------------
    def get_editor_text(self) -> str:
        """Retorna o texto atual da área de edição."""
        return self.text_area.toPlainText()

    def set_editor_text(self, text: str) -> None:
        """Substitui o texto na área de edição e atualiza contadores."""
        self.text_area.setPlainText(text)
        self._update_counts()

    def refresh_from_shared(self) -> None:
        """Recarrega o texto do editor a partir de `self.shared_json`."""
        if not self.shared_json:
            self.set_editor_text("")
            return
        update_shared_dict_in_place(self.shared_json, self.shared_json)
        self.set_editor_text(format_json(self.shared_json))

    def set_json_data(
        self,
        data: dict[str, Any],
        *,
        update_original: bool = False,
        apply_uppercase: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        """Atualiza `self.shared_json` in-place, formata o texto no editor e notifica ouvintes."""
        if update_original:
            self.original_data = copy.deepcopy(data)

        processed = uppercase_target_fields(data) if apply_uppercase else copy.deepcopy(data)
        if isinstance(processed, dict):
            self.shared_json.clear()
            self.shared_json.update(processed)

        self.set_editor_text(format_json(self.shared_json))

        if notify:
            if self.on_json_changed is not None:
                self.on_json_changed(self.shared_json)
            self.json_changed.emit(self.shared_json)

        return self.shared_json

    def get_json_data(self) -> dict[str, Any] | None:
        """Retorna o dicionário compartilhado (ou `None` se vazio)."""
        return self.shared_json if self.shared_json else None

    def validate_and_format(
        self, show_dialog_on_success: bool = False, show_error_dialog: bool = True
    ) -> bool:
        """
        Valida o JSON no editor, verifica estrutura mínima (`template` + `perguntas`),
        converte campos alvo para UPPERCASE, formata e atualiza `self.shared_json`.
        """
        raw_text = self.get_editor_text()
        try:
            parsed = validate_json_text(raw_text)
        except json.JSONDecodeError as exc:
            self.lbl_status.setText(
                f"JSON inválido (Linha {exc.lineno}, Coluna {exc.colno}): {exc.msg}"
            )
            logger.warning("Erro de sintaxe JSON na linha %d, col %d: %s", exc.lineno, exc.colno, exc.msg)
            if show_error_dialog:
                QMessageBox.critical(
                    self,
                    "Erro de Validação JSON",
                    f"O JSON informado não está bem-formado:\n\n"
                    f"Erro: {exc.msg}\n"
                    f"Linha: {exc.lineno}, Coluna: {exc.colno}",
                )
            return False
        except ValueError as exc:
            self.lbl_status.setText(f"Erro: {exc}")
            logger.warning("Erro de validação JSON: %s", exc)
            if show_error_dialog:
                QMessageBox.critical(self, "Erro de Validação JSON", str(exc))
            return False

        is_valid_struct, struct_msg = validate_clinical_json_structure(parsed)
        if not is_valid_struct:
            self.lbl_status.setText(struct_msg)
            logger.warning("Estrutura JSON clínica inválida: %s", struct_msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Estrutura JSON Inválida", struct_msg)
            return False

        if self.original_data is None:
            self.original_data = copy.deepcopy(parsed)

        self.set_json_data(parsed, update_original=False, apply_uppercase=True, notify=True)
        self.lbl_status.setText(
            "JSON validado, formatado e atualizado (campos de texto em UPPERCASE)."
        )
        if show_dialog_on_success:
            QMessageBox.information(
                self,
                "JSON Validado",
                "JSON validado, formatado e atualizado com sucesso (textos em UPPERCASE).",
            )
        return True

    save_changes = validate_and_format

    def save_json_as_dialog(self) -> bool:
        """Valida/formata o JSON atual e abre diálogo 'Salvar como…'."""
        if not self.validate_and_format(show_dialog_on_success=False):
            return False

        initial_name = self.current_file.name if self.current_file else "ficha_clinica.json"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar JSON como…",
            initial_name,
            "Arquivos JSON (*.json);;Todos os arquivos (*.*)",
        )
        if not save_path:
            return False

        try:
            save_json_file(save_path, self.shared_json, apply_uppercase=False)
            self.current_file = Path(save_path)
            self.lbl_status.setText(f"Arquivo salvo com sucesso em: {self.current_file.name}")
            logger.info("JSON salvo em '%s'", self.current_file)
            return True
        except OSError as exc:
            logger.error("Erro ao gravar JSON em '%s': %s", save_path, exc)
            QMessageBox.critical(
                self,
                "Erro ao Salvar Arquivo",
                f"Não foi possível gravar o arquivo:\n{save_path}\n\nDetalhes: {exc}",
            )
            self.lbl_status.setText("Erro ao gravar arquivo no disco.")
            return False

    export_to_file_dialog = save_json_as_dialog

    def load_file(
        self, file_path: str | Path, show_error_dialog: bool = True
    ) -> bool:
        """Carrega um arquivo `.json` diretamente no editor, validando-o."""
        path = Path(file_path)
        try:
            raw_content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            self.lbl_status.setText(f"Erro ao ler arquivo: {path.name}")
            if show_error_dialog:
                QMessageBox.critical(
                    self,
                    "Erro ao Abrir Arquivo",
                    f"Não foi possível ler o arquivo:\n{path}\n\nDetalhes: {exc}",
                )
            return False

        try:
            parsed = validate_json_text(raw_content)
        except json.JSONDecodeError as exc:
            self.set_editor_text(raw_content)
            self.lbl_status.setText(
                f"Erro de validação em '{path.name}' (linha {exc.lineno}, coluna {exc.colno})."
            )
            if show_error_dialog:
                QMessageBox.critical(
                    self,
                    "JSON Inválido",
                    f"O arquivo '{path.name}' contém JSON malformado:\n"
                    f"{exc.msg} (Linha {exc.lineno}, Coluna {exc.colno})",
                )
            return False
        except ValueError as exc:
            self.lbl_status.setText(str(exc))
            if show_error_dialog:
                QMessageBox.critical(self, "JSON Inválido", str(exc))
            return False

        is_valid_struct, struct_msg = validate_clinical_json_structure(parsed)
        if not is_valid_struct:
            self.lbl_status.setText(struct_msg)
            if show_error_dialog:
                QMessageBox.critical(self, "Estrutura JSON Inválida", struct_msg)
            return False

        self.current_file = path
        self.set_json_data(parsed, update_original=True, apply_uppercase=True, notify=True)
        self.lbl_status.setText(f"Arquivo carregado com sucesso: {path.name} (textos em UPPERCASE)")
        return True

    def load_from_file_dialog(self) -> bool:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Carregar JSON de Ficha Clínica",
            "",
            "Arquivos JSON (*.json);;Todos os arquivos (*.*)",
        )
        if not file_path:
            return False
        return self.load_file(file_path)

    def paste_from_clipboard(self, show_error_dialog: bool = True) -> bool:
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text() if clipboard is not None else ""
        if not clipboard_text.strip():
            self.lbl_status.setText("Aviso: área de transferência vazia.")
            if show_error_dialog:
                QMessageBox.warning(
                    self,
                    "Área de Transferência Vazia",
                    "Não há texto disponível na área de transferência para colar.",
                )
            return False

        self.set_editor_text(clipboard_text)
        return self.validate_and_format(
            show_dialog_on_success=False, show_error_dialog=show_error_dialog
        )

    def reset_json(self) -> bool:
        """Restaura o JSON original carregado na sessão atual."""
        if self.original_data is None:
            self.lbl_status.setText("Nenhum JSON original para redefinir.")
            return False

        restored = copy.deepcopy(self.original_data)
        self.set_json_data(restored, update_original=False, apply_uppercase=True, notify=True)
        nome_origem = self.current_file.name if self.current_file else "original"
        self.lbl_status.setText(f"JSON redefinido para o estado {nome_origem}.")
        return True

    def _handle_back_to_landing(self) -> None:
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
        self.back_to_landing_requested.emit()
