# -*- coding: utf-8 -*-
"""
Testes automatizados da Fase 4:
- Etapa 05: Persistência de opções SELECT Jasper (`ConfigService` + `SqlSelectPage`) e `spec_05_select_options.md`
- Etapa 01 / Config Editor: `LineNumberArea`, atalhos/busca, temas JSON e sincronização reativa via `ConfigService`
- Etapa 08: Auto-Updater (`UpdateService`, `UpdateDialog`, `GeneralPage`, `SettingsDialog`, `MainWindow`)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit

from src.gui.components.sql_editor import (
    SqlEditorWidget,
    load_editor_theme_palette,
)
from src.gui.components.update_dialog import UpdateDialog
from src.gui.main_window import MainWindow
from src.gui.settings.dialog import SettingsDialog
from src.gui.settings.pages.general_page import GeneralPage
from src.gui.wizard.json_editor_page import JsonEditorPage
from src.gui.wizard.sql_insert_page import SqlInsertPage
from src.gui.wizard.sql_select_page import SqlSelectPage
from src.services.config_service import AppConfig, ConfigService
from src.services.update_service import (
    UpdateInfo,
    UpdateService,
    is_newer_version,
    parse_semver,
)


def _isolated_config_service(tmp_path: Path, json_name: str = "config.json") -> ConfigService:
    """Cria `ConfigService` isolado do registro real do usuário."""
    uid = uuid.uuid4().hex[:8]
    cfg = ConfigService(
        organization=f"AutoFichaTestOrg_{uid}",
        application=f"AutoFichaTestApp_{uid}",
        json_path=tmp_path / json_name,
    )
    cfg.settings.clear()
    return cfg


def _sample_ficha() -> dict[str, Any]:
    return {
        "template": {
            "nome": "FICHA PHASE 4 TEST",
            "descricao": "Ficha para testes integrados da Fase 4",
            "ativo": True,
            "layout": "ficha-clinica",
        },
        "perguntas": [
            {
                "nome": "EVOLUÇÃO",
                "titulo": False,
                "respostas": [
                    {"label": "Febre", "tipo_campo": "BOOLEANO", "observacao": True},
                    {"label": "Observação Clínica", "tipo_campo": "TEXTO", "observacao": False},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Etapa 05: Opções SELECT Jasper + Documentação + Persistência
# ---------------------------------------------------------------------------
def test_spec_05_documentation_exists() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    examples_dir = repo_root.parent / "Automatiza Ficha - Exemplos"
    if not examples_dir.exists():
        pytest.skip("Pasta externa 'Automatiza Ficha - Exemplos' ausente no ambiente de CI")
    spec_path = examples_dir / "spec_05_select_options.md"
    assert spec_path.exists(), f"Spec não encontrada em: {spec_path}"
    content = spec_path.read_text(encoding="utf-8")
    assert "select_jasper_options" in content
    assert "COALESCE/BOOL_OR" in content
    assert "label_only" in content
    assert "Cabeçalho" in content


def test_select_jasper_options_persist_across_pages(tmp_path: Path) -> None:
    org = f"AutoFichaPersistOrg_{uuid.uuid4().hex[:8]}"
    app_name = f"AutoFichaPersistApp_{uuid.uuid4().hex[:8]}"
    json_path = tmp_path / "settings.json"

    cfg1 = ConfigService(organization=org, application=app_name, json_path=json_path)
    cfg1.settings.clear()

    # Padrão de fábrica agora usa label_only
    defaults = cfg1.get_select_jasper_options()
    assert defaults["column_naming"] == "label_only"

    shared = _sample_ficha()
    page1 = SqlSelectPage(shared_json=shared, config_service=cfg1)
    assert page1.generate_sql(show_error_dialog=False) is True

    # Altera estilo booleano na UI -> atualiza preview em tempo real e persiste no ConfigService
    idx_sim_nao = page1.cmb_boolean_style.findData("sim_nao")
    assert idx_sim_nao >= 0
    page1.cmb_boolean_style.setCurrentIndex(idx_sim_nao)
    assert "then 'SIM' else 'NÃO' end" in page1.get_preview_text()

    saved_opts = cfg1.get_select_jasper_options()
    assert saved_opts["boolean_style"] == "sim_nao"

    # Salva mais opções no ConfigService para simular reinício com outro ConfigService
    saved_opts["include_obs"] = False
    saved_opts["include_metadata"] = True
    saved_opts["include_paciente"] = False
    cfg1.save_select_jasper_options(saved_opts)

    cfg2 = ConfigService(organization=org, application=app_name, json_path=json_path)
    page2 = SqlSelectPage(shared_json=shared, config_service=cfg2)
    try:
        assert page2.cmb_boolean_style.currentData() == "sim_nao"
        restored = cfg2.get_select_jasper_options()
        assert restored["boolean_style"] == "sim_nao"
        assert restored["include_obs"] is False
        assert restored["include_metadata"] is True
        assert restored["include_paciente"] is False
        assert page2.generate_sql(show_error_dialog=False) is True
        sql2 = page2.get_preview_text()
        assert "then 'SIM' else 'NÃO' end" in sql2
        assert "febre_obs" not in sql2
        assert "----- PACIENTE" not in sql2
    finally:
        page1.deleteLater()
        page2.deleteLater()
        QApplication.processEvents()


def test_appconfig_from_dict_preserves_boolean_and_dict_fields() -> None:
    cfg = AppConfig.from_dict(
        {
            "auto_check_updates": False,
            "last_update_check": "2026-01-15T10:30:00+00:00",
            "ignored_update_version": "v0.2.9",
            "select_jasper_options": {
                "boolean_style": "1_0",
                "include_obs": False,
                "include_all_blocks": True,
            },
        }
    )
    assert cfg.auto_check_updates is False
    assert cfg.last_update_check == "2026-01-15T10:30:00+00:00"
    assert cfg.ignored_update_version == "v0.2.9"
    assert cfg.select_jasper_options["include_obs"] is False
    assert cfg.select_jasper_options["include_all_blocks"] is True


# ---------------------------------------------------------------------------
# Etapa 01 & Settings Editor Wiring: Line Numbers, Search, Themes, ConfigSync
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("theme_name", ["vscode", "monokai", "dracula", "github", "solarized"])
def test_editor_theme_palette_loads_from_json(theme_name: str) -> None:
    palette = load_editor_theme_palette(theme_name)
    assert palette["background"].startswith("#")
    assert "styles" in palette
    assert "keyword" in palette["styles"]


def test_sql_editor_features_and_config_sync(tmp_path: Path) -> None:
    cfg = _isolated_config_service(tmp_path)
    editor = SqlEditorWidget(config_service=cfg)
    editor.set_text("SELECT a FROM t WHERE x = 1 AND $P{pid} = 1;\nSELECT b FROM t WHERE x = 2;\n")
    try:
        # Line numbers visíveis por padrão e ocultáveis via API
        assert editor._show_line_numbers is True
        assert editor.line_number_area_width() > 0
        assert editor._line_number_area.isHidden() is False

        editor.set_show_line_numbers(False)
        assert editor._line_number_area.isHidden() is True
        assert editor.line_number_area_width() == 0

        # Tab size
        editor.set_tab_size(2)
        dist_2 = editor.tabStopDistance()
        editor.set_tab_size(8)
        assert editor.tabStopDistance() > dist_2

        # Whitespace
        editor.set_show_whitespace(True)
        flags = editor.document().defaultTextOption().flags()
        assert bool(flags & QTextOption.Flag.ShowTabsAndSpaces)

        # Find first / next / previous
        assert editor.find_first("WHERE") is True
        first_pos = editor.textCursor().position()
        assert editor.find_next() is True
        second_pos = editor.textCursor().position()
        assert second_pos > first_pos
        assert editor.find_previous() is True
        assert editor.textCursor().position() <= second_pos

        # Atualização reativa via ConfigService
        cfg.set("show_line_numbers", True)
        cfg.set("show_whitespace", False)
        cfg.set("tab_size", 6)
        cfg.set("font_size", 15)
        cfg.set("editor_theme", "monokai")

        assert editor._tab_size == 6
        assert editor._show_line_numbers is True
        assert editor._show_whitespace is False
        assert editor.font().pointSize() == 15
        assert editor._current_editor_theme == "monokai"
    finally:
        editor.deleteLater()
        QApplication.processEvents()

    # After widget destruction, ConfigService updates must not raise RuntimeError
    cfg.set("font_size", 12)


def test_wizard_pages_apply_editor_config(tmp_path: Path) -> None:
    cfg = _isolated_config_service(tmp_path)
    json_page = JsonEditorPage(shared_json=_sample_ficha(), config_service=cfg)
    insert_page = SqlInsertPage(shared_json=_sample_ficha(), config_service=cfg)
    select_page = SqlSelectPage(shared_json=_sample_ficha(), config_service=cfg)
    try:
        cfg.set("font_size", 14)
        cfg.set("tab_size", 2)
        cfg.set("show_whitespace", True)
        cfg.set("show_line_numbers", False)

        json_editor = json_page.findChild(QPlainTextEdit)
        assert json_editor is not None
        assert json_editor.font().pointSize() == 14
        flags = json_editor.document().defaultTextOption().flags()
        assert bool(flags & QTextOption.Flag.ShowTabsAndSpaces)

        insert_editor = insert_page.findChild(SqlEditorWidget)
        select_editor = select_page.findChild(SqlEditorWidget)
        assert insert_editor is not None and select_editor is not None
        assert insert_editor._tab_size == 2
        assert select_editor._show_line_numbers is False
    finally:
        json_page.deleteLater()
        insert_page.deleteLater()
        select_page.deleteLater()
        QApplication.processEvents()


# ---------------------------------------------------------------------------
# Etapa 08: Auto-Updater (UpdateService, UpdateDialog, GeneralPage, Settings)
# ---------------------------------------------------------------------------
def test_semver_comparison() -> None:
    assert parse_semver("v0.2.0") == (0, 2, 0)
    assert parse_semver("1.4.2-beta.1") == (1, 4, 2)
    assert is_newer_version("v0.2.0", "v0.3.0") is True
    assert is_newer_version("v0.2.0", "v0.2.1") is True
    assert is_newer_version("v0.3.0", "v0.3.0") is False
    assert is_newer_version("v0.3.1", "v0.3.0") is False


def test_update_service_auto_check_interval_and_ignore(tmp_path: Path) -> None:
    cfg = _isolated_config_service(tmp_path)
    payload = {
        "tag_name": "v0.3.0",
        "html_url": "https://github.com/example/releases/tag/v0.3.0",
        "body": "## Novidades\n- Correções gerais",
        "published_at": "2026-06-01T12:00:00Z",
        "assets": [
            {
                "name": "AutomatizadorFichas_v0.3.0.exe",
                "browser_download_url": "https://example.com/AutomatizadorFichas_v0.3.0.exe",
            }
        ],
    }
    svc = UpdateService(config_service=cfg, fetcher=lambda _url: payload)

    now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    # Sem check anterior e auto_check_updates=True -> deve checar
    assert svc.should_auto_check(now=now) is True

    # Menos de 24h desde último check -> não deve checar
    cfg.set("last_update_check", (now - timedelta(hours=4)).isoformat())
    assert svc.should_auto_check(now=now) is False

    # 25h desde último check -> deve checar
    cfg.set("last_update_check", (now - timedelta(hours=25)).isoformat())
    assert svc.should_auto_check(now=now) is True

    # Desabilitado -> nunca checa automaticamente
    cfg.set("auto_check_updates", False)
    assert svc.should_auto_check(now=now) is False

    # check_for_updates encontra nova versão e atualiza timestamp
    info = svc.check_for_updates(current_version="v0.2.0")
    assert info is not None
    assert info.version == "v0.3.0"
    assert info.asset_url.endswith(".exe")
    assert cfg.config.last_update_check != ""

    # Ignorar versão suprime check automático (force=False), mas force=True retorna
    cfg.set("ignored_update_version", "v0.3.0")
    assert svc.check_for_updates(current_version="v0.2.0", force=False) is None
    assert svc.check_for_updates(current_version="v0.2.0", force=True) is not None


def test_update_service_download_and_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _isolated_config_service(tmp_path)
    svc = UpdateService(config_service=cfg)

    fake_bytes = b"MZ" + b"\x90" * 4096

    class _FakeHeaders:
        def get(self, name: str) -> str | None:
            if name.lower() == "content-length":
                return str(len(fake_bytes))
            return None

    class _FakeResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._pos = 0
            self.headers = _FakeHeaders()

        def read(self, size: int = -1) -> bytes:
            if self._pos >= len(self._data):
                return b""
            end = len(self._data) if size < 0 else min(len(self._data), self._pos + size)
            chunk = self._data[self._pos:end]
            self._pos = end
            return chunk

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: _FakeResponse(fake_bytes))

    progress_events: list[tuple[int, int]] = []
    dest_dir = tmp_path / "downloads"
    downloaded = svc.download_update(
        "https://example.com/AutomatizadorFichas_v0.3.0.exe",
        progress_callback=lambda done, total: progress_events.append((done, total)),
        dest_dir=dest_dir,
        version="v0.3.0",
    )
    assert downloaded.exists()
    assert downloaded.read_bytes() == fake_bytes
    assert progress_events[-1] == (len(fake_bytes), len(fake_bytes))

    target_exe = tmp_path / "AutomatizadorFichas.exe"
    target_exe.write_bytes(b"OLD")
    bat = svc.create_windows_update_batch(downloaded, target_exe, restart=True)
    assert bat.exists()
    bat_text = bat.read_text(encoding="utf-8")
    assert ".bak" in bat_text
    assert str(downloaded) in bat_text
    assert str(target_exe) in bat_text


def test_update_dialog_and_settings_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _isolated_config_service(tmp_path)
    info = UpdateInfo(
        version="v0.3.0",
        release_url="https://github.com/example/releases/tag/v0.3.0",
        release_notes="### Melhorias\n- Item A",
        asset_url="https://example.com/app.exe",
        published_at="2026-06-01T12:00:00Z",
    )

    # 1. UpdateDialog: Markdown + Ignorar Esta Versão persiste ignored_update_version
    upd_dlg = UpdateDialog(info, current_version="v0.2.0", config_service=cfg)
    assert "Item A" in upd_dlg.txt_release_notes.toPlainText()
    upd_dlg.btn_ignore_version.click()
    assert upd_dlg.user_choice == "ignore"
    assert cfg.config.ignored_update_version == "v0.3.0"

    # 2. GeneralPage: formatação de data DD/MM/AAAA HH:MM e "Nunca"
    page = GeneralPage()
    cfg.set("last_update_check", "")
    page.load_from_config(cfg.config)
    assert page.lbl_last_update_check.text() == "Última verificação: Nunca"
    page.set_last_update_check_text("2026-06-01T14:35:00")
    assert "01/06/2026 14:35" in page.lbl_last_update_check.text()

    # 3. SettingsDialog + Verificar Agora (sem rede real)
    mock_svc = UpdateService(
        config_service=cfg,
        fetcher=lambda _url: {"tag_name": "v0.2.0", "assets": []},
    )
    info_calls: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, text: info_calls.append(text) or QMessageBox.StandardButton.Ok,
    )

    settings_dlg = SettingsDialog(config_service=cfg, update_service=mock_svc, current_version="v0.2.0")
    try:
        settings_dlg.general_page.btn_check_updates_now.click()
        assert len(info_calls) == 1
        assert "versão mais recente" in info_calls[0].lower()
        assert cfg.config.last_update_check != ""
        assert "Nunca" not in settings_dlg.general_page.lbl_last_update_check.text()
    finally:
        settings_dlg.deleteLater()
        upd_dlg.deleteLater()
        page.deleteLater()
        QApplication.processEvents()


def test_mainwindow_async_startup_update_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _isolated_config_service(tmp_path)
    cfg.set("auto_check_updates", True)
    cfg.set("last_update_check", "")

    payload = {
        "tag_name": "v0.9.0",
        "html_url": "https://github.com/example/releases/tag/v0.9.0",
        "body": "- Update disponível",
        "published_at": "2026-06-10T09:00:00Z",
        "assets": [{"name": "app.exe", "browser_download_url": "https://example.com/app.exe"}],
    }
    upd_svc = UpdateService(config_service=cfg, fetcher=lambda _url: payload)

    shown_dialogs: list[str] = []
    monkeypatch.setattr(UpdateDialog, "exec", lambda self: shown_dialogs.append(self.update_info.version) or 0)

    win = MainWindow(config_service=cfg, update_service=upd_svc)
    try:
        thread = win.check_updates_on_startup()
        assert thread is not None
        thread.join(timeout=3.0)
        assert not thread.is_alive()
        QApplication.processEvents()
        assert shown_dialogs == ["v0.9.0"]
    finally:
        win.close()
        win.deleteLater()
        QApplication.processEvents()
