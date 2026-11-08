# -*- coding: utf-8 -*-
"""
Página Inicial do Wizard — LandingPage (src/gui/wizard/landing_page.py).

Implementa a tela inicial PySide6 conforme Spec 00 e `spec_json_editor.md`:
- Logo `salutem_ferramenta_interna_logo.png` no topo (altura ~120px, mantém aspect ratio, cantos arredondados)
- Título: "Automatizador de Fichas – Carregar JSON"
- Botão "Baixar Skill (SKILL.md)" com tooltip completo
- Explicação curta (2 linhas) centralizada
- Botões "Carregar JSON de Arquivo" e "Colar JSON da Área de Transferência"
- Barra de status / feedback visual
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import src.resources.resources_rc  # noqa: F401
from src.utils.json_utils import parse_and_validate_clinical_json
from src.utils.resource_path import get_skill_file_path, resource_path
from src.utils.logo_utils import load_logo_pixmap

logger = logging.getLogger("gui.wizard.landing")

SKILL_TOOLTIP_TEXT = (
    "Esta skill ensina a IA a extrair fichas clínicas de PDFs/imagens/texto e "
    "gerar o JSON estruturado esperado pelo sistema.\n\n"
    "Como usar:\n"
    "1. Baixe este arquivo.\n"
    "2. Anexe/o envie para a IA de sua preferência (Claude, ChatGPT, modelos gratuitos via OpenRouter, etc.).\n"
    "3. Envie o PDF da ficha clínica para a IA.\n"
    "4. A IA, seguindo a skill, vai conversar com você para validar campos, tipos, labels, etc.\n"
    "5. Quando vocês chegarem a um acordo, a IA gerará o JSON final.\n"
    "6. Copie/cole ou carregue esse JSON aqui."
)

SHORT_EXPLANATION_TEXT = (
    "Baixe o arquivo SKILL.md acima e envie-o junto com o PDF da ficha clínica para a IA de sua preferência. "
    "Valide os campos e tipos com a IA até que ela gere o JSON final da ficha no padrão Salutem."
)


def _load_landing_logo(target_height: int = 120) -> QPixmap:
    """Carrega o logo da aplicação escalado para a altura alvo mantendo a proporção e com cantos arredondados."""
    return load_logo_pixmap(height=target_height, radius=16)


class _StatusVarAdapter:
    """Adaptador de status compatível com `get()` / `set(text)`."""

    def __init__(self, label: QLabel) -> None:
        self._label = label

    def get(self) -> str:
        return self._label.text()

    def set(self, value: str) -> None:
        self._label.setText(str(value))


class _TooltipAdapter:
    """Adaptador leve para inspeção do tooltip do botão de Skill."""

    def __init__(self, widget: QWidget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window: object | None = None

    def show_tooltip(self) -> None:
        self.tip_window = True

    def hide_tooltip(self) -> None:
        self.tip_window = None


class LandingPage(QWidget):
    """
    Página 0 do Wizard: Tela Inicial com logo, download da SKILL.md e importação de JSON.

    Signals:
        json_loaded (dict, object): Emitido quando um JSON válido é carregado (`data, source_path`).
    """

    json_loaded = Signal(dict, object)

    def __init__(
        self,
        parent: QWidget | None = None,
        on_json_loaded: Callable[[dict[str, Any], Path | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_json_loaded = on_json_loaded
        self.setAccessibleName("Página Inicial — Carregar JSON")
        self._build_ui()
        self.status_var = _StatusVarAdapter(self.lbl_status)
        self.skill_tooltip = _TooltipAdapter(self.btn_download_skill, SKILL_TOOLTIP_TEXT)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 24, 32, 16)
        root_layout.setSpacing(16)

        root_layout.addStretch(1)

        # Logo centralizado (~120px de altura, cantos arredondados)
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        self.lbl_logo = QLabel(self)
        self.lbl_logo.setAccessibleName("Logo Salutem Ferramenta Interna")
        logo_pm = _load_landing_logo(120)
        if not logo_pm.isNull():
            self.lbl_logo.setPixmap(logo_pm)
        logo_row.addWidget(self.lbl_logo)
        logo_row.addStretch(1)
        root_layout.addLayout(logo_row)

        # Título Principal
        self.lbl_title = QLabel("Automatizador de Fichas – Carregar JSON", self)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 16pt; font-weight: 700;")
        root_layout.addWidget(self.lbl_title)

        # Seção 1: Download da Skill + Explicação
        skill_group = QGroupBox("1. Instruções para Extração via IA (Skill)", self)
        skill_layout = QVBoxLayout(skill_group)
        skill_layout.setContentsMargins(16, 16, 16, 16)
        skill_layout.setSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_download_skill = QPushButton("Baixar Skill (SKILL.md)", skill_group)
        self.btn_download_skill.setAccessibleName("Baixar Skill SKILL.md")
        self.btn_download_skill.setToolTip(SKILL_TOOLTIP_TEXT)
        self.btn_download_skill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download_skill.clicked.connect(lambda: self.download_skill())
        btn_row.addWidget(self.btn_download_skill)

        skill_layout.addLayout(btn_row)

        self.lbl_explanation = QLabel(SHORT_EXPLANATION_TEXT, skill_group)
        self.lbl_explanation.setWordWrap(True)
        self.lbl_explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_explanation.setStyleSheet("color: #475569; font-size: 10pt;")
        skill_layout.addWidget(self.lbl_explanation)

        root_layout.addWidget(skill_group)

        # Seção 2: Carregar ou Colar JSON
        load_group = QGroupBox("2. Importar JSON da Ficha Clínica", self)
        load_layout = QHBoxLayout(load_group)
        load_layout.setContentsMargins(16, 20, 16, 16)
        load_layout.setSpacing(12)

        self.btn_load_file = QPushButton("Carregar JSON de Arquivo", load_group)
        self.btn_load_file.setProperty("variant", "primary")
        self.btn_load_file.setMinimumHeight(38)
        self.btn_load_file.setAccessibleName("Carregar JSON de Arquivo")
        self.btn_load_file.setToolTip("Abrir um arquivo .json de ficha clínica do computador (Ctrl+O)")
        self.btn_load_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_file.clicked.connect(self.load_json_from_file_dialog)
        load_layout.addWidget(self.btn_load_file, 1)

        self.btn_paste_clipboard = QPushButton(
            "Colar JSON da Área de Transferência", load_group
        )
        self.btn_paste_clipboard.setMinimumHeight(38)
        self.btn_paste_clipboard.setAccessibleName("Colar JSON da Área de Transferência")
        self.btn_paste_clipboard.setToolTip("Colar JSON copiado da área de transferência (Ctrl+Shift+V)")
        self.btn_paste_clipboard.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_paste_clipboard.clicked.connect(self.paste_json_from_clipboard)
        load_layout.addWidget(self.btn_paste_clipboard, 1)

        root_layout.addWidget(load_group)

        root_layout.addStretch(1)

        # Barra de status inferior da página
        self.lbl_status = QLabel("Aguardando JSON…", self)
        self.lbl_status.setAccessibleName("Status da Tela Inicial")
        self.lbl_status.setStyleSheet("padding: 6px 10px; border-radius: 4px;")
        root_layout.addWidget(self.lbl_status)

    def download_skill(self, destination_path: str | Path | None = None) -> bool:
        """
        Copia o arquivo `SKILL.md` embutido nos recursos do projeto para o destino escolhido.
        """
        from src.utils.resource_path import get_skill_file_path

        source_path = get_skill_file_path()
        if not source_path.exists():
            msg = f"O arquivo SKILL.md não foi encontrado em:\n{source_path}"
            logger.error(msg)
            QMessageBox.critical(self, "Recurso Não Encontrado", msg)
            self.lbl_status.setText("Erro: arquivo SKILL.md não encontrado nos recursos.")
            return False

        if destination_path is None:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar Arquivo da Skill",
                "SKILL.md",
                "Markdown (SKILL.md) (*.md);;Todos os arquivos (*.*)",
            )
            if not selected:
                return False
            dest = Path(selected)
        else:
            dest = Path(destination_path)

        try:
            shutil.copyfile(source_path, dest)
            self.lbl_status.setText(f"Skill salva com sucesso em: {dest}")
            logger.info("SKILL.md exportada para '%s'", dest)
            if destination_path is None:
                QMessageBox.information(
                    self,
                    "Download Concluído",
                    f"O arquivo '{dest.name}' foi salvo com sucesso em:\n{dest}",
                )
            return True
        except OSError as exc:
            logger.error("Erro ao salvar SKILL.md em '%s': %s", dest, exc)
            QMessageBox.critical(
                self,
                "Erro ao Salvar Skill",
                f"Não foi possível salvar o arquivo em:\n{dest}\n\nDetalhes: {exc}",
            )
            self.lbl_status.setText(f"Erro ao salvar SKILL.md: {exc}")
            return False

    def load_json_from_file_dialog(self) -> bool:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Carregar JSON de Ficha Clínica",
            "",
            "Arquivos JSON (*.json);;Todos os arquivos (*.*)",
        )
        if not file_path:
            return False
        return self.load_json_from_path(file_path)

    def load_json_from_path(
        self, file_path: str | Path, show_error_dialog: bool = True
    ) -> bool:
        """Lê, valida e carrega um arquivo JSON a partir do caminho informado."""
        path = Path(file_path)
        try:
            raw_text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            msg = f"Não foi possível ler o arquivo:\n{path}\n\nDetalhes: {exc}"
            logger.error("Erro ao ler JSON '%s': %s", path, exc)
            self.lbl_status.setText(f"Erro ao ler arquivo: {path.name}")
            if show_error_dialog:
                QMessageBox.critical(self, "Erro ao Abrir Arquivo", msg)
            return False

        return self._process_raw_json(
            raw_text, source_path=path, show_error_dialog=show_error_dialog
        )

    def paste_json_from_clipboard(self, show_error_dialog: bool = True) -> bool:
        clipboard = QApplication.clipboard()
        raw_text = clipboard.text() if clipboard is not None else ""
        if not raw_text.strip():
            msg = "Não há texto disponível na área de transferência."
            self.lbl_status.setText(f"Erro: {msg}")
            if show_error_dialog:
                QMessageBox.critical(self, "Área de Transferência Vazia", msg)
            return False

        return self._process_raw_json(
            raw_text, source_path=None, show_error_dialog=show_error_dialog
        )

    def _process_raw_json(
        self,
        raw_text: str,
        source_path: Path | None = None,
        show_error_dialog: bool = True,
    ) -> bool:
        """Valida sintaxe e estrutura mínima (`template` + `perguntas`) e notifica carregamento."""
        try:
            validated_data = parse_and_validate_clinical_json(
                raw_text,
                require_clinical_structure=True,
                apply_uppercase=True,
            )
        except json.JSONDecodeError as exc:
            origem = f" no arquivo '{source_path.name}'" if source_path else ""
            detalhe = (
                f"O JSON informado{origem} contém erro de sintaxe:\n\n"
                f"Erro: {exc.msg}\n"
                f"Linha: {exc.lineno}, Coluna: {exc.colno}"
            )
            self.lbl_status.setText(
                f"Erro de validação JSON (Linha {exc.lineno}, Coluna {exc.colno}): {exc.msg}"
            )
            logger.warning("JSON inválido carregado%s: %s", origem, exc)
            if show_error_dialog:
                QMessageBox.critical(self, "JSON Inválido", detalhe)
            return False
        except ValueError as exc:
            self.lbl_status.setText(f"Erro de validação: {exc}")
            logger.warning("Estrutura JSON inválida: %s", exc)
            if show_error_dialog:
                QMessageBox.critical(self, "JSON Inválido", str(exc))
            return False

        self.lbl_status.setText("JSON válido carregado com sucesso!")
        logger.info("JSON carregado com sucesso (origem=%s)", source_path or "clipboard")
        if self.on_json_loaded is not None:
            self.on_json_loaded(validated_data, source_path)
        self.json_loaded.emit(validated_data, source_path)
        return True