# -*- coding: utf-8 -*-
"""
Diálogo de Nova Versão Disponível (src/gui/components/update_dialog.py).

Exibe informações da release encontrada no GitHub Releases, release notes em Markdown,
barra de progresso para download e ações ("Atualizar Agora", "Lembrar Depois",
"Ignorar Esta Versão").
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from src.services.config_service import ConfigService
    from src.services.update_service import UpdateInfo, UpdateService

logger = logging.getLogger("gui.components.update_dialog")


class UpdateDialog(QDialog):
    """Modal exibido quando há uma atualização disponível."""

    _progress_signal = Signal(int, int)
    _download_finished_signal = Signal(str)
    _download_error_signal = Signal(str)

    def __init__(
        self,
        update_info: UpdateInfo,
        current_version: str = "v0.2.0",
        update_service: UpdateService | None = None,
        config_service: ConfigService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.update_info = update_info
        self.current_version = current_version
        self._update_service = update_service
        self._config_service = config_service
        self.user_choice: str = "later"
        self.downloaded_path: Path | None = None

        self.setWindowTitle(f"Nova versão {update_info.version} disponível")
        self.setAccessibleName("Diálogo de Atualização")
        self.setMinimumSize(520, 420)
        self.resize(580, 460)

        self._build_ui()
        self._progress_signal.connect(self._on_download_progress)
        self._download_finished_signal.connect(self._on_download_finished)
        self._download_error_signal.connect(self._on_download_error)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.lbl_header = QLabel(
            f"Nova versão {self.update_info.version} disponível!",
            self,
        )
        self.lbl_header.setStyleSheet("font-size: 13pt; font-weight: 700;")
        layout.addWidget(self.lbl_header)

        published = self.update_info.published_at[:10] if self.update_info.published_at else "—"
        self.lbl_versions = QLabel(
            f"Versão atual: {self.current_version}  |  Nova versão: {self.update_info.version}  |  Publicada em: {published}",
            self,
        )
        self.lbl_versions.setStyleSheet("color: #64748b;")
        layout.addWidget(self.lbl_versions)

        lbl_notes = QLabel("Notas da versão (Release Notes):", self)
        lbl_notes.setStyleSheet("font-weight: 600;")
        layout.addWidget(lbl_notes)

        self.txt_release_notes = QTextBrowser(self)
        self.txt_release_notes.setAccessibleName("Notas da Versão")
        self.txt_release_notes.setOpenExternalLinks(True)
        notes_md = self.update_info.release_notes.strip() or "_Sem notas informadas._"
        self.txt_release_notes.setMarkdown(notes_md)
        layout.addWidget(self.txt_release_notes, 1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setAccessibleName("Progresso do Download da Atualização")
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("", self)
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_ignore_version = QPushButton("Ignorar Esta Versão", self)
        self.btn_ignore_version.setAccessibleName("Ignorar Esta Versão")
        self.btn_ignore_version.clicked.connect(self.ignore_this_version)
        btn_row.addWidget(self.btn_ignore_version)

        btn_row.addStretch(1)

        self.btn_remind_later = QPushButton("Lembrar Depois", self)
        self.btn_remind_later.setAccessibleName("Lembrar Depois")
        self.btn_remind_later.clicked.connect(self.remind_later)
        btn_row.addWidget(self.btn_remind_later)

        self.btn_update_now = QPushButton("Atualizar Agora", self)
        self.btn_update_now.setProperty("variant", "primary")
        self.btn_update_now.setAccessibleName("Atualizar Agora")
        self.btn_update_now.clicked.connect(self.start_update)
        btn_row.addWidget(self.btn_update_now)

        layout.addLayout(btn_row)

    def ignore_this_version(self) -> None:
        self.user_choice = "ignore"
        if self._config_service is not None:
            self._config_service.set("ignored_update_version", self.update_info.version)
        self.reject()

    def remind_later(self) -> None:
        self.user_choice = "later"
        self.reject()

    def start_update(self) -> None:
        self.user_choice = "update"
        if self._update_service is None:
            self.accept()
            return

        if not self.update_info.asset_url:
            QMessageBox.warning(
                self,
                "Download Indisponível",
                "Nenhum arquivo .exe encontrado nesta release.",
            )
            return

        self.btn_update_now.setEnabled(False)
        self.btn_ignore_version.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setVisible(True)
        self.lbl_status.setText("Baixando atualização…")

        def _worker() -> None:
            try:
                assert self._update_service is not None
                path = self._update_service.download_update(
                    self.update_info.asset_url,
                    progress_callback=lambda done, total: self._progress_signal.emit(done, total),
                    version=self.update_info.version,
                )
                self._download_finished_signal.emit(str(path))
            except Exception as exc:
                self._download_error_signal.emit(str(exc))

        threading.Thread(target=_worker, name="UpdateDownloadThread", daemon=True).start()

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = min(100, int((downloaded / total) * 100))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.lbl_status.setText(f"Baixando: {downloaded // 1024} KB / {total // 1024} KB")
        else:
            self.progress_bar.setRange(0, 0)
            self.lbl_status.setText(f"Baixando: {downloaded // 1024} KB")

    def _on_download_finished(self, path_str: str) -> None:
        self.downloaded_path = Path(path_str)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Download concluído. Aplicando atualização…")
        if self._update_service is not None:
            try:
                self._update_service.install_update(self.downloaded_path)
            except Exception as exc:
                self._on_download_error(str(exc))
                return
        self.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_download_error(self, error_msg: str) -> None:
        self.btn_update_now.setEnabled(True)
        self.btn_ignore_version.setEnabled(True)
        self.lbl_status.setText(f"Erro no download: {error_msg}")
        QMessageBox.critical(self, "Erro na Atualização", f"Não foi possível baixar a atualização:\n{error_msg}")


__all__ = ["UpdateDialog"]
