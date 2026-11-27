# -*- coding: utf-8 -*-
"""
Local default credentials service (`backend/app/services/default_credentials_service.py`).

Allows users to configure optional local default credentials per connection type
(`postgres`, `sftp`, `jasperserver`) stored exclusively in local `app_settings` (non-secret
metadata) and `SecretVaultService` (passwords / SSH keys). Zero credentials are ever built-in.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.db.sqlite_store import SQLiteStore, utc_now_iso
from backend.app.services.secret_vault import SecretVaultService

_SSH_PEM_BEGIN_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_SSH_PEM_END_RE = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")


def validate_ssh_private_key_pem(value: str | None) -> str | None:
    """
    Validate that a non-empty SSH private key has plausible PEM/OpenSSH structure
    (`-----BEGIN ... PRIVATE KEY-----` ... `-----END ... PRIVATE KEY-----`).
    `None` and empty string `""` (used to clear a stored key) are allowed.
    """
    if value is None or value == "":
        return value
    cleaned = value.lstrip("\ufeff").strip()
    if not cleaned:
        raise ValueError(
            "Chave privada SSH inválida: forneça uma chave em formato PEM/OpenSSH "
            "(-----BEGIN ... PRIVATE KEY----- / -----END ... PRIVATE KEY-----)."
        )
    begin_match = _SSH_PEM_BEGIN_RE.search(cleaned)
    end_match = _SSH_PEM_END_RE.search(cleaned)
    if (
        begin_match is None
        or end_match is None
        or begin_match.end() >= end_match.start()
        or not cleaned[begin_match.end() : end_match.start()].strip()
    ):
        raise ValueError(
            "Chave privada SSH inválida: forneça uma chave em formato PEM/OpenSSH "
            "(-----BEGIN ... PRIVATE KEY----- / -----END ... PRIVATE KEY-----)."
        )
    return value

CredentialKind = Literal["postgres", "sftp", "jasperserver"]
CredentialMode = Literal["default", "custom"]
SftpAuthType = Literal["password", "private_key"]

ALL_CREDENTIAL_KINDS: tuple[CredentialKind, ...] = ("postgres", "sftp", "jasperserver")
_SETTINGS_KEY = "default_credentials"


class DefaultCredentialRead(BaseModel):
    """Redacted metadata for one connection type's local default credentials (NEVER exposes secrets)."""

    model_config = ConfigDict(extra="forbid")

    kind: CredentialKind
    username: str = ""
    organization: str = ""
    auth_type: SftpAuthType = "password"
    default_dbname: str = ""
    default_dbname_ambulatorial: str = ""
    default_dbname_hospitalar: str = ""
    default_remote_base_dir: str = "/"
    private_key_filename: str = ""
    private_key_path: str = ""
    has_password: bool = False
    has_private_key: bool = False
    has_passphrase: bool = False
    configured: bool = False
    updated_at: str | None = None


class DefaultCredentialUpdate(BaseModel):
    """Update payload for one connection type's local default credentials."""

    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, max_length=255)
    organization: str | None = Field(default=None, max_length=255)
    auth_type: SftpAuthType | None = None
    default_dbname: str | None = Field(default=None, max_length=128)
    default_dbname_ambulatorial: str | None = Field(default=None, max_length=128)
    default_dbname_hospitalar: str | None = Field(default=None, max_length=128)
    default_remote_base_dir: str | None = Field(default=None, max_length=512)
    private_key_filename: str | None = Field(default=None, max_length=255)
    private_key_path: str | None = Field(default=None, max_length=1024)
    password: str | None = Field(default=None, repr=False)
    private_key: str | None = Field(default=None, repr=False)
    passphrase: str | None = Field(default=None, repr=False)

    @field_validator("private_key")
    @classmethod
    def _validate_private_key(cls, value: str | None) -> str | None:
        return validate_ssh_private_key_pem(value)


class DefaultCredentialsService:
    """Manages local user-configured default credentials and runtime credential inheritance."""

    def __init__(
        self,
        store: SQLiteStore | None = None,
        vault: SecretVaultService | None = None,
    ) -> None:
        self.store = store or SQLiteStore()
        self.vault = vault or SecretVaultService()

    @staticmethod
    def _secret_account(kind: CredentialKind, field_name: str) -> str:
        return f"default:{kind}:{field_name}"

    def _load_meta_map(self) -> dict[str, dict[str, Any]]:
        raw = self.store.get_setting(_SETTINGS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): dict(v)
            for k, v in raw.items()
            if k in ALL_CREDENTIAL_KINDS and isinstance(v, dict)
        }

    def _save_meta_map(self, meta_map: dict[str, dict[str, Any]]) -> None:
        self.store.set_settings({_SETTINGS_KEY: meta_map})

    def get_default(self, kind: CredentialKind) -> DefaultCredentialRead:
        """Return redacted metadata and secret presence flags for `kind`."""
        meta = self._load_meta_map().get(kind, {})
        has_password = self.vault.has_secret(self._secret_account(kind, "password"))
        private_key_filename = (
            str(meta.get("private_key_filename") or "").strip() if kind == "sftp" else ""
        )
        private_key_path = (
            str(meta.get("private_key_path") or "").strip() if kind == "sftp" else ""
        )
        has_private_key = (
            self.vault.has_secret(self._secret_account(kind, "private_key"))
            or bool(private_key_path)
            if kind == "sftp"
            else False
        )
        has_passphrase = (
            self.vault.has_secret(self._secret_account(kind, "passphrase"))
            if kind == "sftp"
            else False
        )
        username = str(meta.get("username") or "").strip()
        auth_type_raw = str(meta.get("auth_type") or "password")
        auth_type: SftpAuthType = "private_key" if auth_type_raw == "private_key" else "password"
        configured = bool(username or has_password or has_private_key)
        return DefaultCredentialRead(
            kind=kind,
            username=username,
            organization=str(meta.get("organization") or "").strip(),
            auth_type=auth_type,
            default_dbname=str(meta.get("default_dbname") or "").strip(),
            default_dbname_ambulatorial=str(meta.get("default_dbname_ambulatorial") or "").strip(),
            default_dbname_hospitalar=str(meta.get("default_dbname_hospitalar") or "").strip(),
            default_remote_base_dir=str(meta.get("default_remote_base_dir") or "/").strip() or "/",
            private_key_filename=private_key_filename,
            private_key_path=private_key_path,
            has_password=has_password,
            has_private_key=has_private_key,
            has_passphrase=has_passphrase,
            configured=configured,
            updated_at=meta.get("updated_at"),
        )

    def get_all_defaults(self) -> dict[str, DefaultCredentialRead]:
        """Return redacted default credential metadata for all supported connection types."""
        return {kind: self.get_default(kind) for kind in ALL_CREDENTIAL_KINDS}

    def update_default(
        self,
        kind: CredentialKind,
        payload: DefaultCredentialUpdate,
    ) -> DefaultCredentialRead:
        """Persist non-secret metadata in SQLite settings and secrets in `SecretVaultService`."""
        fields = payload.model_dump(exclude_unset=True)

        for secret_field in ("password", "private_key", "passphrase"):
            if secret_field not in fields:
                continue
            raw_val = fields.pop(secret_field)
            if raw_val is None:
                continue
            account = self._secret_account(kind, secret_field)
            if raw_val == "":
                self.vault.delete_secret(account)
                if secret_field == "private_key" and "private_key_filename" not in fields:
                    fields["private_key_filename"] = ""
            else:
                if secret_field == "private_key":
                    validate_ssh_private_key_pem(raw_val)
                self.vault.set_secret(account, raw_val)

        meta_map = self._load_meta_map()
        current = dict(meta_map.get(kind, {}))
        for key in (
            "username",
            "organization",
            "auth_type",
            "default_dbname",
            "default_dbname_ambulatorial",
            "default_dbname_hospitalar",
            "default_remote_base_dir",
            "private_key_filename",
            "private_key_path",
        ):
            if key in fields and fields[key] is not None:
                current[key] = str(fields[key]).strip()
        current["updated_at"] = utc_now_iso()
        meta_map[kind] = current
        self._save_meta_map(meta_map)
        return self.get_default(kind)

    def clear_default(self, kind: CredentialKind) -> DefaultCredentialRead:
        """Remove default metadata and secrets for `kind` from local storage and vault."""
        for secret_field in ("password", "private_key", "passphrase"):
            self.vault.delete_secret(self._secret_account(kind, secret_field))
        meta_map = self._load_meta_map()
        if kind in meta_map:
            del meta_map[kind]
            self._save_meta_map(meta_map)
        return self.get_default(kind)

    # ------------------------------------------------------------------ Resolution Helpers

    def resolve_postgres_credentials(
        self,
        *,
        credential_mode: str,
        profile_id: str,
        custom_user: str = "",
        custom_dbname: str = "",
        system_type: str | None = None,
    ) -> tuple[str, str | None, str]:
        """Resolve effective `(username, password, dbname)` honoring default vs custom mode."""
        mode = "default" if credential_mode == "default" else "custom"
        defaults = self.get_default("postgres")

        effective_user = custom_user.strip()
        effective_dbname = custom_dbname.strip()

        if not effective_dbname:
            if system_type == "hospitalar" and defaults.default_dbname_hospitalar:
                effective_dbname = defaults.default_dbname_hospitalar
            elif system_type == "ambulatorial" and defaults.default_dbname_ambulatorial:
                effective_dbname = defaults.default_dbname_ambulatorial
            elif defaults.default_dbname:
                effective_dbname = defaults.default_dbname

        if mode == "default":
            if not effective_user:
                effective_user = defaults.username
            password = self.vault.get_secret(self._secret_account("postgres", "password"))
            return effective_user, password, effective_dbname

        password = self.vault.get_secret(f"db_profile:{profile_id}")
        return effective_user, password, effective_dbname

    def resolve_sftp_credentials(
        self,
        *,
        credential_mode: str,
        profile_id: str,
        custom_user: str = "",
        custom_auth_type: str = "password",
        custom_remote_base_dir: str = "/",
        custom_private_key_filename: str = "",
        custom_private_key_path: str = "",
    ) -> dict[str, Any]:
        """Resolve effective SFTP credentials (`username`, `auth_type`, `password`, `private_key`, `private_key_filename`, `private_key_path`, `passphrase`, `remote_base_dir`)."""
        mode = "default" if credential_mode == "default" else "custom"
        defaults = self.get_default("sftp")

        remote_base_dir = (custom_remote_base_dir or "").strip()
        if not remote_base_dir or remote_base_dir == "/":
            remote_base_dir = defaults.default_remote_base_dir or "/"

        if mode == "default":
            return {
                "username": custom_user.strip() or defaults.username,
                "auth_type": defaults.auth_type,
                "password": self.vault.get_secret(self._secret_account("sftp", "password")),
                "private_key": self.vault.get_secret(self._secret_account("sftp", "private_key")),
                "private_key_filename": defaults.private_key_filename,
                "private_key_path": defaults.private_key_path,
                "passphrase": self.vault.get_secret(self._secret_account("sftp", "passphrase")),
                "remote_base_dir": remote_base_dir,
            }

        return {
            "username": custom_user.strip(),
            "auth_type": "private_key" if custom_auth_type == "private_key" else "password",
            "password": self.vault.get_secret(f"sftp_password:{profile_id}"),
            "private_key": self.vault.get_secret(f"sftp_key:{profile_id}"),
            "private_key_filename": (custom_private_key_filename or "").strip(),
            "private_key_path": (custom_private_key_path or "").strip(),
            "passphrase": self.vault.get_secret(f"sftp_passphrase:{profile_id}"),
            "remote_base_dir": remote_base_dir,
        }

    def resolve_jasperserver_credentials(
        self,
        *,
        credential_mode: str,
        profile_id: str,
        custom_user: str = "",
        custom_organization: str = "",
    ) -> dict[str, Any]:
        """Resolve effective JasperReports Server credentials (`username`, `organization`, `password`)."""
        mode = "default" if credential_mode == "default" else "custom"
        defaults = self.get_default("jasperserver")

        if mode == "default":
            return {
                "username": custom_user.strip() or defaults.username,
                "organization": custom_organization.strip() or defaults.organization,
                "password": self.vault.get_secret(self._secret_account("jasperserver", "password")),
            }

        return {
            "username": custom_user.strip(),
            "organization": custom_organization.strip(),
            "password": self.vault.get_secret(f"jasperserver_password:{profile_id}"),
        }
