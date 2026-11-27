import { ApiError } from "@/lib/api";
import type {
  ClientSyncApplyResponse,
  ClientSyncPreviewResponse,
  ClientSystemRead,
  ClientSystemType,
  ClientUnitRead,
  CredentialKind,
  DbConnectionTestResult,
  DefaultCredentialRead,
  DefaultCredentialUpdatePayload,
  EnvironmentKind,
  JasperServerTestResult,
  SftpConnectionTestResult,
} from "@/types/studio";

export type ClientSyncSourceFormat =
  | "auto"
  | "normalized_json"
  | "portal_json"
  | "portal_html";

export interface ClientUnitCreatePayload {
  external_id?: string | null;
  unit_code?: string | null;
  name: string;
  hosting?: string;
  license_status?: string;
  notes?: string;
  tags?: string[];
  integrations?: string[];
}

export interface ClientUnitUpdatePayload {
  external_id?: string | null;
  unit_code?: string | null;
  name?: string;
  hosting?: string;
  license_status?: string;
  notes?: string;
  tags?: string[];
  integrations?: string[];
}

export interface ClientSystemCreatePayload {
  system_key?: string | null;
  label: string;
  system_type?: ClientSystemType;
  environment?: EnvironmentKind;
  system_url?: string;
  version_label?: string;
  db_profile_id?: string | null;
  sftp_profile_id?: string | null;
  jasperserver_profile_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ClientSystemUpdatePayload {
  system_key?: string | null;
  label?: string;
  system_type?: ClientSystemType;
  environment?: EnvironmentKind;
  system_url?: string;
  version_label?: string;
  db_profile_id?: string | null;
  sftp_profile_id?: string | null;
  jasperserver_profile_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ClientSyncSnippetResponse {
  management_portal_url: string;
  console_snippet: string;
  bookmarklet: string;
  instructions: string[];
}

export interface ClientSyncPreviewPayload {
  raw_payload: string | Record<string, unknown> | unknown[];
  source_format?: ClientSyncSourceFormat;
}

export interface ClientSyncApplyPayload {
  units?: Record<string, unknown>[];
  raw_payload?: string | Record<string, unknown> | unknown[];
  source_format?: ClientSyncSourceFormat;
  import_ssh_passwords?: boolean;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (
    init?.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail: unknown = undefined;
    let message = `HTTP ${response.status} ${response.statusText}`;
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

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const clientsApi = {
  // Clients & Systems CRUD
  listClients: (params?: {
    search?: string;
    system_type?: ClientSystemType;
    environment?: EnvironmentKind;
  }) => {
    const qs = new URLSearchParams();
    if (params?.search?.trim()) qs.set("search", params.search.trim());
    if (params?.system_type) qs.set("system_type", params.system_type);
    if (params?.environment) qs.set("environment", params.environment);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return requestJson<ClientUnitRead[]>(`/api/clients${suffix}`);
  },

  getClient: (unitId: string) =>
    requestJson<ClientUnitRead>(`/api/clients/${encodeURIComponent(unitId)}`),

  createClient: (payload: ClientUnitCreatePayload) =>
    requestJson<ClientUnitRead>("/api/clients", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateClient: (unitId: string, payload: ClientUnitUpdatePayload) =>
    requestJson<ClientUnitRead>(`/api/clients/${encodeURIComponent(unitId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteClient: (unitId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/clients/${encodeURIComponent(unitId)}`,
      { method: "DELETE" },
    ),

  createClientSystem: (unitId: string, payload: ClientSystemCreatePayload) =>
    requestJson<ClientSystemRead>(
      `/api/clients/${encodeURIComponent(unitId)}/systems`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  updateClientSystem: (
    unitId: string,
    systemId: string,
    payload: ClientSystemUpdatePayload,
  ) =>
    requestJson<ClientSystemRead>(
      `/api/clients/${encodeURIComponent(unitId)}/systems/${encodeURIComponent(systemId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    ),

  deleteClientSystem: (unitId: string, systemId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/clients/${encodeURIComponent(unitId)}/systems/${encodeURIComponent(systemId)}`,
      { method: "DELETE" },
    ),

  // Authenticated Local Portal Sync
  getSyncSnippet: () =>
    requestJson<ClientSyncSnippetResponse>("/api/clients/sync/snippet"),

  saveSyncConfig: (managementPortalUrl: string) =>
    requestJson<{ management_portal_url: string }>("/api/clients/sync/config", {
      method: "PUT",
      body: JSON.stringify({ management_portal_url: managementPortalUrl }),
    }),

  previewClientSync: (payload: ClientSyncPreviewPayload) =>
    requestJson<ClientSyncPreviewResponse>("/api/clients/sync/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  applyClientSync: (payload: ClientSyncApplyPayload) =>
    requestJson<ClientSyncApplyResponse>("/api/clients/sync/apply", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Default Credentials (Block 0 Vault API)
  listDefaultCredentials: () =>
    requestJson<Record<CredentialKind, DefaultCredentialRead>>(
      "/api/credentials/defaults",
    ),

  getDefaultCredential: (kind: CredentialKind) =>
    requestJson<DefaultCredentialRead>(
      `/api/credentials/defaults/${encodeURIComponent(kind)}`,
    ),

  updateDefaultCredential: (
    kind: CredentialKind,
    payload: DefaultCredentialUpdatePayload,
  ) =>
    requestJson<DefaultCredentialRead>(
      `/api/credentials/defaults/${encodeURIComponent(kind)}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  deleteDefaultCredential: (kind: CredentialKind) =>
    requestJson<DefaultCredentialRead>(
      `/api/credentials/defaults/${encodeURIComponent(kind)}`,
      { method: "DELETE" },
    ),

  // Optional 1-click profile connection tests
  testDbProfile: (profileId: string) =>
    requestJson<DbConnectionTestResult>(
      `/api/db/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),

  testSftpProfile: (profileId: string) =>
    requestJson<SftpConnectionTestResult>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),

  testJasperServerProfile: (profileId: string) =>
    requestJson<JasperServerTestResult>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),
};
