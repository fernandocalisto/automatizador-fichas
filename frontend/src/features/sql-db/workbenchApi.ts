import { ApiError } from "@/lib/api";
import type {
  ArtifactRevisionRead,
  SelectPreviewResult,
  TableSchemaDetail,
  TableSummary,
} from "@/types/studio";

export interface SyncQueryPayload {
  direction: "jrxml_to_sql" | "sql_to_jrxml";
  sql_select?: string;
  inline_jrxml?: string;
  save_artifact?: boolean;
}

export interface SyncQueryResponse {
  ok: boolean;
  project_id: string;
  direction: "jrxml_to_sql" | "sql_to_jrxml";
  sql_select: string;
  jrxml?: string;
  saved_revision: ArtifactRevisionRead | null;
}

async function fetchWorkbenchJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail: unknown = undefined;
    let message = `HTTP ${response.status} ${response.statusText}`.trim();
    try {
      const payload = await response.json();
      detail = payload?.detail ?? payload;
      if (typeof payload?.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload?.detail)) {
        message = payload.detail
          .map((item: { msg?: string }) => item.msg || JSON.stringify(item))
          .join("; ");
      }
    } catch {
      const text = await response.text().catch(() => "");
      if (text) message = text;
    }
    throw new ApiError(response.status, message, detail);
  }

  return (await response.json()) as T;
}

export async function listProfileSchemas(profileId: string): Promise<string[]> {
  const res = await fetchWorkbenchJson<{
    profile_id: string;
    schemas: string[];
  }>(`/api/db/profiles/${encodeURIComponent(profileId)}/schemas`);
  return Array.isArray(res.schemas) ? res.schemas : [];
}

export async function listProfileTables(
  profileId: string,
  opts?: { schema?: string; search?: string; limit?: number },
): Promise<TableSummary[]> {
  const params = new URLSearchParams();
  if (opts?.schema) params.set("schema", opts.schema);
  if (opts?.search) params.set("search", opts.search);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return fetchWorkbenchJson<TableSummary[]>(
    `/api/db/profiles/${encodeURIComponent(profileId)}/tables${qs ? `?${qs}` : ""}`,
  );
}

export async function describeProfileTable(
  profileId: string,
  tableName: string,
  schema = "public",
): Promise<TableSchemaDetail> {
  const params = new URLSearchParams();
  if (schema) params.set("schema", schema);
  return fetchWorkbenchJson<TableSchemaDetail>(
    `/api/db/profiles/${encodeURIComponent(profileId)}/tables/${encodeURIComponent(tableName)}?${params.toString()}`,
  );
}

export async function previewProfileSelect(
  profileId: string,
  payload: {
    sql_select: string;
    params?: Record<string, unknown>;
    limit?: number;
  },
): Promise<SelectPreviewResult> {
  return fetchWorkbenchJson<SelectPreviewResult>(
    `/api/db/profiles/${encodeURIComponent(profileId)}/preview-select`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function listProfileDatabases(
  profileId: string,
): Promise<string[]> {
  const res = await fetchWorkbenchJson<{
    profile_id: string;
    databases: string[];
  }>(`/api/db/profiles/${encodeURIComponent(profileId)}/databases`);
  return Array.isArray(res.databases) ? res.databases : [];
}

export async function syncProjectQuery(
  projectId: string,
  payload: SyncQueryPayload,
): Promise<SyncQueryResponse> {
  return fetchWorkbenchJson<SyncQueryResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/jasper/sync-query`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
