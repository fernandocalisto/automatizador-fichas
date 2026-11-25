# -*- coding: utf-8 -*-
"""Service for discovering built-in Jasper subreports, managing custom overrides, and materializing runtime dirs."""

from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import (
    BUILTIN_SUBREPORTS_DIR,
    get_custom_subreports_dir,
    get_data_dir,
)
from backend.app.db.schemas import SubreportInfo, SubreportSource

STANDARD_SUBREPORTS: tuple[str, ...] = (
    "cabecalho_retrato.jasper",
    "cabecalho_paisagem.jasper",
    "dados_paciente.jasper",
    "rodape_retrato.jasper",
)

_SAFE_JASPER_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.jasper$")


class SubreportError(Exception):
    """Base error for subreport management operations."""


class SubreportValidationError(SubreportError):
    """Raised when an uploaded subreport filename or payload is invalid."""


class SubreportNotFoundError(SubreportError):
    """Raised when a target custom subreport does not exist."""


def _sanitize_jasper_filename(filename: str) -> str:
    if not filename or not filename.strip():
        raise SubreportValidationError("Subreport filename cannot be empty.")

    raw = filename.strip()
    if "/" in raw or "\\" in raw or ".." in raw:
        raise SubreportValidationError(f"Invalid subreport filename '{filename}': path separators are not allowed.")

    clean = Path(raw).name
    if clean.lower().endswith(".jasper"):
        clean = clean[:-7] + ".jasper"
    else:
        raise SubreportValidationError(
            f"Invalid file extension for '{filename}': only compiled '.jasper' files are accepted."
        )

    if not _SAFE_JASPER_FILENAME_RE.match(clean):
        raise SubreportValidationError(
            f"Invalid subreport filename '{clean}': use only letters, digits, underscores, hyphens, and dots."
        )
    return clean


def _file_metadata(path: Path) -> tuple[int, str, str]:
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return len(data), sha256, mtime


class SubreportService:
    """Manages built-in and custom `.jasper` subreports and materializes `$P{caminho_relatorio}`."""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        custom_dir: Path | None = None,
        runtime_dir: Path | None = None,
    ) -> None:
        self._explicit_builtin_dir = builtin_dir.resolve() if builtin_dir is not None else None
        self._explicit_custom_dir = custom_dir.resolve() if custom_dir is not None else None
        self._explicit_runtime_dir = runtime_dir.resolve() if runtime_dir is not None else None

    @property
    def builtin_dir(self) -> Path:
        return self._explicit_builtin_dir if self._explicit_builtin_dir is not None else BUILTIN_SUBREPORTS_DIR

    @property
    def custom_dir(self) -> Path:
        if self._explicit_custom_dir is not None:
            self._explicit_custom_dir.mkdir(parents=True, exist_ok=True)
            return self._explicit_custom_dir
        return get_custom_subreports_dir()

    @property
    def default_runtime_dir(self) -> Path:
        if self._explicit_runtime_dir is not None:
            return self._explicit_runtime_dir
        return get_data_dir() / "runtime_subreports"

    def _discover_dir_map(self, directory: Path) -> dict[str, Path]:
        if not directory.exists():
            return {}
        found: dict[str, Path] = {}
        for p in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            if p.is_file() and p.suffix.lower() == ".jasper":
                canonical_name = p.stem + ".jasper"
                found[canonical_name] = p
        return found

    def count_builtin_subreports(self) -> int:
        """Return count of built-in `.jasper` files available in BUILTIN_SUBREPORTS_DIR."""
        return len(self._discover_dir_map(self.builtin_dir))

    def count_custom_subreports(self) -> int:
        """Return count of custom `.jasper` files uploaded to custom_subreports_dir."""
        return len(self._discover_dir_map(self.custom_dir))

    def list_subreports(self) -> list[SubreportInfo]:
        """List effective subreports (built-ins merged with custom overrides and custom extras)."""
        builtin_map = self._discover_dir_map(self.builtin_dir)
        custom_map = self._discover_dir_map(self.custom_dir)

        all_names = set(builtin_map.keys()) | set(custom_map.keys())
        standard_order = {name: idx for idx, name in enumerate(STANDARD_SUBREPORTS)}

        def _sort_key(filename: str) -> tuple[int, int, str]:
            if filename in standard_order:
                return (0, standard_order[filename], filename.lower())
            if filename in builtin_map:
                return (1, 0, filename.lower())
            return (2, 0, filename.lower())

        results: list[SubreportInfo] = []
        for filename in sorted(all_names, key=_sort_key):
            in_builtin = filename in builtin_map
            in_custom = filename in custom_map
            is_standard = filename in STANDARD_SUBREPORTS

            if in_custom and in_builtin:
                active_path = custom_map[filename]
                source: SubreportSource = "custom_override"
                is_overridden = True
            elif in_custom:
                active_path = custom_map[filename]
                source = "custom_extra"
                is_overridden = False
            else:
                active_path = builtin_map[filename]
                source = "builtin"
                is_overridden = False

            size_bytes, sha256, updated_at = _file_metadata(active_path)
            results.append(
                SubreportInfo(
                    filename=filename,
                    name=Path(filename).stem,
                    source=source,
                    is_builtin_standard=is_standard,
                    is_overridden=is_overridden,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    path=str(active_path),
                    updated_at=updated_at,
                )
            )
        return results

    def get_subreport(self, filename: str) -> SubreportInfo:
        """Return metadata for a single effective subreport by filename."""
        clean = _sanitize_jasper_filename(filename)
        for info in self.list_subreports():
            if info.filename == clean:
                return info
        raise SubreportNotFoundError(f"Subreport '{clean}' not found.")

    def save_custom_subreport(self, filename: str, content: bytes) -> SubreportInfo:
        """Save an uploaded `.jasper` file into custom_subreports_dir (override or extra)."""
        clean = _sanitize_jasper_filename(filename)
        if not content:
            raise SubreportValidationError(f"Uploaded subreport '{clean}' is empty.")

        dest = self.custom_dir / clean
        dest.write_bytes(content)

        if self.default_runtime_dir.exists():
            self.materialize_runtime_dir()

        return self.get_subreport(clean)

    def delete_custom_subreport(self, filename: str) -> dict[str, Any]:
        """Remove a custom subreport (resetting back to built-in if overriding one of the standard ones)."""
        clean = _sanitize_jasper_filename(filename)
        custom_target = self.custom_dir / clean
        if not custom_target.exists():
            raise SubreportNotFoundError(
                f"Custom subreport '{clean}' does not exist (cannot delete or reset)."
            )

        custom_target.unlink()
        builtin_exists = (self.builtin_dir / clean).exists()

        if self.default_runtime_dir.exists():
            self.materialize_runtime_dir()

        active = self.get_subreport(clean) if builtin_exists else None
        return {
            "deleted": clean,
            "reset_to_builtin": builtin_exists,
            "active": active.model_dump() if active is not None else None,
        }

    def materialize_runtime_dir(self, target_dir: Path | None = None) -> Path:
        """
        Materialize a merged directory containing all built-in `.jasper` files overlaid
        with any user-uploaded custom `.jasper` files, ready for `$P{caminho_relatorio}`.
        """
        out_dir = (target_dir.resolve() if target_dir is not None else self.default_runtime_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        builtin_map = self._discover_dir_map(self.builtin_dir)
        custom_map = self._discover_dir_map(self.custom_dir)

        effective_map: dict[str, Path] = {**builtin_map, **custom_map}

        # Remove stale .jasper files no longer present in either builtin or custom
        for existing in list(out_dir.iterdir()):
            if existing.is_file() and existing.suffix.lower() == ".jasper":
                canonical = existing.stem + ".jasper"
                if canonical not in effective_map:
                    existing.unlink()

        for filename, src_path in effective_map.items():
            dst_path = out_dir / filename
            if src_path.resolve() != dst_path.resolve():
                shutil.copy2(src_path, dst_path)

        return out_dir

    def get_caminho_relatorio(self, target_dir: Path | None = None) -> str:
        """
        Materialize the runtime subreports directory and return its POSIX path string
        guaranteed to end with a trailing slash `/` for JasperReports `$P{caminho_relatorio}`.
        """
        runtime_path = self.materialize_runtime_dir(target_dir=target_dir)
        return runtime_path.resolve().as_posix().rstrip("/") + "/"
