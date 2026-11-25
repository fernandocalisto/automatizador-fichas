# -*- coding: utf-8 -*-
"""PostgreSQL profile management, OS keyring + encrypted vault secrets, and safe SQL execution."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import inspect
import json
import os
import platform
import re
import secrets
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import keyring
import psycopg
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.config import APP_NAME, get_data_dir
from backend.app.core.sql_insert import validate_postgres_syntax
from backend.app.db.sqlite_store import SQLiteStore, utc_now_iso
from backend.app.services.workspace_service import WorkspaceService

KEYRING_SERVICE_NAME = "SalutemFichaStudio"
VAULT_FILENAME = ".vault.json"
VALID_SSL_MODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
_TEMPLATE_ID_NOTICE_RE = re.compile(r"ID\s+gerado:\s*(\d+)", re.IGNORECASE)

SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]

DB_PROFILES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS db_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 5432,
    dbname TEXT NOT NULL,
    user TEXT NOT NULL,
    sslmode TEXT NOT NULL DEFAULT 'prefer',
    read_only INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_db_profiles_default
    ON db_profiles(is_default DESC, name ASC);

CREATE TABLE IF NOT EXISTS db_dry_run_tokens (
    token TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    sql_sha256 TEXT NOT NULL,
    simulated_template_id INTEGER NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_db_dry_run_tokens_lookup
    ON db_dry_run_tokens(project_id, profile_id, sql_sha256);
"""


# =============================================================================
# Exceptions
# =============================================================================


class PostgresServiceError(Exception):
    """Base error for PostgreSQL profile and execution operations."""


class DbProfileNotFoundError(PostgresServiceError):
    """Raised when a connection profile ID does not exist."""


class DbProfileValidationError(PostgresServiceError):
    """Raised when profile parameters or SQL syntax fail validation."""


class ReadOnlyProfileError(PostgresServiceError):
    """Raised when a mutating operation is attempted on a read-only profile."""


class DryRunRequiredError(PostgresServiceError):
    """Raised when COMMIT is attempted without a matching, unconsumed Dry-Run token."""


class PostgresExecutionError(PostgresServiceError):
    """Raised when PostgreSQL driver execution fails."""


# =============================================================================
# Pydantic Schemas
# =============================================================================


class DbProfileCreate(BaseModel):
    """Payload to create a new PostgreSQL connection profile."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    dbname: str = Field(..., min_length=1, max_length=128)
    user: str = Field(..., min_length=1, max_length=128)
    password: str | None = Field(default=None, repr=False)
    sslmode: SslMode = "prefer"
    read_only: bool = False
    is_default: bool = False

    @field_validator("name", "host", "dbname", "user")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank.")
        return cleaned


class DbProfileUpdate(BaseModel):
    """Partial update payload for an existing PostgreSQL connection profile."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    dbname: str | None = Field(default=None, min_length=1, max_length=128)
    user: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, repr=False)
    sslmode: SslMode | None = None
    read_only: bool | None = None
    is_default: bool | None = None

    @field_validator("name", "host", "dbname", "user")
    @classmethod
    def _strip_optional_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank.")
        return cleaned


class DbProfileRead(BaseModel):
    """Redacted PostgreSQL connection profile metadata (NEVER exposes plaintext password)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    name: str
    host: str
    port: int = 5432
    dbname: str
    user: str
    sslmode: SslMode = "prefer"
    read_only: bool = False
    is_default: bool = False
    has_password: bool = False
    created_at: str
    updated_at: str


class DbConnectionTestResult(BaseModel):
    """Result of testing connectivity and server metadata for a PostgreSQL profile."""

    profile_id: str
    ok: bool
    latency_ms: float
    server_version: str | None = None
    current_database: str | None = None
    current_user: str | None = None
    read_only: bool = False
    message: str = ""
    error: str | None = None


class DryRunInsertResult(BaseModel):
    """Result of executing a clinical form SQL INSERT inside a rolled-back transaction."""

    ok: bool = True
    project_id: str
    profile_id: str
    rolled_back: bool = True
    template_id: int | None = None
    simulated_template_id: int | None = None
    notices: list[str] = Field(default_factory=list)
    sql_sha256: str
    dry_run_token: str
    latency_ms: float = 0.0
    message: str = ""


class CommitInsertResult(BaseModel):
    """Result of committing a validated clinical form SQL INSERT after Dry-Run verification."""

    ok: bool = True
    committed: bool = True
    project_id: str
    profile_id: str
    template_id: int | None = None
    notices: list[str] = Field(default_factory=list)
    sql_sha256: str
    artifact_version: int | None = None
    gate2_status: str = "approved"
    latency_ms: float = 0.0
    message: str = ""


class SelectColumnMeta(BaseModel):
    """Column metadata extracted from PostgreSQL cursor description for JasperReports JRXML."""

    name: str
    type_oid: int | None = None
    pg_type: str
    java_class: str
    nullable: bool | None = None


class InspectSelectResult(BaseModel):
    """Result of inspecting a JasperReports SELECT query with LIMIT 0."""

    ok: bool = True
    profile_id: str
    columns: list[SelectColumnMeta] = Field(default_factory=list)
    sample_id_used: int = 0
    sample_atendimento_id: int | None = None
    parameter_placeholders_replaced: int = 0
    latency_ms: float = 0.0
    message: str = ""


# =============================================================================
# Encrypted Fallback Vault (.vault.json — PBKDF2 + SHA-256 CTR XOR + HMAC-SHA256)
# =============================================================================


class _EncryptedVault:
    """
    Server/CI/Docker fallback credential vault stored at `get_data_dir() / '.vault.json'`.
    Uses PBKDF2-HMAC-SHA256 key derivation, SHA-256 counter-mode XOR stream encryption,
    and Encrypt-then-MAC (HMAC-SHA256) integrity verification.
    """

    _PBKDF2_ITERATIONS = 100_000

    def __init__(self, vault_path_resolver: Callable[[], Path]) -> None:
        self._resolve_path = vault_path_resolver

    @property
    def path(self) -> Path:
        return self._resolve_path()

    def _master_secret_bytes(self) -> bytes:
        env_key = os.environ.get("FICHA_STUDIO_VAULT_KEY")
        if env_key:
            return env_key.encode("utf-8")
        try:
            os_user = getpass.getuser()
        except Exception:
            os_user = "studio"
        seed = f"{APP_NAME}::{platform.node()}::{os_user}::{self.path.parent.resolve()}"
        return seed.encode("utf-8")

    def _derive_keys(self, salt: bytes) -> tuple[bytes, bytes]:
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            self._master_secret_bytes(),
            salt,
            self._PBKDF2_ITERATIONS,
            dklen=64,
        )
        return derived[:32], derived[32:]

    @staticmethod
    def _xor_keystream(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
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

    def _load_doc(self) -> dict[str, Any]:
        target = self.path
        if not target.is_file():
            return {"version": 1, "entries": {}}
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
                return raw
        except (OSError, ValueError):
            pass
        return {"version": 1, "entries": {}}

    def _save_doc(self, doc: dict[str, Any]) -> None:
        target = self.path
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

    def set_secret(self, account: str, secret: str) -> None:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(16)
        enc_key, mac_key = self._derive_keys(salt)
        plaintext = secret.encode("utf-8")
        ciphertext = self._xor_keystream(plaintext, enc_key, nonce)
        mac = hmac.new(
            mac_key,
            salt + nonce + account.encode("utf-8") + ciphertext,
            hashlib.sha256,
        ).hexdigest()

        doc = self._load_doc()
        doc.setdefault("entries", {})[account] = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "hmac": mac,
        }
        self._save_doc(doc)

    def get_secret(self, account: str) -> str | None:
        doc = self._load_doc()
        entry = doc.get("entries", {}).get(account)
        if not isinstance(entry, dict):
            return None
        try:
            salt = base64.b64decode(entry["salt"])
            nonce = base64.b64decode(entry["nonce"])
            ciphertext = base64.b64decode(entry["ciphertext"])
            stored_mac = str(entry["hmac"])
        except (KeyError, ValueError, TypeError):
            raise PostgresServiceError("Corrupted credential entry in fallback vault.")

        enc_key, mac_key = self._derive_keys(salt)
        expected_mac = hmac.new(
            mac_key,
            salt + nonce + account.encode("utf-8") + ciphertext,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_mac, stored_mac):
            raise PostgresServiceError(
                "Vault HMAC integrity check failed: encrypted secret may have been tampered with."
            )
        plaintext = self._xor_keystream(ciphertext, enc_key, nonce)
        return plaintext.decode("utf-8")

    def delete_secret(self, account: str) -> None:
        if not self.path.is_file():
            return
        doc = self._load_doc()
        entries = doc.get("entries", {})
        if account in entries:
            del entries[account]
            self._save_doc(doc)


# =============================================================================
# PostgresService
# =============================================================================


class PostgresService:
    """
    Manages PostgreSQL connection profiles, OS keyring / `.vault.json` credentials,
    and safe clinical SQL operations.
    """

    def __init__(
        self,
        store: SQLiteStore | None = None,
        connection_factory: Callable[..., Any] | None = None,
        *,
        vault_path: Path | None = None,
    ) -> None:
        self.store = store or SQLiteStore()
        self._connection_factory = connection_factory
        self._explicit_vault_path = vault_path.resolve() if vault_path is not None else None
        self._vault = _EncryptedVault(self._resolve_vault_path)
        self._initialized_dbs: set[Path] = set()

    def _resolve_vault_path(self) -> Path:
        if self._explicit_vault_path is not None:
            return self._explicit_vault_path
        return get_data_dir() / VAULT_FILENAME

    @property
    def vault_path(self) -> Path:
        """Return active path for the encrypted `.vault.json` fallback file."""
        return self._resolve_vault_path()

    def _ensure_tables(self) -> None:
        db_target = self.store.db_path
        if db_target in self._initialized_dbs and db_target.exists():
            return
        with self.store.connection() as conn:
            conn.executescript(DB_PROFILES_SCHEMA_SQL)
        self._initialized_dbs.add(db_target)

    @staticmethod
    def _keyring_account(profile_id: str) -> str:
        return f"db_profile:{profile_id}"

    # -------------------------------------------------------------------------
    # Secret Management (OS Keyring -> .vault.json fallback)
    # -------------------------------------------------------------------------

    def _store_password(self, profile_id: str, password: str) -> None:
        account = self._keyring_account(profile_id)
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, account, password)
            # Remove stale fallback copy if OS keyring succeeded
            self._vault.delete_secret(account)
        except KeyringError:
            self._vault.set_secret(account, password)

    def _load_password(self, profile_id: str) -> str | None:
        account = self._keyring_account(profile_id)
        try:
            secret = keyring.get_password(KEYRING_SERVICE_NAME, account)
            if secret is not None:
                return secret
        except KeyringError:
            pass
        return self._vault.get_secret(account)

    def _delete_password(self, profile_id: str) -> None:
        account = self._keyring_account(profile_id)
        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, account)
        except (PasswordDeleteError, KeyringError):
            pass
        self._vault.delete_secret(account)

    def _has_password(self, profile_id: str) -> bool:
        secret = self._load_password(profile_id)
        return secret is not None and len(secret) > 0

    # -------------------------------------------------------------------------
    # Profile Metadata Helpers & CRUD
    # -------------------------------------------------------------------------

    def _row_to_profile_read(self, row: dict[str, Any]) -> DbProfileRead:
        profile_id = str(row["id"])
        return DbProfileRead(
            id=profile_id,
            name=str(row["name"]),
            host=str(row["host"]),
            port=int(row["port"]),
            dbname=str(row["dbname"]),
            user=str(row["user"]),
            sslmode=row["sslmode"],
            read_only=bool(row["read_only"]),
            is_default=bool(row["is_default"]),
            has_password=self._has_password(profile_id),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _require_profile_row(self, profile_id: str) -> dict[str, Any]:
        self._ensure_tables()
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM db_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise DbProfileNotFoundError(f"Database profile '{profile_id}' not found.")
        return dict(row)

    def _sync_profiles_setting_mirror(self) -> None:
        """Mirror non-sensitive profile metadata in `app_settings['db_profiles']` (never passwords)."""
        self._ensure_tables()
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM db_profiles ORDER BY is_default DESC, name ASC, created_at ASC"
            ).fetchall()
        redacted = [
            {
                "id": str(r["id"]),
                "name": str(r["name"]),
                "host": str(r["host"]),
                "port": int(r["port"]),
                "dbname": str(r["dbname"]),
                "user": str(r["user"]),
                "sslmode": str(r["sslmode"]),
                "read_only": bool(r["read_only"]),
                "is_default": bool(r["is_default"]),
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in rows
        ]
        self.store.set_settings({"db_profiles": redacted})

    def list_profiles(self) -> list[DbProfileRead]:
        """Return all persisted PostgreSQL profiles (passwords redacted via `has_password`)."""
        self._ensure_tables()
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM db_profiles ORDER BY is_default DESC, name ASC, created_at ASC"
            ).fetchall()
        return [self._row_to_profile_read(dict(r)) for r in rows]

    def get_profile(self, profile_id: str) -> DbProfileRead:
        """Fetch a single PostgreSQL profile by ID or raise DbProfileNotFoundError."""
        row = self._require_profile_row(profile_id)
        return self._row_to_profile_read(row)

    def create_profile(self, payload: DbProfileCreate) -> DbProfileRead:
        """Persist a new PostgreSQL connection profile and store its password in keyring/vault."""
        self._ensure_tables()
        profile_id = str(uuid.uuid4())
        now = utc_now_iso()

        if payload.password:
            self._store_password(profile_id, payload.password)

        try:
            with self.store.connection() as conn:
                if payload.is_default:
                    conn.execute("UPDATE db_profiles SET is_default = 0 WHERE is_default = 1")
                conn.execute(
                    """
                    INSERT INTO db_profiles (
                        id, name, host, port, dbname, user, sslmode,
                        read_only, is_default, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        payload.name,
                        payload.host,
                        int(payload.port),
                        payload.dbname,
                        payload.user,
                        payload.sslmode,
                        1 if payload.read_only else 0,
                        1 if payload.is_default else 0,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM db_profiles WHERE id = ?",
                    (profile_id,),
                ).fetchone()
        except Exception:
            self._delete_password(profile_id)
            raise

        self._sync_profiles_setting_mirror()
        return self._row_to_profile_read(dict(row))

    def update_profile(self, profile_id: str, payload: DbProfileUpdate) -> DbProfileRead:
        """Partially update an existing PostgreSQL profile and optionally rotate/clear its password."""
        existing = self._require_profile_row(profile_id)
        fields = payload.model_dump(exclude_unset=True)

        if "password" in fields:
            raw_pw = fields.pop("password")
            if raw_pw is not None:
                if raw_pw == "":
                    self._delete_password(profile_id)
                else:
                    self._store_password(profile_id, raw_pw)

        db_updates: dict[str, Any] = {}
        for col in ("name", "host", "port", "dbname", "user", "sslmode"):
            if col in fields and fields[col] is not None:
                db_updates[col] = fields[col]
        if "read_only" in fields and fields["read_only"] is not None:
            db_updates["read_only"] = 1 if fields["read_only"] else 0
        if "is_default" in fields and fields["is_default"] is not None:
            db_updates["is_default"] = 1 if fields["is_default"] else 0

        with self.store.connection() as conn:
            if db_updates.get("is_default") == 1:
                conn.execute(
                    "UPDATE db_profiles SET is_default = 0 WHERE id != ?",
                    (profile_id,),
                )
            if db_updates:
                db_updates["updated_at"] = utc_now_iso()
                assignments = ", ".join(f"{col} = ?" for col in db_updates)
                params = [*db_updates.values(), profile_id]
                conn.execute(f"UPDATE db_profiles SET {assignments} WHERE id = ?", params)
            else:
                conn.execute(
                    "UPDATE db_profiles SET updated_at = ? WHERE id = ?",
                    (utc_now_iso(), profile_id),
                )
            row = conn.execute(
                "SELECT * FROM db_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()

        self._sync_profiles_setting_mirror()
        return self._row_to_profile_read(dict(row) if row is not None else existing)

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a PostgreSQL connection profile and purge its stored password."""
        self._require_profile_row(profile_id)
        self._delete_password(profile_id)
        with self.store.connection() as conn:
            conn.execute("DELETE FROM db_dry_run_tokens WHERE profile_id = ?", (profile_id,))
            cursor = conn.execute("DELETE FROM db_profiles WHERE id = ?", (profile_id,))
            deleted = cursor.rowcount > 0
        self._sync_profiles_setting_mirror()
        return deleted

    def get_jdbc_credentials(self, profile_id: str) -> dict[str, Any]:
        """
        Return resolved JDBC credentials (`db_url`, `db_user`, `db_pass`, `read_only`)
        for internal JasperReports compilation/preview subprocesses.
        """
        row = self._require_profile_row(profile_id)
        password = self._load_password(profile_id) or ""
        host = str(row["host"])
        port = int(row["port"])
        dbname = str(row["dbname"])
        sslmode = str(row["sslmode"] or "prefer")
        jdbc_url = f"jdbc:postgresql://{host}:{port}/{dbname}?sslmode={sslmode}"
        return {
            "db_url": jdbc_url,
            "db_user": str(row["user"]),
            "db_pass": password,
            "read_only": bool(row["read_only"]),
        }

    # -------------------------------------------------------------------------
    # PostgreSQL Connection, Notices & Token Signing Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def compute_sql_sha256(sql_text: str) -> str:
        """Compute canonical SHA-256 hex digest of stripped SQL text."""
        normalized = sql_text.strip() if isinstance(sql_text, str) else ""
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _token_signing_key(self) -> bytes:
        secret_row = self.store.get_setting("_dry_run_hmac_secret")
        if isinstance(secret_row, str) and len(secret_row) >= 32:
            return secret_row.encode("utf-8")
        generated = secrets.token_hex(32)
        self.store.set_settings({"_dry_run_hmac_secret": generated})
        return generated.encode("utf-8")

    def _sign_dry_run_binding(
        self,
        token_nonce: str,
        project_id: str,
        profile_id: str,
        sql_sha256: str,
    ) -> str:
        payload = f"{token_nonce}:{project_id}:{profile_id}:{sql_sha256}".encode("utf-8")
        sig = hmac.new(self._token_signing_key(), payload, hashlib.sha256).hexdigest()
        return f"{token_nonce}.{sig}"

    def _verify_and_get_dry_run_token(
        self,
        *,
        dry_run_token: str,
        project_id: str,
        profile_id: str,
        sql_sha256: str,
    ) -> dict[str, Any]:
        if not isinstance(dry_run_token, str) or "." not in dry_run_token.strip():
            raise DryRunRequiredError(
                "Invalid or missing dry_run_token. Execute Dry-Run before committing."
            )
        cleaned_token = dry_run_token.strip()
        token_nonce, _ = cleaned_token.split(".", 1)
        expected_token = self._sign_dry_run_binding(
            token_nonce,
            project_id,
            profile_id,
            sql_sha256,
        )
        if not hmac.compare_digest(expected_token, cleaned_token):
            raise DryRunRequiredError(
                "Dry-Run verification failed: SQL text, project_id, or profile_id was modified after Dry-Run."
            )

        self._ensure_tables()
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM db_dry_run_tokens WHERE token = ?",
                (cleaned_token,),
            ).fetchone()

        if row is None:
            raise DryRunRequiredError(
                "Dry-Run token not found in studio store. Execute Dry-Run before committing."
            )
        record = dict(row)
        if record.get("consumed_at") is not None:
            raise DryRunRequiredError(
                "Dry-Run token has already been consumed. Run Dry-Run again for a new commit."
            )
        if (
            str(record["project_id"]) != project_id
            or str(record["profile_id"]) != profile_id
            or str(record["sql_sha256"]) != sql_sha256
        ):
            raise DryRunRequiredError(
                "Dry-Run token does not match the provided project, profile, or SQL SHA-256."
            )
        return record

    @staticmethod
    @contextmanager
    def _cursor_context(conn: Any) -> Iterator[Any]:
        cur = conn.cursor()
        if hasattr(cur, "__enter__") and hasattr(cur, "__exit__"):
            with cur as active_cur:
                yield active_cur
        else:
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()

    @staticmethod
    def _extract_notice_message(diag: Any) -> str:
        if isinstance(diag, str):
            return diag.strip()
        primary = getattr(diag, "message_primary", None) or getattr(diag, "message", None)
        if primary:
            return str(primary).strip()
        return str(diag).strip()

    @classmethod
    def _parse_template_id_from_notices(cls, notices: list[str]) -> int | None:
        parsed_id: int | None = None
        for notice in notices:
            match = _TEMPLATE_ID_NOTICE_RE.search(notice)
            if match:
                parsed_id = int(match.group(1))
        return parsed_id

    def _open_pg_connection(self, profile_id: str) -> Any:
        row = self._require_profile_row(profile_id)
        password = self._load_password(profile_id)
        conn_kwargs: dict[str, Any] = {
            "host": str(row["host"]),
            "port": int(row["port"]),
            "dbname": str(row["dbname"]),
            "user": str(row["user"]),
            "password": password if password else None,
            "sslmode": str(row["sslmode"] or "prefer"),
            "autocommit": False,
        }
        if self._connection_factory is None:
            return psycopg.connect(**conn_kwargs, connect_timeout=10)

        try:
            return self._connection_factory(**conn_kwargs)
        except TypeError:
            sig = inspect.signature(self._connection_factory)
            params = list(sig.parameters.values())
            if len(params) == 0:
                return self._connection_factory()
            if len(params) == 1:
                return self._connection_factory(conn_kwargs)
            raise

    # -------------------------------------------------------------------------
    # Connectivity Test, Transactional Dry-Run & Commit
    # -------------------------------------------------------------------------

    def test_connection(self, profile_id: str) -> DbConnectionTestResult:
        """Test PostgreSQL connectivity, measure round-trip latency (ms), and read server version."""
        profile = self.get_profile(profile_id)
        started = time.perf_counter()
        conn: Any = None
        try:
            conn = self._open_pg_connection(profile_id)
            with self._cursor_context(conn) as cur:
                cur.execute("SELECT version(), current_database(), current_user;")
                row = cur.fetchone()
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

            server_version: str | None = None
            current_db: str | None = None
            current_usr: str | None = None
            if row is not None:
                if isinstance(row, dict):
                    server_version = str(row.get("version") or "")
                    current_db = str(row.get("current_database") or "")
                    current_usr = str(row.get("current_user") or "")
                else:
                    server_version = str(row[0]) if len(row) > 0 and row[0] is not None else None
                    current_db = str(row[1]) if len(row) > 1 and row[1] is not None else None
                    current_usr = str(row[2]) if len(row) > 2 and row[2] is not None else None

            return DbConnectionTestResult(
                profile_id=profile_id,
                ok=True,
                latency_ms=latency_ms,
                server_version=server_version,
                current_database=current_db,
                current_user=current_usr,
                read_only=profile.read_only,
                message="PostgreSQL connection succeeded.",
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            return DbConnectionTestResult(
                profile_id=profile_id,
                ok=False,
                latency_ms=latency_ms,
                read_only=profile.read_only,
                message="PostgreSQL connection failed.",
                error=str(exc),
            )
        finally:
            if conn is not None:
                try:
                    if hasattr(conn, "rollback"):
                        conn.rollback()
                except Exception:
                    pass
                finally:
                    if hasattr(conn, "close"):
                        conn.close()

    def dry_run_insert(
        self,
        project_id: str,
        profile_id: str,
        sql_text: str,
    ) -> DryRunInsertResult:
        """
        Execute `sql_text` inside a non-autocommit PostgreSQL transaction, capture `RAISE NOTICE`
        diagnostics (including `ID gerado: <id>`), ALWAYS call `conn.rollback()` in `finally`,
        and persist a signed `dry_run_token` bound to `(project_id, profile_id, sha256(sql_text.strip()))`.
        """
        profile = self.get_profile(profile_id)
        if profile.read_only:
            raise ReadOnlyProfileError(
                f"Profile '{profile.name}' ({profile_id}) has read_only=True; INSERT dry-run is forbidden."
            )

        valid, syntax_msg = validate_postgres_syntax(sql_text)
        if not valid:
            raise DbProfileValidationError(syntax_msg)

        sql_sha256 = self.compute_sql_sha256(sql_text)
        notices: list[str] = []

        def _on_notice(diag: Any) -> None:
            msg = self._extract_notice_message(diag)
            if msg:
                notices.append(msg)

        started = time.perf_counter()
        conn = self._open_pg_connection(profile_id)
        try:
            if hasattr(conn, "add_notice_handler"):
                conn.add_notice_handler(_on_notice)
            with self._cursor_context(conn) as cur:
                cur.execute(sql_text)
        except Exception as exc:
            if isinstance(exc, PostgresServiceError):
                raise
            raise PostgresExecutionError(f"PostgreSQL Dry-Run failed: {exc}") from exc
        finally:
            try:
                conn.rollback()
            finally:
                if hasattr(conn, "close"):
                    conn.close()

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        simulated_id = self._parse_template_id_from_notices(notices)

        token_nonce = secrets.token_urlsafe(24)
        dry_run_token = self._sign_dry_run_binding(
            token_nonce,
            project_id,
            profile_id,
            sql_sha256,
        )

        self._ensure_tables()
        with self.store.connection() as sconn:
            sconn.execute(
                """
                INSERT INTO db_dry_run_tokens (
                    token, project_id, profile_id, sql_sha256, simulated_template_id, created_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    dry_run_token,
                    project_id,
                    profile_id,
                    sql_sha256,
                    simulated_id,
                    utc_now_iso(),
                ),
            )

        return DryRunInsertResult(
            ok=True,
            project_id=project_id,
            profile_id=profile_id,
            rolled_back=True,
            template_id=simulated_id,
            simulated_template_id=simulated_id,
            notices=notices,
            sql_sha256=sql_sha256,
            dry_run_token=dry_run_token,
            latency_ms=latency_ms,
            message="Dry-Run succeeded and transaction was safely rolled back.",
        )

    def commit_insert(
        self,
        project_id: str,
        profile_id: str,
        sql_text: str,
        dry_run_token: str,
        workspace_service: WorkspaceService | None = None,
    ) -> CommitInsertResult:
        """
        Verify `read_only=False` and exact `(project_id, profile_id, sha256(sql_text.strip()))`
        `dry_run_token` match, execute `sql_text` with `conn.commit()`, extract `template_id` from
        PostgreSQL notices, version `sql_insert`, set `project.template_db_id`, and approve `gate2_sql_insert`.
        """
        profile = self.get_profile(profile_id)
        if profile.read_only:
            raise ReadOnlyProfileError(
                f"Profile '{profile.name}' ({profile_id}) has read_only=True; COMMIT is forbidden."
            )

        sql_sha256 = self.compute_sql_sha256(sql_text)
        self._verify_and_get_dry_run_token(
            dry_run_token=dry_run_token,
            project_id=project_id,
            profile_id=profile_id,
            sql_sha256=sql_sha256,
        )

        valid, syntax_msg = validate_postgres_syntax(sql_text)
        if not valid:
            raise DbProfileValidationError(syntax_msg)

        notices: list[str] = []

        def _on_notice(diag: Any) -> None:
            msg = self._extract_notice_message(diag)
            if msg:
                notices.append(msg)

        started = time.perf_counter()
        conn = self._open_pg_connection(profile_id)
        try:
            if hasattr(conn, "add_notice_handler"):
                conn.add_notice_handler(_on_notice)
            with self._cursor_context(conn) as cur:
                cur.execute(sql_text)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if isinstance(exc, PostgresServiceError):
                raise
            raise PostgresExecutionError(f"PostgreSQL COMMIT failed: {exc}") from exc
        finally:
            if hasattr(conn, "close"):
                conn.close()

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        template_id = self._parse_template_id_from_notices(notices)

        cleaned_token = dry_run_token.strip()
        with self.store.connection() as sconn:
            sconn.execute(
                "UPDATE db_dry_run_tokens SET consumed_at = ? WHERE token = ?",
                (utc_now_iso(), cleaned_token),
            )

        artifact_version: int | None = None
        resolved_ws = workspace_service or WorkspaceService(store=self.store)
        project_exists = self.store.get_project(project_id) is not None

        if project_exists or workspace_service is not None:
            id_suffix = f" (ID gerado: {template_id})" if template_id is not None else ""
            saved_resp = resolved_ws.save_artifact(
                project_id,
                "sql_insert",
                sql_text,
                summary=f"Committed SQL INSERT to PostgreSQL profile '{profile.name}'{id_suffix}",
                created_by="user",
            )
            artifact_version = saved_resp.artifact.version_num
            if template_id is not None:
                self.store.update_project(project_id, template_db_id=template_id)
            self.store.upsert_gate(
                project_id,
                "gate2_sql_insert",
                "approved",
                decided_by="user",
                notes=f"Committed to PostgreSQL profile '{profile.name}'{id_suffix}",
            )

        return CommitInsertResult(
            ok=True,
            committed=True,
            project_id=project_id,
            profile_id=profile_id,
            template_id=template_id,
            notices=notices,
            sql_sha256=sql_sha256,
            artifact_version=artifact_version,
            gate2_status="approved",
            latency_ms=latency_ms,
            message="SQL INSERT committed successfully.",
        )

