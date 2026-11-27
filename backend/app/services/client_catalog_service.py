# -*- coding: utf-8 -*-
"""
Multi-system client catalog & local authenticated portal sync service
(`backend/app/services/client_catalog_service.py`).

Manages:
- `client_units` (1) -> `client_systems` (N) in local SQLite (`studio.db`);
- Pluggable `UnitCatalogProvider` + resilient parsers for 3 user-supplied formats
  (`normalized_json`, `portal_json`, `portal_html`);
- Dry-run diff preview (`preview_sync`) without mutating DB or leaking secrets;
- Idempotent apply (`apply_sync`) provisioning/linking `db_profiles`, `sftp_profiles`,
  and `jasperserver_profiles` while strictly enforcing PRD `read_only=True`,
  preserving custom credentials / user-chosen `dbname`, and keeping all passwords
  exclusively inside `SecretVaultService` (never in SQLite).
- Safe local collector snippet & bookmarklet generator with zero hardcoded domains.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import urllib.parse
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.db.schemas import CredentialMode, EnvironmentKind
from backend.app.db.sqlite_store import SQLiteStore, utc_now_iso
from backend.app.services.default_credentials_service import DefaultCredentialsService
from backend.app.services.postgres_service import (
    DbProfileCreate,
    DbProfileUpdate,
    PostgresService,
)
from backend.app.services.secret_vault import SecretVaultService

ClientSystemType = Literal["ambulatorial", "hospitalar", "painel", "compras", "outro"]
SyncSourceFormat = Literal["auto", "normalized_json", "portal_json", "portal_html"]

PORTAL_URL_SETTING_KEY = "management_portal_url"

CLIENT_CATALOG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS client_units (
    id TEXT PRIMARY KEY,
    external_id TEXT NULL,
    unit_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    hosting TEXT NOT NULL DEFAULT '',
    license_status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    integrations_json TEXT NOT NULL DEFAULT '[]',
    last_synced_at TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_client_units_name
    ON client_units(name ASC);

CREATE TABLE IF NOT EXISTS client_systems (
    id TEXT PRIMARY KEY,
    client_unit_id TEXT NOT NULL REFERENCES client_units(id) ON DELETE CASCADE,
    system_key TEXT NOT NULL,
    label TEXT NOT NULL,
    system_type TEXT NOT NULL DEFAULT 'ambulatorial'
        CHECK (system_type IN ('ambulatorial', 'hospitalar', 'painel', 'compras', 'outro')),
    environment TEXT NOT NULL DEFAULT 'PRD'
        CHECK (environment IN ('DEV', 'HML', 'PRD')),
    system_url TEXT NOT NULL DEFAULT '',
    version_label TEXT NOT NULL DEFAULT '',
    db_profile_id TEXT NULL,
    sftp_profile_id TEXT NULL,
    jasperserver_profile_id TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (client_unit_id, system_key)
);

CREATE INDEX IF NOT EXISTS idx_client_systems_unit
    ON client_systems(client_unit_id);

CREATE TABLE IF NOT EXISTS sftp_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL DEFAULT '',
    auth_type TEXT NOT NULL DEFAULT 'password' CHECK (auth_type IN ('password', 'private_key')),
    credential_mode TEXT NOT NULL DEFAULT 'custom' CHECK (credential_mode IN ('default', 'custom')),
    remote_base_dir TEXT NOT NULL DEFAULT '/',
    environment TEXT NOT NULL DEFAULT 'HML' CHECK (environment IN ('DEV', 'HML', 'PRD')),
    read_only INTEGER NOT NULL DEFAULT 1,
    linked_db_profile_id TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jasperserver_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    organization TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    credential_mode TEXT NOT NULL DEFAULT 'custom' CHECK (credential_mode IN ('default', 'custom')),
    default_folder_uri TEXT NOT NULL DEFAULT '/',
    environment TEXT NOT NULL DEFAULT 'HML' CHECK (environment IN ('DEV', 'HML', 'PRD')),
    read_only INTEGER NOT NULL DEFAULT 1,
    linked_db_profile_id TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# =============================================================================
# Exceptions
# =============================================================================


class ClientCatalogError(Exception):
    """Base exception for client catalog operations."""


class ClientUnitNotFoundError(ClientCatalogError):
    """Raised when a client unit does not exist."""


class ClientSystemNotFoundError(ClientCatalogError):
    """Raised when a client system does not exist."""


class ClientCatalogValidationError(ClientCatalogError):
    """Raised when client data, portal URL, or sync payloads are invalid."""


# =============================================================================
# Pydantic Models & Provider Protocol
# =============================================================================


class ClientSystemEntry(BaseModel):
    """Normalized representation of a single system/environment belonging to a client unit."""

    model_config = ConfigDict(extra="allow")

    system_key: str
    label: str
    system_type: ClientSystemType = "ambulatorial"
    environment: EnvironmentKind = "PRD"
    system_url: str = ""
    version_label: str = ""
    postgres: dict[str, Any] | None = None
    sftp: dict[str, Any] | None = None
    jasperserver: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientUnitEntry(BaseModel):
    """Normalized representation of a client unit with its 1:N systems."""

    model_config = ConfigDict(extra="allow")

    external_id: str | None = None
    unit_code: str
    name: str
    hosting: str = ""
    license_status: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    systems: list[ClientSystemEntry] = Field(default_factory=list)


class ClientCatalogPayload(BaseModel):
    """Normalized sync payload containing one or more client units."""

    model_config = ConfigDict(extra="allow")

    units: list[ClientUnitEntry] = Field(default_factory=list)
    source: str = "normalized_json"


@runtime_checkable
class UnitCatalogProvider(Protocol):
    """Pluggable provider contract for parsing raw portal data into `ClientCatalogPayload`."""

    def parse(
        self, raw_payload: str | dict[str, Any] | list[Any]
    ) -> tuple[ClientCatalogPayload, list[str]]:
        """Parse raw input into a normalized catalog payload and a list of warnings."""
        ...


class ClientSystemRead(BaseModel):
    """Persisted client system linked to optional PG/SFTP/JasperServer profiles."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_unit_id: str
    system_key: str
    label: str
    system_type: ClientSystemType = "ambulatorial"
    environment: EnvironmentKind = "PRD"
    system_url: str = ""
    version_label: str = ""
    db_profile_id: str | None = None
    sftp_profile_id: str | None = None
    jasperserver_profile_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ClientUnitRead(BaseModel):
    """Persisted client unit including all its systems."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None = None
    unit_code: str
    name: str
    hosting: str = ""
    license_status: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    systems: list[ClientSystemRead] = Field(default_factory=list)
    last_synced_at: str | None = None
    created_at: str
    updated_at: str


class ClientUnitCreate(BaseModel):
    """Payload to manually create a client unit."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, max_length=120)
    unit_code: str | None = Field(default=None, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    hosting: str = Field(default="", max_length=120)
    license_status: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Client name cannot be blank.")
        return cleaned


class ClientUnitUpdate(BaseModel):
    """Partial update payload for a client unit."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, max_length=120)
    unit_code: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hosting: str | None = Field(default=None, max_length=120)
    license_status: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None
    integrations: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _clean_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Client name cannot be blank.")
        return cleaned


def _validate_system_url(value: str) -> str:
    """Validate that a non-empty `system_url` uses an explicit `http://` or `https://` scheme."""
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            "system_url deve começar com 'http://' ou 'https://' (esquemas como javascript: ou file: não são permitidos)."
        )
    return cleaned


class ClientSystemCreate(BaseModel):
    """Payload to create or upsert a system under a client unit."""

    model_config = ConfigDict(extra="forbid")

    system_key: str | None = Field(default=None, max_length=120)
    label: str = Field(..., min_length=1, max_length=200)
    system_type: ClientSystemType = "ambulatorial"
    environment: EnvironmentKind = "PRD"
    system_url: str = Field(default="", max_length=1000)
    version_label: str = Field(default="", max_length=120)
    db_profile_id: str | None = None
    sftp_profile_id: str | None = None
    jasperserver_profile_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("System label cannot be blank.")
        return cleaned

    @field_validator("system_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return _validate_system_url(value)


class ClientSystemUpdate(BaseModel):
    """Partial update payload for a client system."""

    model_config = ConfigDict(extra="forbid")

    system_key: str | None = Field(default=None, max_length=120)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    system_type: ClientSystemType | None = None
    environment: EnvironmentKind | None = None
    system_url: str | None = Field(default=None, max_length=1000)
    version_label: str | None = Field(default=None, max_length=120)
    db_profile_id: str | None = None
    sftp_profile_id: str | None = None
    jasperserver_profile_id: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("label")
    @classmethod
    def _clean_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("System label cannot be blank.")
        return cleaned

    @field_validator("system_url")
    @classmethod
    def _validate_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_system_url(value)


class ClientSyncDiffItem(BaseModel):
    """Diff item computed for a single client unit during sync preview."""

    unit_code: str
    name: str
    action: Literal["create", "update", "unchanged"]
    systems_count: int
    changes: list[str] = Field(default_factory=list)


class ClientSyncPreviewResponse(BaseModel):
    """Dry-run sync preview response (never persists changes, never echoes passwords)."""

    ok: bool = True
    total_parsed: int
    to_create: int
    to_update: int
    unchanged: int
    warnings: list[str] = Field(default_factory=list)
    items: list[ClientSyncDiffItem] = Field(default_factory=list)
    normalized_units: list[dict[str, Any]] = Field(default_factory=list)


class ClientSyncApplyResponse(BaseModel):
    """Result summary after idempotently applying a client catalog sync."""

    ok: bool = True
    created_units: int = 0
    updated_units: int = 0
    created_systems: int = 0
    updated_systems: int = 0
    created_profiles: dict[str, int] = Field(
        default_factory=lambda: {"postgres": 0, "sftp": 0, "jasperserver": 0}
    )
    warnings: list[str] = Field(default_factory=list)


class ClientSyncSnippetResponse(BaseModel):
    """Local portal sync collector snippet, bookmarklet, and user-saved portal URL."""

    management_portal_url: str = ""
    console_snippet: str
    bookmarklet: str
    instructions: list[str] = Field(default_factory=list)


# =============================================================================
# Text Normalization & Inference Helpers
# =============================================================================


def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(value or "").lower()).strip()


def _slugify(value: str, *, fallback: str = "item", max_len: int = 64) -> str:
    norm = _strip_accents(value or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
    if not slug:
        slug = fallback
    return slug[:max_len].strip("_") or fallback


def _clean_unit_code(raw_code: str | None, *, name: str, external_id: str | None = None) -> str:
    if raw_code and raw_code.strip():
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", _strip_accents(raw_code.strip())).strip("-")
        if cleaned:
            return cleaned[:80]
    if external_id and str(external_id).strip():
        base = _slugify(name, fallback="unit", max_len=36)
        ext = re.sub(r"[^A-Za-z0-9_-]+", "", str(external_id).strip())
        return f"{base}-{ext}"[:80]
    return _slugify(name, fallback="unit", max_len=64)


def infer_system_type(text: str, *, default: ClientSystemType = "ambulatorial") -> ClientSystemType:
    """Infer Salutem system type from a label, URL, or host description."""
    norm = _normalize_text(text)
    if not norm:
        return default
    if any(k in norm for k in ("hospitalar", "hosp", "internacao", "leito")):
        return "hospitalar"
    if any(k in norm for k in ("painel", "chamada", "totem", "senhas")):
        return "painel"
    if any(k in norm for k in ("compras", "compra", "licitacao", "suprimento", "almox")):
        return "compras"
    if any(k in norm for k in ("ambulatorial", "ambul", "salutem", "upa", "ubs", "esf", "ficha")):
        return "ambulatorial"
    if any(k in norm for k in ("vpn", "proxy", "monitor", "backup", "zabbix", "grafana", "outro")):
        return "outro"
    return default


def infer_environment(text: str) -> EnvironmentKind:
    """Infer environment (`HML` for homolog/hml/teste, `DEV` for dev, else `PRD`)."""
    norm = _normalize_text(text)
    if not norm:
        return "PRD"
    if re.search(r"(?:^|[\s\-_./(])(homolog\w*|hml|teste?s?|staging|stg|trein\w*|sandbox|qa)(?:$|[\s\-_./)])", norm):
        return "HML"
    if re.search(r"(?:^|[\s\-_./(])(dev|desenv\w*)(?:$|[\s\-_./)])", norm):
        return "DEV"
    return "PRD"


def _clean_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", text):
        return ""
    if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:\d+)?(/.*)?$", text):
        return f"https://{text}"
    return ""


def _parse_host_port(
    text: str,
    *,
    default_port: int,
) -> dict[str, Any] | None:
    """Parse `user@host:port/dbname` or `host:port` or `host` into structured fields."""
    raw = (text or "").strip()
    if not raw:
        return None

    # Strip scheme if someone passed postgres:// or ssh://
    raw = re.sub(r"^(?:postgres(?:ql)?|ssh|sftp)://", "", raw, flags=re.IGNORECASE)

    user = ""
    password = ""
    dbname = ""

    # Separate path/dbname
    if "/" in raw:
        host_part, path_part = raw.split("/", 1)
        dbname = path_part.split("?", 1)[0].strip()
    else:
        host_part = raw

    # Separate user[:pass]@host
    if "@" in host_part:
        auth_part, host_part = host_part.rsplit("@", 1)
        if ":" in auth_part:
            user, password = auth_part.split(":", 1)
        else:
            user = auth_part

    host_part = host_part.strip()
    port = default_port
    if ":" in host_part and not host_part.startswith("["):
        h, p = host_part.rsplit(":", 1)
        if p.isdigit():
            host_part = h.strip()
            port = int(p)

    # Extract host token if trailing notes exist (e.g. "10.0.0.5 (usuario: ops)")
    host_match = re.match(r"^([A-Za-z0-9._-]+)", host_part)
    if not host_match:
        return None
    host = host_match.group(1)
    if not host or "." not in host and host != "localhost" and not re.match(r"^[A-Za-z0-9-]+$", host):
        return None

    result: dict[str, Any] = {"host": host, "port": port}
    if user.strip():
        result["user"] = user.strip()
    if password.strip():
        result["password"] = password.strip()
    if dbname:
        result["dbname"] = dbname
    return result


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = str(item or "").strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
    return out


def _label_tokens(text: str) -> set[str]:
    stop = {
        "bd",
        "db",
        "banco",
        "dados",
        "ssh",
        "sftp",
        "dns",
        "url",
        "link",
        "sistema",
        "servidor",
        "server",
        "jasper",
        "jasperserver",
        "acesso",
        "de",
        "do",
        "da",
        "e",
    }
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", _normalize_text(text))
        if len(tok) >= 2 and tok not in stop
    }


def _correlate_systems(
    *,
    dns_items: list[dict[str, Any]],
    bd_items: list[dict[str, Any]],
    ssh_items: list[dict[str, Any]],
    jasper_items: list[dict[str, Any]],
    versions: list[tuple[str, str]],
) -> list[ClientSystemEntry]:
    """Correlate raw DNS, BD, SSH, Jasper, and Version items into cohesive `ClientSystemEntry` rows."""
    systems: list[ClientSystemEntry] = []

    def _new_system(
        *,
        label: str,
        system_url: str = "",
        postgres: dict[str, Any] | None = None,
        sftp: dict[str, Any] | None = None,
        jasperserver: dict[str, Any] | None = None,
        default_type: ClientSystemType = "ambulatorial",
    ) -> ClientSystemEntry:
        clean_label = (label or "Sistema Principal").strip()
        hint_text = f"{clean_label} {system_url}"
        sys_type = infer_system_type(hint_text, default=default_type)
        env = infer_environment(hint_text)
        entry = ClientSystemEntry(
            system_key="",
            label=clean_label,
            system_type=sys_type,
            environment=env,
            system_url=_clean_url(system_url),
            version_label="",
            postgres=postgres,
            sftp=sftp,
            jasperserver=jasperserver,
        )
        systems.append(entry)
        return entry

    # 1. Seed from DNS / web links
    for dns in dns_items:
        label = str(dns.get("label") or dns.get("name") or "").strip()
        url = _clean_url(str(dns.get("url") or ""))
        if not label and url:
            label = "Sistema Web"
        if not label and not url:
            continue
        _new_system(label=label, system_url=url)

    def _best_system_match(
        *,
        label: str,
        target_slot: Literal["postgres", "sftp", "jasperserver"],
        host: str = "",
        allow_shared_slot: bool = False,
    ) -> ClientSystemEntry | None:
        if not systems:
            return None
        cand_type = infer_system_type(label, default="outro")
        cand_env = infer_environment(label)
        cand_tokens = _label_tokens(label)
        is_generic = cand_type == "outro" and len(cand_tokens) == 0

        best_score = -1
        best_sys: ClientSystemEntry | None = None
        for sys in systems:
            slot_val = getattr(sys, target_slot)
            if slot_val is not None and not allow_shared_slot:
                continue

            score = 0
            if sys.environment == cand_env:
                score += 6
            else:
                # Never merge HML/DEV access into PRD system or vice versa when explicit env differs
                if cand_env != "PRD" or sys.environment != "PRD":
                    continue

            if cand_type != "outro" and sys.system_type == cand_type:
                score += 8
            elif is_generic:
                score += 2
            elif cand_type != "outro" and sys.system_type != cand_type:
                # Explicit mismatched system type (e.g. hospitalar vs ambulatorial)
                continue

            overlap = len(cand_tokens & _label_tokens(sys.label))
            score += overlap * 3

            if host and sys.postgres and str(sys.postgres.get("host") or "") == host:
                score += 6
            if host and sys.sftp and str(sys.sftp.get("host") or "") == host:
                score += 6

            if slot_val is None:
                score += 2

            if score > best_score:
                best_score = score
                best_sys = sys

        return best_sys if best_score >= 4 else None

    # 2. Attach / create PostgreSQL items
    for bd in bd_items:
        host = str(bd.get("host") or "").strip()
        if not host:
            continue
        label = str(bd.get("label") or "").strip() or f"BD {host}"
        pg_dict: dict[str, Any] = {
            "label": label,
            "host": host,
            "port": int(bd.get("port") or 5432),
            "credential_mode": str(bd.get("credential_mode") or "default"),
        }
        if bd.get("dbname"):
            pg_dict["dbname"] = str(bd["dbname"]).strip()
        if bd.get("user"):
            pg_dict["user"] = str(bd["user"]).strip()

        matched = _best_system_match(label=label, target_slot="postgres", host=host)
        if matched is not None:
            matched.postgres = pg_dict
        else:
            _new_system(label=label, postgres=pg_dict)

    # 3. Attach / create SSH/SFTP items
    for ssh in ssh_items:
        host = str(ssh.get("host") or "").strip()
        if not host:
            continue
        label = str(ssh.get("label") or "").strip() or f"SSH {host}"
        sftp_dict: dict[str, Any] = {
            "label": label,
            "host": host,
            "port": int(ssh.get("port") or 22),
            "credential_mode": str(ssh.get("credential_mode") or "default"),
        }
        if ssh.get("user"):
            sftp_dict["user"] = str(ssh["user"]).strip()
        if ssh.get("password"):
            sftp_dict["password"] = str(ssh["password"])
        if ssh.get("remote_base_dir"):
            sftp_dict["remote_base_dir"] = str(ssh["remote_base_dir"]).strip()

        matched = _best_system_match(label=label, target_slot="sftp", host=host)
        if matched is not None:
            matched.sftp = sftp_dict
        else:
            _new_system(label=label, sftp=sftp_dict)

    # 4. Attach / create JasperServer items
    for js in jasper_items:
        base_url = _clean_url(str(js.get("base_url") or js.get("url") or ""))
        if not base_url:
            continue
        label = str(js.get("label") or "").strip() or "JasperServer"
        js_dict: dict[str, Any] = {
            "label": label,
            "base_url": base_url,
            "credential_mode": str(js.get("credential_mode") or "default"),
        }
        if js.get("organization"):
            js_dict["organization"] = str(js["organization"]).strip()
        if js.get("user"):
            js_dict["user"] = str(js["user"]).strip()

        cand_type = infer_system_type(label, default="outro")
        cand_env = infer_environment(label)
        cand_tokens = _label_tokens(label)
        is_generic_jasper = cand_type == "outro" and len(cand_tokens) == 0 and len(jasper_items) == 1

        if is_generic_jasper and systems:
            # Shared JasperServer across systems in the same environment
            attached = False
            for sys in systems:
                if sys.environment == cand_env and sys.jasperserver is None:
                    sys.jasperserver = dict(js_dict)
                    attached = True
            if not attached:
                systems[0].jasperserver = dict(js_dict)
        else:
            matched = _best_system_match(label=label, target_slot="jasperserver")
            if matched is not None:
                matched.jasperserver = js_dict
            else:
                _new_system(label=label, jasperserver=js_dict)

    # 5. Apply extracted version labels
    for ver_label, ver_value in versions:
        clean_ver = (ver_value or "").strip()
        if not clean_ver:
            continue
        v_type = infer_system_type(ver_label, default="outro")
        v_env = infer_environment(ver_label)
        v_tokens = _label_tokens(ver_label)
        matched_any = False
        for sys in systems:
            if v_type != "outro" and sys.system_type == v_type:
                if v_env == "PRD" or sys.environment == v_env:
                    if not sys.version_label:
                        sys.version_label = clean_ver
                    matched_any = True
            elif v_tokens and (v_tokens & _label_tokens(sys.label)):
                if not sys.version_label:
                    sys.version_label = clean_ver
                matched_any = True
        if not matched_any and len(systems) == 1 and not systems[0].version_label:
            systems[0].version_label = clean_ver

    # 6. Assign deterministic, unique `system_key` values
    used_keys: set[str] = set()
    for idx, sys in enumerate(systems):
        base_key = f"{sys.system_type}_{sys.environment.lower()}"
        if base_key not in used_keys:
            sys.system_key = base_key
            used_keys.add(base_key)
        else:
            label_slug = _slugify(sys.label, fallback=f"sys_{idx + 1}", max_len=36)
            candidate = f"{base_key}_{label_slug}"
            counter = 2
            final_key = candidate
            while final_key in used_keys:
                final_key = f"{candidate}_{counter}"
                counter += 1
            sys.system_key = final_key
            used_keys.add(final_key)

    return systems


# =============================================================================
# Format 1: Normalized JSON Provider
# =============================================================================


class NormalizedJsonProvider:
    """Parses direct `ClientCatalogPayload` JSON (`{"units": [...]}` or `[...]`)."""

    def parse(
        self, raw_payload: str | dict[str, Any] | list[Any]
    ) -> tuple[ClientCatalogPayload, list[str]]:
        data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        warnings: list[str] = []

        if isinstance(data, list):
            raw_units = data
            source = "normalized_json"
        elif isinstance(data, dict) and isinstance(data.get("units"), list):
            raw_units = data["units"]
            source = str(data.get("source") or "normalized_json")
        else:
            raise ClientCatalogValidationError(
                "Invalid normalized_json format: expected {'units': [...]} or a list of unit objects."
            )

        units: list[ClientUnitEntry] = []
        for idx, item in enumerate(raw_units):
            if not isinstance(item, dict):
                warnings.append(f"Item #{idx + 1} ignorado: formato inválido.")
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                warnings.append(f"Item #{idx + 1} ignorado: campo 'name' ausente.")
                continue
            unit_code = _clean_unit_code(
                item.get("unit_code"),
                name=name,
                external_id=str(item["external_id"]) if item.get("external_id") is not None else None,
            )
            normalized_systems: list[ClientSystemEntry] = []
            used_keys: set[str] = set()
            for s_idx, raw_sys in enumerate(item.get("systems") or []):
                if not isinstance(raw_sys, dict):
                    continue
                s_label = str(raw_sys.get("label") or "").strip() or f"Sistema {s_idx + 1}"
                s_type = raw_sys.get("system_type") or infer_system_type(s_label)
                if s_type not in ("ambulatorial", "hospitalar", "painel", "compras", "outro"):
                    s_type = infer_system_type(str(s_type))
                s_env = raw_sys.get("environment") or infer_environment(s_label)
                if s_env not in ("DEV", "HML", "PRD"):
                    s_env = infer_environment(str(s_env))
                raw_key = str(raw_sys.get("system_key") or "").strip()
                s_key = _slugify(raw_key or f"{s_type}_{s_env.lower()}_{s_label}")
                if not raw_key:
                    base = f"{s_type}_{s_env.lower()}"
                    s_key = base if base not in used_keys else _slugify(f"{base}_{s_label}")
                counter = 2
                candidate = s_key
                while candidate in used_keys:
                    candidate = f"{s_key}_{counter}"
                    counter += 1
                used_keys.add(candidate)

                normalized_systems.append(
                    ClientSystemEntry(
                        system_key=candidate,
                        label=s_label,
                        system_type=s_type,  # type: ignore[arg-type]
                        environment=s_env,  # type: ignore[arg-type]
                        system_url=_clean_url(str(raw_sys.get("system_url") or "")),
                        version_label=str(raw_sys.get("version_label") or "").strip(),
                        postgres=dict(raw_sys["postgres"]) if isinstance(raw_sys.get("postgres"), dict) else None,
                        sftp=dict(raw_sys["sftp"]) if isinstance(raw_sys.get("sftp"), dict) else None,
                        jasperserver=dict(raw_sys["jasperserver"]) if isinstance(raw_sys.get("jasperserver"), dict) else None,
                        metadata=dict(raw_sys["metadata"]) if isinstance(raw_sys.get("metadata"), dict) else {},
                    )
                )

            units.append(
                ClientUnitEntry(
                    external_id=str(item["external_id"]).strip() if item.get("external_id") is not None else None,
                    unit_code=unit_code,
                    name=name,
                    hosting=str(item.get("hosting") or "").strip(),
                    license_status=str(item.get("license_status") or "").strip(),
                    notes=str(item.get("notes") or "").strip(),
                    tags=_dedupe_strings(list(item.get("tags") or [])),
                    integrations=_dedupe_strings(list(item.get("integrations") or [])),
                    systems=normalized_systems,
                )
            )

        return ClientCatalogPayload(units=units, source=source), warnings


# =============================================================================
# Format 2: Portal JSON Provider (`/api/management/data`)
# =============================================================================


class PortalJsonProvider:
    """Resilient extractor for raw JSON payloads captured from `/api/management/data`."""

    @staticmethod
    def _extract_client_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("clients", "clientes", "units", "unidades", "items", "results", "data"):
                val = data.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
                if isinstance(val, dict):
                    nested = PortalJsonProvider._extract_client_list(val)
                    if nested:
                        return nested
        return []

    @staticmethod
    def _normalize_jasper_url(raw_url: str, *, host: str = "", port: int | None = None) -> str:
        cleaned = _clean_url(raw_url)
        if cleaned:
            # Strip trailing login/monitoring endpoints to obtain JasperServer base URL
            cleaned = re.sub(
                r"/(?:login\.html|j_spring_security_check|rest_v2(?:/.*)?|flow\.html(?:\?.*)?)$",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).rstrip("/")
            return cleaned
        host_clean = (host or "").strip()
        if not host_clean:
            return ""
        parsed = _parse_host_port(host_clean, default_port=int(port) if port else 443)
        if not parsed:
            return ""
        eff_host = parsed["host"]
        eff_port = int(port) if port else int(parsed["port"])
        scheme = "http" if eff_port in (80, 8080) else "https"
        if (scheme == "http" and eff_port == 80) or (scheme == "https" and eff_port == 443):
            return f"{scheme}://{eff_host}/jasperserver"
        return f"{scheme}://{eff_host}:{eff_port}/jasperserver"

    @staticmethod
    def _extract_dns(raw_obj: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sources = [
            raw_obj.get("dnsAccess"),
            raw_obj.get("dns"),
            raw_obj.get("links"),
            raw_obj.get("urls"),
            raw_obj.get("sistemas"),
            raw_obj.get("web_links"),
        ]
        for src in sources:
            if isinstance(src, list):
                for item in src:
                    if isinstance(item, str):
                        out.append({"label": "Sistema Web", "url": item})
                    elif isinstance(item, dict):
                        url = (
                            item.get("link")
                            or item.get("url")
                            or item.get("href")
                            or item.get("endereco")
                            or item.get("dns")
                            or ""
                        )
                        label = (
                            item.get("dnsName")
                            or item.get("label")
                            or item.get("nome")
                            or item.get("name")
                            or item.get("tipo")
                            or item.get("title")
                            or ""
                        )
                        if url or label:
                            out.append({"label": str(label), "url": str(url)})
            elif isinstance(src, dict):
                for k, v in src.items():
                    if isinstance(v, str) and v.strip():
                        out.append({"label": str(k), "url": v.strip()})
                    elif isinstance(v, dict):
                        url = v.get("link") or v.get("url") or v.get("href") or ""
                        out.append(
                            {
                                "label": str(v.get("dnsName") or v.get("label") or k),
                                "url": str(url),
                            }
                        )
        return out

    @staticmethod
    def _safe_int_port(value: Any, default: int) -> int:
        if value is None or value == "":
            return default
        try:
            port = int(str(value).strip())
            return port if 1 <= port <= 65535 else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_databases(raw_obj: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sources = [
            raw_obj.get("dbAccess"),
            raw_obj.get("bancos"),
            raw_obj.get("databases"),
            raw_obj.get("dbs"),
            raw_obj.get("bd"),
            raw_obj.get("postgres"),
        ]
        for src in sources:
            if isinstance(src, list):
                for item in src:
                    if isinstance(item, str):
                        parsed = _parse_host_port(item, default_port=5432)
                        if parsed:
                            out.append({"label": "PostgreSQL", **parsed})
                    elif isinstance(item, dict):
                        host_raw = str(
                            item.get("host")
                            or item.get("ip")
                            or item.get("servidor")
                            or item.get("endereco")
                            or item.get("address")
                            or ""
                        ).strip()
                        explicit_port = PortalJsonProvider._safe_int_port(
                            item.get("port") or item.get("porta"),
                            5432,
                        )
                        parsed = (
                            _parse_host_port(host_raw, default_port=explicit_port)
                            if host_raw
                            else None
                        )
                        if parsed:
                            entry: dict[str, Any] = {
                                "label": str(
                                    item.get("label")
                                    or item.get("nome")
                                    or item.get("name")
                                    or item.get("tipo")
                                    or "PostgreSQL"
                                ).strip(),
                                "host": parsed["host"],
                                "port": PortalJsonProvider._safe_int_port(
                                    item.get("port") or item.get("porta"),
                                    int(parsed["port"]),
                                ),
                            }
                            dbname = (
                                item.get("databaseName")
                                or item.get("dbname")
                                or item.get("database")
                                or item.get("banco")
                                or parsed.get("dbname")
                            )
                            user = (
                                item.get("adminUser")
                                or item.get("user")
                                or item.get("usuario")
                                or item.get("username")
                                or parsed.get("user")
                            )
                            if dbname and str(dbname).strip():
                                entry["dbname"] = str(dbname).strip()
                            if user and str(user).strip():
                                entry["user"] = str(user).strip()
                            out.append(entry)
            elif isinstance(src, dict):
                if src.get("host") or src.get("ip"):
                    out.extend(PortalJsonProvider._extract_databases({"bd": [src]}))
                else:
                    for k, v in src.items():
                        if isinstance(v, str):
                            parsed = _parse_host_port(v, default_port=5432)
                            if parsed:
                                out.append({"label": str(k), **parsed})
                        elif isinstance(v, dict):
                            merged = {"label": str(k), **v}
                            out.extend(PortalJsonProvider._extract_databases({"bd": [merged]}))
        return out

    @staticmethod
    def _extract_ssh(raw_obj: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sources = [
            raw_obj.get("sshAccess"),
            raw_obj.get("ssh"),
            raw_obj.get("sftp"),
            raw_obj.get("servidores"),
            raw_obj.get("servers"),
        ]
        for src in sources:
            if isinstance(src, list):
                for item in src:
                    if isinstance(item, str):
                        parsed = _parse_host_port(item, default_port=22)
                        if parsed:
                            out.append({"label": "SSH", **parsed})
                    elif isinstance(item, dict):
                        host_raw = str(
                            item.get("host")
                            or item.get("ip")
                            or item.get("servidor")
                            or item.get("endereco")
                            or item.get("address")
                            or ""
                        ).strip()
                        explicit_port = PortalJsonProvider._safe_int_port(
                            item.get("port") or item.get("porta"),
                            22,
                        )
                        parsed = (
                            _parse_host_port(host_raw, default_port=explicit_port)
                            if host_raw
                            else None
                        )
                        if parsed:
                            entry: dict[str, Any] = {
                                "label": str(
                                    item.get("label")
                                    or item.get("nome")
                                    or item.get("name")
                                    or item.get("tipo")
                                    or "SSH"
                                ).strip(),
                                "host": parsed["host"],
                                "port": PortalJsonProvider._safe_int_port(
                                    item.get("port") or item.get("porta"),
                                    int(parsed["port"]),
                                ),
                            }
                            user = (
                                item.get("user")
                                or item.get("usuario")
                                or item.get("username")
                                or parsed.get("user")
                            )
                            password = (
                                item.get("password")
                                or item.get("senha")
                                or parsed.get("password")
                            )
                            remote_dir = (
                                item.get("remote_base_dir")
                                or item.get("diretorio")
                                or item.get("path")
                            )
                            if user and str(user).strip():
                                entry["user"] = str(user).strip()
                            if password and str(password):
                                entry["password"] = str(password)
                            if remote_dir and str(remote_dir).strip():
                                entry["remote_base_dir"] = str(remote_dir).strip()
                            out.append(entry)
            elif isinstance(src, dict):
                if src.get("host") or src.get("ip"):
                    out.extend(PortalJsonProvider._extract_ssh({"ssh": [src]}))
                else:
                    for k, v in src.items():
                        if isinstance(v, str):
                            parsed = _parse_host_port(v, default_port=22)
                            if parsed:
                                out.append({"label": str(k), **parsed})
                        elif isinstance(v, dict):
                            out.extend(PortalJsonProvider._extract_ssh({"ssh": [{"label": str(k), **v}]}))
        return out

    @staticmethod
    def _extract_jasper(raw_obj: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sources = [
            raw_obj.get("jasperAccess"),
            raw_obj.get("jasper"),
            raw_obj.get("jasperserver"),
            raw_obj.get("jasper_urls"),
            raw_obj.get("jasper_servers"),
        ]
        for src in sources:
            if isinstance(src, str) and src.strip():
                url = PortalJsonProvider._normalize_jasper_url(src)
                if url:
                    out.append({"label": "JasperServer", "base_url": url})
            elif isinstance(src, list):
                for item in src:
                    if isinstance(item, str) and item.strip():
                        url = PortalJsonProvider._normalize_jasper_url(item)
                        if url:
                            out.append({"label": "JasperServer", "base_url": url})
                    elif isinstance(item, dict):
                        raw_url = str(
                            item.get("base_url")
                            or item.get("url")
                            or item.get("monitoringUrl")
                            or item.get("link")
                            or item.get("href")
                            or ""
                        ).strip()
                        raw_host = str(item.get("host") or item.get("ip") or "").strip()
                        raw_port = item.get("port") or item.get("porta")
                        port_int = (
                            PortalJsonProvider._safe_int_port(raw_port, 443)
                            if raw_port is not None and raw_port != ""
                            else None
                        )
                        url = PortalJsonProvider._normalize_jasper_url(
                            raw_url,
                            host=raw_host,
                            port=port_int,
                        )
                        if url:
                            entry: dict[str, Any] = {
                                "label": str(
                                    item.get("label")
                                    or item.get("nome")
                                    or item.get("name")
                                    or "JasperServer"
                                ).strip(),
                                "base_url": url,
                            }
                            if item.get("organization") or item.get("org"):
                                entry["organization"] = str(
                                    item.get("organization") or item.get("org")
                                ).strip()
                            if item.get("user") or item.get("usuario") or item.get("username"):
                                entry["user"] = str(
                                    item.get("user")
                                    or item.get("usuario")
                                    or item.get("username")
                                ).strip()
                            out.append(entry)
            elif isinstance(src, dict):
                if src.get("url") or src.get("base_url") or src.get("monitoringUrl") or src.get("host"):
                    out.extend(PortalJsonProvider._extract_jasper({"jasper": [src]}))
                else:
                    for k, v in src.items():
                        if isinstance(v, str) and v.strip():
                            url = PortalJsonProvider._normalize_jasper_url(v)
                            if url:
                                out.append({"label": str(k), "base_url": url})
                        elif isinstance(v, dict):
                            out.extend(
                                PortalJsonProvider._extract_jasper({"jasper": [{"label": str(k), **v}]})
                            )
        return out

    @staticmethod
    def _extract_versions(raw_obj: dict[str, Any]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        sources = [
            raw_obj.get("versionUrls"),
            raw_obj.get("versoes"),
            raw_obj.get("versions"),
            raw_obj.get("versoes_sistema"),
        ]
        for src in sources:
            if isinstance(src, dict):
                for k, v in src.items():
                    if v:
                        out.append((str(k), str(v).strip()))
            elif isinstance(src, list):
                for item in src:
                    if isinstance(item, dict):
                        lbl = str(
                            item.get("label")
                            or item.get("sistema")
                            or item.get("nome")
                            or item.get("name")
                            or ""
                        ).strip()
                        ver = str(
                            item.get("versao")
                            or item.get("version")
                            or item.get("value")
                            or ""
                        ).strip()
                        if ver and ver.upper() != "N/A":
                            out.append((lbl or "Sistema", ver))
                    elif isinstance(item, str) and ":" in item:
                        lbl, ver = item.split(":", 1)
                        out.append((lbl.strip(), ver.strip()))
        return out

    def parse(
        self, raw_payload: str | dict[str, Any] | list[Any]
    ) -> tuple[ClientCatalogPayload, list[str]]:
        data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        raw_clients = self._extract_client_list(data)
        warnings: list[str] = []
        if not raw_clients:
            raise ClientCatalogValidationError(
                "No client entries found in portal_json payload."
            )

        # Optional top-level relational lookup tables from `/api/management/data`
        estab_by_id: dict[str, str] = {}
        org_by_id: dict[str, str] = {}
        integs_by_client: dict[str, list[str]] = {}
        license_by_client: dict[str, str] = {}
        if isinstance(data, dict):
            for est in data.get("estabelecimentos") or []:
                if isinstance(est, dict) and est.get("id") is not None and est.get("name"):
                    estab_by_id[str(est["id"])] = str(est["name"]).strip()
            for org in data.get("organizations") or []:
                if isinstance(org, dict) and org.get("id") is not None and org.get("name"):
                    org_by_id[str(org["id"])] = str(org["name"]).strip()
            for ci in data.get("clientIntegrations") or []:
                if not isinstance(ci, dict) or ci.get("clientId") is None:
                    continue
                iname = str(ci.get("integrationName") or ci.get("name") or "").strip()
                itype = str(ci.get("typeName") or ci.get("type") or "").strip()
                if not iname:
                    continue
                label = f"{iname} ({itype})" if itype else iname
                integs_by_client.setdefault(str(ci["clientId"]), []).append(label)
            for lic in data.get("licenses") or []:
                if not isinstance(lic, dict) or lic.get("clientId") is None:
                    continue
                cid = str(lic["clientId"])
                if cid not in license_by_client:
                    license_by_client[cid] = "Ativa" if lic.get("isActive") else "Inativa"

        units: list[ClientUnitEntry] = []
        for idx, item in enumerate(raw_clients):
            name = str(
                item.get("name")
                or item.get("nome")
                or item.get("title")
                or item.get("cliente")
                or item.get("companyName")
                or item.get("razao_social")
                or ""
            ).strip()
            if not name:
                warnings.append(f"Registro #{idx + 1} do portal ignorado: nome ausente.")
                continue

            ext_id_val = item.get("external_id") or item.get("id") or item.get("codigo_externo")
            external_id = (
                str(ext_id_val).strip()
                if ext_id_val is not None and str(ext_id_val).strip()
                else None
            )
            raw_code = item.get("unit_code") or item.get("sigla") or item.get("code") or item.get("codigo")
            unit_code = _clean_unit_code(
                str(raw_code) if raw_code is not None else None,
                name=name,
                external_id=external_id,
            )

            hosting = str(
                item.get("hostingType")
                or item.get("hosting")
                or item.get("hospedagem")
                or item.get("infra")
                or item.get("tipo_hospedagem")
                or ""
            ).strip()
            license_status = str(
                item.get("licenseStatus")
                or item.get("license_status")
                or item.get("licenca")
                or item.get("status_licenca")
                or item.get("status")
                or (license_by_client.get(external_id, "") if external_id else "")
                or ""
            ).strip()
            notes = str(
                item.get("notes")
                or item.get("observacoes")
                or item.get("description")
                or ""
            ).strip()

            raw_tags = item.get("tags") or item.get("etiquetas") or []
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            tag_items: list[str] = [
                t.get("name") or t.get("label") or "" if isinstance(t, dict) else str(t)
                for t in (raw_tags if isinstance(raw_tags, list) else [])
            ]
            est_id = item.get("estabelecimentoId")
            if est_id is not None and str(est_id) in estab_by_id:
                tag_items.append(estab_by_id[str(est_id)])
            org_id = item.get("organizationId")
            if org_id is not None and str(org_id) in org_by_id:
                tag_items.append(org_by_id[str(org_id)])
            tags = _dedupe_strings(tag_items)

            access_container: dict[str, Any] = dict(item)
            for nested_key in ("acessos", "acessos_tecnicos", "technical_access", "accesses"):
                if isinstance(item.get(nested_key), dict):
                    access_container.update(item[nested_key])

            raw_integs = (
                access_container.get("integrations")
                or access_container.get("integracoes")
                or item.get("integrations")
                or item.get("integracoes")
                or []
            )
            if isinstance(raw_integs, str):
                raw_integs = [x.strip() for x in re.split(r"[,;\n]+", raw_integs) if x.strip()]
            integ_list: list[str] = []
            for x in (raw_integs if isinstance(raw_integs, list) else []):
                if isinstance(x, dict):
                    if x.get("status") is False:
                        continue
                    iname = str(x.get("name") or x.get("nome") or x.get("label") or "").strip()
                    itype = str(x.get("type") or x.get("typeName") or "").strip()
                    if iname:
                        integ_list.append(f"{iname} ({itype})" if itype else iname)
                elif str(x).strip():
                    integ_list.append(str(x).strip())
            if external_id and external_id in integs_by_client:
                integ_list.extend(integs_by_client[external_id])
            integrations = _dedupe_strings(integ_list)

            systems = _correlate_systems(
                dns_items=self._extract_dns(access_container),
                bd_items=self._extract_databases(access_container),
                ssh_items=self._extract_ssh(access_container),
                jasper_items=self._extract_jasper(access_container),
                versions=self._extract_versions(item),
            )
            if not systems:
                warnings.append(f"Cliente '{name}' sem acessos técnicos/DNS identificados.")

            units.append(
                ClientUnitEntry(
                    external_id=external_id,
                    unit_code=unit_code,
                    name=name,
                    hosting=hosting,
                    license_status=license_status,
                    notes=notes,
                    tags=tags,
                    integrations=integrations,
                    systems=systems,
                )
            )

        return ClientCatalogPayload(units=units, source="portal_json"), warnings


# =============================================================================
# Format 3: Portal HTML Provider (`.management-client-card`)
# =============================================================================


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_HtmlNode] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts: list[str] = []

        def _walk(node: _HtmlNode) -> None:
            for t in node.text_parts:
                parts.append(t)
            for child in node.children:
                if child.tag in ("br", "li", "div", "p", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd"):
                    parts.append("\n")
                _walk(child)
                if child.tag in ("li", "div", "p", "tr", "h1", "h2", "h3", "h4", "h5", "dt", "dd"):
                    parts.append("\n")

        _walk(self)
        return re.sub(r"[ \t]+", " ", "".join(parts)).strip()

    def inline_text(self) -> str:
        return re.sub(r"\s+", " ", self.text()).strip()

    def iter_descendants(self) -> list[_HtmlNode]:
        result: list[_HtmlNode] = []
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(reversed(node.children))
        return result


class _SimpleDomBuilder(HTMLParser):
    _VOID_TAGS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode(tag="root")
        self._stack: list[_HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        node = _HtmlNode(
            tag=tag_l,
            attrs={k.lower(): (v or "") for k, v in attrs},
        )
        self._stack[-1].children.append(node)
        if tag_l not in self._VOID_TAGS:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == tag_l:
                del self._stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].text_parts.append(data)


class PortalHtmlProvider:
    """Parses saved portal HTML containing `.management-client-card` elements."""

    _SECTION_HEADER_RE = re.compile(
        r"^(DNS|SSH|SFTP|BD|Banco(?:s)?(?:\s+de\s+Dados)?|Jasper(?:Server)?|Integra[cç][oõ]es|Vers[oõ]es(?:\s+do\s+Sistema)?|Acessos\s+T[eé]cnicos)\s*:?\s*(.*)$",
        re.IGNORECASE,
    )

    @staticmethod
    def _classify_section(header: str) -> str:
        norm = _normalize_text(header)
        if norm.startswith("dns"):
            return "dns"
        if norm.startswith(("ssh", "sftp")):
            return "ssh"
        if norm.startswith(("bd", "banco")):
            return "bd"
        if norm.startswith("jasper"):
            return "jasper"
        if norm.startswith("integrac"):
            return "integrations"
        if norm.startswith("vers"):
            return "versions"
        if norm.startswith("acessos"):
            return "accesses"
        return ""

    def _parse_card(self, card: _HtmlNode) -> ClientUnitEntry | None:
        descendants = card.iter_descendants()

        # 1. Name
        name = (card.attrs.get("data-gestao-card-title") or "").strip()
        if not name:
            for node in descendants:
                if node.tag in ("h1", "h2", "h3", "h4") or "card-title" in node.classes:
                    txt = node.inline_text()
                    if txt:
                        name = txt
                        break
        if not name:
            return None

        # 2. Badges: ID, Hosting, License, Tags
        external_id: str | None = (card.attrs.get("data-client-id") or card.attrs.get("data-id") or "").strip() or None
        hosting = ""
        license_status = ""
        tags: list[str] = []

        for node in descendants:
            cls_str = " ".join(node.classes).lower()
            if node.tag == "span" or "badge" in cls_str or "pill" in cls_str or "tag" in cls_str:
                txt = node.inline_text()
                if not txt or len(txt) > 80:
                    continue
                id_match = re.match(r"^ID\s*:\s*([A-Za-z0-9_-]+)$", txt, re.IGNORECASE)
                if id_match:
                    external_id = id_match.group(1)
                    continue
                norm_txt = _normalize_text(txt)
                if norm_txt in ("on-premise", "on premise", "onpremise", "cloud", "nuvem", "saas", "hibrido", "local"):
                    hosting = txt
                    continue
                if any(k in norm_txt for k in ("licenca", "ativa", "ativo", "inativo", "suspens", "bloquead", "trial", "vencid")):
                    if not license_status:
                        license_status = txt
                    continue
                if "tag" in cls_str or "pill" in cls_str:
                    tags.append(txt)

        if not external_id:
            full_text = card.text()
            m_id = re.search(r"\bID\s*:\s*([A-Za-z0-9_-]+)\b", full_text)
            if m_id:
                external_id = m_id.group(1)

        # 3. Extract structured anchor/password metadata per section
        dns_items: list[dict[str, Any]] = []
        bd_items: list[dict[str, Any]] = []
        ssh_items: list[dict[str, Any]] = []
        jasper_items: list[dict[str, Any]] = []
        versions: list[tuple[str, str]] = []
        integrations: list[str] = []

        seen_dns_urls: set[str] = set()
        seen_jasper_urls: set[str] = set()

        # Walk top-level/nested block nodes to track active section & capture links/password inputs
        def _extract_links_from_node(node: _HtmlNode) -> list[tuple[str, str]]:
            links: list[tuple[str, str]] = []
            for d in [node, *node.iter_descendants()]:
                if d.tag == "a" and d.attrs.get("href"):
                    href = d.attrs["href"].strip()
                    if href.startswith(("http://", "https://")):
                        links.append((d.inline_text(), href))
            return links

        def _extract_password_from_node(node: _HtmlNode) -> str:
            for d in [node, *node.iter_descendants()]:
                if d.attrs.get("data-password"):
                    return d.attrs["data-password"].strip()
                if d.attrs.get("data-secret"):
                    return d.attrs["data-secret"].strip()
                if d.tag == "input" and d.attrs.get("type", "").lower() == "password" and d.attrs.get("value"):
                    return d.attrs["value"].strip()
            txt = node.inline_text()
            m_pw = re.search(r"(?:senha|pass(?:word)?)\s*[:=]\s*([^\s|;,)]+)", txt, re.IGNORECASE)
            if m_pw:
                val = m_pw.group(1).strip()
                if val and not set(val) <= {"*", "•"}:
                    return val
            return ""

        def _consume_line(section: str, line: str, *, node: _HtmlNode | None = None) -> None:
            clean = line.strip(" -•|\t")
            if not clean:
                return

            if section == "versions":
                # Supports "Ambulatorial: 4.12.0" or "Ambulatorial v4.12.0"
                m = re.match(r"^([^:]+?)\s*:\s*(.+)$", clean)
                if m:
                    versions.append((m.group(1).strip(), m.group(2).strip()))
                else:
                    m2 = re.match(r"^([A-Za-zÀ-ÿ\s]+?)\s+(v?\d+(?:\.\d+)+[^\s]*)$", clean)
                    if m2:
                        versions.append((m2.group(1).strip(), m2.group(2).strip()))
                return

            if section == "integrations":
                for part in re.split(r"[,;|]+", clean):
                    p = part.strip()
                    if p:
                        integrations.append(p)
                return

            if section == "dns":
                url_match = re.search(r"(https?://[^\s<>\"]+)", clean)
                if url_match:
                    url = url_match.group(1).rstrip(".,;)")
                    if url not in seen_dns_urls:
                        seen_dns_urls.add(url)
                        prefix = clean[: url_match.start()].strip(" :-–—|")
                        label = prefix or "Sistema Web"
                        dns_items.append({"label": label, "url": url})
                return

            if section == "jasper":
                url_match = re.search(r"(https?://[^\s<>\"]+)", clean)
                if url_match:
                    url = url_match.group(1).rstrip(".,;)")
                    if url not in seen_jasper_urls:
                        seen_jasper_urls.add(url)
                        prefix = clean[: url_match.start()].strip(" :-–—|")
                        label = prefix or "JasperServer"
                        jasper_items.append({"label": label, "base_url": url})
                return

            if section == "bd":
                # e.g. "Ambulatorial: 10.0.1.20:5432" or "BD Hospitalar — 10.0.1.21:5432/salutem_hosp"
                m = re.search(r"([A-Za-z0-9._-]+@[A-Za-z0-9._-]+(?::\d+)?(?:/[A-Za-z0-9._-]+)?|\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/[A-Za-z0-9._-]+)?|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)(?:/[A-Za-z0-9._-]+)?)", clean)
                if m:
                    parsed = _parse_host_port(m.group(1), default_port=5432)
                    if parsed:
                        prefix = clean[: m.start()].strip(" :-–—|")
                        label = prefix or "PostgreSQL"
                        bd_items.append({"label": label, **parsed})
                return

            if section == "ssh":
                m = re.search(r"([A-Za-z0-9._-]+@[A-Za-z0-9._-]+(?::\d+)?|\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+:\d+)", clean)
                if m:
                    parsed = _parse_host_port(m.group(1), default_port=22)
                    if parsed:
                        prefix = clean[: m.start()].strip(" :-–—|")
                        label = prefix or "SSH"
                        # Check for inline user/password after host
                        tail = clean[m.end() :]
                        if "user" not in parsed:
                            m_usr = re.search(r"(?:user|usu[aá]rio)\s*[:=]\s*([^\s|;,)]+)", tail, re.IGNORECASE)
                            if m_usr:
                                parsed["user"] = m_usr.group(1).strip()
                        pw = _extract_password_from_node(node) if node is not None else ""
                        if not pw:
                            m_pw = re.search(r"(?:senha|pass(?:word)?)\s*[:=]\s*([^\s|;,)]+)", tail, re.IGNORECASE)
                            if m_pw:
                                val = m_pw.group(1).strip()
                                if val and not set(val) <= {"*", "•"}:
                                    pw = val
                        if pw:
                            parsed["password"] = pw
                        ssh_items.append({"label": label, **parsed})
                return

        # Structured traversal: visit leaf structural blocks in document order
        structural_tags = frozenset(
            {
                "section",
                "article",
                "div",
                "ul",
                "ol",
                "li",
                "p",
                "table",
                "thead",
                "tbody",
                "tr",
                "dl",
                "dt",
                "dd",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            }
        )
        current_section = ""
        block_nodes = [
            n
            for n in descendants
            if n.tag in structural_tags or n.tag == "strong"
        ]
        # Track nodes already consumed as part of a leaf block so inline <strong> inside <li> isn't re-parsed
        consumed_nodes: set[int] = set()
        for node in block_nodes:
            if id(node) in consumed_nodes:
                continue
            has_child_blocks = any(c.tag in structural_tags for c in node.children)
            direct_text = re.sub(r"\s+", " ", "".join(node.text_parts)).strip()
            inline = node.inline_text()

            if has_child_blocks:
                # Container node: only inspect direct text if it declares a section header
                if direct_text:
                    m_hdr = self._SECTION_HEADER_RE.match(direct_text)
                    if m_hdr:
                        sec = self._classify_section(m_hdr.group(1))
                        if sec:
                            current_section = sec
                            if m_hdr.group(2).strip():
                                _consume_line(current_section, m_hdr.group(2).strip(), node=node)
                continue

            for d in node.iter_descendants():
                consumed_nodes.add(id(d))

            if not inline:
                continue

            m_hdr = self._SECTION_HEADER_RE.match(inline)
            if m_hdr:
                sec = self._classify_section(m_hdr.group(1))
                if sec:
                    current_section = sec
                    rest = m_hdr.group(2).strip()
                    links = _extract_links_from_node(node)
                    if current_section == "dns" and links:
                        for l_txt, href in links:
                            if href not in seen_dns_urls:
                                seen_dns_urls.add(href)
                                label = l_txt if l_txt and not l_txt.startswith("http") else (rest.split("http")[0].strip(" :-") or "Sistema Web")
                                dns_items.append({"label": label, "url": href})
                    elif current_section == "jasper" and links:
                        for l_txt, href in links:
                            if href not in seen_jasper_urls:
                                seen_jasper_urls.add(href)
                                label = l_txt if l_txt and not l_txt.startswith("http") else "JasperServer"
                                jasper_items.append({"label": label, "base_url": href})
                    elif rest:
                        _consume_line(current_section, rest, node=node)
                    continue

            if current_section in ("dns", "jasper"):
                links = _extract_links_from_node(node)
                if links:
                    for l_txt, href in links:
                        if current_section == "dns" and href not in seen_dns_urls:
                            seen_dns_urls.add(href)
                            # Derive label from text before link or link text
                            label = inline.replace(href, "").strip(" :-–—|")
                            if not label or label == l_txt:
                                label = l_txt if not l_txt.startswith("http") else "Sistema Web"
                            else:
                                # Remove duplicate link text if inline was "Ambulatorial: https://..."
                                label = label.replace(l_txt, "").strip(" :-–—|") or l_txt
                            dns_items.append({"label": label, "url": href})
                        elif current_section == "jasper" and href not in seen_jasper_urls:
                            seen_jasper_urls.add(href)
                            label = inline.replace(href, "").strip(" :-–—|")
                            if not label or label.startswith("http"):
                                label = l_txt if l_txt and not l_txt.startswith("http") else "JasperServer"
                            jasper_items.append({"label": label, "base_url": href})
                    continue

            if current_section:
                _consume_line(current_section, inline, node=node)

        systems = _correlate_systems(
            dns_items=dns_items,
            bd_items=bd_items,
            ssh_items=ssh_items,
            jasper_items=jasper_items,
            versions=versions,
        )

        unit_code = _clean_unit_code(None, name=name, external_id=external_id)
        return ClientUnitEntry(
            external_id=external_id,
            unit_code=unit_code,
            name=name,
            hosting=hosting,
            license_status=license_status,
            tags=_dedupe_strings(tags),
            integrations=_dedupe_strings(integrations),
            systems=systems,
        )

    def parse(
        self, raw_payload: str | dict[str, Any] | list[Any]
    ) -> tuple[ClientCatalogPayload, list[str]]:
        if not isinstance(raw_payload, str):
            raise ClientCatalogValidationError("portal_html parser requires an HTML string.")

        builder = _SimpleDomBuilder()
        builder.feed(raw_payload)
        builder.close()

        cards = [
            node
            for node in builder.root.iter_descendants()
            if "management-client-card" in node.classes or "data-gestao-card-title" in node.attrs
        ]
        # Avoid double-counting nested elements inside a matched card
        top_cards: list[_HtmlNode] = []
        card_set = set(id(c) for c in cards)
        for c in cards:
            desc_ids = {id(d) for d in c.iter_descendants()}
            if not any(id(other) in desc_ids for other in top_cards):
                # Also skip if c is inside an already collected card
                if not any(id(c) in {id(d) for d in prev.iter_descendants()} for prev in top_cards):
                    top_cards.append(c)
        _ = card_set

        warnings: list[str] = []
        if not top_cards:
            raise ClientCatalogValidationError(
                "Nenhum card '.management-client-card' encontrado no HTML fornecido."
            )

        units: list[ClientUnitEntry] = []
        for idx, card in enumerate(top_cards):
            parsed = self._parse_card(card)
            if parsed is None:
                warnings.append(f"Card HTML #{idx + 1} ignorado: título não encontrado.")
                continue
            if not parsed.systems:
                warnings.append(f"Cliente '{parsed.name}' sem sistemas/acessos técnicos detectados no card.")
            units.append(parsed)

        return ClientCatalogPayload(units=units, source="portal_html"), warnings


# =============================================================================
# Security Sanitizer for Preview Output
# =============================================================================


def _redact_unit_for_preview(unit: ClientUnitEntry) -> dict[str, Any]:
    """Serialize a `ClientUnitEntry` for preview response, stripping any plaintext secrets."""
    dumped = unit.model_dump(mode="json")
    for sys_item in dumped.get("systems") or []:
        for conn_key in ("postgres", "sftp", "jasperserver"):
            conn = sys_item.get(conn_key)
            if isinstance(conn, dict):
                had_pw = bool(conn.pop("password", None))
                conn.pop("private_key", None)
                conn.pop("passphrase", None)
                if had_pw and conn_key == "sftp":
                    sys_item.setdefault("metadata", {})["has_ssh_password_in_source"] = True
    return dumped


# =============================================================================
# Collector Snippet & Bookmarklet Generator (ZERO hardcoded portal URLs)
# =============================================================================


def _build_console_snippet() -> str:
    return (
        "(async () => {\n"
        "  const download = (payload) => {\n"
        "    const json = JSON.stringify(payload, null, 2);\n"
        "    const blob = new Blob([json], { type: 'application/json' });\n"
        "    const url = URL.createObjectURL(blob);\n"
        "    const a = document.createElement('a');\n"
        "    a.href = url;\n"
        "    a.download = 'salutem-clients-export.json';\n"
        "    document.body.appendChild(a);\n"
        "    a.click();\n"
        "    a.remove();\n"
        "    setTimeout(() => URL.revokeObjectURL(url), 1500);\n"
        "    return json;\n"
        "  };\n"
        "  const copyOrDownload = async (payload) => {\n"
        "    const json = JSON.stringify(payload, null, 2);\n"
        "    try {\n"
        "      await navigator.clipboard.writeText(json);\n"
        "      console.info('[Salutem Studio] JSON copiado para a área de transferência.');\n"
        "    } catch {\n"
        "      download(payload);\n"
        "      console.info('[Salutem Studio] Arquivo salutem-clients-export.json baixado.');\n"
        "    }\n"
        "    return payload;\n"
        "  };\n"
        "  try {\n"
        "    const res = await fetch('/api/management/data', { credentials: 'include' });\n"
        "    if (res.ok) {\n"
        "      const data = await res.json();\n"
        "      return await copyOrDownload(data);\n"
        "    }\n"
        "  } catch {}\n"
        "  const cards = Array.from(document.querySelectorAll('.management-client-card, [data-gestao-card-title]'));\n"
        "  const html = cards.map((el) => el.outerHTML).join('\\n');\n"
        "  if (!html) {\n"
        "    console.warn('[Salutem Studio] Nenhum card de cliente encontrado nesta página.');\n"
        "    return null;\n"
        "  }\n"
        "  try {\n"
        "    await navigator.clipboard.writeText(html);\n"
        "    console.info('[Salutem Studio] HTML dos cards copiado para a área de transferência.');\n"
        "  } catch {\n"
        "    const blob = new Blob([html], { type: 'text/html' });\n"
        "    const a = document.createElement('a');\n"
        "    a.href = URL.createObjectURL(blob);\n"
        "    a.download = 'salutem-clients-cards.html';\n"
        "    a.click();\n"
        "  }\n"
        "  return { cards_captured: cards.length };\n"
        "})();"
    )


def _build_bookmarklet() -> str:
    compact = (
        "(async()=>{const d=(p)=>{const j=JSON.stringify(p,null,2);"
        "navigator.clipboard.writeText(j).then(()=>alert('JSON copiado! Cole no Salutem Studio.'))"
        ".catch(()=>{const a=document.createElement('a');"
        "a.href=URL.createObjectURL(new Blob([j],{type:'application/json'}));"
        "a.download='salutem-clients-export.json';a.click();});};"
        "try{const r=await fetch('/api/management/data',{credentials:'include'});"
        "if(r.ok){d(await r.json());return;}}catch{}"
        "const c=[...document.querySelectorAll('.management-client-card,[data-gestao-card-title]')];"
        "if(!c.length){alert('Nenhum card de cliente encontrado.');return;}"
        "const h=c.map(e=>e.outerHTML).join('\\n');"
        "navigator.clipboard.writeText(h).then(()=>alert('HTML de '+c.length+' cards copiado!'))"
        ".catch(()=>{const a=document.createElement('a');"
        "a.href=URL.createObjectURL(new Blob([h],{type:'text/html'}));"
        "a.download='salutem-clients-cards.html';a.click();});})();"
    )
    return "javascript:" + urllib.parse.quote(compact, safe="()[]{}=:;,.!/'")


# =============================================================================
# ClientCatalogService
# =============================================================================


class ClientCatalogService:
    """Manages multi-system client units, authenticated portal sync, and profile provisioning."""

    def __init__(
        self,
        store: SQLiteStore | None = None,
        *,
        vault: SecretVaultService | None = None,
        postgres_service: PostgresService | None = None,
        default_credentials_service: DefaultCredentialsService | None = None,
    ) -> None:
        self.store = store or SQLiteStore()
        self.vault = vault or SecretVaultService()
        self.default_credentials = default_credentials_service or DefaultCredentialsService(
            store=self.store,
            vault=self.vault,
        )
        self.postgres_service = postgres_service or PostgresService(
            store=self.store,
            vault=self.vault,
            default_credentials_service=self.default_credentials,
        )
        self._initialized_dbs: set[Any] = set()
        self._providers: dict[str, UnitCatalogProvider] = {
            "normalized_json": NormalizedJsonProvider(),
            "portal_json": PortalJsonProvider(),
            "portal_html": PortalHtmlProvider(),
        }

    def _ensure_tables(self) -> None:
        db_target = self.store.db_path
        if db_target in self._initialized_dbs and db_target.exists():
            return
        self.postgres_service._ensure_tables()
        with self.store.connection() as conn:
            conn.executescript(CLIENT_CATALOG_SCHEMA_SQL)
        self._initialized_dbs.add(db_target)

    # -------------------------------------------------------------------------
    # Local Portal URL Config & Collector Snippet
    # -------------------------------------------------------------------------

    def get_portal_url(self) -> str:
        """Return user-configured local management portal URL (always empty by default)."""
        val = self.store.get_setting(PORTAL_URL_SETTING_KEY, "")
        return str(val or "").strip()

    def set_portal_url(self, url: str) -> str:
        """Persist or clear the local management portal URL in SQLite `app_settings`."""
        cleaned = (url or "").strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            raise ClientCatalogValidationError(
                "A URL do portal deve começar com http:// ou https:// (ou ficar vazia para limpar)."
            )
        self.store.set_settings({PORTAL_URL_SETTING_KEY: cleaned})
        return cleaned

    def get_collector_snippet(self) -> ClientSyncSnippetResponse:
        """Return safe console snippet, bookmarklet, and locally saved portal URL."""
        return ClientSyncSnippetResponse(
            management_portal_url=self.get_portal_url(),
            console_snippet=_build_console_snippet(),
            bookmarklet=_build_bookmarklet(),
            instructions=[
                "1. Informe e salve localmente a URL do portal de gestão (armazenada apenas nesta máquina).",
                "2. Abra o portal no seu navegador onde você já está autenticado.",
                "3. Execute o Bookmarklet ou cole o Snippet no DevTools Console (F12) — ele tenta primeiro /api/management/data na sua sessão e faz fallback automático para os cards da página.",
                "4. Cole o JSON/HTML capturado abaixo (ou envie o arquivo .json/.html baixado) e clique em Pré-visualizar.",
            ],
        )

    # -------------------------------------------------------------------------
    # Row Deserialization Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(raw: Any) -> list[str]:
        if isinstance(raw, list):
            return [str(x) for x in raw]
        try:
            parsed = json.loads(raw or "[]")
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []

    @staticmethod
    def _parse_json_dict(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        try:
            parsed = json.loads(raw or "{}")
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _row_to_system_read(self, row: sqlite3.Row | dict[str, Any]) -> ClientSystemRead:
        data = dict(row)
        return ClientSystemRead(
            id=str(data["id"]),
            client_unit_id=str(data["client_unit_id"]),
            system_key=str(data["system_key"]),
            label=str(data["label"]),
            system_type=data["system_type"],
            environment=data["environment"],
            system_url=str(data.get("system_url") or ""),
            version_label=str(data.get("version_label") or ""),
            db_profile_id=data.get("db_profile_id"),
            sftp_profile_id=data.get("sftp_profile_id"),
            jasperserver_profile_id=data.get("jasperserver_profile_id"),
            metadata=self._parse_json_dict(data.get("metadata_json")),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )

    def _row_to_unit_read(
        self,
        row: sqlite3.Row | dict[str, Any],
        systems: list[ClientSystemRead],
    ) -> ClientUnitRead:
        data = dict(row)
        return ClientUnitRead(
            id=str(data["id"]),
            external_id=data.get("external_id"),
            unit_code=str(data["unit_code"]),
            name=str(data["name"]),
            hosting=str(data.get("hosting") or ""),
            license_status=str(data.get("license_status") or ""),
            notes=str(data.get("notes") or ""),
            tags=self._parse_json_list(data.get("tags_json")),
            integrations=self._parse_json_list(data.get("integrations_json")),
            systems=systems,
            last_synced_at=data.get("last_synced_at"),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )

    # -------------------------------------------------------------------------
    # Manual CRUD: Clients & Systems
    # -------------------------------------------------------------------------

    def list_clients(
        self,
        *,
        search: str | None = None,
        system_type: ClientSystemType | None = None,
        environment: EnvironmentKind | None = None,
    ) -> list[ClientUnitRead]:
        """List all clients with their systems, supporting search and system filters."""
        self._ensure_tables()
        with self.store.connection() as conn:
            unit_rows = conn.execute(
                "SELECT * FROM client_units ORDER BY name COLLATE NOCASE ASC, unit_code ASC"
            ).fetchall()
            sys_rows = conn.execute(
                "SELECT * FROM client_systems ORDER BY environment ASC, system_type ASC, label COLLATE NOCASE ASC"
            ).fetchall()

        systems_by_unit: dict[str, list[ClientSystemRead]] = {}
        for sr in sys_rows:
            sys_obj = self._row_to_system_read(sr)
            systems_by_unit.setdefault(sys_obj.client_unit_id, []).append(sys_obj)

        q = _normalize_text(search or "")
        result: list[ClientUnitRead] = []
        for ur in unit_rows:
            uid = str(ur["id"])
            unit = self._row_to_unit_read(ur, systems_by_unit.get(uid, []))

            if system_type is not None:
                if not any(s.system_type == system_type for s in unit.systems):
                    continue
            if environment is not None:
                if not any(s.environment == environment for s in unit.systems):
                    continue
            if q:
                haystack = " ".join(
                    [
                        unit.name,
                        unit.unit_code,
                        unit.external_id or "",
                        unit.hosting,
                        unit.license_status,
                        " ".join(unit.tags),
                        " ".join(unit.integrations),
                        " ".join(f"{s.label} {s.system_url} {s.version_label}" for s in unit.systems),
                    ]
                )
                if q not in _normalize_text(haystack):
                    continue

            result.append(unit)
        return result

    def get_client(self, unit_id: str) -> ClientUnitRead:
        """Fetch a single client unit and all of its systems."""
        self._ensure_tables()
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM client_units WHERE id = ?", (unit_id,)).fetchone()
            if row is None:
                raise ClientUnitNotFoundError(f"Client unit '{unit_id}' not found.")
            sys_rows = conn.execute(
                "SELECT * FROM client_systems WHERE client_unit_id = ? ORDER BY environment ASC, system_type ASC, label COLLATE NOCASE ASC",
                (unit_id,),
            ).fetchall()
        return self._row_to_unit_read(row, [self._row_to_system_read(sr) for sr in sys_rows])

    def create_client(self, payload: ClientUnitCreate) -> ClientUnitRead:
        """Create a new client unit manually."""
        self._ensure_tables()
        unit_id = str(uuid.uuid4())
        now = utc_now_iso()
        unit_code = _clean_unit_code(
            payload.unit_code,
            name=payload.name,
            external_id=payload.external_id,
        )
        try:
            with self.store.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO client_units (
                        id, external_id, unit_code, name, hosting, license_status,
                        notes, tags_json, integrations_json, last_synced_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        unit_id,
                        payload.external_id.strip() if payload.external_id else None,
                        unit_code,
                        payload.name.strip(),
                        payload.hosting.strip(),
                        payload.license_status.strip(),
                        payload.notes.strip(),
                        json.dumps(_dedupe_strings(payload.tags), ensure_ascii=False),
                        json.dumps(_dedupe_strings(payload.integrations), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ClientCatalogValidationError(
                f"Já existe um cliente com o código '{unit_code}'."
            ) from exc
        return self.get_client(unit_id)

    def update_client(self, unit_id: str, payload: ClientUnitUpdate) -> ClientUnitRead:
        """Partially update a client unit."""
        self._ensure_tables()
        self.get_client(unit_id)
        fields = payload.model_dump(exclude_unset=True)
        updates: dict[str, Any] = {}

        for col in ("external_id", "name", "hosting", "license_status", "notes"):
            if col in fields:
                val = fields[col]
                updates[col] = val.strip() if isinstance(val, str) else val
        if "unit_code" in fields and fields["unit_code"] is not None:
            updates["unit_code"] = _clean_unit_code(fields["unit_code"], name=updates.get("name") or unit_id)
        if "tags" in fields and fields["tags"] is not None:
            updates["tags_json"] = json.dumps(_dedupe_strings(fields["tags"]), ensure_ascii=False)
        if "integrations" in fields and fields["integrations"] is not None:
            updates["integrations_json"] = json.dumps(
                _dedupe_strings(fields["integrations"]), ensure_ascii=False
            )

        if updates:
            updates["updated_at"] = utc_now_iso()
            assignments = ", ".join(f"{col} = ?" for col in updates)
            params = [*updates.values(), unit_id]
            try:
                with self.store.connection() as conn:
                    conn.execute(f"UPDATE client_units SET {assignments} WHERE id = ?", params)
            except sqlite3.IntegrityError as exc:
                raise ClientCatalogValidationError(
                    "Conflito de unicidade ao atualizar o código do cliente."
                ) from exc
        return self.get_client(unit_id)

    def delete_client(self, unit_id: str) -> bool:
        """Delete a client unit and cascade-delete its `client_systems` rows."""
        self._ensure_tables()
        with self.store.connection() as conn:
            cursor = conn.execute("DELETE FROM client_units WHERE id = ?", (unit_id,))
            if cursor.rowcount == 0:
                raise ClientUnitNotFoundError(f"Client unit '{unit_id}' not found.")
        return True

    def upsert_system(
        self,
        unit_id: str,
        payload: ClientSystemCreate,
        *,
        system_id: str | None = None,
    ) -> ClientSystemRead:
        """Create or update a system belonging to `unit_id`."""
        self._ensure_tables()
        self.get_client(unit_id)
        now = utc_now_iso()
        sys_key = _slugify(
            payload.system_key or f"{payload.system_type}_{payload.environment.lower()}_{payload.label}",
            max_len=80,
        )
        metadata_json = json.dumps(payload.metadata or {}, ensure_ascii=False)

        with self.store.connection() as conn:
            existing = None
            if system_id:
                existing = conn.execute(
                    "SELECT * FROM client_systems WHERE id = ? AND client_unit_id = ?",
                    (system_id, unit_id),
                ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT * FROM client_systems WHERE client_unit_id = ? AND system_key = ?",
                    (unit_id, sys_key),
                ).fetchone()

            if existing is not None:
                target_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE client_systems
                    SET system_key = ?, label = ?, system_type = ?, environment = ?,
                        system_url = ?, version_label = ?, db_profile_id = ?,
                        sftp_profile_id = ?, jasperserver_profile_id = ?,
                        metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        sys_key,
                        payload.label.strip(),
                        payload.system_type,
                        payload.environment,
                        _clean_url(payload.system_url),
                        payload.version_label.strip(),
                        payload.db_profile_id,
                        payload.sftp_profile_id,
                        payload.jasperserver_profile_id,
                        metadata_json,
                        now,
                        target_id,
                    ),
                )
            else:
                target_id = system_id or str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO client_systems (
                        id, client_unit_id, system_key, label, system_type, environment,
                        system_url, version_label, db_profile_id, sftp_profile_id,
                        jasperserver_profile_id, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_id,
                        unit_id,
                        sys_key,
                        payload.label.strip(),
                        payload.system_type,
                        payload.environment,
                        _clean_url(payload.system_url),
                        payload.version_label.strip(),
                        payload.db_profile_id,
                        payload.sftp_profile_id,
                        payload.jasperserver_profile_id,
                        metadata_json,
                        now,
                        now,
                    ),
                )
            row = conn.execute("SELECT * FROM client_systems WHERE id = ?", (target_id,)).fetchone()
        return self._row_to_system_read(row)

    def update_system(
        self,
        unit_id: str,
        system_id: str,
        payload: ClientSystemUpdate,
    ) -> ClientSystemRead:
        """Partially update an existing client system."""
        self._ensure_tables()
        self.get_client(unit_id)
        with self.store.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM client_systems WHERE id = ? AND client_unit_id = ?",
                (system_id, unit_id),
            ).fetchone()
            if existing is None:
                raise ClientSystemNotFoundError(
                    f"System '{system_id}' not found for client '{unit_id}'."
                )

            fields = payload.model_dump(exclude_unset=True)
            updates: dict[str, Any] = {}
            for col in (
                "label",
                "system_type",
                "environment",
                "version_label",
                "db_profile_id",
                "sftp_profile_id",
                "jasperserver_profile_id",
            ):
                if col in fields:
                    val = fields[col]
                    updates[col] = val.strip() if isinstance(val, str) else val
            if "system_key" in fields and fields["system_key"] is not None:
                updates["system_key"] = _slugify(fields["system_key"], max_len=80)
            if "system_url" in fields and fields["system_url"] is not None:
                updates["system_url"] = _clean_url(fields["system_url"])
            if "metadata" in fields and fields["metadata"] is not None:
                updates["metadata_json"] = json.dumps(fields["metadata"], ensure_ascii=False)

            if updates:
                updates["updated_at"] = utc_now_iso()
                assignments = ", ".join(f"{col} = ?" for col in updates)
                params = [*updates.values(), system_id]
                try:
                    conn.execute(f"UPDATE client_systems SET {assignments} WHERE id = ?", params)
                except sqlite3.IntegrityError as exc:
                    raise ClientCatalogValidationError(
                        "Já existe um sistema com esta chave neste cliente."
                    ) from exc

            row = conn.execute("SELECT * FROM client_systems WHERE id = ?", (system_id,)).fetchone()
        return self._row_to_system_read(row)

    def delete_system(self, unit_id: str, system_id: str) -> bool:
        """Delete a system from a client unit."""
        self._ensure_tables()
        with self.store.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM client_systems WHERE id = ? AND client_unit_id = ?",
                (system_id, unit_id),
            )
            if cursor.rowcount == 0:
                raise ClientSystemNotFoundError(
                    f"System '{system_id}' not found for client '{unit_id}'."
                )
        return True

    # -------------------------------------------------------------------------
    # Format Detection & Parsing
    # -------------------------------------------------------------------------

    def _detect_format(self, raw_payload: str | dict[str, Any] | list[Any]) -> str:
        if isinstance(raw_payload, str):
            stripped = raw_payload.lstrip("\ufeff").strip()
            if not stripped:
                raise ClientCatalogValidationError("O conteúdo de sincronização está vazio.")
            if stripped.startswith("<") or "management-client-card" in stripped or "data-gestao-card-title" in stripped:
                return "portal_html"
            try:
                parsed = json.loads(stripped)
            except ValueError as exc:
                raise ClientCatalogValidationError(
                    "Formato não reconhecido: forneça JSON válido ou HTML contendo cards '.management-client-card'."
                ) from exc
            return self._detect_format(parsed)

        if isinstance(raw_payload, dict):
            if isinstance(raw_payload.get("units"), list):
                return "normalized_json"
            return "portal_json"

        if isinstance(raw_payload, list):
            if raw_payload and isinstance(raw_payload[0], dict):
                first = raw_payload[0]
                if "systems" in first and ("unit_code" in first or "name" in first):
                    return "normalized_json"
            return "portal_json"

        raise ClientCatalogValidationError("Tipo de payload não suportado para sincronização.")

    def parse_payload(
        self,
        raw_payload: str | dict[str, Any] | list[Any],
        *,
        source_format: SyncSourceFormat = "auto",
    ) -> tuple[ClientCatalogPayload, list[str]]:
        """Parse raw payload into a normalized `ClientCatalogPayload` using the selected or detected provider."""
        resolved_format = (
            self._detect_format(raw_payload) if source_format == "auto" else source_format
        )
        provider = self._providers.get(resolved_format)
        if provider is None:
            raise ClientCatalogValidationError(f"Unsupported source_format: '{source_format}'.")
        return provider.parse(raw_payload)

    # -------------------------------------------------------------------------
    # Sync Preview (Dry-Run Diff — Zero Mutation, Zero Password Echo)
    # -------------------------------------------------------------------------

    def _find_existing_unit_map(self) -> tuple[dict[str, ClientUnitRead], dict[str, ClientUnitRead]]:
        existing = self.list_clients()
        by_code = {u.unit_code.lower(): u for u in existing}
        by_ext = {
            u.external_id.lower(): u for u in existing if u.external_id
        }
        return by_code, by_ext

    def _compute_unit_changes(
        self,
        existing: ClientUnitRead,
        incoming: ClientUnitEntry,
    ) -> list[str]:
        changes: list[str] = []
        if existing.name != incoming.name:
            changes.append(f"Nome: '{existing.name}' -> '{incoming.name}'")
        if incoming.hosting and existing.hosting != incoming.hosting:
            changes.append(f"Hospedagem: '{existing.hosting or '—'}' -> '{incoming.hosting}'")
        if incoming.license_status and existing.license_status != incoming.license_status:
            changes.append(f"Licença: '{existing.license_status or '—'}' -> '{incoming.license_status}'")
        if incoming.tags and sorted(existing.tags) != sorted(incoming.tags):
            changes.append("Tags atualizadas")
        if incoming.integrations and sorted(existing.integrations) != sorted(incoming.integrations):
            changes.append("Integrações atualizadas")

        existing_sys_by_key = {s.system_key: s for s in existing.systems}
        for inc_sys in incoming.systems:
            cur_sys = existing_sys_by_key.get(inc_sys.system_key)
            if cur_sys is None:
                changes.append(f"+ Sistema '{inc_sys.label}' ({inc_sys.system_type}/{inc_sys.environment})")
                continue
            if cur_sys.label != inc_sys.label:
                changes.append(f"Sistema '{inc_sys.system_key}': rótulo atualizado")
            if cur_sys.system_type != inc_sys.system_type:
                changes.append(f"Sistema '{inc_sys.label}': tipo {cur_sys.system_type} -> {inc_sys.system_type}")
            if cur_sys.environment != inc_sys.environment:
                changes.append(f"Sistema '{inc_sys.label}': ambiente {cur_sys.environment} -> {inc_sys.environment}")
            if inc_sys.system_url and cur_sys.system_url != inc_sys.system_url:
                changes.append(f"Sistema '{inc_sys.label}': URL atualizada")
            if inc_sys.version_label and cur_sys.version_label != inc_sys.version_label:
                changes.append(f"Sistema '{inc_sys.label}': versão {cur_sys.version_label or '—'} -> {inc_sys.version_label}")
            if inc_sys.postgres and not cur_sys.db_profile_id:
                changes.append(f"Sistema '{inc_sys.label}': vincular perfil PostgreSQL")
            if inc_sys.sftp and not cur_sys.sftp_profile_id:
                changes.append(f"Sistema '{inc_sys.label}': vincular perfil SFTP")
            if inc_sys.jasperserver and not cur_sys.jasperserver_profile_id:
                changes.append(f"Sistema '{inc_sys.label}': vincular perfil JasperServer")

        return changes

    def preview_sync(
        self,
        raw_payload: str | dict[str, Any] | list[Any],
        *,
        source_format: SyncSourceFormat = "auto",
    ) -> ClientSyncPreviewResponse:
        """Parse payload and compute exact diff against SQLite without mutating anything."""
        self._ensure_tables()
        catalog, warnings = self.parse_payload(raw_payload, source_format=source_format)
        by_code, by_ext = self._find_existing_unit_map()

        items: list[ClientSyncDiffItem] = []
        to_create = 0
        to_update = 0
        unchanged = 0

        for unit in catalog.units:
            existing = by_code.get(unit.unit_code.lower())
            if existing is None and unit.external_id:
                existing = by_ext.get(unit.external_id.lower())

            if existing is None:
                to_create += 1
                create_notes = [f"Novo cliente com {len(unit.systems)} sistema(s)"]
                for s in unit.systems:
                    create_notes.append(f"+ {s.label} ({s.system_type}/{s.environment})")
                items.append(
                    ClientSyncDiffItem(
                        unit_code=unit.unit_code,
                        name=unit.name,
                        action="create",
                        systems_count=len(unit.systems),
                        changes=create_notes,
                    )
                )
            else:
                changes = self._compute_unit_changes(existing, unit)
                if changes:
                    to_update += 1
                    items.append(
                        ClientSyncDiffItem(
                            unit_code=existing.unit_code,
                            name=unit.name,
                            action="update",
                            systems_count=len(unit.systems),
                            changes=changes,
                        )
                    )
                else:
                    unchanged += 1
                    items.append(
                        ClientSyncDiffItem(
                            unit_code=existing.unit_code,
                            name=unit.name,
                            action="unchanged",
                            systems_count=len(unit.systems),
                            changes=[],
                        )
                    )

        return ClientSyncPreviewResponse(
            ok=True,
            total_parsed=len(catalog.units),
            to_create=to_create,
            to_update=to_update,
            unchanged=unchanged,
            warnings=warnings,
            items=items,
            normalized_units=[_redact_unit_for_preview(u) for u in catalog.units],
        )

    # -------------------------------------------------------------------------
    # Profile Provisioning Helpers (PG / SFTP / JasperServer)
    # -------------------------------------------------------------------------

    def _default_pg_dbname(self, system_type: ClientSystemType) -> str:
        defaults = self.default_credentials.get_default("postgres")
        if system_type == "hospitalar" and defaults.default_dbname_hospitalar:
            return defaults.default_dbname_hospitalar
        if system_type == "ambulatorial" and defaults.default_dbname_ambulatorial:
            return defaults.default_dbname_ambulatorial
        return defaults.default_dbname or ""

    def _provision_postgres_profile(
        self,
        *,
        unit_name: str,
        system: ClientSystemEntry,
        existing_profile_id: str | None,
    ) -> tuple[str | None, bool]:
        pg = system.postgres
        if not isinstance(pg, dict) or not str(pg.get("host") or "").strip():
            return existing_profile_id, False

        host = str(pg["host"]).strip()
        port = int(pg.get("port") or 5432)
        env: EnvironmentKind = system.environment
        profile_name = f"{unit_name} — {system.label} ({env})"[:120]
        incoming_dbname = str(pg.get("dbname") or "").strip() or self._default_pg_dbname(system.system_type)
        incoming_user = str(pg.get("user") or "").strip()

        existing_row: dict[str, Any] | None = None
        with self.store.connection() as conn:
            if existing_profile_id:
                row = conn.execute(
                    "SELECT * FROM db_profiles WHERE id = ?",
                    (existing_profile_id,),
                ).fetchone()
                if row is not None:
                    existing_row = dict(row)
            if existing_row is None:
                row = conn.execute(
                    "SELECT * FROM db_profiles WHERE host = ? AND port = ? AND environment = ? AND name = ?",
                    (host, port, env, profile_name),
                ).fetchone()
                if row is not None:
                    existing_row = dict(row)

        if existing_row is not None:
            pid = str(existing_row["id"])
            # Preserve custom credentials and user-customized dbname!
            update_fields: dict[str, Any] = {
                "name": profile_name,
                "host": host,
                "port": port,
                "environment": env,
            }
            if env == "PRD":
                update_fields["read_only"] = True
            existing_dbname = str(existing_row.get("dbname") or "").strip()
            if not existing_dbname and incoming_dbname:
                update_fields["dbname"] = incoming_dbname
            # Only fill user if profile is in default mode and currently empty
            if str(existing_row.get("credential_mode") or "custom") == "default" and incoming_user and not existing_row.get("user"):
                update_fields["user"] = incoming_user
            self.postgres_service.update_profile(pid, DbProfileUpdate(**update_fields))
            return pid, False

        # Create new PostgreSQL profile: PRD is ALWAYS read_only=True, default mode
        read_only = True if env == "PRD" else bool(pg.get("read_only", False))
        created = self.postgres_service.create_profile(
            DbProfileCreate(
                name=profile_name,
                host=host,
                port=port,
                dbname=incoming_dbname,
                user=incoming_user,
                sslmode="prefer",
                credential_mode="default",
                environment=env,
                read_only=read_only,
                is_default=False,
            )
        )
        return created.id, True

    def _provision_sftp_profile(
        self,
        *,
        unit_name: str,
        system: ClientSystemEntry,
        existing_profile_id: str | None,
        linked_db_profile_id: str | None,
        import_ssh_passwords: bool,
    ) -> tuple[str | None, bool]:
        sftp = system.sftp
        if not isinstance(sftp, dict) or not str(sftp.get("host") or "").strip():
            return existing_profile_id, False

        host = str(sftp["host"]).strip()
        port = int(sftp.get("port") or 22)
        env: EnvironmentKind = system.environment
        username = str(sftp.get("user") or sftp.get("username") or "").strip()
        raw_password = str(sftp.get("password") or "").strip()
        defaults = self.default_credentials.get_default("sftp")
        remote_base_dir = (
            str(sftp.get("remote_base_dir") or "").strip()
            or defaults.default_remote_base_dir
            or "/"
        )
        profile_name = f"{unit_name} — {system.label} SSH ({env})"[:120]
        now = utc_now_iso()

        with self.store.connection() as conn:
            existing_row = None
            if existing_profile_id:
                existing_row = conn.execute(
                    "SELECT * FROM sftp_profiles WHERE id = ?",
                    (existing_profile_id,),
                ).fetchone()
            if existing_row is None:
                existing_row = conn.execute(
                    "SELECT * FROM sftp_profiles WHERE host = ? AND port = ? AND environment = ? AND name = ?",
                    (host, port, env, profile_name),
                ).fetchone()

            if existing_row is not None:
                pid = str(existing_row["id"])
                existing_mode = str(existing_row["credential_mode"] or "default")
                new_mode: CredentialMode = "custom" if existing_mode == "custom" else "default"
                effective_user = str(existing_row["username"] or "") or username
                effective_read_only = 1 if env == "PRD" else int(existing_row["read_only"])
                effective_linked_db = linked_db_profile_id or existing_row["linked_db_profile_id"]

                # NEVER overwrite existing custom password; only upgrade default -> custom if requested
                if existing_mode != "custom" and import_ssh_passwords and raw_password:
                    new_mode = "custom"
                    self.vault.set_secret(f"sftp_password:{pid}", raw_password)

                conn.execute(
                    """
                    UPDATE sftp_profiles
                    SET name = ?, host = ?, port = ?, username = ?, credential_mode = ?,
                        environment = ?, read_only = ?, linked_db_profile_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        profile_name,
                        host,
                        port,
                        effective_user,
                        new_mode,
                        env,
                        effective_read_only,
                        effective_linked_db,
                        now,
                        pid,
                    ),
                )
                return pid, False

            pid = str(uuid.uuid4())
            use_custom_pw = bool(import_ssh_passwords and raw_password)
            credential_mode: CredentialMode = "custom" if use_custom_pw else "default"
            read_only = 1 if env == "PRD" else (1 if sftp.get("read_only", True) else 0)

            if use_custom_pw:
                self.vault.set_secret(f"sftp_password:{pid}", raw_password)

            conn.execute(
                """
                INSERT INTO sftp_profiles (
                    id, name, host, port, username, auth_type, credential_mode,
                    remote_base_dir, environment, read_only, linked_db_profile_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'password', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    profile_name,
                    host,
                    port,
                    username,
                    credential_mode,
                    remote_base_dir,
                    env,
                    read_only,
                    linked_db_profile_id,
                    now,
                    now,
                ),
            )
            return pid, True

    def _provision_jasperserver_profile(
        self,
        *,
        unit_name: str,
        system: ClientSystemEntry,
        existing_profile_id: str | None,
        linked_db_profile_id: str | None,
    ) -> tuple[str | None, bool]:
        js = system.jasperserver
        if not isinstance(js, dict) or not str(js.get("base_url") or "").strip():
            return existing_profile_id, False

        base_url = _clean_url(str(js["base_url"])).rstrip("/")
        env: EnvironmentKind = system.environment
        organization = str(js.get("organization") or "").strip()
        username = str(js.get("user") or js.get("username") or "").strip()
        profile_name = f"{unit_name} — {system.label} Jasper ({env})"[:120]
        now = utc_now_iso()

        with self.store.connection() as conn:
            existing_row = None
            if existing_profile_id:
                existing_row = conn.execute(
                    "SELECT * FROM jasperserver_profiles WHERE id = ?",
                    (existing_profile_id,),
                ).fetchone()
            if existing_row is None:
                existing_row = conn.execute(
                    "SELECT * FROM jasperserver_profiles WHERE base_url = ? AND environment = ?",
                    (base_url, env),
                ).fetchone()

            if existing_row is not None:
                pid = str(existing_row["id"])
                effective_read_only = 1 if env == "PRD" else int(existing_row["read_only"])
                effective_linked_db = linked_db_profile_id or existing_row["linked_db_profile_id"]
                effective_org = str(existing_row["organization"] or "") or organization
                effective_user = str(existing_row["username"] or "") or username
                # NEVER overwrite credential_mode='custom' or custom password
                conn.execute(
                    """
                    UPDATE jasperserver_profiles
                    SET base_url = ?, organization = ?, username = ?,
                        environment = ?, read_only = ?, linked_db_profile_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        base_url,
                        effective_org,
                        effective_user,
                        env,
                        effective_read_only,
                        effective_linked_db,
                        now,
                        pid,
                    ),
                )
                return pid, False

            pid = str(uuid.uuid4())
            read_only = 1 if env == "PRD" else (1 if js.get("read_only", True) else 0)
            conn.execute(
                """
                INSERT INTO jasperserver_profiles (
                    id, name, base_url, organization, username, credential_mode,
                    default_folder_uri, environment, read_only, linked_db_profile_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'default', '/', ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    profile_name,
                    base_url,
                    organization,
                    username,
                    env,
                    read_only,
                    linked_db_profile_id,
                    now,
                    now,
                ),
            )
            return pid, True

    # -------------------------------------------------------------------------
    # Sync Apply (Idempotent Upsert + Profile Provisioning)
    # -------------------------------------------------------------------------

    def apply_sync(
        self,
        units: list[ClientUnitEntry] | list[dict[str, Any]],
        *,
        import_ssh_passwords: bool = False,
    ) -> ClientSyncApplyResponse:
        """Idempotently upsert client units, systems, and linked PG/SFTP/JasperServer profiles."""
        self._ensure_tables()
        normalized_units = [
            u if isinstance(u, ClientUnitEntry) else ClientUnitEntry.model_validate(u)
            for u in units
        ]

        now = utc_now_iso()
        created_units = 0
        updated_units = 0
        created_systems = 0
        updated_systems = 0
        created_profiles = {"postgres": 0, "sftp": 0, "jasperserver": 0}
        warnings: list[str] = []

        for unit in normalized_units:
            unit_code = _clean_unit_code(
                unit.unit_code,
                name=unit.name,
                external_id=unit.external_id,
            )
            tags_json = json.dumps(_dedupe_strings(unit.tags), ensure_ascii=False)
            integ_json = json.dumps(_dedupe_strings(unit.integrations), ensure_ascii=False)

            with self.store.connection() as conn:
                existing_row = conn.execute(
                    "SELECT * FROM client_units WHERE LOWER(unit_code) = LOWER(?)",
                    (unit_code,),
                ).fetchone()
                if existing_row is None and unit.external_id:
                    existing_row = conn.execute(
                        "SELECT * FROM client_units WHERE external_id = ?",
                        (unit.external_id,),
                    ).fetchone()

                if existing_row is not None:
                    unit_id = str(existing_row["id"])
                    conn.execute(
                        """
                        UPDATE client_units
                        SET external_id = COALESCE(?, external_id),
                            name = ?,
                            hosting = CASE WHEN ? != '' THEN ? ELSE hosting END,
                            license_status = CASE WHEN ? != '' THEN ? ELSE license_status END,
                            notes = CASE WHEN ? != '' THEN ? ELSE notes END,
                            tags_json = ?,
                            integrations_json = ?,
                            last_synced_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            unit.external_id,
                            unit.name.strip(),
                            unit.hosting.strip(),
                            unit.hosting.strip(),
                            unit.license_status.strip(),
                            unit.license_status.strip(),
                            unit.notes.strip(),
                            unit.notes.strip(),
                            tags_json if unit.tags else str(existing_row["tags_json"]),
                            integ_json if unit.integrations else str(existing_row["integrations_json"]),
                            now,
                            now,
                            unit_id,
                        ),
                    )
                    updated_units += 1
                else:
                    unit_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO client_units (
                            id, external_id, unit_code, name, hosting, license_status,
                            notes, tags_json, integrations_json, last_synced_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            unit_id,
                            unit.external_id,
                            unit_code,
                            unit.name.strip(),
                            unit.hosting.strip(),
                            unit.license_status.strip(),
                            unit.notes.strip(),
                            tags_json,
                            integ_json,
                            now,
                            now,
                            now,
                        ),
                    )
                    created_units += 1

            # Upsert systems & linked profiles
            for sys_entry in unit.systems:
                with self.store.connection() as conn:
                    existing_sys = conn.execute(
                        "SELECT * FROM client_systems WHERE client_unit_id = ? AND system_key = ?",
                        (unit_id, sys_entry.system_key),
                    ).fetchone()

                existing_db_id = existing_sys["db_profile_id"] if existing_sys is not None else None
                existing_sftp_id = existing_sys["sftp_profile_id"] if existing_sys is not None else None
                existing_js_id = existing_sys["jasperserver_profile_id"] if existing_sys is not None else None

                db_profile_id, db_created = self._provision_postgres_profile(
                    unit_name=unit.name.strip(),
                    system=sys_entry,
                    existing_profile_id=existing_db_id,
                )
                if db_created:
                    created_profiles["postgres"] += 1

                sftp_profile_id, sftp_created = self._provision_sftp_profile(
                    unit_name=unit.name.strip(),
                    system=sys_entry,
                    existing_profile_id=existing_sftp_id,
                    linked_db_profile_id=db_profile_id,
                    import_ssh_passwords=import_ssh_passwords,
                )
                if sftp_created:
                    created_profiles["sftp"] += 1

                js_profile_id, js_created = self._provision_jasperserver_profile(
                    unit_name=unit.name.strip(),
                    system=sys_entry,
                    existing_profile_id=existing_js_id,
                    linked_db_profile_id=db_profile_id,
                )
                if js_created:
                    created_profiles["jasperserver"] += 1

                # Strip any password from metadata before storing in SQLite and include non-secret display hints
                safe_meta = {
                    k: v
                    for k, v in (sys_entry.metadata or {}).items()
                    if "password" not in k.lower() and "secret" not in k.lower()
                }
                if isinstance(sys_entry.postgres, dict) and sys_entry.postgres.get("host"):
                    safe_meta["pg_host"] = str(sys_entry.postgres["host"])
                    safe_meta["pg_port"] = int(sys_entry.postgres.get("port") or 5432)
                    if sys_entry.postgres.get("dbname"):
                        safe_meta["pg_dbname"] = str(sys_entry.postgres["dbname"])
                if isinstance(sys_entry.sftp, dict) and sys_entry.sftp.get("host"):
                    safe_meta["sftp_host"] = str(sys_entry.sftp["host"])
                    safe_meta["sftp_port"] = int(sys_entry.sftp.get("port") or 22)
                    if sys_entry.sftp.get("user"):
                        safe_meta["sftp_user"] = str(sys_entry.sftp["user"])
                if isinstance(sys_entry.jasperserver, dict) and sys_entry.jasperserver.get("base_url"):
                    safe_meta["jasper_url"] = str(sys_entry.jasperserver["base_url"])
                meta_json = json.dumps(safe_meta, ensure_ascii=False)

                with self.store.connection() as conn:
                    if existing_sys is not None:
                        conn.execute(
                            """
                            UPDATE client_systems
                            SET label = ?, system_type = ?, environment = ?,
                                system_url = CASE WHEN ? != '' THEN ? ELSE system_url END,
                                version_label = CASE WHEN ? != '' THEN ? ELSE version_label END,
                                db_profile_id = ?, sftp_profile_id = ?, jasperserver_profile_id = ?,
                                metadata_json = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                sys_entry.label.strip(),
                                sys_entry.system_type,
                                sys_entry.environment,
                                _clean_url(sys_entry.system_url),
                                _clean_url(sys_entry.system_url),
                                sys_entry.version_label.strip(),
                                sys_entry.version_label.strip(),
                                db_profile_id,
                                sftp_profile_id,
                                js_profile_id,
                                meta_json,
                                now,
                                str(existing_sys["id"]),
                            ),
                        )
                        updated_systems += 1
                    else:
                        conn.execute(
                            """
                            INSERT INTO client_systems (
                                id, client_unit_id, system_key, label, system_type, environment,
                                system_url, version_label, db_profile_id, sftp_profile_id,
                                jasperserver_profile_id, metadata_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(uuid.uuid4()),
                                unit_id,
                                sys_entry.system_key,
                                sys_entry.label.strip(),
                                sys_entry.system_type,
                                sys_entry.environment,
                                _clean_url(sys_entry.system_url),
                                sys_entry.version_label.strip(),
                                db_profile_id,
                                sftp_profile_id,
                                js_profile_id,
                                meta_json,
                                now,
                                now,
                            ),
                        )
                        created_systems += 1

        return ClientSyncApplyResponse(
            ok=True,
            created_units=created_units,
            updated_units=updated_units,
            created_systems=created_systems,
            updated_systems=updated_systems,
            created_profiles=created_profiles,
            warnings=warnings,
        )
