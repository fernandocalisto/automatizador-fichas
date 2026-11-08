#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Janela Principal da Aplicação em PySide6 (src/gui/main_window.py).

Implementa `MainWindow(QMainWindow)` e `AboutDialog(QDialog)` conforme Spec 00:
- MenuBar: Arquivo, Editar, Ferramentas, Janela, Ajuda (Sobre)
- Toolbar: Novo, Abrir, Salvar, Gerar INSERT, Gerar SELECT, Config, Tema (ThemeSwitch), Ajuda
- Central QStackedWidget: 5 páginas (LandingPage, JsonEditorPage, QuestionsPage, SqlInsertPage, SqlSelectPage)
- Bottom QDockWidget: abas Output/Log, Validação, Propriedades
- StatusBar: Conexão, Encoding, Ln/Col, Tema, Versão
- AboutDialog modal (400x300) com logo, versão, copyright e links
- Persistência de geometria/estado (`saveState`/`restoreState`) e última página em `QSettings`
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import src.resources.resources_rc  # noqa: F401
from src.gui.components.theme_switch import THEME_LABELS, ThemeSwitch
from src.gui.components.toast import Toast
from src.gui.settings.dialog import SettingsDialog
from src.gui.wizard.json_editor_page import JsonEditorPage
from src.gui.wizard.landing_page import LandingPage
from src.gui.wizard.questions_page import QuestionsPage
from src.gui.wizard.sql_insert_page import SqlInsertPage
from src.gui.wizard.sql_select_page import SqlSelectPage
from src.services.config_service import ConfigService
from src.services.help_service import HelpService
from src.services.log_service import LogService
from src.services.theme_service import ThemeService
from src.utils.json_utils import update_shared_dict_in_place
from src.utils.logo_utils import load_logo_pixmap
from src.utils.resource_path import resource_path

logger = logging.getLogger("gui.main_window")

APP_VERSION = "v0.2.0"
APP_TITLE_BASE = "Automatizador de Fichas"


def load_app_logo_pixmap(
    width: int | None = None, height: int | None = None
) -> QPixmap:
    """Carrega o logo da aplicação com cantos arredondados."""
    return load_logo_pixmap(width=width, height=height, radius=16)


def load_app_icon() -> QIcon:
    """Retorna o `QIcon` da aplicação com cantos arredondados."""
    pm = load_app_logo_pixmap()
    if not pm.isNull():
        return QIcon(pm)
    return QIcon()


class AboutDialog(QDialog):
    """
    Diálogo modal 'Sobre' (400x300) exibindo logo, versão, copyright e links.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Sobre — {APP_TITLE_BASE}")
        self.setAccessibleName("Diálogo Sobre o Automatizador de Fichas")
        self.setModal(True)
        self.setFixedSize(400, 300)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        # Logo centralizado
        self.lbl_logo = QLabel(self)
        self.lbl_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pm = load_app_logo_pixmap(height=72)
        if not logo_pm.isNull():
            self.lbl_logo.setPixmap(logo_pm)
        layout.addWidget(self.lbl_logo)

        # Nome e Versão
        self.lbl_title = QLabel(
            f"<b>{APP_TITLE_BASE}</b> — Ferramenta Interna", self
        )
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 12pt;")
        layout.addWidget(self.lbl_title)

        self.lbl_version = QLabel(f"Versão {APP_VERSION} (PySide6)", self)
        self.lbl_version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_version.setStyleSheet("color: #64748b; font-weight: 600;")
        layout.addWidget(self.lbl_version)

        # Descrição e Copyright
        self.lbl_copyright = QLabel(
            "Utilitário para estruturação de fichas clínicas JSON e geração "
            "automatizada de scripts PostgreSQL INSERT e SELECT Jasper.\n\n"
            "© 2026 Fernando Calisto / Salutem. Todos os direitos reservados.",
            self,
        )
        self.lbl_copyright.setWordWrap(True)
        self.lbl_copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_copyright.setStyleSheet("font-size: 9pt;")
        layout.addWidget(self.lbl_copyright)

        # Links externos
        self.lbl_links = QLabel(
            f'<a href="{HelpService.GITHUB_URL}">Repositório GitHub</a> &nbsp;|&nbsp; '
            f'<a href="{HelpService.GITHUB_URL}/issues">Reportar Problema</a>',
            self,
        )
        self.lbl_links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_links.setOpenExternalLinks(True)
        layout.addWidget(self.lbl_links)

        layout.addStretch(1)

        # Botão Fechar
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_close = QPushButton("Fechar", self)
        self.btn_close.setProperty("variant", "primary")
        self.btn_close.setDefault(True)
        self.btn_close.setMinimumWidth(100)
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)


class MainWindow(QMainWindow):
    """
    Janela Principal da Aplicação em PySide6 (src/gui/main_window.py).

    Implementa `MainWindow(QMainWindow)` e `AboutDialog(QDialog)` conforme Spec 00:
    - MenuBar: Arquivo, Editar, Ferramentas, Janela, Ajuda (Sobre)
    - Toolbar: Novo, Abrir, Salvar, Gerar INSERT, Gerar SELECT, Config, Tema (ThemeSwitch), Ajuda
    - Central QStackedWidget: 5 páginas (LandingPage, JsonEditorPage, QuestionsPage, SqlInsertPage, SqlSelectPage)
    - Bottom QDockWidget: abas Output/Log, Validação, Propriedades
    - StatusBar: Conexão, Encoding, Ln/Col, Tema, Versão
    """

    page_changed = Signal(int)

    PAGE_LANDING = 0
    PAGE_JSON_EDITOR = 1
    PAGE_QUESTIONS = 2
    PAGE_SQL_INSERT = 3
    PAGE_SQL_SELECT = 4

    PAGE_TITLES: list[str] = [
        "1. Tela Inicial",
        "2. Editar JSON",
        "3. Perguntas & Respostas",
        "4. Gerar SQL INSERT",
        "5. Gerar SELECT Jasper",
    ]

    def __init__(
        self,
        config_service: ConfigService | None = None,
        theme_service: ThemeService | None = None,
        log_service: LogService | None = None,
        help_service: HelpService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_service = config_service or ConfigService()
        self.theme_service = theme_service or ThemeService(self.config_service)
        self.log_service = log_service or LogService()
        self.help_service = help_service or HelpService()

        # Dicionário compartilhado in-place entre todas as páginas do Wizard
        self.json_data: dict[str, Any] = {}
        self.current_view: str = "landing"
        self._listeners: list[Callable[[dict[str, Any] | None], None]] = []

        self.setObjectName("MainWindow")
        self.setWindowTitle(f"{APP_TITLE_BASE} – Carregar JSON")
        self.setMinimumSize(960, 640)
        self.resize(1280, 800)

        app_icon = load_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self._create_actions()
        self._build_menubar()
        self._build_toolbar()
        self._build_central_area()
        self._build_bottom_dock()
        self._build_statusbar()
        self._connect_signals()

        # Restaura estado salvo (geometria, docks e última página)
        self.restore_window_state()

    # -------------------------------------------------------------------------
    # Construção de Ações, MenuBar e ToolBar
    # -------------------------------------------------------------------------
    def _create_actions(self) -> None:
        style = self.style()

        # Arquivo
        self.action_new = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "Novo",
            self,
        )
        self.action_new.setShortcut(QKeySequence("Ctrl+N"))
        self.action_new.setStatusTip("Iniciar nova sessão e voltar à Tela Inicial (Ctrl+N)")
        self.action_new.triggered.connect(self.new_session)

        self.action_open = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Abrir",
            self,
        )
        self.action_open.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open.setStatusTip("Abrir arquivo JSON de ficha clínica (Ctrl+O)")
        self.action_open.triggered.connect(self.open_json_dialog)

        self.action_paste_json = QAction(
            "Colar JSON da Área de Transferência",
            self,
        )
        self.action_paste_json.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.action_paste_json.triggered.connect(self.paste_json_clipboard)

        self.action_save = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Salvar",
            self,
        )
        self.action_save.setShortcut(QKeySequence("Ctrl+S"))
        self.action_save.setStatusTip("Salvar arquivo JSON ou SQL da página atual (Ctrl+S)")
        self.action_save.triggered.connect(self.save_current_document)

        self.action_exit = QAction("Sair", self)
        self.action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_exit.triggered.connect(self.close)

        # Editar
        self.action_undo = QAction("Desfazer", self)
        self.action_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.action_undo.triggered.connect(self._undo_in_active_editor)

        self.action_redo = QAction("Refazer", self)
        self.action_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self.action_redo.triggered.connect(self._redo_in_active_editor)

        self.action_cut = QAction("Recortar", self)
        self.action_cut.setShortcut(QKeySequence("Ctrl+X"))
        self.action_cut.triggered.connect(self._cut_in_active_editor)

        self.action_copy = QAction("Copiar", self)
        self.action_copy.setShortcut(QKeySequence("Ctrl+C"))
        self.action_copy.triggered.connect(self._copy_in_active_editor)

        self.action_paste = QAction("Colar", self)
        self.action_paste.setShortcut(QKeySequence("Ctrl+V"))
        self.action_paste.triggered.connect(self._paste_in_active_editor)

        self.action_validate_json = QAction("Validar && Formatar JSON", self)
        self.action_validate_json.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.action_validate_json.triggered.connect(self._validate_and_format_json)

        # Ferramentas / Geração SQL
        self.action_generate_insert = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            "Gerar INSERT",
            self,
        )
        self.action_generate_insert.setStatusTip(
            "Ir para a página SQL INSERT e gerar script PostgreSQL"
        )
        self.action_generate_insert.triggered.connect(self.trigger_generate_insert)

        self.action_generate_select = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            "Gerar SELECT",
            self,
        )
        self.action_generate_select.setStatusTip(
            "Ir para a página SELECT Jasper e gerar consulta SQL"
        )
        self.action_generate_select.triggered.connect(self.trigger_generate_select)

        self.action_validate_sql = QAction("Validar Sintaxe PostgreSQL", self)
        self.action_validate_sql.triggered.connect(self.trigger_validate_sql)

        self.action_download_skill = QAction("Baixar Skill (SKILL.md)…", self)
        self.action_download_skill.triggered.connect(
            lambda: self.landing_page.download_skill()
        )

        # Configurações, Tema e Ajuda
        self.action_settings = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Config",
            self,
        )
        self.action_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.action_settings.setStatusTip("Abrir Configurações do Sistema (Ctrl+,)")
        self.action_settings.triggered.connect(lambda: self.open_settings_dialog())

        self.action_help = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton),
            "Ajuda",
            self,
        )
        self.action_help.setShortcut(QKeySequence("F1"))
        self.action_help.setStatusTip("Abrir documentação e atalhos (F1)")
        self.action_help.triggered.connect(self.show_help)

        self.action_github = QAction("Repositório no GitHub", self)
        self.action_github.triggered.connect(
            self.help_service.open_github_repository
        )

        self.action_about = QAction("Sobre", self)
        self.action_about.setStatusTip("Exibir informações sobre o Automatizador de Fichas")
        self.action_about.triggered.connect(self.show_about_dialog)

    def _build_menubar(self) -> None:
        menubar: QMenuBar = self.menuBar()
        menubar.setAccessibleName("Barra de Menus Principal")

        # 1. Arquivo
        self.menu_arquivo: QMenu = menubar.addMenu("&Arquivo")
        self.menu_arquivo.addAction(self.action_new)
        self.menu_arquivo.addAction(self.action_open)
        self.menu_arquivo.addAction(self.action_paste_json)
        self.menu_arquivo.addAction(self.action_save)
        self.menu_arquivo.addSeparator()
        self.menu_arquivo.addAction(self.action_exit)

        # 2. Editar
        self.menu_editar: QMenu = menubar.addMenu("&Editar")
        self.menu_editar.addAction(self.action_undo)
        self.menu_editar.addAction(self.action_redo)
        self.menu_editar.addSeparator()
        self.menu_editar.addAction(self.action_cut)
        self.menu_editar.addAction(self.action_copy)
        self.menu_editar.addAction(self.action_paste)
        self.menu_editar.addSeparator()
        self.menu_editar.addAction(self.action_validate_json)
        self.menu_editar.addSeparator()
        self.menu_editar.addAction(self.action_settings)

        # 3. Ferramentas
        self.menu_ferramentas: QMenu = menubar.addMenu("&Ferramentas")
        self.menu_ferramentas.addAction(self.action_generate_insert)
        self.menu_ferramentas.addAction(self.action_generate_select)
        self.menu_ferramentas.addAction(self.action_validate_sql)
        self.menu_ferramentas.addSeparator()
        self.menu_ferramentas.addAction(self.action_download_skill)

        # 4. Janela
        self.menu_janela: QMenu = menubar.addMenu("&Janela")
        self.action_toggle_bottom_dock = QAction(
            "Alternar Painel Inferior", self
        )
        self.action_toggle_bottom_dock.setCheckable(True)
        self.action_toggle_bottom_dock.setChecked(True)
        self.action_toggle_bottom_dock.triggered.connect(
            lambda checked: self.bottom_dock.setVisible(checked)
        )
        self.menu_janela.addAction(self.action_toggle_bottom_dock)

        # 5. Ajuda
        self.menu_ajuda: QMenu = menubar.addMenu("A&juda")
        self.menu_ajuda.addAction(self.action_help)
        self.menu_ajuda.addAction(self.action_github)
        self.menu_ajuda.addSeparator()
        self.menu_ajuda.addAction(self.action_about)

    def _build_toolbar(self) -> None:
        self.main_toolbar = QToolBar("Barra de Ferramentas Principal", self)
        self.main_toolbar.setObjectName("MainToolBar")
        self.main_toolbar.setAccessibleName("Barra de Ferramentas Principal")
        self.main_toolbar.setMovable(False)
        self.main_toolbar.setIconSize(QSize(18, 18))
        self.main_toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.main_toolbar)

        # Botões exigidos: Novo, Abrir, Salvar, Gerar INSERT, Gerar SELECT, Config, Tema, Ajuda
        self.main_toolbar.addAction(self.action_new)
        self.main_toolbar.addAction(self.action_open)
        self.main_toolbar.addAction(self.action_save)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.action_generate_insert)
        self.main_toolbar.addAction(self.action_generate_select)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.action_settings)

        self.theme_switch = ThemeSwitch(self.theme_service, self.main_toolbar)
        self.action_theme_widget = self.main_toolbar.addWidget(self.theme_switch)

        self.main_toolbar.addAction(self.action_help)

    # -------------------------------------------------------------------------
    # Área Central: Barra de Etapas + QStackedWidget (5 Páginas)
    # -------------------------------------------------------------------------
    def _build_central_area(self) -> None:
        self.central_container = QWidget(self)
        central_layout = QVBoxLayout(self.central_container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Barra superior de navegação entre as 5 páginas do Wizard
        self.step_bar = QFrame(self.central_container)
        self.step_bar.setObjectName("WizardStepBar")
        step_layout = QHBoxLayout(self.step_bar)
        step_layout.setContentsMargins(12, 6, 12, 6)
        step_layout.setSpacing(6)

        self.step_buttons: list[QPushButton] = []
        for idx, title in enumerate(self.PAGE_TITLES):
            btn = QPushButton(title, self.step_bar)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setAccessibleName(f"Ir para {title}")
            btn.clicked.connect(lambda _checked=False, i=idx: self.navigate_to_page(i))
            step_layout.addWidget(btn)
            self.step_buttons.append(btn)

        step_layout.addStretch(1)
        central_layout.addWidget(self.step_bar)

        # QStackedWidget central com as 5 páginas
        self.central_stack = QStackedWidget(self.central_container)
        self.central_stack.setObjectName("CentralStackedWidget")
        self.central_stack.setAccessibleName("Páginas Centrais do Wizard")

        # Página 0: LandingPage
        self.landing_page = LandingPage(
            parent=self.central_stack,
            on_json_loaded=self._on_landing_json_loaded,
        )
        self.central_stack.addWidget(self.landing_page)

        # Página 1: JsonEditorPage
        self.json_editor_page = JsonEditorPage(
            parent=self.central_stack,
            shared_json=self.json_data,
            on_json_changed=self._on_json_updated_from_editor_page,
            on_back_to_landing=self.show_landing,
            theme_service=self.theme_service,
        )
        self.central_stack.addWidget(self.json_editor_page)

        # Página 2: QuestionsPage
        self.questions_page = QuestionsPage(
            parent=self.central_stack,
            shared_json=self.json_data,
            on_json_changed=self._on_json_updated_from_questions_page,
            on_back_to_landing=self.show_landing,
        )
        self.central_stack.addWidget(self.questions_page)

        # Página 3: SqlInsertPage
        self.sql_insert_page = SqlInsertPage(
            parent=self.central_stack,
            shared_json=self.json_data,
            on_sql_generated=lambda sql: self._on_sql_generated("INSERT", sql),
            on_back_to_landing=self.show_landing,
            theme_service=self.theme_service,
        )
        self.central_stack.addWidget(self.sql_insert_page)

        # Página 4: SqlSelectPage
        self.sql_select_page = SqlSelectPage(
            parent=self.central_stack,
            shared_json=self.json_data,
            on_sql_generated=lambda sql: self._on_sql_generated("SELECT", sql),
            on_back_to_landing=self.show_landing,
            theme_service=self.theme_service,
        )
        self.central_stack.addWidget(self.sql_select_page)

        central_layout.addWidget(self.central_stack, 1)
        self.setCentralWidget(self.central_container)

        # Aliases de compatibilidade
        self.landing_frame = self.landing_page
        self.json_editor_tab = self.json_editor_page
        self.perguntas_tab = self.questions_page
        self.sql_insert_tab = self.sql_insert_page
        self.sql_select_tab = self.sql_select_page

        self._update_step_buttons(self.PAGE_LANDING)

    # -------------------------------------------------------------------------
    # Bottom QDockWidget (Output/Log, Validação, Propriedades)
    # -------------------------------------------------------------------------
    def _build_bottom_dock(self) -> None:
        self.bottom_dock = QDockWidget("Painel Inferior", self)
        self.bottom_dock.setObjectName("BottomDockWidget")
        self.bottom_dock.setAccessibleName("Painel Inferior de Saída e Diagnóstico")
        self.bottom_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )

        self.bottom_tabs = QTabWidget(self.bottom_dock)
        self.bottom_tabs.setAccessibleName("Abas do Painel Inferior")
        self.bottom_tabs.setDocumentMode(True)

        mono_font = QFont("JetBrains Mono", 9)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)

        # Aba 1: Output/Log
        self.log_output_text = QPlainTextEdit(self.bottom_tabs)
        self.log_output_text.setReadOnly(True)
        self.log_output_text.setFont(mono_font)
        self.log_output_text.setAccessibleName("Saída de Log da Aplicação")
        self.bottom_tabs.addTab(self.log_output_text, "Output/Log")

        # Aba 2: Validação
        self.validation_output_text = QPlainTextEdit(self.bottom_tabs)
        self.validation_output_text.setReadOnly(True)
        self.validation_output_text.setFont(mono_font)
        self.validation_output_text.setAccessibleName("Resultados de Validação")
        self.validation_output_text.setPlainText(
            "Nenhuma validação executada nesta sessão."
        )
        self.bottom_tabs.addTab(self.validation_output_text, "Validação")

        # Aba 3: Propriedades
        self.properties_table = QTableWidget(0, 2, self.bottom_tabs)
        self.properties_table.setAccessibleName("Propriedades da Ficha Carregada")
        self.properties_table.setHorizontalHeaderLabels(["Propriedade", "Valor"])
        self.properties_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.properties_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.properties_table.verticalHeader().setVisible(False)
        self.properties_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.bottom_tabs.addTab(self.properties_table, "Propriedades")

        self.bottom_dock.setWidget(self.bottom_tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

        self.menu_janela.addAction(self.bottom_dock.toggleViewAction())
        self._refresh_properties_panel()

    # -------------------------------------------------------------------------
    # StatusBar (Conexão, Encoding, Ln/Col, Tema, Versão)
    # -------------------------------------------------------------------------
    def _build_statusbar(self) -> None:
        status_bar = QStatusBar(self)
        status_bar.setObjectName("MainStatusBar")
        status_bar.setAccessibleName("Barra de Status")
        self.setStatusBar(status_bar)

        self.lbl_status_connection = QLabel("Conexão: Offline", status_bar)
        self.lbl_status_connection.setAccessibleName("Status da Conexão")
        self.lbl_status_connection.setStyleSheet("padding: 0 8px;")

        self.lbl_status_encoding = QLabel("UTF-8", status_bar)
        self.lbl_status_encoding.setAccessibleName("Codificação do Arquivo")
        self.lbl_status_encoding.setStyleSheet("padding: 0 8px;")

        self.lbl_status_cursor = QLabel("Ln 1, Col 1", status_bar)
        self.lbl_status_cursor.setAccessibleName("Posição do Cursor Linha e Coluna")
        self.lbl_status_cursor.setStyleSheet("padding: 0 8px;")

        self.lbl_status_theme = QLabel("", status_bar)
        self.lbl_status_theme.setAccessibleName("Tema Atual")
        self.lbl_status_theme.setStyleSheet("padding: 0 8px;")

        self.lbl_status_version = QLabel(APP_VERSION, status_bar)
        self.lbl_status_version.setAccessibleName("Versão da Aplicação")
        self.lbl_status_version.setStyleSheet("padding: 0 8px; font-weight: 600;")

        status_bar.addPermanentWidget(self.lbl_status_connection)
        status_bar.addPermanentWidget(self.lbl_status_encoding)
        status_bar.addPermanentWidget(self.lbl_status_cursor)
        status_bar.addPermanentWidget(self.lbl_status_theme)
        status_bar.addPermanentWidget(self.lbl_status_version)

        self._update_theme_status_label(self.theme_service.current_app_theme())
        status_bar.showMessage("Pronto.")

    # -------------------------------------------------------------------------
    # Sinais e Eventos Internos
    # -------------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.central_stack.currentChanged.connect(self._on_central_page_changed)

        # Atualização de Ln/Col na StatusBar
        self.json_editor_page.cursor_position_changed.connect(
            self.update_cursor_position
        )
        self.sql_insert_page.cursor_position_changed.connect(
            self.update_cursor_position
        )
        self.sql_select_page.cursor_position_changed.connect(
            self.update_cursor_position
        )

        # Resultados de validação no Bottom Dock
        self.sql_insert_page.validation_finished.connect(
            lambda ok, msg: self._record_validation("SQL INSERT", ok, msg)
        )
        self.sql_select_page.validation_finished.connect(
            lambda ok, msg: self._record_validation("SELECT Jasper", ok, msg)
        )

        # Atualização do tema na StatusBar
        self.theme_service.app_theme_changed.connect(self._update_theme_status_label)

        # Ponte de logs em tempo real para o painel Output/Log
        bridge = LogService.get_signal_bridge()
        bridge.log_emitted.connect(self._append_log_message)

    def _append_log_message(self, level_name: str, formatted_message: str) -> None:
        self.log_output_text.appendPlainText(formatted_message)

    def _record_validation(self, source: str, is_valid: bool, message: str) -> None:
        prefix = "✓ VÁLIDO" if is_valid else "✕ ERRO"
        self.validation_output_text.appendPlainText(f"[{source}] {prefix}: {message}")
        if not is_valid:
            self.bottom_dock.setVisible(True)
            self.bottom_tabs.setCurrentWidget(self.validation_output_text)

    def update_cursor_position(self, line: int, col: int) -> None:
        """Atualiza o indicador `Ln/Col` na barra de status."""
        self.lbl_status_cursor.setText(f"Ln {line}, Col {col}")

    def _update_theme_status_label(self, theme_key: str) -> None:
        label = THEME_LABELS.get(theme_key, theme_key.capitalize())
        effective = self.theme_service.resolve_effective_app_theme(theme_key)
        effective_label = THEME_LABELS.get(effective, effective)
        if theme_key == "system":
            self.lbl_status_theme.setText(f"Tema: {label} ({effective_label})")
        else:
            self.lbl_status_theme.setText(f"Tema: {label}")

    def _refresh_properties_panel(self) -> None:
        """Atualiza a tabela de Propriedades no painel inferior com os dados do JSON ativo."""
        rows: list[tuple[str, str]] = []
        if not self.json_data or not isinstance(self.json_data, dict):
            rows = [
                ("Status", "Nenhuma ficha carregada"),
                ("Arquivo", "—"),
                ("Perguntas", "0"),
                ("Respostas", "0"),
            ]
        else:
            tmpl = self.json_data.get("template", {})
            if not isinstance(tmpl, dict):
                tmpl = {}
            perguntas = self.json_data.get("perguntas", [])
            if not isinstance(perguntas, list):
                perguntas = []
            total_respostas = sum(
                len(p.get("respostas", []))
                for p in perguntas
                if isinstance(p, dict) and isinstance(p.get("respostas"), list)
            )
            current_file = (
                str(self.json_editor_page.current_file)
                if self.json_editor_page.current_file
                else "Área de Transferência / Memória"
            )
            rows = [
                ("Nome da Ficha", str(tmpl.get("nome", "—"))),
                ("Descrição", str(tmpl.get("descricao", "—"))),
                ("Layout", str(tmpl.get("layout", "ficha-clinica"))),
                ("Orientação", str(tmpl.get("orientacao", "RETRATO"))),
                ("Páginas", str(tmpl.get("quantidade_pagina", 1))),
                ("Total de Perguntas", str(len(perguntas))),
                ("Total de Respostas", str(total_respostas)),
                ("Origem", current_file),
            ]

        self.properties_table.setRowCount(len(rows))
        for row_idx, (prop, val) in enumerate(rows):
            self.properties_table.setItem(row_idx, 0, QTableWidgetItem(prop))
            self.properties_table.setItem(row_idx, 1, QTableWidgetItem(val))

    def _add_history_entry(self, description: str, file_path: Path | None = None) -> None:
        if not hasattr(self, "history_list"):
            return
        item = QListWidgetItem(description)
        if file_path is not None:
            item.setData(Qt.ItemDataRole.UserRole, str(file_path))
            item.setToolTip(str(file_path))
        self.history_list.insertItem(0, item)

    def _on_history_item_activated(self, item: QListWidgetItem) -> None:
        stored_path = item.data(Qt.ItemDataRole.UserRole)
        if stored_path:
            path = Path(str(stored_path))
            if path.exists() and path.suffix.lower() == ".json":
                self.landing_page.load_json_from_path(path)

    def _on_favorite_item_clicked(self, item: QListWidgetItem) -> None:
        page_idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page_idx, int):
            self.navigate_to_page(page_idx)

    # -------------------------------------------------------------------------
    # Navegação entre as 5 Páginas Centrais e Sincronização de Dados
    # -------------------------------------------------------------------------
    def _update_step_buttons(self, active_index: int) -> None:
        for idx, btn in enumerate(self.step_buttons):
            is_current = idx == active_index
            btn.setChecked(is_current)
            btn.setProperty("variant", "primary" if is_current else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def navigate_to_page(self, index: int) -> None:
        """Navega para uma das 5 páginas do `QStackedWidget` central (0..4)."""
        if 0 <= index < self.central_stack.count():
            self.central_stack.setCurrentIndex(index)

    def _on_central_page_changed(self, index: int) -> None:
        self._update_step_buttons(index)
        if index == self.PAGE_LANDING:
            self.current_view = "landing"
            self.update_cursor_position(1, 1)
        else:
            self.current_view = "notebook"
            if self.json_data:
                if index == self.PAGE_JSON_EDITOR:
                    self.questions_page.apply_changes()
                    self.json_editor_page.refresh_from_shared()
                elif index in (self.PAGE_SQL_INSERT, self.PAGE_SQL_SELECT):
                    self.questions_page.apply_changes()

        # Persiste a última página visitada no QSettings
        try:
            self.config_service.settings.setValue("window/last_page", index)
        except Exception:
            pass

        self.page_changed.emit(index)

    def show_landing(self) -> None:
        """Limpa o estado atual e retorna para a Página 0 (`LandingPage`)."""
        self.json_data.clear()
        self.sql_insert_page.clear_preview()
        self.sql_select_page.clear_preview()
        self.landing_page.status_var.set("Aguardando JSON…")
        self.central_stack.setCurrentIndex(self.PAGE_LANDING)
        self.setWindowTitle(f"{APP_TITLE_BASE} – Carregar JSON")
        self.current_view = "landing"
        self._refresh_properties_panel()
        self._notify_listeners()

    def show_notebook(self) -> None:
        """Exibe a visão de edição após carregamento de um JSON válido."""
        tmpl = self.json_data.get("template", {})
        nome_ficha = (
            tmpl.get("nome", "Ficha Carregada")
            if isinstance(tmpl, dict)
            else "Ficha Carregada"
        )
        self.setWindowTitle(f"{APP_TITLE_BASE} – {nome_ficha}")
        self.current_view = "notebook"
        if self.central_stack.currentIndex() == self.PAGE_LANDING:
            self.central_stack.setCurrentIndex(self.PAGE_JSON_EDITOR)

    def _on_landing_json_loaded(
        self, validated_data: dict[str, Any], source_path: Path | None = None
    ) -> None:
        """Callback chamado quando um JSON válido é carregado na `LandingPage`."""
        update_shared_dict_in_place(self.json_data, validated_data)
        self.json_editor_page.current_file = source_path
        self.json_editor_page.set_json_data(
            self.json_data,
            update_original=True,
            apply_uppercase=True,
            notify=False,
        )
        self.questions_page.refresh_from_shared()
        self.sql_insert_page.clear_preview()
        self.sql_select_page.clear_preview()

        self.show_notebook()
        self.central_stack.setCurrentIndex(self.PAGE_JSON_EDITOR)
        self._refresh_properties_panel()

        origem_nome = source_path.name if source_path else "Área de Transferência"
        self._add_history_entry(f"JSON: {origem_nome}", source_path)
        self._record_validation(
            "JSON", True, f"Ficha carregada com sucesso ({origem_nome})."
        )
        self.statusBar().showMessage(f"JSON carregado: {origem_nome}", 5000)
        self._notify_listeners()

    def _on_json_updated_from_editor_page(self, updated_data: dict[str, Any]) -> None:
        if updated_data is not self.json_data:
            update_shared_dict_in_place(self.json_data, updated_data)
        self.questions_page.refresh_from_shared()
        self._refresh_properties_panel()
        self._record_validation(
            "JSON Editor", True, "JSON validado, formatado e convertido para UPPERCASE."
        )
        self._notify_listeners()

    def _on_json_updated_from_questions_page(
        self, updated_data: dict[str, Any]
    ) -> None:
        if updated_data is not self.json_data:
            update_shared_dict_in_place(self.json_data, updated_data)
        self.json_editor_page.refresh_from_shared()
        self._refresh_properties_panel()
        self._notify_listeners()

    def _on_sql_generated(self, sql_kind: str, sql_text: str) -> None:
        lines_count = sql_text.count("\n") + 1 if sql_text else 0
        self._add_history_entry(f"SQL {sql_kind} ({lines_count} linhas)")
        self._record_validation(
            f"SQL {sql_kind}",
            True,
            f"Script {sql_kind} gerado com sucesso ({lines_count} linhas).",
        )
        self.statusBar().showMessage(
            f"Script SQL {sql_kind} gerado com sucesso ({lines_count} linhas).", 5000
        )

    # -------------------------------------------------------------------------
    # Ações de Menu e Toolbar
    # -------------------------------------------------------------------------
    def new_session(self) -> None:
        """Reinicia para uma nova sessão na Tela Inicial."""
        self.show_landing()
        self.statusBar().showMessage("Nova sessão iniciada.", 3000)

    def open_json_dialog(self) -> bool:
        """Abre diálogo de seleção de arquivo JSON e carrega na aplicação."""
        return self.landing_page.load_json_from_file_dialog()

    def paste_json_clipboard(self) -> bool:
        """Importa e valida JSON a partir da área de transferência."""
        return self.landing_page.paste_json_from_clipboard()

    def save_current_document(self) -> bool:
        """Salva o conteúdo da página ativa (JSON ou SQL)."""
        idx = self.central_stack.currentIndex()
        if idx == self.PAGE_SQL_INSERT:
            return self.sql_insert_page.save_as_sql_dialog()
        if idx == self.PAGE_SQL_SELECT:
            return self.sql_select_page.save_as_sql_dialog()
        if self.json_data:
            return self.json_editor_page.save_json_as_dialog()
        Toast.show(
            self,
            "Carregue um arquivo JSON antes de salvar.",
            level="warning",
        )
        return False

    def trigger_generate_insert(self) -> bool:
        """Navega para a página SQL INSERT e dispara a geração do script."""
        self.navigate_to_page(self.PAGE_SQL_INSERT)
        return self.sql_insert_page.generate_sql(show_error_dialog=True)

    def trigger_generate_select(self) -> bool:
        """Navega para a página SELECT Jasper e dispara a geração da consulta."""
        self.navigate_to_page(self.PAGE_SQL_SELECT)
        return self.sql_select_page.generate_sql(show_error_dialog=True)

    def trigger_validate_sql(self) -> bool:
        """Valida a sintaxe PostgreSQL na página SQL ativa."""
        idx = self.central_stack.currentIndex()
        if idx == self.PAGE_SQL_SELECT:
            return self.sql_select_page.validate_syntax(show_dialog=True)
        self.navigate_to_page(self.PAGE_SQL_INSERT)
        return self.sql_insert_page.validate_syntax(show_dialog=True)

    def _validate_and_format_json(self) -> bool:
        self.navigate_to_page(self.PAGE_JSON_EDITOR)
        return self.json_editor_page.validate_and_format(show_dialog_on_success=False)

    def _active_plain_text_editor(self) -> QPlainTextEdit | None:
        idx = self.central_stack.currentIndex()
        if idx == self.PAGE_JSON_EDITOR:
            return self.json_editor_page.text_area
        if idx == self.PAGE_SQL_INSERT:
            return self.sql_insert_page.preview_text
        if idx == self.PAGE_SQL_SELECT:
            return self.sql_select_page.preview_text
        return None

    def _undo_in_active_editor(self) -> None:
        ed = self._active_plain_text_editor()
        if ed is not None:
            ed.undo()

    def _redo_in_active_editor(self) -> None:
        ed = self._active_plain_text_editor()
        if ed is not None:
            ed.redo()

    def _cut_in_active_editor(self) -> None:
        ed = self._active_plain_text_editor()
        if ed is not None:
            ed.cut()

    def _copy_in_active_editor(self) -> None:
        ed = self._active_plain_text_editor()
        if ed is not None:
            ed.copy()

    def _paste_in_active_editor(self) -> None:
        ed = self._active_plain_text_editor()
        if ed is not None:
            ed.paste()

    def open_settings_dialog(self, initial_row: int = 0) -> SettingsDialog:
        """Abre o diálogo modal de configurações na categoria solicitada."""
        dlg = SettingsDialog(
            config_service=self.config_service,
            theme_service=self.theme_service,
            help_service=self.help_service,
            parent=self,
        )
        if dlg.category_list.count() > 0:
            row = min(max(0, initial_row), dlg.category_list.count() - 1)
            dlg.category_list.setCurrentRow(row)
        dlg.exec()
        return dlg

    def show_help(self) -> SettingsDialog:
        """Abre a página de Ajuda Contextual e Atalhos no diálogo de configurações."""
        return self.open_settings_dialog(initial_row=4)

    def show_about_dialog(self) -> AboutDialog:
        """Exibe o diálogo modal 'Sobre' (400x300)."""
        dlg = AboutDialog(self)
        dlg.exec()
        return dlg

    # -------------------------------------------------------------------------
    # Persistência de Estado (`saveState` / `restoreState` + `QSettings`)
    # -------------------------------------------------------------------------
    def save_window_state(self) -> None:
        """Salva geometria, estado das docks, e página atual no `QSettings`."""
        settings: QSettings = self.config_service.settings
        try:
            settings.setValue("window/geometry", self.saveGeometry())
            settings.setValue("window/state", self.saveState())
            settings.setValue("window/last_page", self.central_stack.currentIndex())
            settings.sync()
        except Exception as exc:
            logger.warning("Não foi possível salvar estado da janela: %s", exc)

    def restore_window_state(self) -> None:
        """Restaura geometria, estado das docks, e última página do `QSettings`."""
        settings: QSettings = self.config_service.settings
        try:
            geom = settings.value("window/geometry")
            if isinstance(geom, QByteArray) and not geom.isEmpty():
                self.restoreGeometry(geom)

            state = settings.value("window/state")
            if isinstance(state, QByteArray) and not state.isEmpty():
                self.restoreState(state)

            last_page_raw = settings.value("window/last_page", self.PAGE_LANDING)
            last_page = int(last_page_raw) if last_page_raw is not None else 0
            if 0 <= last_page < self.central_stack.count():
                if last_page == self.PAGE_LANDING or self.json_data:
                    self.central_stack.setCurrentIndex(last_page)
        except Exception as exc:
            logger.warning("Não foi possível restaurar estado da janela: %s", exc)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_window_state()
        super().closeEvent(event)

    # -------------------------------------------------------------------------
    # Métodos Utilitários e de Compatibilidade
    # -------------------------------------------------------------------------
    def get_json_data(self) -> dict[str, Any] | None:
        """Retorna o dicionário compartilhado ativo (ou `None` se estiver vazio)."""
        return self.json_data if self.json_data else None

    def set_json_data(
        self, data: dict[str, Any], *, update_editor: bool = True
    ) -> dict[str, Any]:
        """Define os dados do dicionário compartilhado in-place e sincroniza todas as páginas."""
        update_shared_dict_in_place(self.json_data, data)
        if update_editor:
            self.json_editor_page.set_json_data(
                self.json_data,
                update_original=True,
                apply_uppercase=False,
                notify=False,
            )
        self.questions_page.refresh_from_shared()
        self.sql_insert_page.clear_preview()
        self.sql_select_page.clear_preview()
        if self.current_view == "landing":
            self.show_notebook()
        self._refresh_properties_panel()
        self._notify_listeners()
        return self.json_data

    def register_json_listener(
        self, callback: Callable[[dict[str, Any] | None], None]
    ) -> None:
        """Registra um callback invocado sempre que o JSON compartilhado muda."""
        self._listeners.append(callback)

    def _notify_listeners(self) -> None:
        active = self.json_data if self.json_data else None
        for callback in self._listeners:
            callback(active)

    # Métodos de conveniência para testes legados
    def withdraw(self) -> None:
        self.hide()

    def destroy(self) -> None:
        self.close()
        self.deleteLater()

    def clipboard_get(self) -> str:
        clipboard = QApplication.clipboard()
        return clipboard.text() if clipboard is not None else ""


# Alias de compatibilidade
MainApp = MainWindow

__all__ = [
    "APP_TITLE_BASE",
    "APP_VERSION",
    "AboutDialog",
    "MainApp",
    "MainWindow",
    "load_app_icon",
    "load_app_logo_pixmap",
]
