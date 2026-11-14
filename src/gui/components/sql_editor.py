# -*- coding: utf-8 -*-
"""
Widget Editor SQL reutilizável (src/gui/components/sql_editor.py).

Fornece `SqlEditorWidget` baseado em `QPlainTextEdit` com:
- Syntax Highlighter customizado (PostgreSQL + Jasper)
- Margem de numeração de linhas (`LineNumberArea`)
- Atalhos de busca e substituição (`Ctrl+F`, `Ctrl+H`, `F3`, `Shift+F3`)
- Consumo dos temas JSON em `src/resources/editor_themes/*.json`
- Integração com `ThemeService` e `ConfigService` (`tab_size`, `show_line_numbers`,
  `show_whitespace`, `font_family`, `font_size`, `editor_theme`)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from PySide6.QtCore import QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import QInputDialog, QPlainTextEdit, QWidget

from src.utils.resource_path import resource_path

logger = logging.getLogger("gui.components.sql_editor")

BUILTIN_EDITOR_THEMES: dict[str, dict[str, Any]] = {
    "vscode": {
        "background": "#1E1E1E",
        "foreground": "#D4D4D4",
        "selection": "#264F78",
        "line_number": "#858585",
        "line_number_bg": "#1E1E1E",
        "styles": {
            "keyword": {"fore": "#569cd6"},
            "type": {"fore": "#4ec9b0"},
            "function": {"fore": "#dcdcaa"},
            "number": {"fore": "#b5cea8"},
            "string": {"fore": "#ce9178"},
            "comment": {"fore": "#6a9955"},
            "operator": {"fore": "#d4d4d4"},
            "preprocessor": {"fore": "#c586c0"},
            "jasper_param": {"fore": "#d19a66"},
            "jasper_clause": {"fore": "#569cd6"},
            "jasper_raw": {"fore": "#ce9178"},
        },
    },
    "monokai": {
        "background": "#272822",
        "foreground": "#F8F8F2",
        "selection": "#49483E",
        "line_number": "#90908A",
        "line_number_bg": "#272822",
        "styles": {
            "keyword": {"fore": "#f92672"},
            "type": {"fore": "#66d9ef"},
            "function": {"fore": "#a6e22e"},
            "number": {"fore": "#ae81ff"},
            "string": {"fore": "#e6db74"},
            "comment": {"fore": "#75715e"},
            "operator": {"fore": "#f8f8f2"},
            "preprocessor": {"fore": "#ae81ff"},
            "jasper_param": {"fore": "#fd971f"},
            "jasper_clause": {"fore": "#f92672"},
            "jasper_raw": {"fore": "#e6db74"},
        },
    },
    "dracula": {
        "background": "#282A36",
        "foreground": "#F8F8F2",
        "selection": "#44475A",
        "line_number": "#6272A4",
        "line_number_bg": "#282A36",
        "styles": {
            "keyword": {"fore": "#ff79c6"},
            "type": {"fore": "#8be9fd"},
            "function": {"fore": "#50fa7b"},
            "number": {"fore": "#bd93f9"},
            "string": {"fore": "#f1fa8c"},
            "comment": {"fore": "#6272a4"},
            "operator": {"fore": "#f8f8f2"},
            "preprocessor": {"fore": "#ffb86c"},
            "jasper_param": {"fore": "#ffb86c"},
            "jasper_clause": {"fore": "#ff79c6"},
            "jasper_raw": {"fore": "#f1fa8c"},
        },
    },
    "github": {
        "background": "#FFFFFF",
        "foreground": "#24292E",
        "selection": "#C8C8FA",
        "line_number": "#6A737D",
        "line_number_bg": "#F6F8FA",
        "styles": {
            "keyword": {"fore": "#d73a49"},
            "type": {"fore": "#005cc5"},
            "function": {"fore": "#6f42c1"},
            "number": {"fore": "#005cc5"},
            "string": {"fore": "#032f62"},
            "comment": {"fore": "#6a737d"},
            "operator": {"fore": "#24292e"},
            "preprocessor": {"fore": "#6f42c1"},
            "jasper_param": {"fore": "#e36209"},
            "jasper_clause": {"fore": "#d73a49"},
            "jasper_raw": {"fore": "#032f62"},
        },
    },
    "solarized": {
        "background": "#002B36",
        "foreground": "#839496",
        "selection": "#073642",
        "line_number": "#586E75",
        "line_number_bg": "#002B36",
        "styles": {
            "keyword": {"fore": "#859900"},
            "type": {"fore": "#268bd2"},
            "function": {"fore": "#b58900"},
            "number": {"fore": "#2aa198"},
            "string": {"fore": "#2aa198"},
            "comment": {"fore": "#586e75"},
            "operator": {"fore": "#839496"},
            "preprocessor": {"fore": "#cb4b16"},
            "jasper_param": {"fore": "#cb4b16"},
            "jasper_clause": {"fore": "#859900"},
            "jasper_raw": {"fore": "#2aa198"},
        },
    },
}


def load_editor_theme_palette(
    theme_name: str, theme_service: Optional[object] = None
) -> dict[str, Any]:
    """Carrega dados de tema via `ThemeService`, arquivo JSON em `editor_themes/` ou fallback."""
    target = (theme_name or "vscode").strip().lower()
    fallback = BUILTIN_EDITOR_THEMES.get(target, BUILTIN_EDITOR_THEMES["vscode"])

    data: dict[str, Any] = {}
    if theme_service is not None and hasattr(theme_service, "get_editor_theme_data"):
        try:
            loaded = theme_service.get_editor_theme_data(target)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            logger.debug("Falha ao consultar ThemeService para '%s': %s", target, exc)

    if not data:
        for rel in (
            f"src/resources/editor_themes/{target}.json",
            f"resources/editor_themes/{target}.json",
        ):
            disk_path = resource_path(rel)
            if disk_path.exists():
                try:
                    parsed = json.loads(disk_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        data = parsed
                        break
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("Erro ao ler tema JSON '%s': %s", disk_path, exc)

    merged = dict(fallback)
    merged_styles = dict(fallback.get("styles", {}))
    if isinstance(data, dict):
        for key in (
            "name",
            "background",
            "foreground",
            "caret",
            "selection",
            "line_number",
            "line_number_bg",
            "fold_margin",
        ):
            if data.get(key):
                merged[key] = data[key]
        raw_styles = data.get("styles")
        if isinstance(raw_styles, dict):
            merged_styles.update(raw_styles)
    merged["styles"] = merged_styles
    return merged


# ----------------------------------------------------------------------
# Syntax Highlighter PostgreSQL + Jasper
# ----------------------------------------------------------------------
class SqlSyntaxHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe PostgreSQL + Jasper para QPlainTextEdit."""

    def __init__(
        self,
        document: QTextDocument,
        theme: str = "vscode",
        theme_service: Optional[object] = None,
    ) -> None:
        super().__init__(document)
        self._theme = theme
        self._theme_service = theme_service
        self._build_formats()

    def _style_color(self, styles: dict[str, Any], key: str, default: str) -> str:
        entry = styles.get(key)
        if isinstance(entry, dict) and entry.get("fore"):
            return str(entry["fore"])
        return default

    def _build_formats(self) -> None:
        """Constrói formatos de cor baseados no tema."""
        palette = load_editor_theme_palette(self._theme, self._theme_service)
        styles = palette.get("styles", {})
        fallback_styles = BUILTIN_EDITOR_THEMES.get(
            (self._theme or "vscode").lower(), BUILTIN_EDITOR_THEMES["vscode"]
        )["styles"]

        def pick(key: str, fb_key: str | None = None) -> str:
            fb_default = fallback_styles.get(fb_key or key, {}).get("fore", "#d4d4d4")
            return self._style_color(styles, key, fb_default)

        self.fmt_keyword = QTextCharFormat()
        self.fmt_keyword.setForeground(QColor(pick("keyword")))
        self.fmt_keyword.setFontWeight(QFont.Weight.Bold)

        self.fmt_type = QTextCharFormat()
        self.fmt_type.setForeground(QColor(pick("type", "identifier")))
        self.fmt_type.setFontWeight(QFont.Weight.Bold)

        self.fmt_function = QTextCharFormat()
        self.fmt_function.setForeground(QColor(pick("function")))
        self.fmt_function.setFontWeight(QFont.Weight.Bold)

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor(pick("number")))

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor(pick("string")))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor(pick("comment")))
        self.fmt_comment.setFontItalic(True)

        self.fmt_operator = QTextCharFormat()
        self.fmt_operator.setForeground(QColor(pick("operator")))

        self.fmt_preprocessor = QTextCharFormat()
        self.fmt_preprocessor.setForeground(QColor(pick("preprocessor")))
        self.fmt_preprocessor.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_param = QTextCharFormat()
        self.fmt_jasper_param.setForeground(QColor(pick("jasper_param", "preprocessor")))
        self.fmt_jasper_param.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_clause = QTextCharFormat()
        self.fmt_jasper_clause.setForeground(QColor(pick("jasper_clause", "keyword")))
        self.fmt_jasper_clause.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_raw = QTextCharFormat()
        self.fmt_jasper_raw.setForeground(QColor(pick("jasper_raw", "string")))
        self.fmt_jasper_raw.setFontWeight(QFont.Weight.Bold)

        pg_keywords = [
            "SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "WHERE", "JOIN",
            "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "ON", "AS", "AND", "OR",
            "NOT", "NULL", "TRUE", "FALSE", "CREATE", "TABLE", "INDEX", "VIEW",
            "DROP", "ALTER", "ADD", "COLUMN", "CONSTRAINT", "PRIMARY", "KEY",
            "FOREIGN", "REFERENCES", "UNIQUE", "CHECK", "DEFAULT", "VALUES",
            "INTO", "SET", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET",
            "UNION", "EXCEPT", "INTERSECT", "DISTINCT", "CASE", "WHEN", "THEN",
            "ELSE", "END", "IF", "EXISTS", "IN", "BETWEEN", "LIKE", "ILIKE",
            "IS", "COALESCE", "NULLIF", "CAST", "EXTRACT", "CURRENT_DATE",
            "CURRENT_TIME", "CURRENT_TIMESTAMP", "NOW", "RETURNING", "WITH",
            "RECURSIVE", "WINDOW", "OVER", "PARTITION", "ROW_NUMBER", "RANK",
            "DENSE_RANK", "LEAD", "LAG", "FIRST_VALUE", "LAST_VALUE", "NTILE",
        ]

        pg_functions = [
            "COUNT", "SUM", "AVG", "MIN", "MAX", "COALESCE", "NULLIF", "GREATEST",
            "LEAST", "ABS", "ROUND", "CEIL", "FLOOR", "SQRT", "POWER", "EXP",
            "LN", "LOG", "NOW", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP",
            "EXTRACT", "DATE_TRUNC", "AGE", "DATE_PART", "TO_CHAR", "TO_DATE",
            "TO_TIMESTAMP", "UPPER", "LOWER", "TRIM", "SUBSTRING", "POSITION",
            "LENGTH", "CONCAT", "MD5", "ENCODE", "DECODE",
        ]

        pg_types = [
            "INTEGER", "BIGINT", "SMALLINT", "SERIAL", "BIGSERIAL", "NUMERIC",
            "DECIMAL", "REAL", "DOUBLE PRECISION", "MONEY", "VARCHAR", "CHAR",
            "TEXT", "BYTEA", "TIMESTAMP", "TIMESTAMPTZ", "DATE", "TIME", "TIMETZ",
            "INTERVAL", "BOOLEAN", "POINT", "LINE", "LSEG", "BOX", "PATH",
            "POLYGON", "CIRCLE", "CIDR", "INET", "MACADDR", "UUID", "XML", "JSON",
            "JSONB", "ARRAY", "ENUM", "RANGE", "MULTIRANGE",
        ]

        self._re_keyword = re.compile(rf"\b(?:{'|'.join(map(re.escape, pg_keywords))})\b", re.IGNORECASE)
        self._re_function = re.compile(rf"\b(?:{'|'.join(map(re.escape, pg_functions))})\b", re.IGNORECASE)
        self._re_type = re.compile(rf"\b(?:{'|'.join(map(re.escape, pg_types))})\b", re.IGNORECASE)
        self._re_number = re.compile(r"\b\d+(?:\.\d+)?\b")
        self._re_string = re.compile(r"'([^']|'')*'")
        self._re_comment = re.compile(r"--[^\n]*")
        self._re_operator = re.compile(r"[+\-*/=<>!~%^&|]+")

        self._re_jasper_param = re.compile(r"\$P\{[^}]+\}")
        self._re_jasper_clause = re.compile(r"\$X\{[^}]+\}")
        self._re_jasper_raw = re.compile(r"\$P!\{[^}]+\}")

    def set_theme(self, theme: str) -> None:
        """Muda o tema e reconstrói formatos."""
        self._theme = theme
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if not text:
            return

        protected: list[tuple[int, int]] = []

        for m in self._re_string.finditer(text):
            s, e = m.span()
            protected.append((s, e))
            self.setFormat(s, e - s, self.fmt_string)

        for m in self._re_comment.finditer(text):
            s, e = m.span()
            protected.append((s, e))
            self.setFormat(s, e - s, self.fmt_comment)

        def is_protected(start: int, end: int) -> bool:
            return any(start < p_end and end > p_start for p_start, p_end in protected)

        for m in self._re_jasper_param.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_param)

        for m in self._re_jasper_clause.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_clause)

        for m in self._re_jasper_raw.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_raw)

        for m in self._re_keyword.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_keyword)

        for m in self._re_function.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_function)

        for m in self._re_type.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_type)

        for m in self._re_number.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)

        for m in self._re_operator.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_operator)


# ----------------------------------------------------------------------
# Margem de Numeração de Linhas
# ----------------------------------------------------------------------
class LineNumberArea(QWidget):
    """Área lateral de numeração de linhas associada a um `SqlEditorWidget`."""

    def __init__(self, editor: SqlEditorWidget) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.line_number_area_paint_event(event)


# ----------------------------------------------------------------------
# Widget Principal
# ----------------------------------------------------------------------
class SqlEditorWidget(QPlainTextEdit):
    """
    Editor SQL completo com QPlainTextEdit + Syntax Highlighter customizado.

    Sinais:
        textChanged: emitido quando o texto muda
        cursorPositionChanged(line, col): emitido quando cursor move
    """

    cursorPositionChanged = Signal(int, int)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        read_only: bool = False,
        theme_service: Optional[object] = None,
        config_service: Optional[object] = None,
    ) -> None:
        super().__init__(parent)

        self._theme_service = theme_service
        self._config_service = config_service
        self._current_editor_theme = "vscode"
        self._read_only = read_only
        self._show_line_numbers = True
        self._tab_size = 4
        self._show_whitespace = False
        self._last_search_pattern = ""
        self._last_search_flags = QTextDocument.FindFlag(0)
        self._config_tokens: list[int] = []
        self._line_number_fg = QColor("#858585")
        self._line_number_bg = QColor("#1E1E1E")

        self.setReadOnly(read_only)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._default_font = QFont(font)
        self.setFont(font)

        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)

        self._highlighter = SqlSyntaxHighlighter(
            self.document(), "vscode", theme_service=self._theme_service
        )

        self._setup_shortcuts()
        self._apply_theme()
        self._apply_config_settings()
        self._bind_config_service()
        self._update_line_number_area_width(0)

        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self.textChanged.connect(self._on_text_changed)
        self.destroyed.connect(self._cleanup_subscriptions)

    def _setup_shortcuts(self) -> None:
        self._sc_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self._sc_find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_find.activated.connect(self._prompt_find)

        self._sc_replace = QShortcut(QKeySequence("Ctrl+H"), self)
        self._sc_replace.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_replace.activated.connect(self._prompt_replace)

        self._sc_find_next = QShortcut(QKeySequence("F3"), self)
        self._sc_find_next.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_find_next.activated.connect(self.find_next)

        self._sc_find_prev = QShortcut(QKeySequence("Shift+F3"), self)
        self._sc_find_prev.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_find_prev.activated.connect(self.find_previous)

    def _bind_config_service(self) -> None:
        if self._config_service is None or not hasattr(self._config_service, "subscribe"):
            return
        for key in (
            "tab_size",
            "show_line_numbers",
            "show_whitespace",
            "font_family",
            "font_size",
            "editor_theme",
        ):
            token = self._config_service.subscribe(key, lambda _v, k=key: self._on_config_key_changed(k))
            self._config_tokens.append(token)

    def _cleanup_subscriptions(self) -> None:
        if self._config_service is not None and hasattr(self._config_service, "unsubscribe"):
            for token in self._config_tokens:
                try:
                    self._config_service.unsubscribe(token)
                except Exception:
                    pass
        self._config_tokens.clear()

    def _on_config_key_changed(self, _key: str) -> None:
        try:
            self._apply_config_settings()
        except RuntimeError:
            self._cleanup_subscriptions()

    def _apply_config_settings(self) -> None:
        if self._config_service is None or not hasattr(self._config_service, "config"):
            self.set_tab_size(self._tab_size)
            self.set_show_line_numbers(self._show_line_numbers)
            self.set_show_whitespace(self._show_whitespace)
            return

        cfg = self._config_service.config
        font_family = str(getattr(cfg, "font_family", "JetBrains Mono") or "JetBrains Mono")
        font_size = int(getattr(cfg, "font_size", 10) or 10)
        font = QFont(font_family, font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._default_font = QFont(font)
        self.setFont(font)

        self.set_tab_size(int(getattr(cfg, "tab_size", 4) or 4))
        self.set_show_line_numbers(bool(getattr(cfg, "show_line_numbers", True)))
        self.set_show_whitespace(bool(getattr(cfg, "show_whitespace", False)))

        editor_theme = str(getattr(cfg, "editor_theme", "") or "")
        if editor_theme and editor_theme != self._current_editor_theme:
            self.set_theme(editor_theme)

    def _apply_theme(self) -> None:
        """Aplica tema do editor."""
        theme_name = self._current_editor_theme
        if self._theme_service and hasattr(self._theme_service, "current_editor_theme"):
            try:
                theme_name = self._theme_service.current_editor_theme()
            except Exception as e:
                logger.warning(f"Erro ao obter tema do editor: {e}")

        self._current_editor_theme = theme_name
        palette = load_editor_theme_palette(theme_name, self._theme_service)
        self._line_number_fg = QColor(str(palette.get("line_number", "#858585")))
        self._line_number_bg = QColor(
            str(palette.get("line_number_bg", palette.get("background", "#1E1E1E")))
        )
        if hasattr(self, "_highlighter"):
            self._highlighter.set_theme(theme_name)
        if self._theme_service and hasattr(self._theme_service, "apply_editor_theme"):
            try:
                self._theme_service.apply_editor_theme(self, theme_name)
            except Exception as e:
                logger.warning(f"Erro ao aplicar tema do editor: {e}")
        self._line_number_area.update()

    # ------------------------------------------------------------------
    # Line Numbers
    # ------------------------------------------------------------------
    def line_number_area_width(self) -> int:
        if not self._show_line_numbers:
            return 0
        digits = max(2, len(str(max(1, self.blockCount()))))
        space = 12 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    @Slot(int)
    def _update_line_number_area_width(self, _new_block_count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    @Slot(QRect, int)
    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if not self._show_line_numbers:
            return
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event: QPaintEvent) -> None:
        if not self._show_line_numbers:
            return
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self._line_number_bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())

        painter.setFont(self.font())
        painter.setPen(self._line_number_fg)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    @Slot()
    def _on_cursor_changed(self) -> None:
        """Emite posição do cursor (1-based)."""
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self.cursorPositionChanged.emit(line, col)

    @Slot()
    def _on_text_changed(self) -> None:
        """Callback quando texto muda."""
        pass

    # ------------------------------------------------------------------
    # API Pública
    # ------------------------------------------------------------------
    def set_theme(self, theme_name: str) -> None:
        """Muda tema do editor em runtime."""
        if theme_name == self._current_editor_theme:
            return
        self._current_editor_theme = theme_name
        self._apply_theme()

    def set_read_only(self, read_only: bool) -> None:
        """Define modo somente leitura."""
        self._read_only = read_only
        self.setReadOnly(read_only)

    def set_tab_size(self, spaces: int) -> None:
        """Define a largura visual da tabulação em quantidade de espaços."""
        self._tab_size = max(1, int(spaces))
        space_width = max(1, self.fontMetrics().horizontalAdvance(" "))
        self.setTabStopDistance(float(self._tab_size * space_width))

    def set_show_line_numbers(self, show: bool) -> None:
        """Exibe ou oculta a margem lateral com numeração de linhas."""
        self._show_line_numbers = bool(show)
        self._line_number_area.setVisible(self._show_line_numbers)
        self._update_line_number_area_width(0)

    def set_show_whitespace(self, show: bool) -> None:
        """Exibe ou oculta caracteres de espaço em branco e tabulação."""
        self._show_whitespace = bool(show)
        option = self.document().defaultTextOption()
        flags = option.flags()
        if self._show_whitespace:
            flags |= QTextOption.Flag.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(flags)
        self.document().setDefaultTextOption(option)

    def get_text(self) -> str:
        """Retorna texto atual."""
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Define texto do editor."""
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)
        self._update_line_number_area_width(0)

    def find_first(
        self,
        pattern: str,
        case_sensitive: bool = False,
        whole_words: bool = False,
        regex: bool = False,
    ) -> bool:
        """Busca padrão no texto a partir da posição atual (com fallback do início)."""
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_words:
            flags |= QTextDocument.FindFlag.FindWholeWords
        self._last_search_pattern = pattern
        self._last_search_flags = flags
        if not pattern:
            return False
        if self.find(pattern, flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return self.find(pattern, flags)

    def find_next(self) -> bool:
        """Avança para a próxima ocorrência da última busca."""
        if not self._last_search_pattern:
            return False
        if self.find(self._last_search_pattern, self._last_search_flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return self.find(self._last_search_pattern, self._last_search_flags)

    def find_previous(self) -> bool:
        """Retorna para a ocorrência anterior da última busca."""
        if not self._last_search_pattern:
            return False
        flags = self._last_search_flags | QTextDocument.FindFlag.FindBackward
        if self.find(self._last_search_pattern, flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)
        return self.find(self._last_search_pattern, flags)

    def _prompt_find(self) -> None:
        pattern, ok = QInputDialog.getText(
            self, "Buscar no SQL", "Texto a localizar:", text=self._last_search_pattern
        )
        if ok and pattern:
            self.find_first(pattern)

    def _prompt_replace(self) -> None:
        if self.isReadOnly():
            return
        pattern, ok = QInputDialog.getText(
            self, "Substituir no SQL", "Localizar:", text=self._last_search_pattern
        )
        if not ok or not pattern:
            return
        replacement, ok_rep = QInputDialog.getText(
            self, "Substituir no SQL", f"Substituir '{pattern}' por:"
        )
        if not ok_rep:
            return
        if self.find_first(pattern):
            self.replace(replacement)

    def replace(self, replacement: str) -> None:
        """Substitui seleção atual."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.insertText(replacement)

    def zoom_in(self, range_: int = 1) -> None:
        """Aumenta zoom."""
        self.zoomIn(range_)

    def zoom_out(self, range_: int = 1) -> None:
        """Diminui zoom."""
        self.zoomOut(range_)

    def reset_zoom(self) -> None:
        """Reseta zoom."""
        if hasattr(self, "_default_font"):
            self.setFont(QFont(self._default_font))
        else:
            font = QFont("JetBrains Mono", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.setFont(font)


__all__ = ["LineNumberArea", "SqlEditorWidget", "SqlSyntaxHighlighter"]
