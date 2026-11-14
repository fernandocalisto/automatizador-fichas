# -*- coding: utf-8 -*-
"""
Diálogo de Configurações da Aplicação (src/gui/settings/dialog.py).

Implementa `SettingsDialog(QDialog)` conforme Spec 00:
- Header com logo 32x32 (`salutem_ferramenta_interna_logo.png`) e título
- `QListWidget` à esquerda com as 5 categorias:
  1. Geral (`GeneralPage`)
  2. Tema (`ThemePage`)
  3. Editor SQL (`EditorPage`)
  4. Regex (`RegexPage`)
  5. Ajuda (`HelpPage`)
- `QStackedWidget` à direita exibindo a página selecionada
- Botões de rodapé: `Restaurar Padrões`, `Cancelar`, `Aplicar`, `OK`
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import src.resources.resources_rc  # noqa: F401
from src.gui.components.update_dialog import UpdateDialog
from src.gui.settings.pages import (
    EditorPage,
    GeneralPage,
    HelpPage,
    RegexPage,
    ThemePage,
)
from src.services.config_service import ConfigService
from src.services.help_service import HelpService
from src.services.update_service import UpdateService
from src.utils.resource_path import resource_path

if TYPE_CHECKING:
    from src.services.theme_service import ThemeService

logger = logging.getLogger("gui.settings")


def _load_logo_pixmap(width: int, height: int) -> QPixmap:
    """Carrega o logo Salutem redimensionado com suavização e aspect ratio."""
    for candidate in (
        ":/resources/salutem_ferramenta_interna_logo.png",
        ":/salutem_ferramenta_interna_logo.png",
        str(resource_path("salutem_ferramenta_interna_logo.png")),
    ):
        pm = QPixmap(candidate)
        if not pm.isNull():
            return pm.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    return QPixmap()


class SettingsDialog(QDialog):
    """
    Diálogo de configurações centralizado com `QListWidget` + `QStackedWidget`.

    Signals:
        settings_applied (): Emitido sempre que as configurações são salvas/aplicadas.
    """

    settings_applied = Signal()

    def __init__(
        self,
        config_service: ConfigService | None = None,
        theme_service: ThemeService | None = None,
        help_service: HelpService | None = None,
        parent: QWidget | None = None,
        update_service: UpdateService | None = None,
        current_version: str = "v0.2.0",
    ) -> None:
        super().__init__(parent)
        self.config_service = config_service or ConfigService()
        self.theme_service = theme_service
        self.help_service = help_service or HelpService()
        self.update_service = update_service or UpdateService(self.config_service, parent=self)
        self.current_version = current_version

        self.setWindowTitle("Configurações — Automatizador de Fichas")
        self.setAccessibleName("Diálogo de Configurações")
        self.setMinimumSize(720, 520)
        self.resize(760, 560)

        self._build_ui()
        self.general_page.check_updates_requested.connect(self._on_check_updates_now)
        self.load_all_pages()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # Header com logo 32x32 + título
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(10)

        self.lbl_logo = QLabel(self)
        self.lbl_logo.setFixedSize(32, 32)
        logo_pm = _load_logo_pixmap(32, 32)
        if not logo_pm.isNull():
            self.lbl_logo.setPixmap(logo_pm)
        header_layout.addWidget(self.lbl_logo)

        lbl_header_title = QLabel("Configurações do Sistema", self)
        lbl_header_title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        header_layout.addWidget(lbl_header_title)
        header_layout.addStretch(1)

        root_layout.addLayout(header_layout)

        # Splitter central: QListWidget (esquerda) + QStackedWidget (direita)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        self.category_list = QListWidget(splitter)
        self.category_list.setAccessibleName("Categorias de Configuração")
        self.category_list.setFixedWidth(190)

        self.stack = QStackedWidget(splitter)
        self.stack.setAccessibleName("Páginas de Configuração")

        self.general_page = GeneralPage(self.stack)
        self.theme_page = ThemePage(self.stack)
        self.editor_page = EditorPage(self.stack)
        self.regex_page = RegexPage(self.stack)
        self.help_page = HelpPage(self.help_service, self.stack)

        self._pages = [
            ("Geral", self.general_page),
            ("Tema", self.theme_page),
            ("Editor SQL", self.editor_page),
            ("Regex", self.regex_page),
            ("Ajuda", self.help_page),
        ]

        for label, page_widget in self._pages:
            item = QListWidgetItem(label)
            item.setToolTip(f"Configurações de {label}")
            self.category_list.addItem(item)
            self.stack.addWidget(page_widget)

        self.category_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.category_list.setCurrentRow(0)

        splitter.addWidget(self.category_list)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)

        # Linha divisória
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root_layout.addWidget(sep)

        # Rodapé de botões: Restaurar Padrões | stretch | Cancelar | Aplicar | OK
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(8)

        self.btn_restore = QPushButton("Restaurar Padrões", self)
        self.btn_restore.setAccessibleName("Restaurar Padrões")
        self.btn_restore.setToolTip("Restaura todas as configurações para os valores de fábrica")
        self.btn_restore.clicked.connect(self.restore_defaults)
        footer.addWidget(self.btn_restore)

        footer.addStretch(1)

        self.btn_cancel = QPushButton("Cancelar", self)
        self.btn_cancel.setAccessibleName("Cancelar")
        self.btn_cancel.setToolTip("Descarta alterações não aplicadas e fecha")
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("Aplicar", self)
        self.btn_apply.setAccessibleName("Aplicar")
        self.btn_apply.setToolTip("Salva e aplica as configurações sem fechar a janela")
        self.btn_apply.clicked.connect(self.apply_settings)
        footer.addWidget(self.btn_apply)

        self.btn_ok = QPushButton("OK", self)
        self.btn_ok.setProperty("variant", "primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.setAccessibleName("OK")
        self.btn_ok.setToolTip("Salva as configurações e fecha a janela")
        self.btn_ok.clicked.connect(self._on_ok_clicked)
        footer.addWidget(self.btn_ok)

        root_layout.addLayout(footer)

    def load_all_pages(self) -> None:
        """Popula todas as páginas com os valores atuais de `self.config_service.config`."""
        cfg = self.config_service.config
        for _, page in self._pages:
            page.load_from_config(cfg)

    def apply_settings(self) -> None:
        """Coleta os valores de todas as páginas, persiste no `ConfigService` e aplica tema."""
        updated = copy.deepcopy(self.config_service.config)
        for _, page in self._pages:
            page.apply_to_config(updated)

        self.config_service.save(updated)
        if self.theme_service is not None:
            self.theme_service.apply_app_theme(updated.app_theme, persist=False)

        logger.info("Configurações aplicadas pelo usuário.")
        self.settings_applied.emit()

    def restore_defaults(self) -> None:
        """Restaura os valores padrão no `ConfigService` e recarrega as páginas."""
        self.config_service.reset_to_defaults()
        self.load_all_pages()
        if self.theme_service is not None:
            self.theme_service.apply_app_theme(
                self.config_service.config.app_theme, persist=False
            )
        logger.info("Configurações restauradas para os padrões de fábrica.")
        self.settings_applied.emit()

    def _on_ok_clicked(self) -> None:
        self.apply_settings()
        self.accept()

    def _on_check_updates_now(self) -> None:
        """Executa verificação manual de atualizações e informa o resultado."""
        btn = self.general_page.btn_check_updates_now
        btn.setEnabled(False)
        btn.setText("Verificando...")
        btn.repaint()
        try:
            info = self.update_service.check_for_updates(
                current_version=self.current_version,
                force=True,
            )
            self.general_page.set_last_update_check_text(
                self.config_service.config.last_update_check
            )
        except Exception as exc:
            logger.warning("Falha ao verificar atualizações manualmente: %s", exc)
            QMessageBox.warning(
                self,
                "Verificar Atualizações",
                f"Não foi possível verificar atualizações:\n{exc}",
            )
            return
        finally:
            btn.setEnabled(True)
            btn.setText("Verificar Agora")

        if info is None:
            QMessageBox.information(
                self,
                "Verificar Atualizações",
                f"Você já está na versão mais recente ({self.current_version}).",
            )
            return

        dlg = UpdateDialog(
            update_info=info,
            current_version=self.current_version,
            update_service=self.update_service,
            config_service=self.config_service,
            parent=self,
        )
        dlg.exec()
