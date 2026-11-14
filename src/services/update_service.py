# -*- coding: utf-8 -*-
"""
Serviço de Auto-Atualização via GitHub Releases (src/services/update_service.py).

Implementa `spec_08_updater`:
- Consulta `https://api.github.com/repos/fernandocalisto/automatizador-fichas/releases/latest`
- Comparação semântica de versões (`parse_semver`, `is_newer_version`)
- Controle de intervalo de 24h (`should_auto_check`) e versão ignorada
- Download com progresso (`download_update`)
- Script `.bat` + `QProcess.startDetached` para substituição segura no Windows (`install_update`)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QObject, QProcess, Signal

if TYPE_CHECKING:
    from src.services.config_service import ConfigService

logger = logging.getLogger("services.update_service")

GITHUB_RELEASES_API_URL = (
    "https://api.github.com/repos/fernandocalisto/automatizador-fichas/releases/latest"
)
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_SEMVER_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass
class UpdateInfo:
    """Metadados de uma nova versão disponível no GitHub Releases."""

    version: str
    release_url: str
    release_notes: str
    asset_url: str
    published_at: str
    asset_name: str = ""


def parse_semver(version: str) -> tuple[int, int, int]:
    """Converte uma string de versão (ex.: 'v0.3.1') em tupla `(major, minor, patch)`."""
    cleaned = str(version or "").strip().lstrip("vV")
    match = _SEMVER_RE.search(cleaned)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def is_newer_version(current_version: str, latest_version: str) -> bool:
    """Retorna `True` se `latest_version` for estritamente maior que `current_version`."""
    return parse_semver(latest_version) > parse_semver(current_version)


class UpdateService(QObject):
    """Gerencia verificação, download e instalação de atualizações do aplicativo."""

    update_available = Signal(object)
    no_update_available = Signal(str)
    check_failed = Signal(str)
    download_progress = Signal(int, int)

    def __init__(
        self,
        config_service: ConfigService | None = None,
        api_url: str = GITHUB_RELEASES_API_URL,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_service = config_service
        self.api_url = api_url
        self._fetcher = fetcher

    def should_auto_check(self, now: datetime | None = None) -> bool:
        """Verifica se o auto-check está ativo e se já se passaram 24h desde o último check."""
        if self._config_service is None:
            return True
        cfg = self._config_service.config
        if not bool(getattr(cfg, "auto_check_updates", True)):
            return False

        last_raw = str(getattr(cfg, "last_update_check", "") or "").strip()
        if not last_raw:
            return True

        try:
            last_dt = datetime.fromisoformat(last_raw)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return True

        ref_now = now or datetime.now(timezone.utc)
        if ref_now.tzinfo is None:
            ref_now = ref_now.replace(tzinfo=timezone.utc)

        elapsed = (ref_now - last_dt).total_seconds()
        return elapsed >= CHECK_INTERVAL_SECONDS

    def _fetch_latest_release(self) -> dict[str, Any]:
        if self._fetcher is not None:
            return self._fetcher(self.api_url)

        req = urllib.request.Request(
            self.api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "AutomatizadorFichas-Updater",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Resposta inválida da API de Releases.")
            return parsed

    def _record_check_timestamp(self) -> None:
        if self._config_service is None:
            return
        iso_now = datetime.now(timezone.utc).isoformat()
        try:
            self._config_service.set("last_update_check", iso_now)
        except Exception as exc:
            logger.warning("Não foi possível salvar timestamp de verificação: %s", exc)

    def check_for_updates(
        self, current_version: str = "v0.2.0", force: bool = False
    ) -> UpdateInfo | None:
        """Consulta o GitHub Releases e retorna `UpdateInfo` caso haja versão mais recente."""
        payload = self._fetch_latest_release()
        self._record_check_timestamp()

        tag_name = str(payload.get("tag_name") or "").strip()
        if not tag_name or not is_newer_version(current_version, tag_name):
            return None

        if not force and self._config_service is not None:
            ignored = str(
                getattr(self._config_service.config, "ignored_update_version", "") or ""
            ).strip()
            if ignored and ignored == tag_name:
                return None

        asset_url = ""
        asset_name = ""
        assets = payload.get("assets", [])
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name") or "")
                dl_url = str(asset.get("browser_download_url") or "")
                if name.lower().endswith(".exe") and dl_url:
                    asset_url = dl_url
                    asset_name = name
                    break
            if not asset_url and assets and isinstance(assets[0], dict):
                asset_url = str(assets[0].get("browser_download_url") or "")
                asset_name = str(assets[0].get("name") or "")

        return UpdateInfo(
            version=tag_name,
            release_url=str(payload.get("html_url") or ""),
            release_notes=str(payload.get("body") or ""),
            asset_url=asset_url,
            published_at=str(payload.get("published_at") or ""),
            asset_name=asset_name,
        )

    def check_for_updates_async(
        self, current_version: str = "v0.2.0", force: bool = False
    ) -> threading.Thread:
        """Executa `check_for_updates` em thread daemon sem bloquear a interface."""

        def _worker() -> None:
            try:
                info = self.check_for_updates(current_version=current_version, force=force)
                if info is not None:
                    self.update_available.emit(info)
                else:
                    self.no_update_available.emit(current_version)
            except Exception as exc:
                logger.warning("Falha ao verificar atualizações: %s", exc)
                self.check_failed.emit(str(exc))

        thread = threading.Thread(target=_worker, name="UpdateCheckThread", daemon=True)
        thread.start()
        return thread

    def download_update(
        self,
        asset_url: str,
        progress_callback: Callable[[int, int], None] | None = None,
        dest_dir: Path | None = None,
        version: str = "latest",
    ) -> Path:
        """Baixa o instalador/executável da release para pasta temporária."""
        if not asset_url:
            raise ValueError("URL do asset de atualização não informada.")

        target_dir = dest_dir or Path(tempfile.gettempdir())
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_version = re.sub(r"[^A-Za-z0-9._-]", "_", version or "latest")
        dest_path = target_dir / f"AutomatizadorFichas_{safe_version}.exe"

        req = urllib.request.Request(
            asset_url,
            headers={"User-Agent": "AutomatizadorFichas-Updater"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_header = resp.headers.get("Content-Length") if resp.headers else None
            total_bytes = int(total_header) if total_header and str(total_header).isdigit() else 0
            downloaded = 0
            with dest_path.open("wb") as fp:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fp.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total_bytes)
                    self.download_progress.emit(downloaded, total_bytes)

        return dest_path

    def create_windows_update_batch(
        self,
        new_exe_path: Path,
        target_exe_path: Path,
        restart: bool = True,
    ) -> Path:
        """Gera script `.bat` para substituir o `.exe` em uso no Windows e reiniciar."""
        bat_path = new_exe_path.parent / "update_automatizador.bat"
        bak_path = target_exe_path.with_suffix(target_exe_path.suffix + ".bak")

        lines = [
            "@echo off",
            "setlocal",
            "ping -n 3 127.0.0.1 > nul",
            f'if exist "{bak_path}" del /f /q "{bak_path}"',
            f'if exist "{target_exe_path}" move /y "{target_exe_path}" "{bak_path}"',
            f'move /y "{new_exe_path}" "{target_exe_path}"',
            f'if exist "{bak_path}" del /f /q "{bak_path}"',
        ]
        if restart:
            lines.append(f'start "" "{target_exe_path}"')
        lines.append('del /f /q "%~f0"')

        bat_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return bat_path

    def install_update(
        self,
        new_exe_path: Path,
        target_exe_path: Path | None = None,
        launch_detached: bool = True,
    ) -> bool:
        """Agenda a substituição do executável atual via processo desanexado."""
        if not new_exe_path.exists():
            raise FileNotFoundError(f"Arquivo de atualização não encontrado: {new_exe_path}")

        target = target_exe_path or Path(sys.executable)
        bat_path = self.create_windows_update_batch(new_exe_path, target, restart=True)
        if launch_detached:
            started = QProcess.startDetached("cmd.exe", ["/c", str(bat_path)])
            return bool(started[0] if isinstance(started, tuple) else started)
        return True


__all__ = [
    "CHECK_INTERVAL_SECONDS",
    "GITHUB_RELEASES_API_URL",
    "UpdateInfo",
    "UpdateService",
    "is_newer_version",
    "parse_semver",
]
