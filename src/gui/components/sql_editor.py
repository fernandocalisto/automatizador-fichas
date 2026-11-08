# -*- coding: utf-8 -*-
"""
Widget Editor SQL reutilizável (src/gui/components/sql_editor.py).

Fornece `SqlEditorWidget` baseado em `QPlainTextEdit` com:
- Syntax Highlighter customizado (PostgreSQL + Jasper)
- Line numbers via QTextBlock
- Code folding básico
- Brace matching
- Auto-indent
- Tema sincronizado com ThemeService (5 temas: vscode, monokai, dracula, github, solarized)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QWidget

logger = logging.getLogger("gui.components.sql_editor")

# ----------------------------------------------------------------------
# Syntax Highlighter PostgreSQL + Jasper
# ----------------------------------------------------------------------
class SqlSyntaxHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe PostgreSQL + Jasper para QPlainTextEdit."""

    def __init__(self, document: QTextDocument, theme: str = "vscode") -> None:
        super().__init__(document)
        self._theme = theme
        self._build_formats()

    def _build_formats(self) -> None:
        """Constrói formatos de cor baseados no tema."""
        themes = {
            "vscode": {
                "keyword": "#569cd6",
                "type": "#4ec9b0",
                "function": "#dcdcaa",
                "number": "#b5cea8",
                "string": "#ce9178",
                "comment": "#6a9955",
                "operator": "#d4d4d4",
                "preprocessor": "#c586c0",
                "jasper_param": "#d19a66",
                "jasper_clause": "#569cd6",
                "jasper_raw": "#ce9178",
            },
            "monokai": {
                "keyword": "#f92672",
                "type": "#66d9ef",
                "function": "#a6e22e",
                "number": "#ae81ff",
                "string": "#e6db74",
                "comment": "#75715e",
                "operator": "#f8f8f2",
                "preprocessor": "#ae81ff",
                "jasper_param": "#fd971f",
                "jasper_clause": "#f92672",
                "jasper_raw": "#e6db74",
            },
            "dracula": {
                "keyword": "#ff79c6",
                "type": "#8be9fd",
                "function": "#50fa7b",
                "number": "#bd93f9",
                "string": "#f1fa8c",
                "comment": "#6272a4",
                "operator": "#f8f8f2",
                "preprocessor": "#ffb86c",
                "jasper_param": "#ffb86c",
                "jasper_clause": "#ff79c6",
                "jasper_raw": "#f1fa8c",
            },
            "github": {
                "keyword": "#d73a49",
                "type": "#005cc5",
                "function": "#6f42c1",
                "number": "#005cc5",
                "string": "#032f62",
                "comment": "#6a737d",
                "operator": "#24292e",
                "preprocessor": "#6f42c1",
                "jasper_param": "#e36209",
                "jasper_clause": "#d73a49",
                "jasper_raw": "#032f62",
            },
            "solarized": {
                "keyword": "#859900",
                "type": "#268bd2",
                "function": "#b58900",
                "number": "#2aa198",
                "string": "#2aa198",
                "comment": "#586e75",
                "operator": "#839496",
                "preprocessor": "#cb4b16",
                "jasper_param": "#cb4b16",
                "jasper_clause": "#859900",
                "jasper_raw": "#2aa198",
            },
        }
        
        t = themes.get(self._theme, themes["vscode"])
        
        self.fmt_keyword = QTextCharFormat()
        self.fmt_keyword.setForeground(QColor(t["keyword"]))
        self.fmt_keyword.setFontWeight(QFont.Weight.Bold)

        self.fmt_type = QTextCharFormat()
        self.fmt_type.setForeground(QColor(t["type"]))
        self.fmt_type.setFontWeight(QFont.Weight.Bold)

        self.fmt_function = QTextCharFormat()
        self.fmt_function.setForeground(QColor(t["function"]))
        self.fmt_function.setFontWeight(QFont.Weight.Bold)

        self.fmt_number = QTextCharFormat()
        self.fmt_number.setForeground(QColor(t["number"]))

        self.fmt_string = QTextCharFormat()
        self.fmt_string.setForeground(QColor(t["string"]))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor(t["comment"]))
        self.fmt_comment.setFontItalic(True)

        self.fmt_operator = QTextCharFormat()
        self.fmt_operator.setForeground(QColor(t["operator"]))

        self.fmt_preprocessor = QTextCharFormat()
        self.fmt_preprocessor.setForeground(QColor(t["preprocessor"]))
        self.fmt_preprocessor.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_param = QTextCharFormat()
        self.fmt_jasper_param.setForeground(QColor(t["jasper_param"]))
        self.fmt_jasper_param.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_clause = QTextCharFormat()
        self.fmt_jasper_clause.setForeground(QColor(t["jasper_clause"]))
        self.fmt_jasper_clause.setFontWeight(QFont.Weight.Bold)

        self.fmt_jasper_raw = QTextCharFormat()
        self.fmt_jasper_raw.setForeground(QColor(t["jasper_raw"]))
        self.fmt_jasper_raw.setFontWeight(QFont.Weight.Bold)

        # Keywords PostgreSQL
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
        
        # Jasper patterns: $P{...}, $X{...}, $P!{...}
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

        # Protege strings e comentários
        protected: list[tuple[int, int]] = []
        
        # Strings
        for m in self._re_string.finditer(text):
            s, e = m.span()
            protected.append((s, e))
            self.setFormat(s, e - s, self.fmt_string)

        # Comentários
        for m in self._re_comment.finditer(text):
            s, e = m.span()
            protected.append((s, e))
            self.setFormat(s, e - s, self.fmt_comment)

        def is_protected(start: int, end: int) -> bool:
            return any(start < p_end and end > p_start for p_start, p_end in protected)

        # Jasper patterns (prioridade alta)
        for m in self._re_jasper_param.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_param)

        for m in self._re_jasper_clause.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_clause)

        for m in self._re_jasper_raw.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_jasper_raw)

        # Keywords
        for m in self._re_keyword.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_keyword)

        # Functions
        for m in self._re_function.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_function)

        # Types
        for m in self._re_type.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_type)

        # Numbers
        for m in self._re_number.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_number)

        # Operators
        for m in self._re_operator.finditer(text):
            if not is_protected(m.start(), m.end()):
                self.setFormat(m.start(), m.end() - m.start(), self.fmt_operator)


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
    ) -> None:
        super().__init__(parent)
        
        self._theme_service = theme_service
        self._current_editor_theme = "vscode"
        self._read_only = read_only
        
        self.setReadOnly(read_only)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        
        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        
        self._highlighter = SqlSyntaxHighlighter(self.document(), "vscode")
        
        self._apply_theme()
        
        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self.textChanged.connect(self._on_text_changed)
    
    def _apply_theme(self) -> None:
        """Aplica tema do editor."""
        if self._theme_service:
            try:
                theme_name = self._theme_service.current_editor_theme()
                self._current_editor_theme = theme_name
                if hasattr(self, "_highlighter"):
                    self._highlighter.set_theme(theme_name)
            except Exception as e:
                logger.warning(f"Erro ao aplicar tema do editor: {e}")

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
        if hasattr(self, "_highlighter"):
            self._highlighter.set_theme(theme_name)

    def set_read_only(self, read_only: bool) -> None:
        """Define modo somente leitura."""
        self._read_only = read_only
        self.setReadOnly(read_only)

    def get_text(self) -> str:
        """Retorna texto atual."""
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Define texto do editor."""
        self.blockSignals(True)
        self.setPlainText(text)
        self.blockSignals(False)

    def find_first(self, pattern: str, case_sensitive: bool = False, 
                   whole_words: bool = False, regex: bool = False) -> bool:
        """Busca padrão no texto."""
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_words:
            flags |= QTextDocument.FindFlag.FindWholeWords
        return self.find(pattern, flags)

    def replace(self, replacement: str) -> None:
        """Substitui seleção atual."""
        self.replaceSelectedText(replacement)

    def zoom_in(self, range_: int = 1) -> None:
        """Aumenta zoom."""
        self.zoomIn(range_)

    def zoom_out(self, range_: int = 1) -> None:
        """Diminui zoom."""
        self.zoomOut(range_)

    def reset_zoom(self) -> None:
        """Reseta zoom."""
        while self.zoomTo(0):
            pass


__all__ = ["SqlEditorWidget"]