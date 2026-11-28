# -*- coding: utf-8 -*-
"""
JasperReports Server REST v2 connector service (`backend/app/services/jasperserver_service.py`).

Provides profile CRUD with SecretVault + DefaultCredentials inheritance, REST v2 HTTP client
(JSESSIONID cookie auth with Basic Auth fallback and automatic 401 re-login), repository browsing,
Report Unit inspection and import with hybrid subreport resolution (embedded `{uri}_files/*` and
shared `repo:/...`), and safe 2-step JRXML deployment with JVM compile verification, unified diff,
local backup, and single-use deploy tokens.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import posixpath
import re
import secrets
import shutil
import tempfile
import threading
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.config import get_data_dir
from backend.app.db.schemas import (
    CredentialMode,
    EnvironmentKind,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from backend.app.db.sqlite_store import SQLiteStore, utc_now_iso
from backend.app.services.default_credentials_service import DefaultCredentialsService
from backend.app.services.secret_vault import VAULT_FILENAME, SecretVaultError, SecretVaultService
from backend.app.services.workspace_service import WorkspaceService, validate_jrxml_content

JasperResourceType = Literal["folder", "reportUnit", "jrxml", "jasper", "datasource", "other"]
DeployMode = Literal["update", "create"]

JASPERSERVER_SCHEMA_SQL = """
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

CREATE INDEX IF NOT EXISTS idx_jasperserver_profiles_name
    ON jasperserver_profiles(name ASC);

CREATE TABLE IF NOT EXISTS jasperserver_deploy_tokens (
    token TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('update', 'create')),
    target_uri TEXT NOT NULL,
    main_jrxml_uri TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    datasource_uri TEXT NULL,
    local_sha256 TEXT NOT NULL,
    remote_sha256 TEXT NULL,
    remote_jrxml_snapshot TEXT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_jasperserver_deploy_tokens_lookup
    ON jasperserver_deploy_tokens(project_id, profile_id);
"""

_REPO_URI_RE = re.compile(r"""repo:([^\s"'<>\\]+)""", re.IGNORECASE)
_XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_JSESSIONID_RE = re.compile(r"JSESSIONID=([^;,\s]+)", re.IGNORECASE)
_JAVA_SERIALIZED_MAGIC = b"\xac\xed\x00\x05"

_REPO_COMMON_EXTENSIONS: tuple[str, ...] = (
    ".jasper",
    ".jrxml",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".jrtx",
    ".properties",
)
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp", ".ico"}
)
_SUBREPORT_EXTENSIONS: frozenset[str] = frozenset({".jrxml", ".jasper"})
_STYLE_EXTENSIONS: frozenset[str] = frozenset({".jrtx"})


# =============================================================================
# Exceptions
# =============================================================================


class JasperServerError(Exception):
    """Base error for JasperReports Server operations."""


class JasperServerProfileNotFoundError(JasperServerError):
    """Raised when a JasperServer profile ID does not exist."""


class JasperServerValidationError(JasperServerError, ValueError):
    """Raised when profile input, URI, or deployment parameters are invalid."""


class ReadOnlyJasperServerProfileError(JasperServerError):
    """Raised when a mutating operation is attempted on a read-only JasperServer profile."""


class JasperServerDeployTokenError(JasperServerError):
    """Raised when a deploy token is missing, invalid, mismatched, or already consumed."""


class JasperServerCompileError(JasperServerError):
    """Raised when JVM compilation fails during deploy pre-validation."""


class JasperServerHttpError(JasperServerError):
    """Raised when the remote JasperReports Server returns an unexpected HTTP error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


# =============================================================================
# URI & URL Helpers
# =============================================================================


def _normalize_base_url(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise JasperServerValidationError("base_url não pode ser vazio.")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise JasperServerValidationError(
            "base_url deve começar com 'http://' ou 'https://' e conter um host válido."
        )
    cleaned = cleaned.rstrip("/")
    if cleaned.lower().endswith("/rest_v2"):
        cleaned = cleaned[:-8].rstrip("/")
    return cleaned


def _normalize_repo_uri(raw: str | None, *, default: str = "/") -> str:
    value = (raw or "").strip().replace("\\", "/")
    if not value:
        return default
    if not value.startswith("/"):
        value = f"/{value}"
    parts = [p for p in value.split("/") if p]
    if any(p == ".." for p in parts):
        raise JasperServerValidationError(f"URI de repositório inválida (path traversal): '{raw}'.")
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _sanitize_local_filename(raw_name: str, fallback: str = "resource.bin") -> str:
    base = posixpath.basename((raw_name or "").replace("\\", "/").strip())
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return safe or fallback


def _map_resource_type(raw_type: str | None, uri: str = "", label: str = "") -> JasperResourceType:
    lowered = (raw_type or "").strip().lower()
    if lowered == "folder":
        return "folder"
    if lowered == "reportunit":
        return "reportUnit"
    if lowered == "jrxml":
        return "jrxml"
    if lowered == "jasper":
        return "jasper"
    if "datasource" in lowered:
        return "datasource"
    if lowered == "file":
        hint = f"{uri} {label}".lower()
        if hint.endswith(".jrxml") or ".jrxml" in uri.lower() or "jrxml" in label.lower():
            return "jrxml"
        if hint.endswith(".jasper") or ".jasper" in uri.lower():
            return "jasper"
        return "other"
    return "other"


def _infer_repo_resource_kind(
    ref: str,
    tag_hint: str | None = None,
) -> Literal["subreport", "image", "style", "other"]:
    """Classify a `repo:` reference into `subreport`, `image`, `style`, or `other`."""
    if tag_hint == "subreportExpression":
        return "subreport"
    if tag_hint == "imageExpression":
        return "image"
    if tag_hint == "template":
        return "style"

    cleaned = (ref or "").strip().lower()
    for ext in _SUBREPORT_EXTENSIONS:
        if cleaned.endswith(ext):
            return "subreport"
    for ext in _IMAGE_EXTENSIONS:
        if cleaned.endswith(ext):
            return "image"
    for ext in _STYLE_EXTENSIONS:
        if cleaned.endswith(ext):
            return "style"
    return "other"


def _extract_repo_references_with_kind(
    jrxml_xml: str,
) -> list[tuple[str, Literal["subreport", "image", "style", "other"]]]:
    """
    Extract all `repo:...` references across `<subreportExpression>`, `<imageExpression>`,
    `<template>`, and any other JRXML expressions/text, preserving discovery order and
    prioritizing semantic XML tag classification over generic regex matches.
    """
    if not jrxml_xml:
        return []

    order: list[str] = []
    kinds: dict[str, Literal["subreport", "image", "style", "other"]] = {}

    def _record(candidate: str, kind: Literal["subreport", "image", "style", "other"]) -> None:
        cleaned = candidate.strip().strip("\"'")
        if not cleaned:
            return
        if cleaned not in kinds:
            order.append(cleaned)
            kinds[cleaned] = kind
        elif kinds[cleaned] == "other" and kind != "other":
            kinds[cleaned] = kind

    priority_tags = ("subreportExpression", "imageExpression", "template")
    try:
        root = ET.fromstring(jrxml_xml)
        # Pass 1: semantic tags first
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag in priority_tags and elem.text:
                for match in _REPO_URI_RE.finditer(elem.text):
                    _record(match.group(1), _infer_repo_resource_kind(match.group(1), tag))
        # Pass 2: all other XML elements/attributes (e.g. defaultValueExpression, parameter, variable, textFieldExpression)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if elem.text and "repo:" in elem.text.lower():
                for match in _REPO_URI_RE.finditer(elem.text):
                    _record(match.group(1), _infer_repo_resource_kind(match.group(1), tag))
            for attr_val in elem.attrib.values():
                if attr_val and "repo:" in attr_val.lower():
                    for match in _REPO_URI_RE.finditer(attr_val):
                        _record(match.group(1), _infer_repo_resource_kind(match.group(1), tag))
    except ET.ParseError:
        pass

    # Fallback regex pass on comment-stripped text (catches malformed XML or complex CDATA expressions)
    stripped = _XML_COMMENT_RE.sub("", jrxml_xml)
    for match in _REPO_URI_RE.finditer(stripped):
        _record(match.group(1), _infer_repo_resource_kind(match.group(1)))

    return [(ref, kinds[ref]) for ref in order]


def _extract_repo_uris_from_jrxml(jrxml_xml: str) -> list[str]:
    """Extract all `repo:...` resource references across `<subreportExpression>`, `<imageExpression>`, `<template>`, and expressions."""
    return [ref for ref, _ in _extract_repo_references_with_kind(jrxml_xml)]


def _repo_ref_to_rel_segments(ref: str) -> list[str] | None:
    """Safely normalize a `repo:` reference into relative POSIX path segments, rejecting traversal."""
    cleaned = (ref or "").strip()
    if cleaned.lower().startswith("repo:"):
        cleaned = cleaned[5:].strip()
    cleaned = cleaned.replace("\\", "/").lstrip("/")
    if not cleaned:
        return None
    segments: list[str] = []
    for part in cleaned.split("/"):
        if not part or part == ".":
            continue
        if part == ".." or "\x00" in part or ":" in part:
            return None
        segments.append(part)
    return segments or None


def _safe_join_under(root: Path, segments: list[str], filename_override: str | None = None) -> Path | None:
    """Resolve `segments` under `root`, guaranteeing the result stays strictly inside `root`."""
    if not segments:
        return None
    parts = list(segments[:-1]) + [filename_override or segments[-1]]
    if any(p in ("", ".", "..") or "\x00" in p or ":" in p for p in parts):
        return None
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _call_daemon_compile(
    jasper_daemon: Any,
    jrxml_path: Path,
    jasper_path: Path,
    subreport_dir: Path,
) -> Any:
    """Invoke `jasper_daemon.compile` tolerating test fakes without `subreport_dir` kwarg."""
    try:
        return jasper_daemon.compile(jrxml_path, jasper_path, subreport_dir=subreport_dir)
    except TypeError:
        return jasper_daemon.compile(str(jrxml_path), str(jasper_path))


def _resolve_local_repo_resource(
    resources_dir: Path,
    ref: str,
    kind: Literal["subreport", "image", "style", "other"],
) -> dict[str, Any]:
    """
    Locate a `repo:` reference inside `resources_dir` using the exact same search order as
    JVM `RepoSchemeRepositoryService` (`<resources_dir>/repo/<rel>`, `<resources_dir>/<rel>`,
    and basename fallback `<resources_dir>/<basename>`).
    """
    segments = _repo_ref_to_rel_segments(ref)
    if not segments or not resources_dir.is_dir():
        return {
            "resolved": False,
            "compiled": False,
            "local_path": None,
            "file_path": None,
            "jrxml_path": None,
            "jasper_path": None,
        }

    rel_posix = "/".join(segments)
    basename = segments[-1]
    lower_rel = rel_posix.lower()

    def _candidate_names(path_str: str) -> list[str]:
        low = path_str.lower()
        cands: list[str] = []
        if kind == "subreport":
            if low.endswith(".jrxml"):
                cands.extend([path_str[:-6] + ".jasper", path_str])
            elif low.endswith(".jasper"):
                cands.extend([path_str, path_str[:-7] + ".jrxml"])
            else:
                cands.extend([path_str + ".jasper", path_str, path_str + ".jrxml"])
        else:
            cands.append(path_str)
            if low.endswith(".jrxml"):
                cands.append(path_str[:-6] + ".jasper")
            for ext in _REPO_COMMON_EXTENSIONS:
                if not low.endswith(ext):
                    cands.append(path_str + ext)
        dedup: list[str] = []
        for c in cands:
            if c not in dedup:
                dedup.append(c)
        return dedup

    root_resolved = resources_dir.resolve()
    search_targets: list[tuple[Path, str]] = []
    for cand in _candidate_names(rel_posix):
        search_targets.append((root_resolved / "repo", cand))
    for cand in _candidate_names(rel_posix):
        search_targets.append((root_resolved, cand))
    for cand in _candidate_names(basename):
        search_targets.append((root_resolved, cand))

    primary_file: Path | None = None
    jrxml_file: Path | None = None
    jasper_file: Path | None = None

    for base_root, rel_cand in search_targets:
        cand_segments = [p for p in rel_cand.split("/") if p]
        resolved_cand = _safe_join_under(base_root, cand_segments)
        if resolved_cand is None or not resolved_cand.is_file():
            continue
        if primary_file is None:
            primary_file = resolved_cand
        low_name = resolved_cand.name.lower()
        if low_name.endswith(".jasper") and jasper_file is None:
            jasper_file = resolved_cand
        if low_name.endswith(".jrxml") and jrxml_file is None:
            jrxml_file = resolved_cand
        if primary_file is not None and (
            kind != "subreport" or (jasper_file is not None and jrxml_file is not None)
        ):
            break

    # If exact file has no extension, inspect magic bytes for .jasper / .jrxml
    if primary_file is not None and jasper_file is None and jrxml_file is None:
        try:
            head = primary_file.read_bytes()[:4096]
            if head.startswith(_JAVA_SERIALIZED_MAGIC):
                jasper_file = primary_file
            elif _looks_like_jrxml_bytes(head):
                jrxml_file = primary_file
        except OSError:
            pass

    if primary_file is None:
        return {
            "resolved": False,
            "compiled": False,
            "local_path": None,
            "file_path": None,
            "jrxml_path": None,
            "jasper_path": None,
        }

    chosen = jasper_file if (kind == "subreport" and jasper_file is not None) else primary_file
    rel_display = chosen.relative_to(root_resolved).as_posix()
    return {
        "resolved": True,
        "compiled": jasper_file is not None,
        "local_path": rel_display,
        "file_path": chosen,
        "jrxml_path": jrxml_file,
        "jasper_path": jasper_file,
    }


def _looks_like_jrxml_bytes(data: bytes) -> bool:
    if not data or data.startswith(_JAVA_SERIALIZED_MAGIC):
        return False
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    return b"<jasperReport" in head or (head.startswith(b"<?xml") and b"jasperReport" in data[:16384])


def _is_report_unit_descriptor(raw_bytes: bytes, ctype: str) -> dict[str, Any] | None:
    """Detect whether a response body is a JasperServer `reportUnit` descriptor (JSON or XML)."""
    if not raw_bytes:
        return None
    ctype_low = (ctype or "").lower()
    head = raw_bytes[:512].lstrip(b"\xef\xbb\xbf \t\r\n")

    if "reportunit" in ctype_low or "json" in ctype_low or head.startswith(b"{"):
        try:
            parsed = json.loads(raw_bytes.decode("utf-8", errors="replace"))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and not isinstance(parsed.get("content"), str):
            if "reportunit" in ctype_low or any(
                k in parsed
                for k in ("jrxml", "jrxmlFileReference", "jrxmlFile", "alwaysPromptControls", "dataSource")
            ):
                return parsed

    if head.startswith(b"<") and b"<reportUnit" in raw_bytes[:4096]:
        return {}

    return None


# =============================================================================
# Pydantic Schemas
# =============================================================================


class JasperServerProfileCreate(BaseModel):
    """Payload to create a JasperReports Server connection profile."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=512)
    organization: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, repr=False)
    credential_mode: CredentialMode = "custom"
    default_folder_uri: str = Field(default="/", max_length=512)
    environment: EnvironmentKind = "HML"
    read_only: bool | None = None
    linked_db_profile_id: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Nome do perfil não pode ser vazio.")
        return cleaned

    @field_validator("base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return _normalize_base_url(value)

    @field_validator("organization", "username")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("default_folder_uri")
    @classmethod
    def _validate_folder(cls, value: str) -> str:
        return _normalize_repo_uri(value, default="/")


class JasperServerProfileUpdate(BaseModel):
    """Partial update payload for an existing JasperReports Server profile."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    organization: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, repr=False)
    credential_mode: CredentialMode | None = None
    default_folder_uri: str | None = Field(default=None, max_length=512)
    environment: EnvironmentKind | None = None
    read_only: bool | None = None
    linked_db_profile_id: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def _strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Nome do perfil não pode ser vazio.")
        return cleaned

    @field_validator("base_url")
    @classmethod
    def _validate_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_base_url(value)

    @field_validator("organization", "username")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("default_folder_uri")
    @classmethod
    def _validate_optional_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_repo_uri(value, default="/")


class JasperServerProfileRead(BaseModel):
    """Redacted JasperReports Server profile metadata (never exposes plaintext password)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    name: str
    base_url: str
    organization: str = ""
    username: str = ""
    credential_mode: CredentialMode = "custom"
    default_folder_uri: str = "/"
    environment: EnvironmentKind = "HML"
    read_only: bool = True
    linked_db_profile_id: str | None = None
    has_password: bool = False
    created_at: str
    updated_at: str


class JasperServerTestResult(BaseModel):
    """Connectivity test result against `/rest_v2/serverInfo`."""

    profile_id: str
    ok: bool
    latency_ms: float
    version: str | None = None
    edition: str | None = None
    build: str | None = None
    message: str = ""
    error: str | None = None


class JasperServerResourceItem(BaseModel):
    """Single item returned by `/rest_v2/resources`."""

    uri: str
    label: str
    description: str = ""
    resource_type: JasperResourceType = "other"
    updated_at: str | None = None


class JasperServerReportUnitResource(BaseModel):
    """Sub-resource attached to a JasperServer Report Unit."""

    name: str
    uri: str
    type: str = "file"


class JasperServerReportUnitDetail(BaseModel):
    """Inspected metadata for a JasperReports Server Report Unit."""

    uri: str
    label: str
    description: str = ""
    main_jrxml_uri: str | None = None
    datasource_uri: str | None = None
    input_controls: list[str] = Field(default_factory=list)
    resources: list[JasperServerReportUnitResource] = Field(default_factory=list)


class JasperServerDeployPreview(BaseModel):
    """Result of step-1 deploy pre-validation (compile + remote diff + single-use token)."""

    ok: bool = True
    project_id: str
    profile_id: str
    mode: DeployMode
    target_uri: str
    main_jrxml_uri: str
    remote_exists: bool
    unified_diff: str
    local_sha256: str
    remote_sha256: str | None = None
    deploy_token: str
    compiled_ok: bool = True
    message: str = ""


class JasperServerDeployResult(BaseModel):
    """Result of step-2 deploy execution to JasperReports Server."""

    ok: bool = True
    project_id: str
    profile_id: str
    mode: DeployMode
    target_uri: str
    main_jrxml_uri: str
    local_backup_path: str | None = None
    message: str = ""


# =============================================================================
# JasperServerService
# =============================================================================


class JasperServerService:
    """
    Manages JasperReports Server profiles, REST v2 authentication/requests, repository browsing,
    Report Unit imports (with embedded + `repo:/...` subreports), and safe 2-step JRXML deploys.
    """

    def __init__(
        self,
        store: SQLiteStore | None = None,
        *,
        vault_path: Path | None = None,
        vault: SecretVaultService | None = None,
        default_credentials_service: DefaultCredentialsService | None = None,
        http_transport: httpx.BaseTransport | None = None,
        client_factory: Callable[..., httpx.Client] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.store = store or SQLiteStore()
        self._explicit_vault_path = vault_path.resolve() if vault_path is not None else None
        self._vault = vault or SecretVaultService(vault_path=self._resolve_vault_path)
        self.default_credentials = default_credentials_service or DefaultCredentialsService(
            store=self.store,
            vault=self._vault,
        )
        self._http_transport = http_transport
        self._client_factory = client_factory
        self._timeout = float(timeout)

        self._initialized_dbs: set[Path] = set()
        self._session_lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def _resolve_vault_path(self) -> Path:
        if self._explicit_vault_path is not None:
            return self._explicit_vault_path
        return get_data_dir() / VAULT_FILENAME

    @property
    def vault_path(self) -> Path:
        return self._vault.vault_path

    def _ensure_tables(self) -> None:
        db_target = self.store.db_path
        if db_target in self._initialized_dbs and db_target.exists():
            return
        with self.store.connection() as conn:
            conn.executescript(JASPERSERVER_SCHEMA_SQL)
        self._initialized_dbs.add(db_target)

    @staticmethod
    def _vault_account(profile_id: str) -> str:
        return f"jasperserver_password:{profile_id}"

    # -------------------------------------------------------------------------
    # Secret & Credential Resolution
    # -------------------------------------------------------------------------

    def _store_password(self, profile_id: str, password: str) -> None:
        try:
            self._vault.set_secret(self._vault_account(profile_id), password)
        except SecretVaultError as exc:
            raise JasperServerError(str(exc)) from exc

    def _load_password(self, profile_id: str) -> str | None:
        try:
            return self._vault.get_secret(self._vault_account(profile_id))
        except SecretVaultError as exc:
            raise JasperServerError(str(exc)) from exc

    def _delete_password(self, profile_id: str) -> None:
        self._vault.delete_secret(self._vault_account(profile_id))

    def _has_password(self, profile_id: str, credential_mode: str = "custom") -> bool:
        if credential_mode == "default":
            try:
                return self.default_credentials.get_default("jasperserver").has_password
            except SecretVaultError as exc:
                raise JasperServerError(str(exc)) from exc
        secret = self._load_password(profile_id)
        return secret is not None and len(secret) > 0

    def _resolve_credentials(self, row: dict[str, Any]) -> tuple[str, str, str]:
        """Resolve effective `(username, organization, password)` honoring `default` vs `custom`."""
        profile_id = str(row["id"])
        mode = str(row.get("credential_mode") or "custom")
        try:
            resolved = self.default_credentials.resolve_jasperserver_credentials(
                credential_mode=mode,
                profile_id=profile_id,
                custom_user=str(row.get("username") or ""),
                custom_organization=str(row.get("organization") or ""),
            )
        except SecretVaultError as exc:
            raise JasperServerError(str(exc)) from exc

        username = str(resolved.get("username") or "").strip()
        organization = str(resolved.get("organization") or "").strip()
        password = str(resolved.get("password") or "")
        return username, organization, password

    def _invalidate_session(self, profile_id: str) -> None:
        with self._session_lock:
            self._sessions.pop(profile_id, None)

    # -------------------------------------------------------------------------
    # Profile CRUD
    # -------------------------------------------------------------------------

    def _row_to_profile_read(self, row: dict[str, Any]) -> JasperServerProfileRead:
        profile_id = str(row["id"])
        mode = str(row.get("credential_mode") or "custom")
        env = str(row.get("environment") or "HML")
        return JasperServerProfileRead(
            id=profile_id,
            name=str(row["name"]),
            base_url=str(row["base_url"]),
            organization=str(row.get("organization") or ""),
            username=str(row.get("username") or ""),
            credential_mode="default" if mode == "default" else "custom",
            default_folder_uri=str(row.get("default_folder_uri") or "/"),
            environment=env if env in ("DEV", "HML", "PRD") else "HML",  # type: ignore[arg-type]
            read_only=bool(row["read_only"]),
            linked_db_profile_id=row.get("linked_db_profile_id"),
            has_password=self._has_password(profile_id, mode),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _require_profile_row(self, profile_id: str) -> dict[str, Any]:
        self._ensure_tables()
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM jasperserver_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise JasperServerProfileNotFoundError(
                f"Perfil JasperServer '{profile_id}' não encontrado."
            )
        return dict(row)

    def list_profiles(self) -> list[JasperServerProfileRead]:
        """List all persisted JasperReports Server profiles (never exposes passwords)."""
        self._ensure_tables()
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jasperserver_profiles ORDER BY name ASC, created_at ASC"
            ).fetchall()
        return [self._row_to_profile_read(dict(r)) for r in rows]

    def get_profile(self, profile_id: str) -> JasperServerProfileRead:
        """Return redacted metadata for a single JasperServer profile."""
        return self._row_to_profile_read(self._require_profile_row(profile_id))

    def create_profile(self, payload: JasperServerProfileCreate) -> JasperServerProfileRead:
        """Create a new JasperReports Server profile and persist custom password in SecretVault."""
        self._ensure_tables()
        if payload.credential_mode == "custom" and not payload.username:
            raise JasperServerValidationError(
                "Usuário é obrigatório quando credential_mode é 'custom'."
            )

        effective_read_only = (
            payload.environment == "PRD"
            if payload.read_only is None
            else bool(payload.read_only)
        )
        profile_id = str(uuid.uuid4())
        now = utc_now_iso()

        if payload.password:
            self._store_password(profile_id, payload.password)

        try:
            with self.store.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jasperserver_profiles (
                        id, name, base_url, organization, username, credential_mode,
                        default_folder_uri, environment, read_only, linked_db_profile_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        payload.name,
                        payload.base_url,
                        payload.organization,
                        payload.username,
                        payload.credential_mode,
                        payload.default_folder_uri,
                        payload.environment,
                        1 if effective_read_only else 0,
                        payload.linked_db_profile_id or None,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM jasperserver_profiles WHERE id = ?",
                    (profile_id,),
                ).fetchone()
        except Exception:
            self._delete_password(profile_id)
            raise

        assert row is not None
        return self._row_to_profile_read(dict(row))

    def update_profile(
        self,
        profile_id: str,
        payload: JasperServerProfileUpdate,
    ) -> JasperServerProfileRead:
        """Update an existing JasperReports Server profile and optionally rotate its password."""
        existing = self._require_profile_row(profile_id)
        fields = payload.model_dump(exclude_unset=True)

        password_provided = "password" in fields
        raw_password = fields.pop("password", None)

        next_mode = str(fields.get("credential_mode", existing["credential_mode"]))
        next_user = str(fields.get("username", existing["username"]))
        if next_mode == "custom" and not next_user.strip():
            raise JasperServerValidationError(
                "Usuário é obrigatório quando credential_mode é 'custom'."
            )

        updates: dict[str, Any] = {}
        for key in (
            "name",
            "base_url",
            "organization",
            "username",
            "credential_mode",
            "default_folder_uri",
            "environment",
            "linked_db_profile_id",
        ):
            if key in fields:
                val = fields[key]
                if key == "linked_db_profile_id":
                    updates[key] = val.strip() if isinstance(val, str) and val.strip() else None
                elif val is not None:
                    updates[key] = val

        if "read_only" in fields and fields["read_only"] is not None:
            updates["read_only"] = 1 if fields["read_only"] else 0

        if password_provided and raw_password is not None:
            if raw_password == "":
                self._delete_password(profile_id)
            else:
                self._store_password(profile_id, raw_password)

        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        params = list(updates.values()) + [profile_id]

        with self.store.connection() as conn:
            conn.execute(
                f"UPDATE jasperserver_profiles SET {set_clause} WHERE id = ?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM jasperserver_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()

        self._invalidate_session(profile_id)
        assert row is not None
        return self._row_to_profile_read(dict(row))

    def delete_profile(self, profile_id: str) -> None:
        """Delete a JasperReports Server profile, clear references, and remove its vault secret."""
        self._require_profile_row(profile_id)
        with self.store.connection() as conn:
            conn.execute(
                "DELETE FROM jasperserver_deploy_tokens WHERE profile_id = ?",
                (profile_id,),
            )
            self.store.clear_profile_references(
                conn,
                kind="jasperserver",
                profile_id=profile_id,
            )
            conn.execute("DELETE FROM jasperserver_profiles WHERE id = ?", (profile_id,))
        self._delete_password(profile_id)
        self._invalidate_session(profile_id)

    # -------------------------------------------------------------------------
    # REST v2 HTTP Client & Authentication (JSESSIONID + Basic fallback + 401 retry)
    # -------------------------------------------------------------------------

    def _build_client(self) -> httpx.Client:
        if self._client_factory is not None:
            return self._client_factory()
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self._timeout, connect=10.0),
            "trust_env": False,
        }
        if self._http_transport is not None:
            kwargs["transport"] = self._http_transport
        return httpx.Client(**kwargs)

    @staticmethod
    def _compose_j_username(username: str, organization: str) -> str:
        user = username.strip()
        org = organization.strip()
        if org:
            return f"{user}|{org}"
        return user

    @staticmethod
    def _extract_jsessionid(resp: httpx.Response, client: httpx.Client) -> str | None:
        cookie_val = resp.cookies.get("JSESSIONID")
        if cookie_val:
            return str(cookie_val)
        for header_val in resp.headers.get_list("set-cookie"):
            match = _JSESSIONID_RE.search(header_val)
            if match:
                return match.group(1)
        client_cookie = client.cookies.get("JSESSIONID")
        if client_cookie:
            return str(client_cookie)
        return None

    def _authenticate(
        self,
        client: httpx.Client,
        profile_id: str,
        base_url: str,
        username: str,
        organization: str,
        password: str,
    ) -> dict[str, Any]:
        j_username = self._compose_j_username(username, organization)
        cache_key = (
            base_url,
            j_username,
            hashlib.sha256(password.encode("utf-8")).hexdigest(),
        )

        try:
            resp = client.post(
                f"{base_url}/rest_v2/login",
                data={"j_username": j_username, "j_password": password},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise JasperServerHttpError(
                f"Falha de conexão ao autenticar no JasperServer ({base_url}): {exc}"
            ) from exc

        if resp.status_code in (401, 403):
            raise JasperServerHttpError(
                f"Credenciais inválidas no JasperServer (HTTP {resp.status_code}).",
                status_code=resp.status_code,
            )

        jsessionid = self._extract_jsessionid(resp, client)
        if jsessionid:
            session_state = {
                "jsessionid": jsessionid,
                "use_basic": False,
                "cache_key": cache_key,
            }
        else:
            # No JSESSIONID issued -> fall back to HTTP Basic Auth
            session_state = {
                "jsessionid": None,
                "use_basic": True,
                "cache_key": cache_key,
            }

        with self._session_lock:
            self._sessions[profile_id] = session_state
        return session_state

    def _get_or_create_session(
        self,
        client: httpx.Client,
        profile_id: str,
        base_url: str,
        username: str,
        organization: str,
        password: str,
    ) -> dict[str, Any]:
        j_username = self._compose_j_username(username, organization)
        cache_key = (
            base_url,
            j_username,
            hashlib.sha256(password.encode("utf-8")).hexdigest(),
        )
        with self._session_lock:
            cached = self._sessions.get(profile_id)
            if cached is not None and cached.get("cache_key") == cache_key:
                return dict(cached)
        return self._authenticate(client, profile_id, base_url, username, organization, password)

    def _request(
        self,
        row: dict[str, Any],
        method: str,
        path: str,
        *,
        params: Any = None,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
        json_body: Any = None,
        allow_404: bool = False,
    ) -> httpx.Response:
        profile_id = str(row["id"])
        base_url = str(row["base_url"]).rstrip("/")
        username, organization, password = self._resolve_credentials(row)
        j_username = self._compose_j_username(username, organization)
        url = f"{base_url}{path if path.startswith('/') else '/' + path}"

        def _send_once(client: httpx.Client, session_state: dict[str, Any]) -> httpx.Response:
            req_headers = dict(headers or {})
            req_kwargs: dict[str, Any] = {
                "params": params,
                "headers": req_headers,
            }
            if json_body is not None:
                req_kwargs["json"] = json_body
            elif content is not None:
                req_kwargs["content"] = content

            if session_state.get("jsessionid") and not session_state.get("use_basic"):
                existing_cookie = req_headers.get("Cookie", "").strip()
                js_cookie = f"JSESSIONID={session_state['jsessionid']}"
                req_headers["Cookie"] = f"{existing_cookie}; {js_cookie}" if existing_cookie else js_cookie
            else:
                req_kwargs["auth"] = (j_username, password)

            try:
                return client.request(method, url, **req_kwargs)
            except httpx.HTTPError as exc:
                raise JasperServerHttpError(
                    f"Erro HTTP ao comunicar com JasperServer ({method} {path}): {exc}"
                ) from exc

        with self._build_client() as client:
            session_state = self._get_or_create_session(
                client, profile_id, base_url, username, organization, password
            )
            resp = _send_once(client, session_state)

            if resp.status_code == 401:
                self._invalidate_session(profile_id)
                session_state = self._authenticate(
                    client, profile_id, base_url, username, organization, password
                )
                resp = _send_once(client, session_state)

        if allow_404 and resp.status_code == 404:
            return resp

        if resp.status_code >= 400:
            snippet = (resp.text or "").strip()[:300]
            raise JasperServerHttpError(
                f"JasperServer retornou HTTP {resp.status_code} em {method} {path}"
                + (f": {snippet}" if snippet else "."),
                status_code=resp.status_code,
            )
        return resp

    # -------------------------------------------------------------------------
    # Server Info & Repository Browsing
    # -------------------------------------------------------------------------

    def test_connection(self, profile_id: str) -> JasperServerTestResult:
        """Test authentication and fetch `/rest_v2/serverInfo` metadata + latency."""
        row = self._require_profile_row(profile_id)
        started = time.perf_counter()
        try:
            resp = self._request(
                row,
                "GET",
                "/rest_v2/serverInfo",
                headers={"Accept": "application/json"},
            )
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                data = {}
            version = str(data.get("version") or "").strip() or None
            edition = str(data.get("editionName") or data.get("edition") or "").strip() or None
            build = str(data.get("build") or "").strip() or None
            summary_parts = [p for p in (edition, version, build) if p]
            summary = " · ".join(summary_parts) if summary_parts else "JasperReports Server OK"
            return JasperServerTestResult(
                profile_id=profile_id,
                ok=True,
                latency_ms=latency_ms,
                version=version,
                edition=edition,
                build=build,
                message=f"Conectado com sucesso ({summary}).",
                error=None,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            err_msg = str(exc)
            return JasperServerTestResult(
                profile_id=profile_id,
                ok=False,
                latency_ms=latency_ms,
                version=None,
                edition=None,
                build=None,
                message=f"Falha ao conectar ao JasperReports Server: {err_msg}",
                error=err_msg,
            )

    def list_resources(
        self,
        profile_id: str,
        *,
        folder_uri: str | None = "/",
        q: str | None = None,
        recursive: bool = False,
        types: list[str] | None = None,
    ) -> list[JasperServerResourceItem]:
        """Browse or search repository resources via `GET /rest_v2/resources`."""
        row = self._require_profile_row(profile_id)
        default_uri = str(row.get("default_folder_uri") or "/")
        normalized_folder = _normalize_repo_uri(folder_uri, default=default_uri)
        search_term = (q or "").strip()
        effective_recursive = bool(recursive or search_term)

        query_params: list[tuple[str, str]] = [
            ("folderUri", normalized_folder),
            ("recursive", "true" if effective_recursive else "false"),
            ("forceFullPage", "true"),
        ]
        if search_term:
            query_params.append(("q", search_term))
        if types:
            for item_type in types:
                cleaned_type = item_type.strip()
                if cleaned_type:
                    query_params.append(("type", cleaned_type))

        resp = self._request(
            row,
            "GET",
            "/rest_v2/resources",
            params=query_params,
            headers={"Accept": "application/json"},
        )
        if resp.status_code == 204 or not resp.content:
            return []

        try:
            body = resp.json()
        except ValueError:
            return []

        raw_items: list[Any]
        if isinstance(body, dict):
            raw_items = body.get("resourceLookup") or body.get("resources") or []
        elif isinstance(body, list):
            raw_items = body
        else:
            raw_items = []

        results: list[JasperServerResourceItem] = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            item_uri = str(entry.get("uri") or "").strip()
            if not item_uri:
                continue
            label = str(entry.get("label") or posixpath.basename(item_uri) or item_uri).strip()
            description = str(entry.get("description") or "").strip()
            mapped_type = _map_resource_type(
                str(entry.get("resourceType") or entry.get("type") or ""),
                uri=item_uri,
                label=label,
            )
            updated_at = entry.get("updateDate") or entry.get("updated_at") or entry.get("creationDate")
            results.append(
                JasperServerResourceItem(
                    uri=item_uri,
                    label=label,
                    description=description,
                    resource_type=mapped_type,
                    updated_at=str(updated_at) if updated_at else None,
                )
            )

        type_order = {
            "folder": 0,
            "reportUnit": 1,
            "jrxml": 2,
            "jasper": 3,
            "datasource": 4,
            "other": 5,
        }
        results.sort(key=lambda r: (type_order.get(r.resource_type, 9), r.label.lower(), r.uri.lower()))
        return results

    # -------------------------------------------------------------------------
    # Report Unit Inspection
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_report_unit_descriptor(uri: str, data: dict[str, Any]) -> JasperServerReportUnitDetail:
        label = str(data.get("label") or posixpath.basename(uri) or uri).strip()
        description = str(data.get("description") or "").strip()

        # Resolve main_jrxml_uri across JasperServer REST v2 descriptor variations
        main_jrxml_uri: str | None = None
        jrxml_node = data.get("jrxml")
        if isinstance(jrxml_node, str) and jrxml_node.strip():
            main_jrxml_uri = jrxml_node.strip()
        elif isinstance(jrxml_node, dict):
            if isinstance(jrxml_node.get("jrxmlFileReference"), dict):
                main_jrxml_uri = str(jrxml_node["jrxmlFileReference"].get("uri") or "").strip() or None
            elif isinstance(jrxml_node.get("jrxmlFile"), dict):
                jf = jrxml_node["jrxmlFile"]
                main_jrxml_uri = (
                    str(jf.get("uri") or "").strip()
                    or (f"{uri}_files/{jf['label']}" if jf.get("label") else None)
                )
            elif jrxml_node.get("uri"):
                main_jrxml_uri = str(jrxml_node["uri"]).strip()
        elif isinstance(data.get("jrxmlFileReference"), dict):
            main_jrxml_uri = str(data["jrxmlFileReference"].get("uri") or "").strip() or None
        elif isinstance(data.get("jrxmlFile"), dict):
            jf = data["jrxmlFile"]
            main_jrxml_uri = (
                str(jf.get("uri") or "").strip()
                or (f"{uri}_files/{jf['label']}" if jf.get("label") else None)
            )

        if not main_jrxml_uri:
            main_jrxml_uri = f"{uri}_files/main_jrxml"

        # Resolve datasource_uri
        datasource_uri: str | None = None
        ds_node = data.get("dataSource") or data.get("dataSourceReference")
        if isinstance(ds_node, str) and ds_node.strip():
            datasource_uri = ds_node.strip()
        elif isinstance(ds_node, dict):
            if isinstance(ds_node.get("dataSourceReference"), dict):
                datasource_uri = str(ds_node["dataSourceReference"].get("uri") or "").strip() or None
            elif ds_node.get("uri"):
                datasource_uri = str(ds_node["uri"]).strip() or None

        # Resolve input controls
        input_controls: list[str] = []
        raw_ics = data.get("inputControls")
        ic_list: list[Any] = []
        if isinstance(raw_ics, dict):
            nested = raw_ics.get("inputControl")
            if isinstance(nested, list):
                ic_list = nested
            elif nested is not None:
                ic_list = [nested]
        elif isinstance(raw_ics, list):
            ic_list = raw_ics

        for ic in ic_list:
            if isinstance(ic, str) and ic.strip():
                input_controls.append(ic.strip())
            elif isinstance(ic, dict):
                ic_uri = None
                if isinstance(ic.get("inputControlReference"), dict):
                    ic_uri = ic["inputControlReference"].get("uri")
                elif isinstance(ic.get("inputControl"), dict):
                    ic_uri = ic["inputControl"].get("uri") or ic["inputControl"].get("label")
                else:
                    ic_uri = ic.get("uri") or ic.get("id") or ic.get("label")
                if ic_uri:
                    input_controls.append(str(ic_uri).strip())

        # Resolve internal unit resources (`{uri}_files/*` or references)
        resources: list[JasperServerReportUnitResource] = []
        raw_res = data.get("resources")
        res_list: list[Any] = []
        if isinstance(raw_res, dict):
            nested_res = raw_res.get("resource")
            if isinstance(nested_res, list):
                res_list = nested_res
            elif nested_res is not None:
                res_list = [nested_res]
        elif isinstance(raw_res, list):
            res_list = raw_res

        for entry in res_list:
            if not isinstance(entry, dict):
                continue
            res_name = str(entry.get("name") or "").strip()
            res_uri = str(entry.get("uri") or "").strip()
            res_type = str(entry.get("type") or "file").strip()

            file_node = entry.get("file")
            if isinstance(file_node, dict):
                if isinstance(file_node.get("fileReference"), dict):
                    res_uri = str(file_node["fileReference"].get("uri") or res_uri).strip()
                    res_type = str(file_node["fileReference"].get("type") or res_type).strip()
                elif isinstance(file_node.get("fileResource"), dict):
                    fr = file_node["fileResource"]
                    res_uri = str(fr.get("uri") or res_uri).strip()
                    res_type = str(fr.get("type") or res_type).strip()
                    if not res_name and fr.get("label"):
                        res_name = str(fr["label"]).strip()
                else:
                    res_uri = str(file_node.get("uri") or res_uri).strip()
                    res_type = str(file_node.get("type") or res_type).strip()

            if not res_uri and res_name:
                res_uri = f"{uri}_files/{res_name}"
            if not res_name and res_uri:
                res_name = posixpath.basename(res_uri)

            if res_uri:
                resources.append(
                    JasperServerReportUnitResource(
                        name=res_name or posixpath.basename(res_uri),
                        uri=res_uri,
                        type=res_type or "file",
                    )
                )

        return JasperServerReportUnitDetail(
            uri=uri,
            label=label,
            description=description,
            main_jrxml_uri=main_jrxml_uri,
            datasource_uri=datasource_uri,
            input_controls=input_controls,
            resources=resources,
        )

    def inspect_report_unit(self, profile_id: str, uri: str) -> JasperServerReportUnitDetail:
        """Fetch and parse a Report Unit descriptor (`application/repository.reportUnit+json`)."""
        row = self._require_profile_row(profile_id)
        normalized_uri = _normalize_repo_uri(uri)
        resp = self._request(
            row,
            "GET",
            f"/rest_v2/resources{normalized_uri}",
            headers={"Accept": "application/repository.reportUnit+json"},
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise JasperServerHttpError(
                f"Resposta inválida ao inspecionar Report Unit '{normalized_uri}'."
            ) from exc
        if not isinstance(data, dict):
            raise JasperServerHttpError(
                f"Descriptor inválido para Report Unit '{normalized_uri}'."
            )
        return self._parse_report_unit_descriptor(normalized_uri, data)

    # -------------------------------------------------------------------------
    # Resource Download & Decompile Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _unwrap_file_response(resp: httpx.Response) -> tuple[bytes, str]:
        """Extract raw file bytes from either a binary/XML response or `repository.file+json`."""
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" in ctype:
            try:
                body = resp.json()
                if isinstance(body, dict) and isinstance(body.get("content"), str):
                    decoded = base64.b64decode(body["content"])
                    return decoded, str(body.get("type") or "")
            except Exception:
                pass
        return resp.content, ctype

    def _download_raw_resource(
        self,
        row: dict[str, Any],
        uri: str,
        *,
        params: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> tuple[bytes | None, str]:
        normalized_uri = _normalize_repo_uri(uri)
        resp = self._request(
            row,
            "GET",
            f"/rest_v2/resources{normalized_uri}",
            params=params,
            headers={"Accept": "*/*"},
            allow_404=allow_404,
        )
        if resp.status_code == 404:
            return None, ""
        return self._unwrap_file_response(resp)

    @staticmethod
    def _decompile_jasper_bytes(
        jasper_bytes: bytes,
        jasper_daemon: Any,
        *,
        hint_name: str = "report",
    ) -> str:
        """Decompile binary `.jasper` bytes to UTF-8 JRXML via `jasper_daemon.decompile()`."""
        with tempfile.TemporaryDirectory(prefix="studio_js_decompile_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            stem = _sanitize_local_filename(Path(hint_name).stem, fallback="report")
            in_jasper = tmp_root / f"{stem}.jasper"
            out_jrxml = tmp_root / f"{stem}.jrxml"
            in_jasper.write_bytes(jasper_bytes)

            res = jasper_daemon.decompile(in_jasper, out_jrxml)
            if out_jrxml.is_file():
                return out_jrxml.read_text(encoding="utf-8")
            if isinstance(res, dict):
                for key in ("jrxml", "content", "xml"):
                    if isinstance(res.get(key), str) and res[key].strip():
                        return res[key]
                out_path = res.get("output") or res.get("output_path")
                if out_path and Path(str(out_path)).is_file():
                    return Path(str(out_path)).read_text(encoding="utf-8")
            raise JasperServerError(
                f"Falha ao decompilar '{hint_name}': jasper_daemon não produziu JRXML."
            )

    def _bytes_to_jrxml(
        self,
        raw_bytes: bytes,
        *,
        source_hint: str,
        jasper_daemon: Any,
    ) -> str:
        if _looks_like_jrxml_bytes(raw_bytes):
            return raw_bytes.decode("utf-8-sig", errors="replace").strip()

        is_jasper = (
            raw_bytes.startswith(_JAVA_SERIALIZED_MAGIC)
            or source_hint.lower().endswith(".jasper")
        )
        if is_jasper:
            return self._decompile_jasper_bytes(
                raw_bytes, jasper_daemon, hint_name=source_hint
            )

        # Try UTF-8 XML decode; if not valid JRXML, attempt decompile as last resort
        text = raw_bytes.decode("utf-8-sig", errors="replace").strip()
        if "<jasperReport" in text:
            return text
        return self._decompile_jasper_bytes(raw_bytes, jasper_daemon, hint_name=source_hint)

    def _download_main_jrxml_for_unit(
        self,
        row: dict[str, Any],
        resource_uri: str,
        main_jrxml_uri: str | None,
        jasper_daemon: Any,
    ) -> tuple[str, str]:
        """
        Download main JRXML for a Report Unit:
        1. Try `GET /rest_v2/resources{resource_uri}?file=jrxml`
        2. Fallback to `GET /rest_v2/resources{main_jrxml_uri}`
        Automatically decompiles if server delivers `.jasper`.
        """
        effective_main_uri = _normalize_repo_uri(
            main_jrxml_uri or f"{resource_uri}_files/main_jrxml"
        )

        # Primary attempt: ?file=jrxml on the reportUnit URI
        try:
            primary_bytes, primary_type = self._download_raw_resource(
                row,
                resource_uri,
                params={"file": "jrxml"},
                allow_404=True,
            )
            if primary_bytes and (
                _looks_like_jrxml_bytes(primary_bytes)
                or primary_bytes.startswith(_JAVA_SERIALIZED_MAGIC)
                or "jrxml" in primary_type.lower()
                or "jasper" in primary_type.lower()
            ):
                jrxml_text = self._bytes_to_jrxml(
                    primary_bytes,
                    source_hint=posixpath.basename(effective_main_uri),
                    jasper_daemon=jasper_daemon,
                )
                return jrxml_text, effective_main_uri
        except JasperServerHttpError:
            pass

        # Fallback: direct download from main_jrxml_uri
        fallback_bytes, _ = self._download_raw_resource(
            row,
            effective_main_uri,
            allow_404=False,
        )
        if not fallback_bytes:
            raise JasperServerHttpError(
                f"Não foi possível baixar o JRXML principal em '{effective_main_uri}'."
            )
        jrxml_text = self._bytes_to_jrxml(
            fallback_bytes,
            source_hint=posixpath.basename(effective_main_uri),
            jasper_daemon=jasper_daemon,
        )
        return jrxml_text, effective_main_uri

    # -------------------------------------------------------------------------
    # Hybrid Subreport & `repo:/...` Resource Mirroring, Cache & Inspection
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_repo_cache_dir(profile_id: str) -> Path:
        safe_pid = _sanitize_local_filename(profile_id, fallback="default")
        return get_data_dir() / "jasperserver_repo_cache" / safe_pid

    def _fetch_remote_repo_resource(
        self,
        row: dict[str, Any],
        candidate_uri: str,
    ) -> tuple[bytes | None, str, str]:
        """
        Fetch a remote `repo:` resource from JasperServer supporting:
        - Exact URI (XML `.jrxml`, binary `.jasper`, images, `.jrtx`, `.properties`);
        - `reportUnit` descriptor used as subreport (resolves `{uri}?file=jrxml` / `main_jrxml_uri` / `{uri}_files/main_jrxml`);
        - Extensionless URI fallbacks (`{uri}.jrxml`, `{uri}.jasper`, `{uri}?file=jrxml`, `{uri}_files/main_jrxml`).
        """
        normalized = _normalize_repo_uri(candidate_uri)
        low = normalized.lower()
        download_candidates: list[str] = [normalized]
        if low.endswith(".jasper"):
            stem_uri = normalized[:-7]
            download_candidates.extend([f"{stem_uri}.jrxml", stem_uri])
        elif low.endswith(".jrxml"):
            stem_uri = normalized[:-6]
            download_candidates.extend([stem_uri, f"{stem_uri}.jasper"])
        else:
            has_known_ext = any(low.endswith(ext) for ext in _REPO_COMMON_EXTENSIONS)
            if not has_known_ext:
                download_candidates.extend([f"{normalized}.jrxml", f"{normalized}.jasper"])

        def _resolve_report_unit_jrxml(unit_uri: str, descriptor: dict[str, Any]) -> tuple[bytes | None, str, str]:
            # 1. Try ?file=jrxml on the reportUnit URI
            try:
                primary_bytes, primary_type = self._download_raw_resource(
                    row, unit_uri, params={"file": "jrxml"}, allow_404=True
                )
                if primary_bytes and (
                    _looks_like_jrxml_bytes(primary_bytes)
                    or primary_bytes.startswith(_JAVA_SERIALIZED_MAGIC)
                    or "jrxml" in primary_type.lower()
                    or "jasper" in primary_type.lower()
                ):
                    resolved_type = "jrxml" if _looks_like_jrxml_bytes(primary_bytes) else (primary_type or "jasper")
                    return primary_bytes, resolved_type, unit_uri
            except JasperServerHttpError:
                pass

            # 2. Try parsed main_jrxml_uri and `{unit_uri}_files/main_jrxml`
            ru_detail = self._parse_report_unit_descriptor(unit_uri, descriptor)
            fallback_uris: list[str] = []
            if ru_detail.main_jrxml_uri:
                fallback_uris.append(_normalize_repo_uri(ru_detail.main_jrxml_uri))
            default_main = _normalize_repo_uri(f"{unit_uri}_files/main_jrxml")
            if default_main not in fallback_uris:
                fallback_uris.append(default_main)

            for main_uri in fallback_uris:
                try:
                    fb_bytes, fb_type = self._download_raw_resource(row, main_uri, allow_404=True)
                except JasperServerHttpError:
                    continue
                if fb_bytes is not None and _is_report_unit_descriptor(fb_bytes, fb_type) is None:
                    resolved_type = "jrxml" if _looks_like_jrxml_bytes(fb_bytes) else (fb_type or "jasper")
                    return fb_bytes, resolved_type, main_uri
            return None, "", unit_uri

        for cand in download_candidates:
            raw_bytes, resolved_type = self._download_raw_resource(row, cand, allow_404=True)
            if raw_bytes is None:
                continue
            ru_desc = _is_report_unit_descriptor(raw_bytes, resolved_type)
            if ru_desc is not None:
                ru_bytes, ru_type, ru_uri = _resolve_report_unit_jrxml(cand, ru_desc)
                if ru_bytes is not None:
                    return ru_bytes, ru_type, ru_uri
                continue
            return raw_bytes, resolved_type, cand

        # Final fallback for extensionless reportUnit where direct GET returned 404
        if not any(low.endswith(ext) for ext in _REPO_COMMON_EXTENSIONS):
            ru_bytes, ru_type, ru_uri = _resolve_report_unit_jrxml(normalized, {})
            if ru_bytes is not None:
                return ru_bytes, ru_type, ru_uri

        return None, "", normalized

    def _mirror_and_compile_resource(
        self,
        *,
        raw_bytes: bytes,
        res_type: str,
        target_uri: str,
        repo_rel_segments: list[str] | None,
        cache_dir: Path | None,
        cache_segments: list[str] | None,
        resources_dir: Path,
        name_hint: str,
        jasper_daemon: Any,
        compiled_subreports: list[str],
        warnings: list[str],
    ) -> tuple[str, str | None]:
        """
        Save a downloaded resource mirroring its exact repository tree under:
        - `resources_dir / "repo" / <rel_path>` (when `repo_rel_segments` is provided)
        - `cache_dir / <cache_rel_path>` (shared server cache, when `cache_dir` + `cache_segments` are provided)
        - `resources_dir / <basename>` (flat compatibility copy)

        Auto-compiles `.jrxml` -> `.jasper` in place using `subreport_dir=resources_dir`.
        Returns `(saved_label, jrxml_text_if_jrxml)`.
        """
        is_jrxml = (
            res_type.lower() == "jrxml"
            or name_hint.lower().endswith(".jrxml")
            or target_uri.lower().endswith(".jrxml")
            or _looks_like_jrxml_bytes(raw_bytes)
        )
        is_jasper = (
            not is_jrxml
            and (
                res_type.lower() == "jasper"
                or name_hint.lower().endswith(".jasper")
                or target_uri.lower().endswith(".jasper")
                or raw_bytes.startswith(_JAVA_SERIALIZED_MAGIC)
            )
        )

        safe_basename = _sanitize_local_filename(name_hint, fallback="resource")
        repo_root = resources_dir / "repo"

        def _adjust_filename(orig_name: str, desired_ext: str) -> str:
            low = orig_name.lower()
            if low.endswith(desired_ext):
                return orig_name
            if desired_ext == ".jrxml" and low.endswith(".jasper"):
                return orig_name[:-7] + ".jrxml"
            if desired_ext == ".jasper" and low.endswith(".jrxml"):
                return orig_name[:-6] + ".jasper"
            return orig_name + desired_ext

        if is_jrxml:
            jrxml_text = raw_bytes.decode("utf-8-sig", errors="replace")
            flat_jrxml_name = _adjust_filename(safe_basename, ".jrxml")
            flat_jrxml_path = resources_dir / flat_jrxml_name
            flat_jasper_path = resources_dir / f"{Path(flat_jrxml_name).stem}.jasper"

            primary_jrxml_path = flat_jrxml_path
            primary_jasper_path = flat_jasper_path
            saved_label = flat_jrxml_name

            if repo_rel_segments:
                tree_filename = _adjust_filename(repo_rel_segments[-1], ".jrxml")
                tree_jrxml_path = _safe_join_under(repo_root, repo_rel_segments, tree_filename)
                if tree_jrxml_path is not None:
                    tree_jrxml_path.parent.mkdir(parents=True, exist_ok=True)
                    tree_jrxml_path.write_text(jrxml_text, encoding="utf-8")
                    primary_jrxml_path = tree_jrxml_path
                    primary_jasper_path = tree_jrxml_path.with_suffix(".jasper")
                    saved_label = "/".join(repo_rel_segments[:-1] + [tree_filename])

            # Flat compatibility copy
            if primary_jrxml_path.resolve() != flat_jrxml_path.resolve():
                flat_jrxml_path.parent.mkdir(parents=True, exist_ok=True)
                flat_jrxml_path.write_text(jrxml_text, encoding="utf-8")
            elif not flat_jrxml_path.is_file():
                flat_jrxml_path.write_text(jrxml_text, encoding="utf-8")

            # Shared cache mirror for .jrxml
            cache_jasper_path: Path | None = None
            if cache_dir is not None and cache_segments:
                cache_filename = _adjust_filename(cache_segments[-1], ".jrxml")
                cache_jrxml_path = _safe_join_under(cache_dir, cache_segments, cache_filename)
                if cache_jrxml_path is not None:
                    cache_jrxml_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_jrxml_path.write_text(jrxml_text, encoding="utf-8")
                    cache_jasper_path = cache_jrxml_path.with_suffix(".jasper")

            # Compile once in place with subreport_dir=resources_dir, then mirror compiled .jasper
            try:
                _call_daemon_compile(
                    jasper_daemon,
                    primary_jrxml_path,
                    primary_jasper_path,
                    resources_dir,
                )
                compiled_subreports.append(primary_jasper_path.name)
                if primary_jasper_path.is_file():
                    if primary_jasper_path.resolve() != flat_jasper_path.resolve():
                        shutil.copy2(primary_jasper_path, flat_jasper_path)
                    if cache_jasper_path is not None:
                        cache_jasper_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(primary_jasper_path, cache_jasper_path)
            except Exception as exc:
                warnings.append(f"Falha ao compilar subreport '{saved_label}': {exc}")

            return saved_label, jrxml_text

        if is_jasper:
            flat_jasper_name = _adjust_filename(safe_basename, ".jasper")
            flat_jasper_path = resources_dir / flat_jasper_name
            flat_jasper_path.write_bytes(raw_bytes)
            saved_label = flat_jasper_name

            if repo_rel_segments:
                tree_filename = _adjust_filename(repo_rel_segments[-1], ".jasper")
                tree_path = _safe_join_under(repo_root, repo_rel_segments, tree_filename)
                if tree_path is not None:
                    tree_path.parent.mkdir(parents=True, exist_ok=True)
                    tree_path.write_bytes(raw_bytes)
                    saved_label = "/".join(repo_rel_segments[:-1] + [tree_filename])

            if cache_dir is not None and cache_segments:
                cache_filename = _adjust_filename(cache_segments[-1], ".jasper")
                cache_path = _safe_join_under(cache_dir, cache_segments, cache_filename)
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(raw_bytes)

            return saved_label, None

        # Non-report resource (images, styles .jrtx, properties, etc.)
        flat_path = resources_dir / safe_basename
        flat_path.write_bytes(raw_bytes)
        saved_label = safe_basename

        if repo_rel_segments:
            tree_path = _safe_join_under(repo_root, repo_rel_segments)
            if tree_path is not None:
                tree_path.parent.mkdir(parents=True, exist_ok=True)
                tree_path.write_bytes(raw_bytes)
                saved_label = "/".join(repo_rel_segments)

        if cache_dir is not None and cache_segments:
            cache_path = _safe_join_under(cache_dir, cache_segments)
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(raw_bytes)

        return saved_label, None

    def _hydrate_from_repo_cache(
        self,
        *,
        cache_dir: Path,
        cache_segments: list[str],
        repo_rel_segments: list[str],
        resources_dir: Path,
        kind: Literal["subreport", "image", "style", "other"],
        jasper_daemon: Any,
        compiled_subreports: list[str],
        warnings: list[str],
    ) -> tuple[bool, str | None, str | None]:
        """
        Try to satisfy a `repo:` reference from the shared per-profile cache
        (`get_data_dir() / "jasperserver_repo_cache" / <profile_id>`).
        Returns `(hit, saved_label, jrxml_text_if_any)`.
        """
        if not cache_dir.is_dir():
            return False, None, None

        cache_ref = "/" + "/".join(cache_segments)
        found = _resolve_local_repo_resource(cache_dir, cache_ref, kind)
        if not found["resolved"]:
            return False, None, None

        repo_root = resources_dir / "repo"
        jrxml_text: str | None = None
        saved_label: str | None = None

        cached_jrxml: Path | None = found["jrxml_path"]
        cached_jasper: Path | None = found["jasper_path"]
        cached_file: Path | None = found["file_path"]

        if cached_jrxml is not None and cached_jrxml.is_file():
            jrxml_text = cached_jrxml.read_text(encoding="utf-8", errors="replace")
            tree_jrxml_name = cached_jrxml.name
            tree_jrxml = _safe_join_under(repo_root, repo_rel_segments, tree_jrxml_name)
            flat_jrxml = resources_dir / _sanitize_local_filename(tree_jrxml_name, fallback="subreport.jrxml")
            if tree_jrxml is not None:
                tree_jrxml.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached_jrxml, tree_jrxml)
                saved_label = "/".join(repo_rel_segments[:-1] + [tree_jrxml_name])
            shutil.copy2(cached_jrxml, flat_jrxml)

            target_jasper = tree_jrxml.with_suffix(".jasper") if tree_jrxml is not None else flat_jrxml.with_suffix(".jasper")
            flat_jasper = resources_dir / f"{flat_jrxml.stem}.jasper"

            if cached_jasper is not None and cached_jasper.is_file():
                target_jasper.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached_jasper, target_jasper)
                if target_jasper.resolve() != flat_jasper.resolve():
                    shutil.copy2(cached_jasper, flat_jasper)
            else:
                src_to_compile = tree_jrxml if tree_jrxml is not None else flat_jrxml
                try:
                    _call_daemon_compile(jasper_daemon, src_to_compile, target_jasper, resources_dir)
                    compiled_subreports.append(target_jasper.name)
                    if target_jasper.is_file():
                        if target_jasper.resolve() != flat_jasper.resolve():
                            shutil.copy2(target_jasper, flat_jasper)
                        cache_jasper_dst = cached_jrxml.with_suffix(".jasper")
                        shutil.copy2(target_jasper, cache_jasper_dst)
                except Exception as exc:
                    warnings.append(f"Falha ao compilar subreport em cache '{saved_label or flat_jrxml.name}': {exc}")
            return True, saved_label or flat_jrxml.name, jrxml_text

        if cached_file is not None and cached_file.is_file():
            tree_name = cached_file.name
            tree_dst = _safe_join_under(repo_root, repo_rel_segments, tree_name)
            if tree_dst is not None:
                tree_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached_file, tree_dst)
                saved_label = "/".join(repo_rel_segments[:-1] + [tree_name])
            flat_dst = resources_dir / _sanitize_local_filename(tree_name, fallback="resource.bin")
            shutil.copy2(cached_file, flat_dst)
            return True, saved_label or flat_dst.name, None

        return False, None, None

    @staticmethod
    def inspect_project_repo_resources(
        jrxml_text: str,
        resources_dir: Path | str,
        *,
        can_sync_remote: bool = False,
    ) -> dict[str, Any]:
        """
        Inspect all `repo:...` references (recursively across main JRXML and any locally
        available `.jrxml` subreports) and report resolution & compilation status matching
        `RepoResourcesStatus`.
        """
        res_dir = Path(resources_dir)
        pending: list[tuple[str, Literal["subreport", "image", "style", "other"]]] = (
            _extract_repo_references_with_kind(jrxml_text)
        )
        seen_refs: dict[str, Literal["subreport", "image", "style", "other"]] = {
            ref: kind for ref, kind in pending
        }
        scanned_jrxml_paths: set[Path] = set()

        items: list[dict[str, Any]] = []
        warnings: list[str] = []

        idx = 0
        while idx < len(pending):
            ref, kind = pending[idx]
            idx += 1
            effective_kind = seen_refs.get(ref, kind)

            lookup = _resolve_local_repo_resource(res_dir, ref, effective_kind)
            uri_label = ref if ref.lower().startswith("repo:") else f"repo:{ref}"

            items.append(
                {
                    "uri": uri_label,
                    "local_path": lookup["local_path"],
                    "resolved": bool(lookup["resolved"]),
                    "compiled": bool(lookup["compiled"]),
                    "kind": effective_kind,
                }
            )

            if not lookup["resolved"]:
                warnings.append(f"Recurso '{uri_label}' não encontrado localmente em report_unit_resources.")
            elif effective_kind == "subreport" and not lookup["compiled"]:
                warnings.append(
                    f"Subreport '{uri_label}' encontrado em JRXML mas ainda sem versão compilada (.jasper)."
                )

            # Recursively inspect nested `repo:...` references inside resolved `.jrxml` subreports
            local_jrxml: Path | None = lookup["jrxml_path"]
            if local_jrxml is not None and local_jrxml.is_file():
                norm_jrxml = local_jrxml.resolve()
                if norm_jrxml not in scanned_jrxml_paths:
                    scanned_jrxml_paths.add(norm_jrxml)
                    try:
                        nested_xml = norm_jrxml.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        nested_xml = ""
                    for nested_ref, nested_kind in _extract_repo_references_with_kind(nested_xml):
                        if nested_ref not in seen_refs:
                            seen_refs[nested_ref] = nested_kind
                            pending.append((nested_ref, nested_kind))
                        elif seen_refs[nested_ref] == "other" and nested_kind != "other":
                            seen_refs[nested_ref] = nested_kind

        resolved_count = sum(1 for item in items if item["resolved"])
        missing_count = len(items) - resolved_count
        return {
            "total": len(items),
            "resolved_count": resolved_count,
            "missing_count": missing_count,
            "can_sync_remote": bool(can_sync_remote),
            "items": items,
            "warnings": warnings,
        }

    def sync_missing_repo_resources(
        self,
        profile_id: str,
        jrxml_text: str,
        resources_dir: Path | str,
        jasper_daemon: Any,
        *,
        resource_uri: str | None = None,
    ) -> dict[str, Any]:
        """
        Sync any missing (or uncompiled) `repo:...` resources referenced by `jrxml_text`
        (recursively across nested `.jrxml` subreports) from shared server cache or remote
        JasperReports Server, mirroring into `resources_dir/repo/...` + flat basename copy
        and auto-compiling `.jrxml` -> `.jasper`.
        """
        row = self._require_profile_row(profile_id)
        res_dir = Path(resources_dir)
        res_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = self._get_repo_cache_dir(profile_id)

        synced_uris: list[str] = []
        compiled_files: list[str] = []
        sync_warnings: list[str] = []

        pending: list[tuple[str, Literal["subreport", "image", "style", "other"]]] = (
            _extract_repo_references_with_kind(jrxml_text)
        )
        seen_refs: dict[str, Literal["subreport", "image", "style", "other"]] = {
            ref: kind for ref, kind in pending
        }
        processed_refs: set[str] = set()

        def _enqueue_nested(nested_xml: str) -> None:
            for nested_ref, nested_kind in _extract_repo_references_with_kind(nested_xml):
                if nested_ref not in seen_refs:
                    seen_refs[nested_ref] = nested_kind
                    pending.append((nested_ref, nested_kind))
                elif seen_refs[nested_ref] == "other" and nested_kind != "other":
                    seen_refs[nested_ref] = nested_kind

        idx = 0
        while idx < len(pending):
            ref, kind = pending[idx]
            idx += 1
            if ref in processed_refs:
                continue
            processed_refs.add(ref)
            effective_kind = seen_refs.get(ref, kind)

            rel_segments = _repo_ref_to_rel_segments(ref)
            if not rel_segments:
                sync_warnings.append(f"URI repo inválida ignorada: 'repo:{ref}'.")
                continue

            # 1. Already present locally? Ensure compiled if JRXML and scan nested refs.
            local_check = _resolve_local_repo_resource(res_dir, ref, effective_kind)
            if local_check["resolved"]:
                local_jrxml: Path | None = local_check["jrxml_path"]
                if local_jrxml is not None and local_jrxml.is_file():
                    try:
                        _enqueue_nested(local_jrxml.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        pass
                    if not local_check["compiled"]:
                        target_jasper = local_jrxml.with_suffix(".jasper")
                        try:
                            _call_daemon_compile(jasper_daemon, local_jrxml, target_jasper, res_dir)
                            compiled_files.append(target_jasper.name)
                            flat_jasper = res_dir / target_jasper.name
                            if target_jasper.is_file() and target_jasper.resolve() != flat_jasper.resolve():
                                shutil.copy2(target_jasper, flat_jasper)
                        except Exception as exc:
                            sync_warnings.append(f"Falha ao compilar subreport local 'repo:{ref}': {exc}")
                continue

            # Determine remote absolute candidate URI and cache segments
            is_absolute = ref.startswith("/")
            if is_absolute:
                candidate_uri = _normalize_repo_uri(ref)
                cache_segments = list(rel_segments)
            elif resource_uri:
                candidate_uri = _normalize_repo_uri(f"{_normalize_repo_uri(resource_uri)}_files/{ref}")
                cache_segments = _repo_ref_to_rel_segments(candidate_uri) or list(rel_segments)
            else:
                candidate_uri = _normalize_repo_uri(ref)
                cache_segments = list(rel_segments)

            # 2. Check shared server cache first (reusing headers/logos across reports)
            if is_absolute:
                hit, _saved_label, cached_xml = self._hydrate_from_repo_cache(
                    cache_dir=cache_dir,
                    cache_segments=cache_segments,
                    repo_rel_segments=rel_segments,
                    resources_dir=res_dir,
                    kind=effective_kind,
                    jasper_daemon=jasper_daemon,
                    compiled_subreports=compiled_files,
                    warnings=sync_warnings,
                )
                if hit:
                    synced_uris.append(f"repo:{ref}")
                    if cached_xml:
                        _enqueue_nested(cached_xml)
                    continue

            # 3. Fetch from remote JasperReports Server
            try:
                raw_bytes, resolved_type, resolved_uri = self._fetch_remote_repo_resource(
                    row, candidate_uri
                )
            except JasperServerHttpError as exc:
                sync_warnings.append(f"Erro ao baixar recurso 'repo:{ref}': {exc}")
                continue

            if raw_bytes is None:
                sync_warnings.append(f"Recurso referenciado via repo não encontrado no servidor: 'repo:{ref}'.")
                continue

            _saved_label, downloaded_xml = self._mirror_and_compile_resource(
                raw_bytes=raw_bytes,
                res_type=resolved_type,
                target_uri=resolved_uri,
                repo_rel_segments=rel_segments,
                cache_dir=cache_dir if is_absolute else None,
                cache_segments=cache_segments if is_absolute else None,
                resources_dir=res_dir,
                name_hint=posixpath.basename(ref) or posixpath.basename(resolved_uri),
                jasper_daemon=jasper_daemon,
                compiled_subreports=compiled_files,
                warnings=sync_warnings,
            )
            synced_uris.append(f"repo:{ref}")
            if downloaded_xml:
                _enqueue_nested(downloaded_xml)

        status = self.inspect_project_repo_resources(
            jrxml_text,
            res_dir,
            can_sync_remote=True,
        )
        merged_warnings = list(dict.fromkeys(list(status["warnings"]) + sync_warnings))
        return {
            **status,
            "warnings": merged_warnings,
            "synced": synced_uris,
            "compiled": compiled_files,
        }

    def _sync_report_unit_subreports(
        self,
        row: dict[str, Any],
        *,
        resource_uri: str,
        main_jrxml_uri: str,
        main_jrxml_text: str,
        detail: JasperServerReportUnitDetail,
        resources_dir: Path,
        jasper_daemon: Any,
    ) -> dict[str, Any]:
        """
        Download and compile BOTH subreport/resource patterns into `workspaces/<proj>/report_unit_resources/`:
        1. Embedded resources attached to the Report Unit (`{uri}_files/*`).
        2. Shared repository resources referenced via `repo:/...` across `<subreportExpression>`,
           `<imageExpression>`, `<template>`, and expressions recursively, mirrored into
           `report_unit_resources/repo/<rel_path>` + shared per-profile cache + flat basename copy.
        """
        resources_dir.mkdir(parents=True, exist_ok=True)
        profile_id = str(row["id"])
        cache_dir = self._get_repo_cache_dir(profile_id)

        synced_embedded: list[str] = []
        synced_repo: list[str] = []
        compiled_subreports: list[str] = []
        warnings: list[str] = []

        visited_uris: set[str] = {_normalize_repo_uri(main_jrxml_uri)}
        pending_repo_refs: list[tuple[str, Literal["subreport", "image", "style", "other"]]] = (
            _extract_repo_references_with_kind(main_jrxml_text)
        )
        known_ref_kinds: dict[str, Literal["subreport", "image", "style", "other"]] = {
            ref: kind for ref, kind in pending_repo_refs
        }

        def _enqueue_from_xml(xml_text: str) -> None:
            for nested_ref, nested_kind in _extract_repo_references_with_kind(xml_text):
                if nested_ref not in known_ref_kinds:
                    known_ref_kinds[nested_ref] = nested_kind
                    pending_repo_refs.append((nested_ref, nested_kind))
                elif known_ref_kinds[nested_ref] == "other" and nested_kind != "other":
                    known_ref_kinds[nested_ref] = nested_kind

        # Pattern 1: Embedded unit resources (`{uri}_files/*`)
        for res in detail.resources:
            try:
                res_uri = _normalize_repo_uri(res.uri)
            except JasperServerValidationError:
                continue
            if res_uri in visited_uris:
                continue
            visited_uris.add(res_uri)

            try:
                raw_bytes, ctype = self._download_raw_resource(row, res_uri, allow_404=True)
            except JasperServerHttpError as exc:
                warnings.append(f"Falha ao baixar recurso '{res_uri}': {exc}")
                continue
            if raw_bytes is None:
                warnings.append(f"Recurso embutido não encontrado no servidor: '{res_uri}'.")
                continue

            embedded_name = res.name or posixpath.basename(res_uri)
            embedded_segments = _repo_ref_to_rel_segments(embedded_name)
            saved_label, jrxml_text = self._mirror_and_compile_resource(
                raw_bytes=raw_bytes,
                res_type=res.type or ctype,
                target_uri=res_uri,
                repo_rel_segments=embedded_segments,
                cache_dir=None,
                cache_segments=None,
                resources_dir=resources_dir,
                name_hint=embedded_name,
                jasper_daemon=jasper_daemon,
                compiled_subreports=compiled_subreports,
                warnings=warnings,
            )
            synced_embedded.append(saved_label)
            if jrxml_text:
                _enqueue_from_xml(jrxml_text)

        # Pattern 2: Shared repository resources referenced via `repo:/...` (or relative `repo:name`)
        idx = 0
        while idx < len(pending_repo_refs):
            ref, kind = pending_repo_refs[idx]
            idx += 1
            effective_kind = known_ref_kinds.get(ref, kind)

            is_absolute = ref.startswith("/")
            try:
                if is_absolute:
                    candidate_uri = _normalize_repo_uri(ref)
                else:
                    candidate_uri = _normalize_repo_uri(f"{resource_uri}_files/{ref}")
            except JasperServerValidationError:
                warnings.append(f"URI repo inválida ignorada: 'repo:{ref}'.")
                continue

            if candidate_uri in visited_uris:
                continue
            visited_uris.add(candidate_uri)

            rel_segments = _repo_ref_to_rel_segments(ref)
            if not rel_segments:
                warnings.append(f"URI repo inválida ignorada: 'repo:{ref}'.")
                continue

            # Try shared per-profile cache for absolute `repo:/...` paths first
            if is_absolute:
                hit, cached_label, cached_xml = self._hydrate_from_repo_cache(
                    cache_dir=cache_dir,
                    cache_segments=rel_segments,
                    repo_rel_segments=rel_segments,
                    resources_dir=resources_dir,
                    kind=effective_kind,
                    jasper_daemon=jasper_daemon,
                    compiled_subreports=compiled_subreports,
                    warnings=warnings,
                )
                if hit:
                    synced_repo.append(cached_label or ref)
                    if cached_xml:
                        _enqueue_from_xml(cached_xml)
                    continue

            try:
                raw_bytes, resolved_type, resolved_uri = self._fetch_remote_repo_resource(
                    row, candidate_uri
                )
            except JasperServerHttpError as exc:
                warnings.append(f"Erro ao baixar recurso '{candidate_uri}': {exc}")
                continue

            if raw_bytes is None:
                warnings.append(f"Subreport referenciado via repo não encontrado: 'repo:{ref}'.")
                continue

            saved_label, jrxml_text = self._mirror_and_compile_resource(
                raw_bytes=raw_bytes,
                res_type=resolved_type,
                target_uri=resolved_uri,
                repo_rel_segments=rel_segments,
                cache_dir=cache_dir if is_absolute else None,
                cache_segments=rel_segments if is_absolute else None,
                resources_dir=resources_dir,
                name_hint=posixpath.basename(ref) or posixpath.basename(resolved_uri),
                jasper_daemon=jasper_daemon,
                compiled_subreports=compiled_subreports,
                warnings=warnings,
            )
            synced_repo.append(saved_label)
            if jrxml_text:
                _enqueue_from_xml(jrxml_text)

        return {
            "embedded_resources": synced_embedded,
            "repo_subreports": synced_repo,
            "compiled_subreports": compiled_subreports,
            "warnings": warnings,
        }

    def import_report_to_project(
        self,
        profile_id: str,
        resource_uri: str,
        workspace_service: WorkspaceService,
        jasper_daemon: Any,
        *,
        project_name: str | None = None,
        db_profile_id: str | None = None,
        sync_subreports: bool = True,
    ) -> ProjectRead:
        """
        Import a JasperReports Server Report Unit (or standalone JRXML/Jasper file) into a new
        `free_report` project with `entry_mode='jasperserver_import'`, downloading & compiling
        embedded `{uri}_files/*` resources and shared `repo:/...` subreports.
        """
        row = self._require_profile_row(profile_id)
        normalized_uri = _normalize_repo_uri(resource_uri)

        # Inspect Report Unit (fallback gracefully if importing a standalone .jrxml/.jasper file)
        detail: JasperServerReportUnitDetail | None = None
        is_standalone_file = normalized_uri.lower().endswith((".jrxml", ".jasper"))
        if not is_standalone_file:
            try:
                detail = self.inspect_report_unit(profile_id, normalized_uri)
            except JasperServerHttpError:
                detail = None

        if detail is not None:
            main_jrxml_text, effective_main_uri = self._download_main_jrxml_for_unit(
                row,
                normalized_uri,
                detail.main_jrxml_uri,
                jasper_daemon,
            )
            default_label = detail.label or posixpath.basename(normalized_uri)
            datasource_uri = detail.datasource_uri
        else:
            raw_bytes, _ = self._download_raw_resource(row, normalized_uri, allow_404=False)
            if not raw_bytes:
                raise JasperServerHttpError(f"Arquivo '{normalized_uri}' está vazio.")
            main_jrxml_text = self._bytes_to_jrxml(
                raw_bytes,
                source_hint=posixpath.basename(normalized_uri),
                jasper_daemon=jasper_daemon,
            )
            effective_main_uri = normalized_uri
            default_label = Path(posixpath.basename(normalized_uri)).stem or "relatorio_jasperserver"
            datasource_uri = None
            detail = JasperServerReportUnitDetail(
                uri=normalized_uri,
                label=default_label,
                main_jrxml_uri=effective_main_uri,
            )

        validated_jrxml = validate_jrxml_content(main_jrxml_text)
        final_name = (project_name or "").strip() or default_label
        effective_db_profile = (
            db_profile_id.strip()
            if isinstance(db_profile_id, str) and db_profile_id.strip()
            else row.get("linked_db_profile_id")
        )

        source_origin: dict[str, Any] = {
            "provider": "jasperserver",
            "profile_id": profile_id,
            "resource_uri": normalized_uri,
            "main_jrxml_uri": effective_main_uri,
            "datasource_uri": datasource_uri,
        }

        project = workspace_service.create_project(
            ProjectCreate(
                name=final_name,
                description=detail.description or f"Importado do JasperReports Server ({normalized_uri})",
                project_kind="free_report",
                entry_mode="jasperserver_import",
                default_db_profile_id=effective_db_profile,
                source_origin=source_origin,
                initial_jrxml=validated_jrxml,
            )
        )

        if sync_subreports:
            resources_dir = Path(project.workspace_dir) / "report_unit_resources"
            sync_info = self._sync_report_unit_subreports(
                row,
                resource_uri=normalized_uri,
                main_jrxml_uri=effective_main_uri,
                main_jrxml_text=validated_jrxml,
                detail=detail,
                resources_dir=resources_dir,
                jasper_daemon=jasper_daemon,
            )
            if any(sync_info.values()):
                enriched_origin = dict(source_origin)
                enriched_origin["synced_resources"] = sync_info
                project = workspace_service.update_project(
                    project.id,
                    ProjectUpdate(source_origin=enriched_origin),
                )

        return project

    # -------------------------------------------------------------------------
    # Safe 2-Step Deploy: Prepare Preview + Execute
    # -------------------------------------------------------------------------

    def _compile_project_jrxml_for_deploy(
        self,
        project: ProjectRead,
        local_jrxml: str,
        jasper_daemon: Any,
    ) -> None:
        ws_dir = Path(project.workspace_dir)
        artifacts_dir = ws_dir / "artifacts"
        exports_dir = ws_dir / "exports"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)

        jrxml_path = artifacts_dir / f"{project.slug}.jrxml"
        jrxml_path.write_text(
            local_jrxml if local_jrxml.endswith("\n") else local_jrxml + "\n",
            encoding="utf-8",
        )
        jasper_check_path = exports_dir / f"{project.slug}_deploy_check.jasper"
        resources_dir = ws_dir / "report_unit_resources"
        subreport_dir = resources_dir if resources_dir.is_dir() else None

        try:
            jasper_daemon.compile(
                jrxml_path,
                jasper_check_path,
                subreport_dir=subreport_dir,
            )
        except Exception as exc:
            raise JasperServerCompileError(
                f"Compilação JVM falhou; deploy bloqueado: {exc}"
            ) from exc

    def prepare_deploy_preview(
        self,
        project_id: str,
        profile_id: str,
        workspace_service: WorkspaceService,
        jasper_daemon: Any,
        *,
        mode: DeployMode = "update",
        target_uri: str,
        main_jrxml_uri: str | None = None,
        label: str | None = None,
        datasource_uri: str | None = None,
    ) -> JasperServerDeployPreview:
        """
        Step 1 of safe deploy:
        - Blocks `read_only=True` profiles (403).
        - Validates and compiles local `.jrxml` via JVM daemon (blocks on compile failure).
        - Downloads remote `main_jrxml` (for `update`) and computes unified diff + SHA-256.
        - Issues a single-use `deploy_token` persisted in SQLite.
        """
        row = self._require_profile_row(profile_id)
        if bool(row["read_only"]):
            raise ReadOnlyJasperServerProfileError(
                f"Perfil JasperServer '{row['name']}' está em modo Somente Leitura (read_only). "
                "Deploy bloqueado."
            )

        if mode not in ("update", "create"):
            raise JasperServerValidationError(f"Modo de deploy inválido: '{mode}'.")

        normalized_target = _normalize_repo_uri(target_uri)
        if normalized_target == "/":
            raise JasperServerValidationError(
                "target_uri não pode ser a raiz '/'. Informe o caminho completo da Report Unit."
            )

        project = workspace_service.get_project(project_id)
        latest_jrxml_rev = workspace_service.get_latest_artifact(project_id, "jrxml")
        local_jrxml = validate_jrxml_content(latest_jrxml_rev.content)
        local_sha256 = hashlib.sha256(local_jrxml.encode("utf-8")).hexdigest()

        # Mandatory JVM compilation gate before generating deploy token
        self._compile_project_jrxml_for_deploy(project, local_jrxml, jasper_daemon)

        effective_label = (label or "").strip() or project.name or posixpath.basename(normalized_target)
        effective_datasource = (
            _normalize_repo_uri(datasource_uri)
            if isinstance(datasource_uri, str) and datasource_uri.strip()
            else None
        )

        remote_exists = False
        remote_jrxml: str | None = None
        remote_sha256: str | None = None

        if mode == "update":
            if main_jrxml_uri and main_jrxml_uri.strip():
                effective_main_uri = _normalize_repo_uri(main_jrxml_uri)
            else:
                try:
                    detail = self.inspect_report_unit(profile_id, normalized_target)
                    effective_main_uri = _normalize_repo_uri(
                        detail.main_jrxml_uri or f"{normalized_target}_files/main_jrxml"
                    )
                except JasperServerHttpError:
                    effective_main_uri = _normalize_repo_uri(
                        f"{normalized_target}_files/main_jrxml"
                    )

            remote_bytes, _ = self._download_raw_resource(
                row,
                effective_main_uri,
                allow_404=True,
            )
            if remote_bytes is None:
                remote_bytes, _ = self._download_raw_resource(
                    row,
                    normalized_target,
                    params={"file": "jrxml"},
                    allow_404=True,
                )

            if remote_bytes is not None:
                remote_exists = True
                if _looks_like_jrxml_bytes(remote_bytes):
                    remote_jrxml = remote_bytes.decode("utf-8-sig", errors="replace").strip()
                else:
                    try:
                        remote_jrxml = self._bytes_to_jrxml(
                            remote_bytes,
                            source_hint=posixpath.basename(effective_main_uri),
                            jasper_daemon=jasper_daemon,
                        )
                    except Exception:
                        remote_jrxml = remote_bytes.decode("utf-8-sig", errors="replace")
                remote_sha256 = hashlib.sha256(remote_jrxml.encode("utf-8")).hexdigest()
        else:
            effective_main_uri = _normalize_repo_uri(
                main_jrxml_uri or f"{normalized_target}_files/main_jrxml"
            )
            check_resp = self._request(
                row,
                "GET",
                f"/rest_v2/resources{normalized_target}",
                headers={"Accept": "application/json"},
                allow_404=True,
            )
            remote_exists = check_resp.status_code < 400

        unified_diff = "".join(
            difflib.unified_diff(
                (remote_jrxml or "").splitlines(keepends=True),
                local_jrxml.splitlines(keepends=True),
                fromfile=f"remote:{effective_main_uri}" if remote_exists else "(novo)",
                tofile=f"local:{project.slug}.jrxml",
            )
        )

        token_payload = f"{project_id}:{profile_id}:{local_sha256}:{secrets.token_hex(16)}"
        deploy_token = f"jsd_{hashlib.sha256(token_payload.encode('utf-8')).hexdigest()[:24]}_{secrets.token_urlsafe(12)}"
        now = utc_now_iso()

        self._ensure_tables()
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO jasperserver_deploy_tokens (
                    token, project_id, profile_id, mode, target_uri, main_jrxml_uri,
                    label, datasource_uri, local_sha256, remote_sha256,
                    remote_jrxml_snapshot, created_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    deploy_token,
                    project_id,
                    profile_id,
                    mode,
                    normalized_target,
                    effective_main_uri,
                    effective_label,
                    effective_datasource,
                    local_sha256,
                    remote_sha256,
                    remote_jrxml,
                    now,
                ),
            )

        msg = (
            "Compilação JVM OK. Diff gerado pronto para atualização no JasperServer."
            if mode == "update"
            else "Compilação JVM OK. Pronto para criar nova Report Unit no JasperServer."
        )
        return JasperServerDeployPreview(
            ok=True,
            project_id=project_id,
            profile_id=profile_id,
            mode=mode,
            target_uri=normalized_target,
            main_jrxml_uri=effective_main_uri,
            remote_exists=remote_exists,
            unified_diff=unified_diff,
            local_sha256=local_sha256,
            remote_sha256=remote_sha256,
            deploy_token=deploy_token,
            compiled_ok=True,
            message=msg,
        )

    def execute_deploy(
        self,
        project_id: str,
        deploy_token: str,
        workspace_service: WorkspaceService,
    ) -> JasperServerDeployResult:
        """
        Step 2 of safe deploy:
        - Validates `read_only=False`, local SHA-256 match, and unconsumed single-use `deploy_token`.
        - Atomically consumes token.
        - For `update`: writes local backup `workspaces/<proj>/backups/jasperserver_<ts>_main.jrxml`
          and sends `PUT /rest_v2/resources{main_jrxml_uri}?overwrite=true&createFolders=true`
          (`application/repository.file+json` with base64 content).
        - For `create`: sends `PUT /rest_v2/resources{target_uri}?overwrite=false&createFolders=true`
          (`application/repository.reportUnit+json` with embedded `jrxmlFile` + `dataSource`).
        """
        cleaned_token = (deploy_token or "").strip()
        if not cleaned_token:
            raise JasperServerDeployTokenError("deploy_token é obrigatório.")

        self._ensure_tables()
        with self.store.connection() as conn:
            tok_row = conn.execute(
                """
                SELECT * FROM jasperserver_deploy_tokens
                WHERE token = ? AND project_id = ?
                """,
                (cleaned_token, project_id),
            ).fetchone()

        if tok_row is None:
            raise JasperServerDeployTokenError(
                "Token de deploy inválido ou não pertence a este projeto."
            )
        token_data = dict(tok_row)
        if token_data.get("consumed_at") is not None:
            raise JasperServerDeployTokenError(
                "Token de deploy já foi consumido. Gere um novo preview antes de publicar novamente."
            )

        profile_id = str(token_data["profile_id"])
        profile_row = self._require_profile_row(profile_id)
        if bool(profile_row["read_only"]):
            raise ReadOnlyJasperServerProfileError(
                f"Perfil JasperServer '{profile_row['name']}' está em modo Somente Leitura (read_only). "
                "Deploy bloqueado."
            )

        project = workspace_service.get_project(project_id)
        latest_jrxml_rev = workspace_service.get_latest_artifact(project_id, "jrxml")
        local_jrxml = validate_jrxml_content(latest_jrxml_rev.content)
        current_sha256 = hashlib.sha256(local_jrxml.encode("utf-8")).hexdigest()
        if current_sha256 != str(token_data["local_sha256"]):
            raise JasperServerDeployTokenError(
                "O conteúdo JRXML do projeto mudou após o preview. Gere um novo preview antes de confirmar."
            )

        # Atomic single-use token consumption
        now = utc_now_iso()
        with self.store.connection() as conn:
            cur = conn.execute(
                """
                UPDATE jasperserver_deploy_tokens
                SET consumed_at = ?
                WHERE token = ? AND project_id = ? AND consumed_at IS NULL
                """,
                (now, cleaned_token, project_id),
            )
            if cur.rowcount != 1:
                raise JasperServerDeployTokenError(
                    "Token de deploy já foi consumido por outra requisição."
                )

        mode: DeployMode = "create" if token_data["mode"] == "create" else "update"
        target_uri = str(token_data["target_uri"])
        main_jrxml_uri = str(token_data["main_jrxml_uri"])
        label = str(token_data.get("label") or project.name or "main_jrxml")
        datasource_uri = token_data.get("datasource_uri")
        b64_content = base64.b64encode(local_jrxml.encode("utf-8")).decode("ascii")

        local_backup_path: str | None = None

        if mode == "update":
            backup_content = token_data.get("remote_jrxml_snapshot")
            if backup_content is None:
                remote_bytes, _ = self._download_raw_resource(
                    profile_row, main_jrxml_uri, allow_404=True
                )
                if remote_bytes is not None:
                    backup_content = remote_bytes.decode("utf-8-sig", errors="replace")

            backups_dir = Path(project.workspace_dir) / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_file = backups_dir / f"jasperserver_{stamp}_main.jrxml"
            backup_file.write_text(
                str(backup_content if backup_content is not None else local_jrxml),
                encoding="utf-8",
            )
            local_backup_path = str(backup_file)

            file_payload = {
                "label": posixpath.basename(main_jrxml_uri) or "main_jrxml",
                "type": "jrxml",
                "content": b64_content,
            }
            self._request(
                profile_row,
                "PUT",
                f"/rest_v2/resources{main_jrxml_uri}",
                params={"overwrite": "true", "createFolders": "true"},
                headers={
                    "Content-Type": "application/repository.file+json",
                    "Accept": "application/json",
                },
                json_body=file_payload,
            )
            msg = f"Report Unit atualizada com sucesso em '{main_jrxml_uri}'."
        else:
            report_unit_payload: dict[str, Any] = {
                "label": label,
                "description": project.description or "",
                "jrxml": {
                    "jrxmlFile": {
                        "label": "main_jrxml",
                        "type": "jrxml",
                        "content": b64_content,
                    }
                },
                "alwaysPromptControls": False,
            }
            if datasource_uri:
                report_unit_payload["dataSource"] = {
                    "dataSourceReference": {"uri": str(datasource_uri)}
                }

            self._request(
                profile_row,
                "PUT",
                f"/rest_v2/resources{target_uri}",
                params={"overwrite": "false", "createFolders": "true"},
                headers={
                    "Content-Type": "application/repository.reportUnit+json",
                    "Accept": "application/json",
                },
                json_body=report_unit_payload,
            )

            # Record new source_origin on the project for future 1-click update deploys
            try:
                new_origin = dict(project.source_origin or {})
                new_origin.update(
                    {
                        "provider": "jasperserver",
                        "profile_id": profile_id,
                        "resource_uri": target_uri,
                        "main_jrxml_uri": main_jrxml_uri,
                        "datasource_uri": datasource_uri,
                    }
                )
                workspace_service.update_project(
                    project_id,
                    ProjectUpdate(source_origin=new_origin),
                )
            except Exception:
                pass

            msg = f"Nova Report Unit criada com sucesso em '{target_uri}'."

        return JasperServerDeployResult(
            ok=True,
            project_id=project_id,
            profile_id=profile_id,
            mode=mode,
            target_uri=target_uri,
            main_jrxml_uri=main_jrxml_uri,
            local_backup_path=local_backup_path,
            message=msg,
        )


__all__ = [
    "DeployMode",
    "JasperResourceType",
    "JasperServerCompileError",
    "JasperServerDeployPreview",
    "JasperServerDeployResult",
    "JasperServerDeployTokenError",
    "JasperServerError",
    "JasperServerHttpError",
    "JasperServerProfileCreate",
    "JasperServerProfileNotFoundError",
    "JasperServerProfileRead",
    "JasperServerProfileUpdate",
    "JasperServerReportUnitDetail",
    "JasperServerReportUnitResource",
    "JasperServerResourceItem",
    "JasperServerService",
    "JasperServerTestResult",
    "JasperServerValidationError",
    "ReadOnlyJasperServerProfileError",
]
