# -*- coding: utf-8 -*-
"""
Unified credential vault for Salutem Ficha Studio (`backend/app/services/secret_vault.py`).

Primary storage uses the OS keyring (`keyring` — Windows Credential Manager / SecretService).
Fallback storage (Docker / headless / CI) uses an authenticated AES-256-GCM encrypted file
(`.vault.json`, version 2, PBKDF2-HMAC-SHA256 600k iterations + account AAD), with transparent
backward-compatible decryption for legacy v1.0.0 `.vault.json` entries.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import keyring
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from keyring.errors import KeyringError, PasswordDeleteError

from backend.app.config import APP_NAME, get_data_dir

KEYRING_SERVICE_NAME = "SalutemFichaStudio"
VAULT_FILENAME = ".vault.json"
INSECURE_PLACEHOLDER_KEYS = frozenset(
    {
        "change-me",
        "change-me-in-production",
        "changeme",
        "default",
        "secret",
        "password",
    }
)


class SecretVaultError(RuntimeError):
    """Raised when vault encryption/decryption, integrity, or master key validation fails."""


class SecretVaultService:
    """
    Unified secret store shared across PostgreSQL, SFTP, JasperReports Server, and default credentials.

    Never stores secrets in SQLite and never logs plaintext values.
    """

    _V1_PBKDF2_ITERATIONS = 100_000
    _V2_PBKDF2_ITERATIONS = 600_000

    def __init__(
        self,
        vault_path: Path | Callable[[], Path] | None = None,
        *,
        service_name: str = KEYRING_SERVICE_NAME,
    ) -> None:
        self._service_name = service_name
        if callable(vault_path):
            self._path_resolver: Callable[[], Path] = vault_path
        elif vault_path is not None:
            resolved = Path(vault_path).resolve()
            self._path_resolver = lambda: resolved
        else:
            self._path_resolver = lambda: get_data_dir() / VAULT_FILENAME

    @property
    def vault_path(self) -> Path:
        """Resolve active fallback `.vault.json` path dynamically."""
        return self._path_resolver()

    @property
    def path(self) -> Path:
        """Alias for `vault_path`."""
        return self.vault_path

    # ------------------------------------------------------------------ Key Derivation

    def _master_secret_bytes(self) -> bytes:
        env_key = os.environ.get("FICHA_STUDIO_VAULT_KEY", "").strip()
        if env_key:
            if env_key.lower() in INSECURE_PLACEHOLDER_KEYS:
                raise SecretVaultError(
                    "FICHA_STUDIO_VAULT_KEY usa um valor placeholder inseguro. "
                    "Defina uma chave secreta forte no ambiente ou deixe-a vazia em desenvolvimento."
                )
            return env_key.encode("utf-8")
        try:
            os_user = getpass.getuser()
        except Exception:
            os_user = "studio"
        seed = f"{APP_NAME}::{platform.node()}::{os_user}::{self.vault_path.parent.resolve()}"
        return seed.encode("utf-8")

    def _derive_v2_key(self, salt: bytes, iterations: int = _V2_PBKDF2_ITERATIONS) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            self._master_secret_bytes(),
            salt,
            iterations,
            dklen=32,
        )

    def _derive_v1_keys(self, salt: bytes) -> tuple[bytes, bytes]:
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            self._master_secret_bytes(),
            salt,
            self._V1_PBKDF2_ITERATIONS,
            dklen=64,
        )
        return derived[:32], derived[32:]

    @staticmethod
    def _v1_xor_keystream(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
        if not data:
            return b""
        stream = bytearray()
        counter = 0
        while len(stream) < len(data):
            block = hashlib.sha256(
                enc_key + nonce + counter.to_bytes(4, byteorder="big")
            ).digest()
            stream.extend(block)
            counter += 1
        return bytes(b ^ k for b, k in zip(data, stream[: len(data)]))

    # ------------------------------------------------------------------ Fallback File I/O

    def _load_doc(self) -> dict[str, Any]:
        target = self.vault_path
        if not target.is_file():
            return {"version": 2, "entries": {}}
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
                return raw
        except (OSError, ValueError):
            pass
        return {"version": 2, "entries": {}}

    def _save_doc(self, doc: dict[str, Any]) -> None:
        target = self.vault_path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_suffix(".json.tmp")
        tmp_target.write_text(
            json.dumps(doc, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(tmp_target, 0o600)
        except OSError:
            pass
        tmp_target.replace(target)

    # ------------------------------------------------------------------ Fallback Crypto (v2 + v1 read)

    def set_fallback_secret(self, account: str, secret: str) -> None:
        """Encrypt and persist a secret in `.vault.json` using version 2 (AES-256-GCM)."""
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        key = self._derive_v2_key(salt, self._V2_PBKDF2_ITERATIONS)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(
            nonce,
            secret.encode("utf-8"),
            account.encode("utf-8"),
        )

        doc = self._load_doc()
        doc["version"] = 2
        doc.setdefault("entries", {})[account] = {
            "version": 2,
            "alg": "AES-256-GCM",
            "iterations": self._V2_PBKDF2_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        self._save_doc(doc)

    def _decrypt_v1_entry(self, account: str, entry: dict[str, Any]) -> str:
        try:
            salt = base64.b64decode(entry["salt"])
            nonce = base64.b64decode(entry["nonce"])
            ciphertext = base64.b64decode(entry["ciphertext"])
            stored_mac = str(entry["hmac"])
        except (KeyError, ValueError, TypeError) as exc:
            raise SecretVaultError("Corrupted v1 credential entry in fallback vault.") from exc

        enc_key, mac_key = self._derive_v1_keys(salt)
        expected_mac = hmac.new(
            mac_key,
            salt + nonce + account.encode("utf-8") + ciphertext,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_mac, stored_mac):
            raise SecretVaultError(
                "Vault HMAC integrity check failed: encrypted secret may have been tampered with."
            )
        plaintext = self._v1_xor_keystream(ciphertext, enc_key, nonce)
        return plaintext.decode("utf-8")

    def _decrypt_v2_entry(self, account: str, entry: dict[str, Any]) -> str:
        try:
            salt = base64.b64decode(entry["salt"])
            nonce = base64.b64decode(entry["nonce"])
            ciphertext = base64.b64decode(entry["ciphertext"])
            iterations = int(entry.get("iterations", self._V2_PBKDF2_ITERATIONS))
            if iterations < 10_000:
                raise ValueError("Invalid PBKDF2 iteration count.")
        except (KeyError, ValueError, TypeError) as exc:
            raise SecretVaultError("Corrupted v2 credential entry in fallback vault.") from exc

        key = self._derive_v2_key(salt, iterations)
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, account.encode("utf-8"))
        except InvalidTag as exc:
            raise SecretVaultError(
                "Vault AEAD/HMAC integrity check failed: encrypted secret may have been tampered with."
            ) from exc
        return plaintext.decode("utf-8")

    def get_fallback_secret(self, account: str) -> str | None:
        """Read and authenticate a secret from `.vault.json` (supports both v2 and legacy v1)."""
        doc = self._load_doc()
        entry = doc.get("entries", {}).get(account)
        if not isinstance(entry, dict):
            return None

        entry_version = int(entry.get("version", 1))
        if entry_version == 2:
            return self._decrypt_v2_entry(account, entry)
        if entry_version == 1:
            return self._decrypt_v1_entry(account, entry)
        raise SecretVaultError(f"Unsupported fallback vault entry version: {entry_version}")

    def delete_fallback_secret(self, account: str) -> None:
        """Delete an account entry from `.vault.json` if present."""
        if not self.vault_path.is_file():
            return
        doc = self._load_doc()
        entries = doc.get("entries", {})
        if account in entries:
            del entries[account]
            self._save_doc(doc)

    # ------------------------------------------------------------------ Public Unified API

    def set_secret(self, account: str, secret: str) -> None:
        """Persist a secret in OS keyring, transparently falling back to AES-256-GCM `.vault.json`."""
        try:
            keyring.set_password(self._service_name, account, secret)
            self.delete_fallback_secret(account)
        except KeyringError:
            self.set_fallback_secret(account, secret)

    def get_secret(self, account: str) -> str | None:
        """Load a secret from OS keyring or `.vault.json` fallback."""
        try:
            secret = keyring.get_password(self._service_name, account)
            if secret is not None:
                return secret
        except KeyringError:
            pass
        return self.get_fallback_secret(account)

    def delete_secret(self, account: str) -> None:
        """Delete a secret from both OS keyring and `.vault.json` fallback."""
        try:
            keyring.delete_password(self._service_name, account)
        except (PasswordDeleteError, KeyringError):
            pass
        self.delete_fallback_secret(account)

    def has_secret(self, account: str) -> bool:
        """Return True if a non-empty secret exists for `account`."""
        secret = self.get_secret(account)
        return secret is not None and len(secret) > 0
