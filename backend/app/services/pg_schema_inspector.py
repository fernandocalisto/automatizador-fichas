# -*- coding: utf-8 -*-
"""Read-only PostgreSQL schema inspector and safe SELECT preview service."""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import math
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel, Field

from backend.app.services.postgres_service import (
    DbProfileValidationError,
    PostgresConnectionError,
    PostgresExecutionError,
    PostgresService,
    PostgresServiceError,
    SelectColumnMeta,
)

DEFAULT_STATEMENT_TIMEOUT_MS = "10000"
MIN_PREVIEW_LIMIT = 1
MAX_PREVIEW_LIMIT = 200
DEFAULT_PREVIEW_LIMIT = 50
MAX_TABLES_LIMIT = 500

_JASPER_PLACEHOLDER_RE = re.compile(
    r"\$P(!?)\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}|\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}"
)
_FORBIDDEN_SQL_KEYWORD_RE = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|"
    r"MERGE|COPY|CALL|DO|EXECUTE|VACUUM|REINDEX|CLUSTER|LOCK"
    r")\b",
    re.IGNORECASE,
)
_SELECT_INTO_RE = re.compile(r"\bSELECT\b[\s\S]*?\bINTO\b", re.IGNORECASE)
_DOLLAR_QUOTE_RE = re.compile(r"\$[A-Za-z0-9_]*\$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")

_UDT_TO_JAVA_CLASS: dict[str, str] = {
    "bool": "java.lang.Boolean",
    "boolean": "java.lang.Boolean",
    "bytea": "byte[]",
    "int2": "java.lang.Integer",
    "smallint": "java.lang.Integer",
    "int4": "java.lang.Integer",
    "integer": "java.lang.Integer",
    "int8": "java.lang.Long",
    "bigint": "java.lang.Long",
    "oid": "java.lang.Long",
    "float4": "java.lang.Float",
    "real": "java.lang.Float",
    "float8": "java.lang.Double",
    "double precision": "java.lang.Double",
    "numeric": "java.math.BigDecimal",
    "decimal": "java.math.BigDecimal",
    "money": "java.math.BigDecimal",
    "date": "java.sql.Date",
    "time": "java.sql.Time",
    "timetz": "java.sql.Time",
    "time without time zone": "java.sql.Time",
    "time with time zone": "java.sql.Time",
    "timestamp": "java.sql.Timestamp",
    "timestamptz": "java.sql.Timestamp",
    "timestamp without time zone": "java.sql.Timestamp",
    "timestamp with time zone": "java.sql.Timestamp",
    "text": "java.lang.String",
    "varchar": "java.lang.String",
    "bpchar": "java.lang.String",
    "char": "java.lang.String",
    "character varying": "java.lang.String",
    "character": "java.lang.String",
    "name": "java.lang.String",
    "uuid": "java.lang.String",
    "json": "java.lang.String",
    "jsonb": "java.lang.String",
}


# =============================================================================
# Pydantic Models
# =============================================================================


class TableSummary(BaseModel):
    """Summary metadata for a PostgreSQL table or view."""

    schema_name: str
    table_name: str
    table_type: str
    estimated_rows: int | None = None


class TableColumnDetail(BaseModel):
    """Detailed column metadata mapped to JasperReports Java classes."""

    name: str
    data_type: str
    udt_name: str
    is_nullable: bool
    default_value: str | None = None
    java_class: str
    is_primary_key: bool = False


class TableForeignKeyDetail(BaseModel):
    """Foreign key constraint metadata for a PostgreSQL table."""

    constraint_name: str
    column_name: str
    foreign_schema: str
    foreign_table: str
    foreign_column: str


class TableSchemaDetail(BaseModel):
    """Complete column, PK, and FK definition for a PostgreSQL table or view."""

    schema_name: str
    table_name: str
    columns: list[TableColumnDetail] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    foreign_keys: list[TableForeignKeyDetail] = Field(default_factory=list)


class SelectPreviewResult(BaseModel):
    """Result of executing a strictly READ ONLY bounded SELECT preview."""

    ok: bool = True
    profile_id: str
    columns: list[SelectColumnMeta] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    limit: int = DEFAULT_PREVIEW_LIMIT
    truncated: bool = False
    latency_ms: float = 0.0
    message: str = ""


# =============================================================================
# Helpers
# =============================================================================


def map_pg_type_to_java(udt_name: str | None, data_type: str | None = None) -> str:
    """Map PostgreSQL `udt_name` / `data_type` to a JasperReports Java class name."""
    for candidate in (udt_name, data_type):
        if not candidate:
            continue
        key = candidate.strip().lower()
        if key in _UDT_TO_JAVA_CLASS:
            return _UDT_TO_JAVA_CLASS[key]
        if key.startswith("_"):
            return "java.lang.Object"
    return "java.lang.String"


def serialize_pg_value(value: Any) -> Any:
    """Convert PostgreSQL driver Python values into strictly JSON-safe representations."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    if isinstance(value, decimal.Decimal):
        if value.is_nan() or value.is_infinite():
            return str(value)
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, memoryview):
        raw = value.tobytes()
        return _serialize_bytes(raw)
    if isinstance(value, (bytes, bytearray)):
        return _serialize_bytes(bytes(value))
    if isinstance(value, dict):
        return {str(k): serialize_pg_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_pg_value(item) for item in value]
    return str(value)


def _serialize_bytes(raw: bytes) -> str:
    if len(raw) <= 64:
        return "base64:" + base64.b64encode(raw).decode("ascii")
    return f"<bytea:{len(raw)} bytes>"


def _tokenize_sql(sql_text: str) -> list[tuple[str, str]]:
    """
    Split SQL into `("code" | "literal" | "ws", text)` segments while stripping
    `--` and `/* ... */` comments and preserving quoted strings/identifiers.
    """
    segments: list[tuple[str, str]] = []
    code_buf: list[str] = []
    i = 0
    n = len(sql_text)

    def _flush() -> None:
        if code_buf:
            segments.append(("code", "".join(code_buf)))
            code_buf.clear()

    while i < n:
        ch = sql_text[i]
        # Line comment
        if ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            _flush()
            while i < n and sql_text[i] != "\n":
                i += 1
            if i < n and sql_text[i] == "\n":
                segments.append(("ws", "\n"))
                i += 1
            continue

        # Block comment
        if ch == "/" and i + 1 < n and sql_text[i + 1] == "*":
            _flush()
            i += 2
            newlines = 0
            while i < n:
                if sql_text[i] == "\n":
                    newlines += 1
                if sql_text[i] == "*" and i + 1 < n and sql_text[i + 1] == "/":
                    i += 2
                    break
                i += 1
            else:
                raise DbProfileValidationError("Unclosed block comment '/*' in SQL query.")
            segments.append(("ws", "\n" * newlines if newlines else " "))
            continue

        # Single-quoted string or double-quoted identifier
        if ch in ("'", '"'):
            _flush()
            quote = ch
            start = i
            i += 1
            closed = False
            while i < n:
                if sql_text[i] == quote:
                    if i + 1 < n and sql_text[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                raise DbProfileValidationError(f"Unclosed quote ({quote}) in SQL query.")
            segments.append(("literal", sql_text[start:i]))
            continue

        code_buf.append(ch)
        i += 1

    _flush()
    return segments


def _strip_trailing_semicolons(sql_text: str) -> str:
    cleaned = sql_text.strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _resolve_param_value(param_name: str, params: dict[str, Any]) -> Any:
    if param_name in params:
        return params[param_name]
    lowered = param_name.lower()
    for k, v in params.items():
        if k.lower() == lowered:
            return v
    if lowered == "id":
        return 0
    return None


def validate_and_bind_readonly_select(
    sql_select: str,
    params: dict[str, Any] | None = None,
) -> tuple[str, list[Any]]:
    """
    Validate that `sql_select` is a single read-only SELECT/WITH statement without
    DML/DDL/DO blocks, and bind Jasper `$P{...}`, `$P!{...}`, and `${...}` placeholders
    to `psycopg` `%s` positional parameters.
    """
    if not isinstance(sql_select, str) or not sql_select.strip():
        raise DbProfileValidationError("SQL SELECT query cannot be empty.")

    cleaned = _strip_trailing_semicolons(sql_select)
    segments = _tokenize_sql(cleaned)

    code_only = " ".join(text for kind, text in segments if kind == "code").strip()
    if not code_only:
        raise DbProfileValidationError("SQL SELECT query cannot be empty.")

    # Reject dollar-quoting (e.g., DO $$ ... $$)
    if _DOLLAR_QUOTE_RE.search(code_only):
        raise DbProfileValidationError(
            "Dollar-quoted blocks (DO $$ / PL/pgSQL) are forbidden in read-only SELECT preview."
        )

    # Strip any trailing semicolon that preceded a trailing comment, then reject remaining semicolons
    for idx in range(len(segments) - 1, -1, -1):
        kind, text = segments[idx]
        if kind == "ws":
            continue
        if kind == "code":
            trimmed = text.rstrip()
            while trimmed.endswith(";"):
                trimmed = trimmed[:-1].rstrip()
            segments[idx] = ("code", trimmed)
        break

    for kind, text in segments:
        if kind == "code" and ";" in text:
            raise DbProfileValidationError(
                "Multiple SQL statements are forbidden in read-only SELECT preview."
            )

    first_word_match = re.match(r"^\s*\(*\s*([A-Za-z_]+)", code_only)
    first_kw = first_word_match.group(1).upper() if first_word_match else ""
    if first_kw not in {"SELECT", "WITH"}:
        raise DbProfileValidationError(
            f"Only SELECT or WITH queries are allowed in read-only preview (got '{first_kw or '<empty>'}')."
        )

    forbidden_match = _FORBIDDEN_SQL_KEYWORD_RE.search(code_only)
    if forbidden_match:
        raise DbProfileValidationError(
            f"Forbidden SQL statement/keyword '{forbidden_match.group(1).upper()}' in read-only SELECT preview."
        )

    if _SELECT_INTO_RE.search(code_only):
        raise DbProfileValidationError(
            "Forbidden 'SELECT ... INTO' table-creating syntax in read-only SELECT preview."
        )

    param_map = dict(params or {})
    bound_values: list[Any] = []
    out_parts: list[str] = []

    for kind, text in segments:
        if kind == "ws":
            out_parts.append(text)
            continue
        if kind == "literal":
            out_parts.append(text.replace("%", "%%"))
            continue

        escaped = text.replace("%", "%%")

        def _replace_placeholder(match: re.Match[str]) -> str:
            bang = match.group(1) or ""
            p_name = match.group(2) or match.group(3) or ""
            val = _resolve_param_value(p_name, param_map)

            if bang == "!":
                # Validate $P!{...} strictly: allow safe scalar binding or validated identifier only
                if isinstance(val, str):
                    stripped_val = val.strip()
                    if (
                        ";" in stripped_val
                        or "--" in stripped_val
                        or "/*" in stripped_val
                        or _FORBIDDEN_SQL_KEYWORD_RE.search(stripped_val)
                    ):
                        raise DbProfileValidationError(
                            f"Unsafe value for raw Jasper parameter '$P!{{{p_name}}}'."
                        )
                    if _SAFE_IDENTIFIER_RE.match(stripped_val):
                        bound_values.append(stripped_val)
                        return "%s"
                    raise DbProfileValidationError(
                        f"Unsupported raw SQL fragment in '$P!{{{p_name}}}'. Use scalar/identifier values."
                    )
                bound_values.append(val)
                return "%s"

            bound_values.append(val)
            return "%s"

        replaced = _JASPER_PLACEHOLDER_RE.sub(_replace_placeholder, escaped)
        out_parts.append(replaced)

    final_sql = "".join(out_parts).strip()
    return final_sql, bound_values


# =============================================================================
# PgSchemaInspector Service
# =============================================================================


class PgSchemaInspector:
    """
    Dedicated read-only PostgreSQL schema explorer and bounded SELECT preview runner.

    Every method executes inside `SET TRANSACTION READ ONLY` with
    `SET LOCAL statement_timeout = '10000'` and unconditionally rolls back in `finally`.
    """

    def __init__(
        self,
        postgres_service: PostgresService,
        *,
        statement_timeout_ms: str = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self.postgres_service = postgres_service
        self.statement_timeout_ms = str(statement_timeout_ms)

    @contextmanager
    def _readonly_cursor(self, profile_id: str) -> Iterator[Any]:
        self.postgres_service.get_profile(profile_id)
        conn: Any = None
        try:
            try:
                conn = self.postgres_service._open_pg_connection(profile_id)
            except PostgresServiceError:
                raise
            except Exception as exc:
                raise PostgresConnectionError(
                    f"Failed to connect to PostgreSQL profile '{profile_id}': {exc}"
                ) from exc
            with self.postgres_service._cursor_context(conn) as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = '{self.statement_timeout_ms}'")
                yield cur
        finally:
            if conn is not None:
                try:
                    if hasattr(conn, "rollback"):
                        conn.rollback()
                except Exception:
                    pass
                try:
                    if hasattr(conn, "close"):
                        conn.close()
                except Exception:
                    pass

    def list_schemas(self, profile_id: str) -> list[str]:
        """List user schemas excluding system catalogs, prioritizing `public` first."""
        try:
            with self._readonly_cursor(profile_id) as cur:
                cur.execute(
                    """
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                      AND schema_name NOT LIKE 'pg_toast%'
                      AND schema_name NOT LIKE 'pg_temp%'
                    ORDER BY CASE WHEN schema_name = 'public' THEN 0 ELSE 1 END, schema_name ASC
                    """
                )
                rows = cur.fetchall() if hasattr(cur, "fetchall") else []

            schemas: list[str] = []
            for row in rows:
                name = row["schema_name"] if isinstance(row, dict) else (row[0] if row else None)
                if name:
                    text = str(name)
                    if (
                        text not in ("pg_catalog", "information_schema")
                        and not text.startswith("pg_toast")
                        and not text.startswith("pg_temp")
                    ):
                        schemas.append(text)
            schemas.sort(key=lambda s: (0 if s == "public" else 1, s.lower()))
            return schemas
        except PostgresServiceError:
            raise
        except Exception as exc:
            raise PostgresExecutionError(f"Failed to list schemas: {exc}") from exc

    def list_tables(
        self,
        profile_id: str,
        *,
        schema: str = "public",
        search: str | None = None,
        limit: int = 100,
    ) -> list[TableSummary]:
        """List tables and views in `schema` with estimated row counts from `pg_class.reltuples`."""
        clean_schema = (schema or "public").strip()
        if not clean_schema:
            clean_schema = "public"
        clamped_limit = max(1, min(int(limit), MAX_TABLES_LIMIT))
        search_term = (search or "").strip()

        try:
            with self._readonly_cursor(profile_id) as cur:
                if search_term:
                    cur.execute(
                        """
                        SELECT
                            t.table_schema,
                            t.table_name,
                            t.table_type,
                            CASE
                                WHEN c.reltuples IS NOT NULL AND c.reltuples >= 0
                                THEN c.reltuples::bigint
                                ELSE NULL
                            END AS estimated_rows
                        FROM information_schema.tables t
                        LEFT JOIN pg_catalog.pg_namespace n
                            ON n.nspname = t.table_schema
                        LEFT JOIN pg_catalog.pg_class c
                            ON c.relnamespace = n.oid AND c.relname = t.table_name
                        WHERE t.table_schema = %s
                          AND t.table_name ILIKE %s
                        ORDER BY t.table_name ASC
                        LIMIT %s
                        """,
                        (clean_schema, f"%{search_term}%", clamped_limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            t.table_schema,
                            t.table_name,
                            t.table_type,
                            CASE
                                WHEN c.reltuples IS NOT NULL AND c.reltuples >= 0
                                THEN c.reltuples::bigint
                                ELSE NULL
                            END AS estimated_rows
                        FROM information_schema.tables t
                        LEFT JOIN pg_catalog.pg_namespace n
                            ON n.nspname = t.table_schema
                        LEFT JOIN pg_catalog.pg_class c
                            ON c.relnamespace = n.oid AND c.relname = t.table_name
                        WHERE t.table_schema = %s
                        ORDER BY t.table_name ASC
                        LIMIT %s
                        """,
                        (clean_schema, clamped_limit),
                    )
                rows = cur.fetchall() if hasattr(cur, "fetchall") else []

            results: list[TableSummary] = []
            for row in rows:
                if isinstance(row, dict):
                    s_name = str(row.get("table_schema") or clean_schema)
                    t_name = str(row.get("table_name") or "")
                    t_type = str(row.get("table_type") or "BASE TABLE")
                    est = row.get("estimated_rows")
                else:
                    s_name = str(row[0]) if len(row) > 0 and row[0] else clean_schema
                    t_name = str(row[1]) if len(row) > 1 and row[1] else ""
                    t_type = str(row[2]) if len(row) > 2 and row[2] else "BASE TABLE"
                    est = row[3] if len(row) > 3 else None

                if not t_name:
                    continue
                est_int: int | None = None
                if est is not None:
                    try:
                        parsed_est = int(float(est))
                        est_int = parsed_est if parsed_est >= 0 else None
                    except (TypeError, ValueError):
                        est_int = None
                results.append(
                    TableSummary(
                        schema_name=s_name,
                        table_name=t_name,
                        table_type=t_type,
                        estimated_rows=est_int,
                    )
                )
            return results
        except PostgresServiceError:
            raise
        except Exception as exc:
            raise PostgresExecutionError(f"Failed to list tables in '{clean_schema}': {exc}") from exc

    def describe_table(
        self,
        profile_id: str,
        *,
        schema: str = "public",
        table: str,
    ) -> TableSchemaDetail:
        """Return columns, Java classes, primary keys, and foreign keys for a table/view."""
        clean_schema = (schema or "public").strip() or "public"
        clean_table = (table or "").strip()
        if not clean_table:
            raise DbProfileValidationError("Table name is required.")

        # Support optional schema.table notation in `table`
        if "." in clean_table and clean_schema == "public":
            parts = clean_table.split(".", 1)
            if parts[0].strip() and parts[1].strip():
                clean_schema, clean_table = parts[0].strip(), parts[1].strip()

        try:
            with self._readonly_cursor(profile_id) as cur:
                # 1. Columns
                cur.execute(
                    """
                    SELECT
                        column_name,
                        data_type,
                        udt_name,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position ASC
                    """,
                    (clean_schema, clean_table),
                )
                col_rows = cur.fetchall() if hasattr(cur, "fetchall") else []

                # 2. Primary keys
                cur.execute(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                       AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = %s
                      AND tc.table_name = %s
                    ORDER BY kcu.ordinal_position ASC
                    """,
                    (clean_schema, clean_table),
                )
                pk_rows = cur.fetchall() if hasattr(cur, "fetchall") else []

                # 3. Foreign keys
                cur.execute(
                    """
                    SELECT
                        tc.constraint_name,
                        kcu.column_name,
                        ccu.table_schema AS foreign_schema,
                        ccu.table_name AS foreign_table,
                        ccu.column_name AS foreign_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                       AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                       AND ccu.constraint_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = %s
                      AND tc.table_name = %s
                    ORDER BY tc.constraint_name ASC, kcu.ordinal_position ASC
                    """,
                    (clean_schema, clean_table),
                )
                fk_rows = cur.fetchall() if hasattr(cur, "fetchall") else []

            if not col_rows:
                raise DbProfileValidationError(
                    f"Table or view '{clean_schema}.{clean_table}' not found."
                )

            primary_keys: list[str] = []
            for row in pk_rows:
                pk_col = row["column_name"] if isinstance(row, dict) else (row[0] if row else None)
                if pk_col and str(pk_col) not in primary_keys:
                    primary_keys.append(str(pk_col))
            pk_set = set(primary_keys)

            columns: list[TableColumnDetail] = []
            for row in col_rows:
                if isinstance(row, dict):
                    c_name = str(row["column_name"])
                    d_type = str(row.get("data_type") or "")
                    u_name = str(row.get("udt_name") or d_type)
                    raw_null = row.get("is_nullable", "YES")
                    default_val = row.get("column_default")
                else:
                    c_name = str(row[0])
                    d_type = str(row[1] or "")
                    u_name = str(row[2] or d_type)
                    raw_null = row[3] if len(row) > 3 else "YES"
                    default_val = row[4] if len(row) > 4 else None

                is_nullable = (
                    bool(raw_null)
                    if isinstance(raw_null, bool)
                    else str(raw_null).strip().upper() in ("YES", "TRUE", "T", "1")
                )
                columns.append(
                    TableColumnDetail(
                        name=c_name,
                        data_type=d_type,
                        udt_name=u_name,
                        is_nullable=is_nullable,
                        default_value=str(default_val) if default_val is not None else None,
                        java_class=map_pg_type_to_java(u_name, d_type),
                        is_primary_key=c_name in pk_set,
                    )
                )

            foreign_keys: list[TableForeignKeyDetail] = []
            for row in fk_rows:
                if isinstance(row, dict):
                    fk = TableForeignKeyDetail(
                        constraint_name=str(row["constraint_name"]),
                        column_name=str(row["column_name"]),
                        foreign_schema=str(row["foreign_schema"]),
                        foreign_table=str(row["foreign_table"]),
                        foreign_column=str(row["foreign_column"]),
                    )
                else:
                    fk = TableForeignKeyDetail(
                        constraint_name=str(row[0]),
                        column_name=str(row[1]),
                        foreign_schema=str(row[2]),
                        foreign_table=str(row[3]),
                        foreign_column=str(row[4]),
                    )
                foreign_keys.append(fk)

            return TableSchemaDetail(
                schema_name=clean_schema,
                table_name=clean_table,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=foreign_keys,
            )
        except PostgresServiceError:
            raise
        except Exception as exc:
            raise PostgresExecutionError(
                f"Failed to describe table '{clean_schema}.{clean_table}': {exc}"
            ) from exc

    def preview_select_query(
        self,
        profile_id: str,
        sql_select: str,
        *,
        params: dict[str, Any] | None = None,
        limit: int = DEFAULT_PREVIEW_LIMIT,
    ) -> SelectPreviewResult:
        """
        Execute a strictly READ ONLY SELECT preview wrapped with a bounded LIMIT (1..200),
        binding Jasper `$P{...}` / `${...}` parameters safely and returning JSON-safe rows.
        """
        clamped_limit = max(MIN_PREVIEW_LIMIT, min(int(limit), MAX_PREVIEW_LIMIT))
        parameterized_sql, bound_values = validate_and_bind_readonly_select(sql_select, params=params)
        wrapped_sql = f"SELECT * FROM (\n{parameterized_sql}\n) AS _studio_preview LIMIT %s"
        exec_params = tuple([*bound_values, clamped_limit + 1])

        started = time.perf_counter()
        columns: list[SelectColumnMeta] = []
        raw_rows: list[Any] = []

        try:
            with self._readonly_cursor(profile_id) as cur:
                cur.execute(wrapped_sql, exec_params)
                desc = getattr(cur, "description", None) or []
                for idx, col in enumerate(desc):
                    col_name = (
                        str(col.name)
                        if hasattr(col, "name")
                        else (str(col[0]) if col else f"col_{idx + 1}")
                    )
                    raw_oid = (
                        col.type_code
                        if hasattr(col, "type_code")
                        else (col[1] if len(col) > 1 else None)
                    )
                    type_oid = int(raw_oid) if raw_oid is not None else None
                    null_ok = getattr(
                        col,
                        "null_ok",
                        col[6] if isinstance(col, tuple) and len(col) > 6 else None,
                    )
                    pg_type, java_class = PostgresService.map_pg_oid_to_java(type_oid)
                    columns.append(
                        SelectColumnMeta(
                            name=col_name,
                            type_oid=type_oid,
                            pg_type=pg_type,
                            java_class=java_class,
                            nullable=bool(null_ok) if null_ok is not None else None,
                        )
                    )
                if hasattr(cur, "fetchmany"):
                    raw_rows = list(cur.fetchmany(clamped_limit + 1))
                elif hasattr(cur, "fetchall"):
                    raw_rows = list(cur.fetchall())
        except PostgresServiceError:
            raise
        except Exception as exc:
            raise PostgresExecutionError(f"Read-only SELECT preview failed: {exc}") from exc

        truncated = len(raw_rows) > clamped_limit
        sliced_rows = raw_rows[:clamped_limit]

        # Deduplicate column names if query returns duplicate aliases
        col_keys: list[str] = []
        seen_names: dict[str, int] = {}
        for idx, col in enumerate(columns):
            base_name = col.name or f"col_{idx + 1}"
            count = seen_names.get(base_name, 0)
            seen_names[base_name] = count + 1
            col_keys.append(base_name if count == 0 else f"{base_name}_{count + 1}")

        serialized_rows: list[dict[str, Any]] = []
        for row in sliced_rows:
            if isinstance(row, dict):
                serialized_rows.append({str(k): serialize_pg_value(v) for k, v in row.items()})
            else:
                row_dict: dict[str, Any] = {}
                for idx, key in enumerate(col_keys):
                    val = row[idx] if idx < len(row) else None
                    row_dict[key] = serialize_pg_value(val)
                serialized_rows.append(row_dict)

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        trunc_note = " (resultados truncados pelo limite)" if truncated else ""
        return SelectPreviewResult(
            ok=True,
            profile_id=profile_id,
            columns=columns,
            rows=serialized_rows,
            row_count=len(serialized_rows),
            limit=clamped_limit,
            truncated=truncated,
            latency_ms=latency_ms,
            message=f"{len(serialized_rows)} linha(s) retornada(s) em modo READ ONLY{trunc_note}.",
        )


__all__ = [
    "DEFAULT_PREVIEW_LIMIT",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "MAX_PREVIEW_LIMIT",
    "MIN_PREVIEW_LIMIT",
    "PgSchemaInspector",
    "SelectPreviewResult",
    "TableColumnDetail",
    "TableForeignKeyDetail",
    "TableSchemaDetail",
    "TableSummary",
    "map_pg_type_to_java",
    "serialize_pg_value",
    "validate_and_bind_readonly_select",
]
