# -*- coding: utf-8 -*-
"""Unit and FastAPI integration tests for SSH/SFTP connector (`sftp_service.py` & `api/sftp.py`)."""

from __future__ import annotations

import io
import posixpath
import re
import stat as stat_module
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from backend.app.api.sftp import router as sftp_router
from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services import secret_vault as secret_vault_mod
from backend.app.services.default_credentials_service import (
    DefaultCredentialUpdate,
    DefaultCredentialsService,
)
from backend.app.services.jasper_daemon import JasperDaemonError
from backend.app.services.secret_vault import SecretVaultService
from backend.app.services.sftp_service import (
    ReadOnlySftpProfileError,
    SftpDeployTokenError,
    SftpProfileCreate,
    SftpProfileUpdate,
    SftpService,
    SftpValidationError,
    resolve_safe_remote_path,
)
from backend.app.services.workspace_service import WorkspaceService

SAMPLE_JRXML_V1 = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="ficha_evolucao">
    <detail>
        <band height="40">
            <subreport>
                <subreportExpression><![CDATA[$P{SUBREPORT_DIR} + "cabecalho_retrato.jasper"]]></subreportExpression>
            </subreport>
        </band>
    </detail>
</jasperReport>
"""

SAMPLE_JRXML_V2 = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="ficha_evolucao">
    <detail>
        <band height="60">
            <subreport>
                <subreportExpression><![CDATA[$P{SUBREPORT_DIR} + "cabecalho_retrato.jasper"]]></subreportExpression>
            </subreport>
        </band>
    </detail>
</jasperReport>
"""


# =============================================================================
# In-Memory Fake SFTP & Fake Jasper Daemon
# =============================================================================


@dataclass
class _FakeStat:
    filename: str
    st_mode: int
    st_size: int
    st_mtime: float


class _FakeRemoteFileHandle:
    def __init__(self, fs: dict[str, bytes], path: str, mode: str) -> None:
        self._fs = fs
        self._path = path
        self._mode = mode
        if "r" in mode:
            if path not in fs:
                raise FileNotFoundError(path)
            self._buf = io.BytesIO(fs[path])
        else:
            self._buf = io.BytesIO()

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def write(self, data: bytes | str) -> int:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        return self._buf.write(raw)

    def close(self) -> None:
        if "w" in self._mode:
            self._fs[self._path] = self._buf.getvalue()

    def __enter__(self) -> _FakeRemoteFileHandle:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


class FakeSftpClient:
    """In-memory POSIX SFTP client recording rename/atomic operations for assertions."""

    def __init__(
        self,
        *,
        dirs: set[str] | None = None,
        files: dict[str, bytes] | None = None,
        supports_posix_rename: bool = True,
    ) -> None:
        self.dirs: set[str] = set(dirs or {"/", "/opt/salutem/relatorios"})
        self.files: dict[str, bytes] = dict(files or {})
        self.supports_posix_rename = supports_posix_rename
        self.rename_log: list[tuple[str, str, str]] = []
        self.closed = False
        self._mtime = time.time()

    def stat(self, path: str) -> _FakeStat:
        norm = posixpath.normpath(path)
        if norm in self.dirs:
            return _FakeStat(
                filename=posixpath.basename(norm) or "/",
                st_mode=stat_module.S_IFDIR | 0o755,
                st_size=4096,
                st_mtime=self._mtime,
            )
        if norm in self.files:
            return _FakeStat(
                filename=posixpath.basename(norm),
                st_mode=stat_module.S_IFREG | 0o644,
                st_size=len(self.files[norm]),
                st_mtime=self._mtime,
            )
        raise FileNotFoundError(norm)

    def listdir_attr(self, path: str) -> list[_FakeStat]:
        norm = posixpath.normpath(path)
        if norm not in self.dirs:
            raise FileNotFoundError(norm)
        results: list[_FakeStat] = []
        seen: set[str] = set()
        for d in sorted(self.dirs):
            if d == norm:
                continue
            if posixpath.dirname(d) == norm:
                name = posixpath.basename(d)
                if name and name not in seen:
                    seen.add(name)
                    results.append(
                        _FakeStat(
                            filename=name,
                            st_mode=stat_module.S_IFDIR | 0o755,
                            st_size=4096,
                            st_mtime=self._mtime,
                        )
                    )
        for fpath, content in sorted(self.files.items()):
            if posixpath.dirname(fpath) == norm:
                name = posixpath.basename(fpath)
                if name and name not in seen:
                    seen.add(name)
                    results.append(
                        _FakeStat(
                            filename=name,
                            st_mode=stat_module.S_IFREG | 0o644,
                            st_size=len(content),
                            st_mtime=self._mtime,
                        )
                    )
        return results

    def open(self, path: str, mode: str = "rb") -> _FakeRemoteFileHandle:
        norm = posixpath.normpath(path)
        return _FakeRemoteFileHandle(self.files, norm, mode)

    def posix_rename(self, oldpath: str, newpath: str) -> None:
        if not self.supports_posix_rename:
            raise OSError("posix_rename not supported")
        old_n = posixpath.normpath(oldpath)
        new_n = posixpath.normpath(newpath)
        if old_n not in self.files:
            raise FileNotFoundError(old_n)
        self.files[new_n] = self.files.pop(old_n)
        self.rename_log.append(("posix_rename", old_n, new_n))

    def rename(self, oldpath: str, newpath: str) -> None:
        old_n = posixpath.normpath(oldpath)
        new_n = posixpath.normpath(newpath)
        if old_n not in self.files:
            raise FileNotFoundError(old_n)
        self.files[new_n] = self.files.pop(old_n)
        self.rename_log.append(("rename", old_n, new_n))

    def remove(self, path: str) -> None:
        norm = posixpath.normpath(path)
        self.files.pop(norm, None)

    def close(self) -> None:
        self.closed = True


class FakeJasperDaemon:
    """Controllable JVM daemon fake for compile and decompile tests."""

    def __init__(
        self,
        *,
        compile_should_fail: bool = False,
        decompile_output_xml: str = SAMPLE_JRXML_V1,
    ) -> None:
        self.compile_should_fail = compile_should_fail
        self.decompile_output_xml = decompile_output_xml
        self.compile_calls: list[tuple[Path, Path | None]] = []
        self.decompile_calls: list[tuple[Path, Path | None]] = []

    def compile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path else in_p.with_suffix(".jasper")
        self.compile_calls.append((in_p, out_p))
        if self.compile_should_fail:
            raise JasperDaemonError(
                "Erro de sintaxe na expressão JRXML linha 12",
                error_type="COMPILE_ERROR",
            )
        out_p.write_bytes(b"FAKE_JASPER_BINARY::" + in_p.read_bytes()[:32])
        return {"status": "SUCCESS", "output": str(out_p)}

    def decompile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        in_p = Path(input_path)
        out_p = Path(output_path) if output_path else in_p.with_suffix(".jrxml")
        self.decompile_calls.append((in_p, out_p))
        out_p.write_text(self.decompile_output_xml, encoding="utf-8")
        return {"status": "SUCCESS", "output": str(out_p)}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build isolated SQLiteStore, AES-256-GCM fallback SecretVault (no OS keyring), WorkspaceService, and SftpService."""

    def _fail_keyring(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyringError("headless test keyring disabled")

    monkeypatch.setattr(secret_vault_mod.keyring, "set_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_mod.keyring, "get_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_mod.keyring, "delete_password", _fail_keyring)
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-only-sftp-vault-key-9876543210")

    store = SQLiteStore(tmp_path / "studio.db")
    vault = SecretVaultService(vault_path=tmp_path / ".vault.json")
    default_creds = DefaultCredentialsService(store=store, vault=vault)
    workspace = WorkspaceService(store=store, data_dir=tmp_path / "workspaces")

    fake_fs = FakeSftpClient(
        dirs={
            "/",
            "/opt",
            "/opt/salutem",
            "/opt/salutem/relatorios",
            "/opt/salutem/relatorios/fichas",
        },
        files={
            "/opt/salutem/relatorios/ficha_evolucao.jrxml": SAMPLE_JRXML_V1.encode("utf-8"),
            "/opt/salutem/relatorios/ficha_evolucao.jasper": b"COMPILED_EVOLUCAO_BYTES",
            "/opt/salutem/relatorios/somente_compilada.jasper": b"COMPILED_ONLY_BYTES",
            "/opt/salutem/relatorios/cabecalho_retrato.jasper": b"SUBREPORT_HEADER_BYTES",
            "/opt/salutem/relatorios/readme.txt": b"ignore me",
            "/etc/passwd": b"root:x:0:0",
        },
    )
    captured_connections: list[dict[str, Any]] = []

    def _client_factory(**kwargs: Any) -> FakeSftpClient:
        captured_connections.append(dict(kwargs))
        fake_fs.closed = False
        return fake_fs

    sftp_service = SftpService(
        store=store,
        client_factory=_client_factory,
        vault=vault,
        default_credentials_service=default_creds,
    )
    daemon = FakeJasperDaemon()

    app = FastAPI()
    app.state.store = store
    app.state.sftp_service = sftp_service
    app.state.workspace_service = workspace
    app.state.jasper_daemon = daemon
    app.include_router(sftp_router)
    client = TestClient(app)

    return {
        "tmp_path": tmp_path,
        "store": store,
        "vault": vault,
        "default_creds": default_creds,
        "workspace": workspace,
        "sftp": sftp_service,
        "fake_fs": fake_fs,
        "captured_connections": captured_connections,
        "daemon": daemon,
        "client": client,
    }


# =============================================================================
# Tests: Profile CRUD, SecretVault Redaction & Default vs Custom Credentials
# =============================================================================


def test_profile_crud_vault_isolation_and_prd_read_only_default(
    isolated_env: dict[str, Any],
) -> None:
    sftp: SftpService = isolated_env["sftp"]
    store: SQLiteStore = isolated_env["store"]
    vault: SecretVaultService = isolated_env["vault"]

    # PRD defaults read_only=True when not explicitly overridden
    prd = sftp.create_profile(
        SftpProfileCreate(
            name="Unidade PRD",
            host="10.0.0.10",
            port=2222,
            username="deploy_ro",
            auth_type="password",
            credential_mode="custom",
            password="super-secret-prd-pass",
            remote_base_dir="/opt/salutem/relatorios/",
            environment="PRD",
        )
    )
    assert prd.read_only is True
    assert prd.has_secret is True
    assert prd.remote_base_dir == "/opt/salutem/relatorios"
    assert "password" not in prd.model_dump()
    assert vault.get_secret(f"sftp_password:{prd.id}") == "super-secret-prd-pass"

    # Verify secret is NEVER persisted inside SQLite
    with store.connection() as conn:
        raw_row = dict(
            conn.execute("SELECT * FROM sftp_profiles WHERE id = ?", (prd.id,)).fetchone()
        )
    assert "super-secret-prd-pass" not in str(raw_row)

    # HML defaults read_only=False when not explicitly overridden
    hml = sftp.create_profile(
        SftpProfileCreate(
            name="Unidade HML",
            host="10.0.0.20",
            username="salutem_hml",
            auth_type="private_key",
            private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE\n-----END OPENSSH PRIVATE KEY-----",
            passphrase="key-passphrase",
            environment="HML",
        )
    )
    assert hml.read_only is False
    assert hml.has_secret is True
    assert vault.get_secret(f"sftp_key:{hml.id}") is not None
    assert vault.get_secret(f"sftp_passphrase:{hml.id}") == "key-passphrase"

    # Update rotates secret and clears when empty string passed
    updated = sftp.update_profile(
        prd.id,
        SftpProfileUpdate(name="Unidade PRD Atualizada", password="", read_only=False),
    )
    assert updated.name == "Unidade PRD Atualizada"
    assert updated.read_only is False
    assert updated.has_secret is False
    assert vault.get_secret(f"sftp_password:{prd.id}") is None

    # List & Delete purges secrets
    assert len(sftp.list_profiles()) == 2
    assert sftp.delete_profile(hml.id) is True
    assert vault.get_secret(f"sftp_key:{hml.id}") is None
    assert vault.get_secret(f"sftp_passphrase:{hml.id}") is None
    assert len(sftp.list_profiles()) == 1


def test_default_vs_custom_credential_resolution(isolated_env: dict[str, Any]) -> None:
    sftp: SftpService = isolated_env["sftp"]
    default_creds: DefaultCredentialsService = isolated_env["default_creds"]
    captured: list[dict[str, Any]] = isolated_env["captured_connections"]

    default_creds.update_default(
        "sftp",
        DefaultCredentialUpdate(
            username="corp_default_ssh",
            auth_type="password",
            default_remote_base_dir="/opt/salutem/relatorios",
            password="default-sftp-password",
        ),
    )

    profile = sftp.create_profile(
        SftpProfileCreate(
            name="Servidor Padrão",
            host="10.0.1.50",
            credential_mode="default",
            remote_base_dir="/",
            environment="HML",
        )
    )
    assert profile.has_secret is True

    test_res = sftp.test_connection(profile.id)
    assert test_res.ok is True
    assert test_res.remote_base_dir == "/opt/salutem/relatorios"
    assert test_res.item_count >= 4
    assert captured[-1]["username"] == "corp_default_ssh"
    assert captured[-1]["password"] == "default-sftp-password"
    assert captured[-1]["timeout"] == 15
    assert captured[-1]["banner_timeout"] == 15


# =============================================================================
# Tests: Browse & Path Traversal Protection
# =============================================================================


def test_browse_directory_pairing_search_and_path_traversal_block(
    isolated_env: dict[str, Any],
) -> None:
    sftp: SftpService = isolated_env["sftp"]
    profile = sftp.create_profile(
        SftpProfileCreate(
            name="Browse HML",
            host="10.0.0.30",
            username="dev",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="HML",
        )
    )

    listing = sftp.list_directory(profile.id)
    assert listing.current_path == "/opt/salutem/relatorios"
    assert listing.parent_path is None
    # Folders come first
    assert listing.entries[0].is_dir is True
    assert listing.entries[0].name == "fichas"
    assert listing.entries[0].kind == "dir"

    by_name = {e.name: e for e in listing.entries}
    assert by_name["ficha_evolucao.jrxml"].kind == "jrxml"
    assert by_name["ficha_evolucao.jrxml"].has_paired_file is True
    assert by_name["ficha_evolucao.jasper"].kind == "jasper"
    assert by_name["ficha_evolucao.jasper"].has_paired_file is True
    assert by_name["somente_compilada.jasper"].kind == "jasper"
    assert by_name["somente_compilada.jasper"].has_paired_file is False
    assert by_name["readme.txt"].kind == "other"

    # Search preserves pairing metadata
    filtered = sftp.list_directory(profile.id, search="evolucao")
    assert {e.name for e in filtered.entries} == {
        "ficha_evolucao.jrxml",
        "ficha_evolucao.jasper",
    }
    assert all(e.has_paired_file for e in filtered.entries)

    # Subfolder parent_path stays bounded
    sub_listing = sftp.list_directory(profile.id, remote_path="/opt/salutem/relatorios/fichas")
    assert sub_listing.parent_path == "/opt/salutem/relatorios"

    # Path traversal attempts MUST be blocked
    with pytest.raises(SftpValidationError):
        sftp.list_directory(profile.id, remote_path="/opt/salutem/relatorios/../../../etc")
    with pytest.raises(SftpValidationError):
        sftp.list_directory(profile.id, remote_path="/etc")
    with pytest.raises(SftpValidationError):
        resolve_safe_remote_path("/opt/salutem/relatorios", "../outside")


# =============================================================================
# Tests: Import (.jrxml + subreports, and .jasper with automatic decompile)
# =============================================================================


def test_import_jrxml_and_jasper_with_auto_decompile_and_subreports(
    isolated_env: dict[str, Any],
) -> None:
    sftp: SftpService = isolated_env["sftp"]
    workspace: WorkspaceService = isolated_env["workspace"]
    daemon: FakeJasperDaemon = isolated_env["daemon"]

    profile = sftp.create_profile(
        SftpProfileCreate(
            name="Import HML",
            host="10.0.0.40",
            username="dev",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="HML",
            linked_db_profile_id="pg-linked-1",
        )
    )

    # 1. Import .jrxml + sync referenced subreports
    proj_jrxml = sftp.import_report_to_project(
        profile.id,
        "/opt/salutem/relatorios/ficha_evolucao.jrxml",
        workspace,
        daemon,
        sync_subreports=True,
    )
    assert proj_jrxml.project_kind == "free_report"
    assert proj_jrxml.entry_mode == "sftp_import"
    assert proj_jrxml.default_db_profile_id == "pg-linked-1"
    assert proj_jrxml.source_origin["provider"] == "sftp"
    assert proj_jrxml.source_origin["profile_id"] == profile.id
    assert proj_jrxml.source_origin["remote_dir"] == "/opt/salutem/relatorios"
    assert proj_jrxml.source_origin["base_filename"] == "ficha_evolucao"
    assert proj_jrxml.source_origin["decompiled"] is False
    assert proj_jrxml.source_origin["synced_subreports"] == ["cabecalho_retrato.jasper"]
    sub_file = Path(proj_jrxml.workspace_dir) / "subreports" / "cabecalho_retrato.jasper"
    assert sub_file.is_file()
    assert sub_file.read_bytes() == b"SUBREPORT_HEADER_BYTES"
    assert len(daemon.decompile_calls) == 0

    # 2. Import .jasper -> automatically calls jasper_daemon.decompile()
    proj_jasper = sftp.import_report_to_project(
        profile.id,
        "/opt/salutem/relatorios/somente_compilada.jasper",
        workspace,
        daemon,
        project_name="Ficha Decompilada",
    )
    assert proj_jasper.name == "Ficha Decompilada"
    assert proj_jasper.project_kind == "free_report"
    assert proj_jasper.entry_mode == "sftp_import"
    assert proj_jasper.source_origin["decompiled"] is True
    assert len(daemon.decompile_calls) == 1
    latest = workspace.get_latest_artifact(proj_jasper.id, "jrxml")
    assert "<jasperReport" in latest.content


# =============================================================================
# Tests: 2-Step Safe Deploy (Read-Only 403, Compile Gate, Single-Use Token, Backups, Modes)
# =============================================================================


def test_deploy_blocks_read_only_and_failed_compile(isolated_env: dict[str, Any]) -> None:
    sftp: SftpService = isolated_env["sftp"]
    workspace: WorkspaceService = isolated_env["workspace"]
    daemon: FakeJasperDaemon = isolated_env["daemon"]

    project = workspace.create_project(
        ProjectCreate(
            name="Ficha Deploy Guard",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_JRXML_V2,
        )
    )

    prd_ro = sftp.create_profile(
        SftpProfileCreate(
            name="PRD Protegido",
            host="10.0.0.99",
            username="ops",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="PRD",
        )
    )
    assert prd_ro.read_only is True

    with pytest.raises(ReadOnlySftpProfileError):
        sftp.prepare_deploy_preview(
            project.id,
            prd_ro.id,
            "/opt/salutem/relatorios",
            "ficha_evolucao",
            workspace,
            daemon,
        )

    # Writable HML profile with failing JVM compile -> blocked before issuing deploy_token
    hml = sftp.create_profile(
        SftpProfileCreate(
            name="HML Gravável",
            host="10.0.0.55",
            username="ops",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="HML",
            read_only=False,
        )
    )
    daemon.compile_should_fail = True
    with pytest.raises(SftpValidationError, match="Compilação JRXML falhou"):
        sftp.prepare_deploy_preview(
            project.id,
            hml.id,
            "/opt/salutem/relatorios",
            "ficha_evolucao",
            workspace,
            daemon,
        )


def test_deploy_jrxml_only_both_jasper_only_backups_and_single_use_token(
    isolated_env: dict[str, Any],
) -> None:
    sftp: SftpService = isolated_env["sftp"]
    workspace: WorkspaceService = isolated_env["workspace"]
    daemon: FakeJasperDaemon = isolated_env["daemon"]
    fake_fs: FakeSftpClient = isolated_env["fake_fs"]

    project = workspace.create_project(
        ProjectCreate(
            name="Ficha Evolução Editada",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_JRXML_V2,
        )
    )
    hml = sftp.create_profile(
        SftpProfileCreate(
            name="HML Deploy",
            host="10.0.0.60",
            username="ops",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="HML",
            read_only=False,
        )
    )

    # 1. Default mode MUST be jrxml_only
    preview = sftp.prepare_deploy_preview(
        project.id,
        hml.id,
        "/opt/salutem/relatorios",
        "ficha_evolucao",
        workspace,
        daemon,
    )
    assert preview.publish_mode == "jrxml_only"
    assert preview.target_files == ["/opt/salutem/relatorios/ficha_evolucao.jrxml"]
    assert preview.remote_exists is True
    assert preview.compiled_ok is True
    assert preview.remote_sha256 is not None
    assert preview.local_sha256 != preview.remote_sha256
    assert '-        <band height="40">' in preview.unified_diff
    assert '+        <band height="60">' in preview.unified_diff

    result = sftp.execute_deploy(project.id, preview.deploy_token, workspace, daemon)
    assert result.ok is True
    assert result.published_files == ["/opt/salutem/relatorios/ficha_evolucao.jrxml"]
    assert len(result.backup_files) == 1
    assert re.match(
        r"^/opt/salutem/relatorios/ficha_evolucao\.jrxml\.bak\.\d{8}_\d{6}$",
        result.backup_files[0],
    )
    # Remote backup contains original V1 content, live file contains V2 content
    assert fake_fs.files[result.backup_files[0]] == SAMPLE_JRXML_V1.encode("utf-8")
    assert fake_fs.files["/opt/salutem/relatorios/ficha_evolucao.jrxml"].decode("utf-8").strip() == SAMPLE_JRXML_V2.strip()
    # Local backup created inside project workspace
    assert result.local_backup_path is not None
    assert Path(result.local_backup_path).is_file()
    assert Path(result.local_backup_path).read_bytes() == SAMPLE_JRXML_V1.encode("utf-8")
    # Atomic posix_rename used from .studio_tmp
    assert any(
        op == "posix_rename" and src.endswith(".studio_tmp")
        for op, src, _ in fake_fs.rename_log
    )

    # Single-use token CANNOT be replayed
    with pytest.raises(SftpDeployTokenError, match="já foi utilizado"):
        sftp.execute_deploy(project.id, preview.deploy_token, workspace, daemon)

    # 2. Mode "both" publishes .jrxml AND .jasper and backs up both existing files
    preview_both = sftp.prepare_deploy_preview(
        project.id,
        hml.id,
        "/opt/salutem/relatorios",
        "ficha_evolucao",
        workspace,
        daemon,
        publish_mode="both",
    )
    assert preview_both.target_files == [
        "/opt/salutem/relatorios/ficha_evolucao.jrxml",
        "/opt/salutem/relatorios/ficha_evolucao.jasper",
    ]
    res_both = sftp.execute_deploy(project.id, preview_both.deploy_token, workspace, daemon)
    assert res_both.published_files == [
        "/opt/salutem/relatorios/ficha_evolucao.jrxml",
        "/opt/salutem/relatorios/ficha_evolucao.jasper",
    ]
    assert len(res_both.backup_files) == 2
    assert fake_fs.files["/opt/salutem/relatorios/ficha_evolucao.jasper"].startswith(
        b"FAKE_JASPER_BINARY::"
    )

    # 3. Mode "jasper_only" publishes only .jasper (using rename fallback when posix_rename unavailable)
    fake_fs.supports_posix_rename = False
    preview_jasper = sftp.prepare_deploy_preview(
        project.id,
        hml.id,
        "/opt/salutem/relatorios",
        "nova_ficha",
        workspace,
        daemon,
        publish_mode="jasper_only",
    )
    assert preview_jasper.remote_exists is False
    assert preview_jasper.target_files == ["/opt/salutem/relatorios/nova_ficha.jasper"]
    res_jasper = sftp.execute_deploy(project.id, preview_jasper.deploy_token, workspace, daemon)
    assert res_jasper.published_files == ["/opt/salutem/relatorios/nova_ficha.jasper"]
    assert res_jasper.backup_files == []
    assert "/opt/salutem/relatorios/nova_ficha.jasper" in fake_fs.files
    assert any(op == "rename" for op, _, _ in fake_fs.rename_log)


def test_execute_deploy_rechecks_read_only_and_jrxml_mutation(
    isolated_env: dict[str, Any],
) -> None:
    sftp: SftpService = isolated_env["sftp"]
    workspace: WorkspaceService = isolated_env["workspace"]
    daemon: FakeJasperDaemon = isolated_env["daemon"]

    project = workspace.create_project(
        ProjectCreate(
            name="Ficha Mutada",
            project_kind="free_report",
            entry_mode="jrxml",
            initial_jrxml=SAMPLE_JRXML_V1,
        )
    )
    hml = sftp.create_profile(
        SftpProfileCreate(
            name="HML Mutação",
            host="10.0.0.61",
            username="ops",
            password="pw",
            remote_base_dir="/opt/salutem/relatorios",
            environment="HML",
            read_only=False,
        )
    )

    preview = sftp.prepare_deploy_preview(
        project.id,
        hml.id,
        "/opt/salutem/relatorios",
        "ficha_evolucao",
        workspace,
        daemon,
    )

    # Mutate JRXML after prepare -> token must fail validation
    workspace.save_artifact(project.id, "jrxml", SAMPLE_JRXML_V2)
    with pytest.raises(SftpDeployTokenError, match="alterado"):
        sftp.execute_deploy(project.id, preview.deploy_token, workspace, daemon)

    # New prepare, then flip profile to read_only -> execute must raise ReadOnlySftpProfileError
    preview2 = sftp.prepare_deploy_preview(
        project.id,
        hml.id,
        "/opt/salutem/relatorios",
        "ficha_evolucao",
        workspace,
        daemon,
    )
    sftp.update_profile(hml.id, SftpProfileUpdate(read_only=True))
    with pytest.raises(ReadOnlySftpProfileError):
        sftp.execute_deploy(project.id, preview2.deploy_token, workspace, daemon)


# =============================================================================
# Tests: FastAPI Router Integration (`/api/sftp/*` & `/api/projects/*/deploy/sftp/*`)
# =============================================================================


def test_fastapi_sftp_endpoints_end_to_end(isolated_env: dict[str, Any]) -> None:
    client: TestClient = isolated_env["client"]

    # Create PRD profile (defaults read_only=True)
    create_prd = client.post(
        "/api/sftp/profiles",
        json={
            "name": "PRD HTTP",
            "host": "10.1.0.10",
            "port": 22,
            "username": "ro_user",
            "password": "secret-password",
            "remote_base_dir": "/opt/salutem/relatorios",
            "environment": "PRD",
        },
    )
    assert create_prd.status_code == 201
    prd_body = create_prd.json()
    assert prd_body["read_only"] is True
    assert prd_body["has_secret"] is True
    assert "password" not in prd_body

    # Create HML writable profile
    create_hml = client.post(
        "/api/sftp/profiles",
        json={
            "name": "HML HTTP",
            "host": "10.1.0.20",
            "username": "rw_user",
            "password": "rw-password",
            "remote_base_dir": "/opt/salutem/relatorios",
            "environment": "HML",
            "read_only": False,
        },
    )
    assert create_hml.status_code == 201
    hml_id = create_hml.json()["id"]

    # List & Get & PATCH
    assert len(client.get("/api/sftp/profiles").json()) == 2
    assert client.get(f"/api/sftp/profiles/{hml_id}").status_code == 200
    patch_res = client.patch(f"/api/sftp/profiles/{hml_id}", json={"port": 2202})
    assert patch_res.status_code == 200
    assert patch_res.json()["port"] == 2202

    # Test connection
    test_res = client.post(f"/api/sftp/profiles/{hml_id}/test")
    assert test_res.status_code == 200
    assert test_res.json()["ok"] is True

    # Browse + path traversal blocked with HTTP 400
    browse_ok = client.get(f"/api/sftp/profiles/{hml_id}/browse?search=evolucao")
    assert browse_ok.status_code == 200
    assert len(browse_ok.json()["entries"]) == 2

    browse_bad = client.get(f"/api/sftp/profiles/{hml_id}/browse?path=/etc")
    assert browse_bad.status_code == 400

    # Import .jasper via HTTP -> auto decompile
    imp_res = client.post(
        "/api/sftp/import",
        json={
            "profile_id": hml_id,
            "remote_path": "/opt/salutem/relatorios/somente_compilada.jasper",
            "project_name": "Importada HTTP",
        },
    )
    assert imp_res.status_code == 201
    project_id = imp_res.json()["id"]
    assert imp_res.json()["entry_mode"] == "sftp_import"
    assert imp_res.json()["source_origin"]["decompiled"] is True

    # Prepare deploy against PRD read-only -> HTTP 403
    ro_deploy = client.post(
        f"/api/projects/{project_id}/deploy/sftp/prepare",
        json={
            "profile_id": prd_body["id"],
            "remote_dir": "/opt/salutem/relatorios",
            "base_filename": "ficha_evolucao",
        },
    )
    assert ro_deploy.status_code == 403

    # Prepare & Execute against writable HML -> HTTP 200
    prep_res = client.post(
        f"/api/projects/{project_id}/deploy/sftp/prepare",
        json={
            "profile_id": hml_id,
            "remote_dir": "/opt/salutem/relatorios",
            "base_filename": "ficha_evolucao",
        },
    )
    assert prep_res.status_code == 200
    prep_data = prep_res.json()
    assert prep_data["publish_mode"] == "jrxml_only"
    assert prep_data["deploy_token"]

    exec_res = client.post(
        f"/api/projects/{project_id}/deploy/sftp/execute",
        json={"deploy_token": prep_data["deploy_token"]},
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["ok"] is True
    assert len(exec_res.json()["backup_files"]) == 1

    # Reusing same deploy token -> HTTP 400
    replay_res = client.post(
        f"/api/projects/{project_id}/deploy/sftp/execute",
        json={"deploy_token": prep_data["deploy_token"]},
    )
    assert replay_res.status_code == 400

    # Delete profile
    del_res = client.delete(f"/api/sftp/profiles/{hml_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] == hml_id
    assert client.get(f"/api/sftp/profiles/{hml_id}").status_code == 404
