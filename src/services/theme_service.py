# -*- coding: utf-8 -*-
"""
Serviço de Temas da Aplicação e do Editor (src/services/theme_service.py).

Gerencia:
- Temas da aplicação (`.qss`): `light`, `dark`, `system` (com detecção automática do SO via Qt 6.5+).
- Temas do editor (`.json`): `monokai`, `dracula`, `github`, `solarized`, `vscode`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QFile, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

import src.resources.resources_rc  # noqa: F401
from src.utils.resource_path import resource_path

if TYPE_CHECKING:
    from src.services.config_service import ConfigService

logger = logging.getLogger("services.theme_service")

AVAILABLE_APP_THEMES: list[str] = ["light", "dark", "system"]
AVAILABLE_EDITOR_THEMES: list[str] = [
    "vscode",
    "monokai",
    "dracula",
    "github",
    "solarized",
]


class ThemeService(QObject):
    """
    Serviço gerenciador de temas QSS da aplicação e esquemas de cores do editor.

    Signals:
        app_theme_changed (str): Emitido quando o tema da aplicação muda (nome configurado).
        editor_theme_changed (str): Emitido quando o tema do editor muda.
    """

    app_theme_changed = Signal(str)
    editor_theme_changed = Signal(str)

    def __init__(self, config_service: ConfigService | None = None) -> None:
        super().__init__()
        self._config_service = config_service
        self._current_app_theme: str = (
            config_service.config.app_theme if config_service else "system"
        )
        self._current_editor_theme: str = (
            config_service.config.editor_theme if config_service else "vscode"
        )
        self._qss_cache: dict[str, str] = {}
        self._editor_theme_cache: dict[str, dict[str, Any]] = {}

        if self._config_service is not None:
            self._config_service.subscribe("app_theme", self._on_config_app_theme_changed)
            self._config_service.subscribe("editor_theme", self._on_config_editor_theme_changed)

    def _on_config_app_theme_changed(self, theme_name: str) -> None:
        if theme_name and theme_name != self._current_app_theme:
            self.apply_app_theme(theme_name, persist=False)

    def _on_config_editor_theme_changed(self, theme_name: str) -> None:
        if theme_name and theme_name != self._current_editor_theme:
            self._current_editor_theme = theme_name
            self.editor_theme_changed.emit(theme_name)

    def get_available_app_themes(self) -> list[str]:
        """Retorna a lista de temas disponíveis para a aplicação."""
        return list(AVAILABLE_APP_THEMES)

    def get_available_editor_themes(self) -> list[str]:
        """Retorna a lista de temas disponíveis para o editor."""
        return list(AVAILABLE_EDITOR_THEMES)

    def current_app_theme(self) -> str:
        """Retorna o nome do tema da aplicação atualmente selecionado (`light`, `dark`, `system`)."""
        return self._current_app_theme

    def current_editor_theme(self) -> str:
        """Retorna o nome do tema do editor atualmente selecionado."""
        return self._current_editor_theme

    def resolve_effective_app_theme(self, theme_name: str | None = None) -> str:
        """
        Resolve `"system"` para `"dark"` ou `"light"` consultando o esquema de cores do SO.

        Args:
            theme_name: Nome do tema (`"light"`, `"dark"` ou `"system"`).

        Returns:
            `"dark"` ou `"light"`.
        """
        target = (theme_name or self._current_app_theme or "system").lower()
        if target in ("light", "dark"):
            return target

        app = QApplication.instance()
        if isinstance(app, QApplication):
            try:
                scheme = app.styleHints().colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return "dark"
                if scheme == Qt.ColorScheme.Light:
                    return "light"
            except Exception as exc:
                logger.debug("Não foi possível consultar styleHints().colorScheme(): %s", exc)

            palette = app.palette()
            win_color = palette.color(QPalette.ColorRole.Window)
            if win_color.lightness() < 128:
                return "dark"
        return "light"

    def load_qss(self, theme_name: str) -> str:
        """
        Carrega o conteúdo `.qss` do recurso compilado ou do sistema de arquivos.

        Args:
            theme_name: Nome do arquivo de tema sem extensão (`"light"`, `"dark"`, `"system"`).

        Returns:
            String contendo o stylesheet QSS.
        """
        effective = (
            self.resolve_effective_app_theme(theme_name)
            if theme_name == "system"
            else theme_name.lower()
        )
        if effective not in ("light", "dark", "system"):
            effective = "light"

        if effective in self._qss_cache:
            return self._qss_cache[effective]

        # 1. Tenta carregar via Qt Resource System (qrc)
        for qrc_path in (f":/themes/{effective}.qss", f":/resources/themes/{effective}.qss"):
            qfile = QFile(qrc_path)
            if qfile.exists() and qfile.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
                try:
                    data = bytes(qfile.readAll()).decode("utf-8")
                    self._qss_cache[effective] = data
                    return data
                finally:
                    qfile.close()

        # 2. Fallback para arquivo em disco
        for rel in (
            Path("resources") / "themes" / f"{effective}.qss",
            Path("src") / "resources" / "themes" / f"{effective}.qss",
        ):
            disk_path = resource_path(rel)
            if disk_path.exists():
                data = disk_path.read_text(encoding="utf-8")
                self._qss_cache[effective] = data
                return data

        logger.warning("Arquivo QSS não encontrado para o tema '%s'.", theme_name)
        return ""

    def apply_app_theme(self, theme_name: str, persist: bool = True) -> None:
        """
        Carrega o `.qss` correspondente e aplica no `QApplication` ativo.

        Args:
            theme_name: `"light"`, `"dark"` ou `"system"`.
            persist: Se `True` e houver `ConfigService`, persiste a escolha.
        """
        normalized = theme_name.strip().lower()
        if normalized not in AVAILABLE_APP_THEMES:
            logger.warning("Tema '%s' inválido; usando 'system'.", theme_name)
            normalized = "system"

        self._current_app_theme = normalized
        qss = self.load_qss(normalized)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(qss)

        if persist and self._config_service is not None:
            if self._config_service.config.app_theme != normalized:
                self._config_service.set("app_theme", normalized)

        logger.info(
            "Tema da aplicação aplicado: '%s' (efetivo: '%s')",
            normalized,
            self.resolve_effective_app_theme(normalized),
        )
        self.app_theme_changed.emit(normalized)

    def get_editor_theme_data(self, theme_name: str | None = None) -> dict[str, Any]:
        """
        Carrega e retorna o dicionário JSON de configuração de cores de um tema de editor.

        Args:
            theme_name: Nome do tema (`"monokai"`, `"dracula"`, `"github"`, `"solarized"`, `"vscode"`).

        Returns:
            Dicionário com as cores do tema.
        """
        target = (theme_name or self._current_editor_theme or "vscode").strip().lower()
        if target not in AVAILABLE_EDITOR_THEMES:
            target = "vscode"

        if target in self._editor_theme_cache:
            return self._editor_theme_cache[target]

        # 1. Tenta via Qt Resource System
        for qrc_path in (
            f":/editor_themes/{target}.json",
            f":/resources/editor_themes/{target}.json",
        ):
            qfile = QFile(qrc_path)
            if qfile.exists() and qfile.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
                try:
                    raw = bytes(qfile.readAll()).decode("utf-8")
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        self._editor_theme_cache[target] = parsed
                        return parsed
                finally:
                    qfile.close()

        # 2. Fallback para arquivo em disco
        for rel in (
            Path("resources") / "editor_themes" / f"{target}.json",
            Path("src") / "resources" / "editor_themes" / f"{target}.json",
        ):
            disk_path = resource_path(rel)
            if disk_path.exists():
                parsed = json.loads(disk_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    self._editor_theme_cache[target] = parsed
                    return parsed

        # 3. Fallback seguro em memória
        return {
            "name": "VS Code Dark+",
            "background": "#1E1E1E",
            "foreground": "#D4D4D4",
            "caret": "#FFFFFF",
            "selection": "#264F78",
            "line_number": "#858585",
            "line_number_bg": "#1E1E1E",
            "fold_margin": "#1E1E1E",
            "styles": {"default": {"fore": "#D4D4D4"}},
        }

    def apply_editor_theme(self, editor: Any, theme_name: str | None = None) -> None:
        """
        Aplica um tema de editor (e fonte configurada) em um widget `QsciScintilla` ou `QPlainTextEdit`/`QTextEdit`.

        Args:
            editor: Instância do widget de editor (`QsciScintilla`, `QPlainTextEdit`, `QTextEdit`).
            theme_name: Nome do esquema de cores do editor.
        """
        target = (theme_name or self._current_editor_theme or "vscode").strip().lower()
        if target not in AVAILABLE_EDITOR_THEMES:
            target = "vscode"

        self._current_editor_theme = target
        theme_data = self.get_editor_theme_data(target)

        font_family = (
            self._config_service.config.font_family
            if self._config_service
            else "JetBrains Mono"
        )
        font_size = (
            self._config_service.config.font_size if self._config_service else 11
        )
        font = QFont(font_family, font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)

        bg = theme_data.get("background", "#1E1E1E")
        fg = theme_data.get("foreground", "#D4D4D4")
        caret = theme_data.get("caret", "#FFFFFF")
        selection = theme_data.get("selection", "#264F78")
        line_num_fg = theme_data.get("line_number", "#858585")
        line_num_bg = theme_data.get("line_number_bg", bg)
        fold_bg = theme_data.get("fold_margin", bg)

        # Suporte a QsciScintilla (quando utilizado)
        if hasattr(editor, "setPaper") and hasattr(editor, "setColor"):
            try:
                editor.setFont(font)
                editor.setPaper(QColor(bg))
                editor.setColor(QColor(fg))
                if hasattr(editor, "setCaretForegroundColor"):
                    editor.setCaretForegroundColor(QColor(caret))
                if hasattr(editor, "setSelectionBackgroundColor"):
                    editor.setSelectionBackgroundColor(QColor(selection))
                if hasattr(editor, "setMarginsForegroundColor"):
                    editor.setMarginsForegroundColor(QColor(line_num_fg))
                if hasattr(editor, "setMarginsBackgroundColor"):
                    editor.setMarginsBackgroundColor(QColor(line_num_bg))
                if hasattr(editor, "setFoldMarginColors"):
                    editor.setFoldMarginColors(QColor(fold_bg), QColor(fold_bg))
                if hasattr(editor, "setMarginsFont"):
                    margin_font = QFont(font_family, max(8, font_size - 1))
                    editor.setMarginsFont(margin_font)
            except Exception as exc:
                logger.warning("Erro ao aplicar tema QScintilla '%s': %s", target, exc)
            return

        # Suporte a QPlainTextEdit / QTextEdit / QWidget padrão
        if hasattr(editor, "setFont"):
            editor.setFont(font)
        if hasattr(editor, "setStyleSheet"):
            editor.setStyleSheet(
                f"background-color: {bg}; color: {fg}; "
                f"selection-background-color: {selection}; "
                f'font-family: "{font_family}", "Consolas", monospace; '
                f"font-size: {font_size}pt;"
            )
