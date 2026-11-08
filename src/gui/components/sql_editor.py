# -*- coding: utf-8 -*-
"""
Widget Editor SQL reutilizável com QScintilla (src/gui/components/sql_editor.py).

Fornece `SqlEditorWidget` baseado em `QsciScintilla` com:
- Lexer PostgreSQL (keywords, functions, types)
- Lexer Jasper Reports ($P{}, $X{}, $P!{})
- Line numbers margin
- Code folding (BoxedTree style)
- Brace matching
- Auto-indent
- Tema sincronizado com ThemeService (5 temas: vscode, monokai, dracula, github, solarized)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QWidget, QPlainTextEdit

# QScintilla imports - optional dependency
# Note: QScintilla bindings are for PyQt6 (PyQt6-QScintilla package)
# We import from PyQt6.Qsci since that's what the package provides
try:
    from PyQt6.Qsci import (
        QsciLexerCustom,
        QsciLexerPostgreSQL,
        QsciScintilla,
        QsciScintillaBase,
    )
    QSCI_AVAILABLE = True
except ImportError:
    QSCI_AVAILABLE = False
    QsciScintilla = QWidget  # fallback type
    QsciLexerCustom = object
    QsciLexerPostgreSQL = object

logger = logging.getLogger("gui.components.sql_editor")

# ----------------------------------------------------------------------
# Lexer PostgreSQL customizado (herda de QsciLexerPostgreSQL se disponível)
# ----------------------------------------------------------------------
if QSCI_AVAILABLE:
    class PostgreSQLJasperLexer(QsciLexerPostgreSQL):
        """
        Lexer PostgreSQL estendido para Jasper Reports ($P{}, $X{}, $P!{}).
        """

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._jasper_styles = {
                100: "JasperParameter",      # $P{...}
                101: "JasperClause",         # $X{...}
                102: "JasperRaw",            # $P!{...}
            }
            self.setDefaultColor(QColor("#0f172a"))  # slate-900

        def language(self) -> str:
            return "PostgreSQL + Jasper"

        def description(self, style: int) -> str:
            return self._jasper_styles.get(style, super().description(style))

        def styleText(self, start: int, end: int) -> None:
            """Highlighting customizado para Jasper + PostgreSQL padrão."""
            # Primeiro, deixa o lexer PostgreSQL fazer o trabalho base
            super().styleText(start, end)

            # Depois, sobrescreve regiões Jasper
            editor = self.editor()
            if not editor:
                return

            text = editor.text()[start:end]
            if not text:
                return

            # Estados para parsing simples
            i = 0
            length = len(text)
            while i < length:
                ch = text[i]
                if ch == '$' and i + 1 < length:
                    next_ch = text[i + 1]
                    if next_ch in ('P', 'X'):
                        # $P{...} ou $X{...} ou $P!{...}
                        style = 100 if next_ch == 'P' else 101
                        if i + 2 < length and text[i + 2] == '!':
                            style = 102
                            i += 3
                        else:
                            i += 2
                        # Avança até fechar }
                        brace_count = 0
                        start_pos = i
                        while i < length:
                            if text[i] == '{':
                                brace_count += 1
                            elif text[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    i += 1
                                    break
                            i += 1
                        # Aplica estilo
                        self.setStyling(i - start_pos, style)
                        continue
                i += 1


# ----------------------------------------------------------------------
# Widget Principal
# ----------------------------------------------------------------------
class SqlEditorWidget(QsciScintilla if QSCI_AVAILABLE else QWidget):
    """
    Editor SQL completo com QScintilla.
    
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
        
        if not QSCI_AVAILABLE:
            logger.warning("QScintilla não disponível - SqlEditorWidget em modo fallback")
            self._setup_fallback()
            return

        self._theme_service = theme_service
        self._current_editor_theme = "vscode"
        self._read_only = read_only
        
        self._setup_editor()
        self._setup_lexer()
        self._setup_margins()
        self._setup_folding()
        self._setup_indentation()
        self._setup_brace_matching()
        self._setup_shortcuts()
        self._apply_theme()
        
        # Conecta sinais
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)

    def _setup_fallback(self) -> None:
        """Configuração mínima quando QScintilla não está disponível."""
        self.setReadOnly(True)
        self.setPlaceholderText("QScintilla não instalado (pip install PyQt6-QScintilla)")

    def _setup_editor(self) -> None:
        """Configurações básicas do editor."""
        self.setUtf8(True)
        self.setReadOnly(self._read_only)
        
        # Fonte monoespaçada
        font = QFont("JetBrains Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setMarginsFont(font)
        
        # Caret
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#eff6ff"))  # blue-50
        self.setCaretWidth(2)
        
        # Seleção
        self.setSelectionBackgroundColor(QColor("#dbeafe"))  # blue-100
        self.setSelectionForegroundColor(QColor("#0f172a"))  # slate-900
        
        # Whitespace
        self.setWhitespaceVisibility(QsciScintillaBase.WhitespaceVisibility.WsInvisible)
        self.setWhitespaceSize(2)
        
        # Indent guides
        self.setIndentationGuides(True)
        self.setIndentationGuidesBackgroundColor(QColor("#e2e8f0"))
        self.setIndentationGuidesForegroundColor(QColor("#94a3b8"))

    def _setup_lexer(self) -> None:
        """Configura o lexer PostgreSQL + Jasper."""
        self._lexer = PostgreSQLJasperLexer(self)
        
        # Cores do lexer (serão sobrescritas pelo tema)
        self._lexer.setDefaultPaper(QColor("#ffffff"))
        self._lexer.setDefaultColor(QColor("#0f172a"))
        
        # Keywords PostgreSQL
        self._lexer.setColor(QColor("#1d4ed8"), QsciLexerPostgreSQL.Keyword)  # blue-700
        self._lexer.setColor(QColor("#059669"), QsciLexerPostgreSQL.Type)      # emerald-600
        self._lexer.setColor(QColor("#7c3aed"), QsciLexerPostgreSQL.Function)  # violet-600
        self._lexer.setColor(QColor("#dc2626"), QsciLexerPostgreSQL.Number)    # red-600
        self._lexer.setColor(QColor("#ea580c"), QsciLexerPostgreSQL.String)    # orange-600
        self._lexer.setColor(QColor("#64748b"), QsciLexerPostgreSQL.Comment)   # slate-500
        self._lexer.setColor(QColor("#475569"), QsciLexerPostgreSQL.Operator)  # slate-600
        self._lexer.setColor(QColor("#0891b2"), QsciLexerPostgreSQL.PreProcessor)  # cyan-600
        
        # Jasper custom styles
        self._lexer.setColor(QColor("#7c2d12"), 100)   # $P{} - amber-900
        self._lexer.setColor(QColor("#1d4ed8"), 101)   # $X{} - blue-700
        self._lexer.setColor(QColor("#be123c"), 102)   # $P!{} - rose-800
        self._lexer.setPaper(QColor("#fef3c7"), 100)   # amber-50 bg
        self._lexer.setPaper(QColor("#dbeafe"), 101)   # blue-50 bg
        self._lexer.setPaper(QColor("#ffe4e6"), 102)   # rose-50 bg
        
        self.setLexer(self._lexer)

    def _setup_margins(self) -> None:
        """Configura margem de números de linha."""
        # Margem 0 = line numbers
        font = QFont("JetBrains Mono", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setMarginsFont(font)
        self.setMarginWidth(0, "99999")
        self.setMarginLineNumbers(0, True)
        self.setMarginsBackgroundColor(QColor("#f8fafc"))  # slate-50
        self.setMarginsForegroundColor(QColor("#64748b"))  # slate-500
        self.setMarginSensitivity(0, True)

    def _setup_folding(self) -> None:
        """Configura code folding estilo BoxedTree."""
        self.setFolding(QsciScintillaBase.FoldStyle.BoxedTreeFoldStyle)
        self.setFoldMarginColors(QColor("#e2e8f0"), QColor("#f8fafc"))
        self.setMarginWidth(2, 16)  # margem de fold

    def _setup_indentation(self) -> None:
        """Configura indentação automática."""
        self.setIndentationsUseTabs(False)
        self.setIndentationWidth(4)
        self.setTabIndents(True)
        self.setBackspaceUnindents(True)
        self.setAutoIndent(True)

    def _setup_brace_matching(self) -> None:
        """Configura matching de parênteses/chaves."""
        self.setBraceMatching(QsciScintillaBase.BraceMatch.SloppyBraceMatch)

    def _setup_shortcuts(self) -> None:
        """Configura atalhos padrão do editor."""
        # Ctrl+F / Ctrl+H - Find/Replace (built-in via QsciScintilla)
        # F3 / Shift+F3 - Next/Previous (built-in)
        pass

    def _apply_theme(self) -> None:
        """Aplica tema do editor baseado no ThemeService."""
        if self._theme_service is None:
            return
            
        try:
            theme_name = self._theme_service.current_editor_theme()
            self._current_editor_theme = theme_name
            self._load_editor_theme(theme_name)
        except Exception as e:
            logger.warning(f"Erro ao aplicar tema do editor: {e}")

    def _load_editor_theme(self, theme_name: str) -> None:
        """Carrega tema JSON do editor."""
        theme_map = {
            "vscode": "vscode.json",
            "monokai": "monokai.json",
            "dracula": "dracula.json",
            "github": "github.json",
            "solarized": "solarized.json",
        }
        
        filename = theme_map.get(theme_name, "vscode.json")
        theme_path = Path(__file__).parent.parent / "resources" / "editor_themes" / filename
        
        if not theme_path.exists():
            logger.warning(f"Tema do editor não encontrado: {theme_path}")
            return
        
        try:
            import json
            with open(theme_path, "r", encoding="utf-8") as f:
                theme = json.load(f)
            
            self._apply_theme_colors(theme)
        except Exception as e:
            logger.warning(f"Erro ao carregar tema {theme_name}: {e}")

    def _apply_theme_colors(self, theme: dict) -> None:
        """Aplica cores do tema JSON ao editor e lexer."""
        # Editor background/foreground
        bg = theme.get("background", "#ffffff")
        fg = theme.get("foreground", "#0f172a")
        caret = theme.get("caret", "#3b82f6")
        selection_bg = theme.get("selectionBackground", "#dbeafe")
        selection_fg = theme.get("selectionForeground", "#0f172a")
        line_highlight = theme.get("lineHighlight", "#eff6ff")
        margin_bg = theme.get("marginBackground", "#f8fafc")
        margin_fg = theme.get("marginForeground", "#64748b")
        fold_bg = theme.get("foldBackground", "#e2e8f0")
        fold_fg = theme.get("foldForeground", "#f8fafc")
        indent_guide_bg = theme.get("indentGuideBackground", "#e2e8f0")
        indent_guide_fg = theme.get("indentGuideForeground", "#94a3b8")
        whitespace = theme.get("whitespace", "#cbd5e1")
        
        # Editor
        self.setPaper(QColor(bg))
        self.setColor(QColor(fg))
        self.setCaretForegroundColor(QColor(caret))
        self.setCaretLineBackgroundColor(QColor(line_highlight))
        self.setSelectionBackgroundColor(QColor(selection_bg))
        self.setSelectionForegroundColor(QColor(selection_fg))
        self.setWhitespaceForegroundColor(QColor(whitespace))
        self.setMarginsBackgroundColor(QColor(margin_bg))
        self.setMarginsForegroundColor(QColor(margin_fg))
        self.setFoldMarginColors(QColor(fold_bg), QColor(fold_fg))
        self.setIndentationGuidesBackgroundColor(QColor(indent_guide_bg))
        self.setIndentationGuidesForegroundColor(QColor(indent_guide_fg))
        
        # Lexer colors
        if hasattr(self, "_lexer"):
            lexer_colors = theme.get("lexer", {})
            if lexer_colors:
                self._lexer.setDefaultPaper(QColor(bg))
                self._lexer.setDefaultColor(QColor(fg))
                
                # Mapeia cores do tema para estilos do lexer
                style_map = {
                    "keyword": QsciLexerPostgreSQL.Keyword,
                    "type": QsciLexerPostgreSQL.Type,
                    "function": QsciLexerPostgreSQL.Function,
                    "number": QsciLexerPostgreSQL.Number,
                    "string": QsciLexerPostgreSQL.String,
                    "comment": QsciLexerPostgreSQL.Comment,
                    "operator": QsciLexerPostgreSQL.Operator,
                    "preprocessor": QsciLexerPostgreSQL.PreProcessor,
                    "jasper_param": 100,
                    "jasper_clause": 101,
                    "jasper_raw": 102,
                }
                
                for key, style_id in style_map.items():
                    color = lexer_colors.get(key)
                    if color:
                        self._lexer.setColor(QColor(color), style_id)
                    
                    paper = lexer_colors.get(f"{key}Background")
                    if paper:
                        self._lexer.setPaper(QColor(paper), style_id)

    @Slot()
    def _on_text_changed(self) -> None:
        """Callback quando texto muda."""
        pass  # Para override externo se necessário

    @Slot(int, int)
    def _on_cursor_position_changed(self, line: int, index: int) -> None:
        """Callback quando cursor move."""
        self.cursorPositionChanged.emit(line + 1, index + 1)  # 1-based

    # ------------------------------------------------------------------
    # API Pública
    # ------------------------------------------------------------------
    def set_theme(self, theme_name: str) -> None:
        """Muda tema do editor em runtime."""
        if theme_name == self._current_editor_theme:
            return
        self._current_editor_theme = theme_name
        self._load_editor_theme(theme_name)

    def set_read_only(self, read_only: bool) -> None:
        """Define modo somente leitura."""
        self._read_only = read_only
        if QSCI_AVAILABLE:
            self.setReadOnly(read_only)

    def get_text(self) -> str:
        """Retorna texto atual."""
        if QSCI_AVAILABLE:
            return self.text()
        return ""

    def set_text(self, text: str) -> None:
        """Define texto do editor."""
        if QSCI_AVAILABLE:
            self.setText(text)

    def find_first(self, pattern: str, case_sensitive: bool = False, whole_words: bool = False, regex: bool = False) -> bool:
        """Busca padrão (wrapper QsciScintilla.findFirst)."""
        if not QSCI_AVAILABLE:
            return False
        return self.findFirst(
            pattern,
            case_sensitive,
            whole_words,
            regex,
            False,  # forward
            True,   # wrap
        )

    def replace(self, replacement: str) -> None:
        """Substitui seleção atual."""
        if QSCI_AVAILABLE:
            self.replaceSelectedText(replacement)

    def zoom_in(self, range_: int = 1) -> None:
        """Aumenta zoom."""
        if QSCI_AVAILABLE:
            self.zoomIn(range_)

    def zoom_out(self, range_: int = 1) -> None:
        """Diminui zoom."""
        if QSCI_AVAILABLE:
            self.zoomOut(range_)

    def reset_zoom(self) -> None:
        """Reseta zoom."""
        if QSCI_AVAILABLE:
            while self.zoomTo(0):
                pass


# ----------------------------------------------------------------------
# Fallback se QScintilla não disponível
# ----------------------------------------------------------------------
if not QSCI_AVAILABLE:
    # Redefine como QPlainTextEdit para ter API compatível
    class SqlEditorWidget(QPlainTextEdit):
        """Fallback quando QScintilla não está instalado."""
        cursorPositionChanged = Signal(int, int)
        
        def __init__(self, parent=None, read_only=False, theme_service=None):
            super().__init__(parent)
            self.setReadOnly(read_only)
            self.setPlaceholderText("QScintilla não instalado. Execute: pip install PyQt6-QScintilla")
            font = QFont("JetBrains Mono", 11)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.setFont(font)
        
        def set_theme(self, theme_name: str) -> None:
            pass
        
        def set_read_only(self, read_only: bool) -> None:
            self.setReadOnly(read_only)
        
        def get_text(self) -> str:
            return self.toPlainText()
        
        def set_text(self, text: str) -> None:
            self.setPlainText(text)
        
        def find_first(self, *args, **kwargs) -> bool:
            return False
        
        def replace(self, replacement: str) -> None:
            self.replaceSelectedText(replacement)
        
        def zoom_in(self, range_: int = 1) -> None:
            self.zoomIn(range_)
        
        def zoom_out(self, range_: int = 1) -> None:
            self.zoomOut(range_)
        
        def reset_zoom(self) -> None:
            while self.zoomTo(0):
                pass


__all__ = ["SqlEditorWidget"]