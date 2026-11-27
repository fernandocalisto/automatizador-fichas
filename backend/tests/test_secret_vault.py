# -*- coding: utf-8 -*-
"""Tests for unified SecretVaultService (AES-256-GCM v2 + v1 compat) and DefaultCredentialsService."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.errors import KeyringError, PasswordDeleteError

from backend.app.db.sqlite_store import SQLiteStore
from backend.app.main import create_app
from backend.app.services.default_credentials_service import (
    DefaultCredentialsService,
    DefaultCredentialUpdate,
)
from backend.app.services.postgres_service import DbProfileCreate, PostgresService
from backend.app.services.secret_vault import SecretVaultError, SecretVaultService


@pytest.fixture()
def vault_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "vault_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "strong-test-vault-key-2026-v2")

    class FailingKeyringError(KeyringError):
        pass

    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise FailingKeyringError("headless keyring disabled for vault test")

    monkeypatch.setattr(keyring, "set_password", _fail)
    monkeypatch.setattr(keyring, "get_password", _fail)
    monkeypatch.setattr(keyring, "delete_password", _fail)
    return data_dir


def test_secret_vault_v2_aes_gcm_roundtrip_and_tamper_detection(vault_env: Path) -> None:
    vault = SecretVaultService(vault_path=vault_env / ".vault.json")
    vault.set_secret("sftp_password:unit-1", "Sup3r!Secr3t#2026")
    vault.set_secret("jasperserver_password:unit-1", "Jasper!Key#99")

    assert vault.get_secret("sftp_password:unit-1") == "Sup3r!Secr3t#2026"
    assert vault.get_secret("jasperserver_password:unit-1") == "Jasper!Key#99"
    assert vault.has_secret("sftp_password:unit-1") is True

    raw = json.loads(vault.vault_path.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["entries"]["sftp_password:unit-1"]["version"] == 2
    assert raw["entries"]["sftp_password:unit-1"]["alg"] == "AES-256-GCM"
    assert "Sup3r!Secr3t" not in vault.vault_path.read_text(encoding="utf-8")

    # Cross-account swap must fail AAD authentication
    raw["entries"]["jasperserver_password:unit-1"] = raw["entries"]["sftp_password:unit-1"]
    vault.vault_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SecretVaultError, match="integrity"):
        vault.get_secret("jasperserver_password:unit-1")

    vault.delete_secret("sftp_password:unit-1")
    assert vault.get_secret("sftp_password:unit-1") is None


def test_secret_vault_reads_legacy_v1_and_upgrades_on_rewrite(vault_env: Path) -> None:
    vault = SecretVaultService(vault_path=vault_env / ".vault.json")
    account = "db_profile:legacy-1"
    secret = "LegacyPassword!v1"

    # Construct an authentic v1.0.0 entry
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", b"strong-test-vault-key-2026-v2", salt, 100_000, dklen=64)
    enc_key, mac_key = derived[:32], derived[32:]
    plaintext = secret.encode("utf-8")
    keystream = hashlib.sha256(enc_key + nonce + (0).to_bytes(4, "big")).digest()
    ciphertext = bytes(b ^ k for b, k in zip(plaintext, keystream[: len(plaintext)]))
    mac = hmac.new(mac_key, salt + nonce + account.encode("utf-8") + ciphertext, hashlib.sha256).hexdigest()

    v1_doc = {
        "version": 1,
        "entries": {
            account: {
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "hmac": mac,
            }
        },
    }
    vault.vault_path.parent.mkdir(parents=True, exist_ok=True)
    vault.vault_path.write_text(json.dumps(v1_doc), encoding="utf-8")

    assert vault.get_secret(account) == secret

    # Rewriting upgrades entry transparently to v2
    vault.set_secret(account, "UpgradedPassword!v2")
    upgraded_doc = json.loads(vault.vault_path.read_text(encoding="utf-8"))
    assert upgraded_doc["entries"][account]["version"] == 2
    assert vault.get_secret(account) == "UpgradedPassword!v2"


def test_secret_vault_rejects_placeholder_env_key(
    vault_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "change-me-in-production")
    vault = SecretVaultService(vault_path=vault_env / ".vault.json")
    with pytest.raises(SecretVaultError, match="placeholder"):
        vault.set_secret("test:acc", "abc")


def test_default_credentials_inheritance_and_api_redaction(vault_env: Path) -> None:
    store = SQLiteStore(db_path=vault_env / "studio.db")
    vault = SecretVaultService(vault_path=vault_env / ".vault.json")
    defaults_svc = DefaultCredentialsService(store=store, vault=vault)
    pg_svc = PostgresService(store=store, vault=vault, default_credentials_service=defaults_svc)

    # Zero built-in credentials initially
    initial = defaults_svc.get_all_defaults()
    assert initial["postgres"].configured is False
    assert initial["postgres"].username == ""
    assert initial["postgres"].has_password is False

    app = create_app(
        store=store,
        secret_vault=vault,
        default_credentials_service=defaults_svc,
        postgres_service=pg_svc,
    )
    with TestClient(app) as client:
        put_res = client.put(
            "/api/credentials/defaults/postgres",
            json={
                "username": "std_pg_user",
                "password": "StdPgPassword!2026",
                "default_dbname": "salutem_default",
                "default_dbname_hospitalar": "salutem_hosp",
            },
        )
        assert put_res.status_code == 200
        body = put_res.json()
        assert body["username"] == "std_pg_user"
        assert body["has_password"] is True
        assert body["configured"] is True
        assert "password" not in body
        assert "StdPgPassword!2026" not in put_res.text

        # Profile with credential_mode='default' inherits default username, password, and dbname
        prof = pg_svc.create_profile(
            DbProfileCreate(
                name="Cliente Padrão",
                host="10.0.0.50",
                port=5432,
                dbname="",
                user="",
                credential_mode="default",
                environment="PRD",
                read_only=True,
            )
        )
        assert prof.credential_mode == "default"
        assert prof.has_password is True
        jdbc = pg_svc.get_jdbc_credentials(prof.id)
        assert jdbc["db_user"] == "std_pg_user"
        assert jdbc["db_pass"] == "StdPgPassword!2026"
        assert "/salutem_default?" in jdbc["db_url"]

        # Rotating default password updates inherited profile automatically
        defaults_svc.update_default("postgres", DefaultCredentialUpdate(password="Rotated!2027"))
        assert pg_svc.get_jdbc_credentials(prof.id)["db_pass"] == "Rotated!2027"

        # SQLite never stores plaintext secret
        assert b"Rotated!2027" not in store.db_path.read_bytes()

        # DELETE clears defaults cleanly
        del_res = client.delete("/api/credentials/defaults/postgres")
        assert del_res.status_code == 200
        assert del_res.json()["configured"] is False
        assert del_res.json()["has_password"] is False


def test_default_sftp_key_upload_and_local_path_inheritance(vault_env: Path) -> None:
    store = SQLiteStore(db_path=vault_env / "studio_sftp_keys.db")
    vault = SecretVaultService(vault_path=vault_env / ".vault_sftp_keys.json")
    defaults_svc = DefaultCredentialsService(store=store, vault=vault)

    app = create_app(
        store=store,
        secret_vault=vault,
        default_credentials_service=defaults_svc,
    )
    with TestClient(app) as client:
        # 1. Uploaded .key file stored in vault + private_key_filename metadata
        fake_pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nSYNTHETIC_DEFAULT_KEY_DATA\n-----END OPENSSH PRIVATE KEY-----"
        res_upload = client.put(
            "/api/credentials/defaults/sftp",
            json={
                "username": "deploy_default",
                "auth_type": "private_key",
                "private_key": fake_pem,
                "private_key_filename": "acesso_producao.key",
                "default_remote_base_dir": "/opt/salutem/relatorios",
            },
        )
        assert res_upload.status_code == 200
        body = res_upload.json()
        assert body["configured"] is True
        assert body["has_private_key"] is True
        assert body["private_key_filename"] == "acesso_producao.key"
        assert body["private_key_path"] == ""
        assert "private_key" not in body
        assert "SYNTHETIC_DEFAULT_KEY_DATA" not in res_upload.text
        assert b"SYNTHETIC_DEFAULT_KEY_DATA" not in store.db_path.read_bytes()

        resolved = defaults_svc.resolve_sftp_credentials(
            credential_mode="default",
            profile_id="prof-1",
        )
        assert resolved["auth_type"] == "private_key"
        assert resolved["private_key"] == fake_pem
        assert resolved["private_key_filename"] == "acesso_producao.key"
        assert resolved["private_key_path"] == ""

        # 2. Clearing vault key and switching to local private_key_path
        local_key = vault_env / "local_default.key"
        local_key.write_text(fake_pem, encoding="utf-8")
        res_path = client.put(
            "/api/credentials/defaults/sftp",
            json={
                "username": "",
                "auth_type": "private_key",
                "private_key": "",
                "private_key_path": str(local_key),
            },
        )
        assert res_path.status_code == 200
        path_body = res_path.json()
        assert path_body["private_key_filename"] == ""
        assert path_body["private_key_path"] == str(local_key)
        assert path_body["has_private_key"] is True
        assert path_body["configured"] is True

        resolved_path = defaults_svc.resolve_sftp_credentials(
            credential_mode="default",
            profile_id="prof-1",
        )
        assert resolved_path["private_key"] is None
        assert resolved_path["private_key_path"] == str(local_key)

        # 3. Custom mode does NOT inherit default private_key_path
        resolved_custom = defaults_svc.resolve_sftp_credentials(
            credential_mode="custom",
            profile_id="prof-custom",
            custom_user="custom_u",
            custom_auth_type="private_key",
            custom_private_key_filename="custom.key",
            custom_private_key_path="/tmp/custom.key",
        )
        assert resolved_custom["private_key_filename"] == "custom.key"
        assert resolved_custom["private_key_path"] == "/tmp/custom.key"

        # 4. DELETE clears path, filename, and vault secrets
        del_res = client.delete("/api/credentials/defaults/sftp")
        assert del_res.status_code == 200
        assert del_res.json()["has_private_key"] is False
        assert del_res.json()["private_key_path"] == ""
        assert del_res.json()["private_key_filename"] == ""
        assert del_res.json()["configured"] is False
