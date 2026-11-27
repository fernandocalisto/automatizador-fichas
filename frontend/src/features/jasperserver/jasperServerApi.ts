import { ApiError } from "@/lib/api";
import type {
  JasperServerDeployPreview,
  JasperServerDeployResult,
  JasperServerProfileCreatePayload,
  JasperServerProfileRead,
  JasperServerProfileUpdatePayload,
  JasperServerReportUnitDetail,
  JasperServerResourceItem,
  JasperServerTestResult,
  ProjectRead,
} from "@/types/studio";

export interface JasperServerImportPayload {
  profile_id: string;
  resource_uri: string;
  project_name?: string | null;
  db_profile_id?: string | null;
  sync_subreports?: boolean;
}

export interface JasperServerDeployPreparePayload {
  profile_id: string;
  mode: "update" | "create";
  target_uri: string;
  main_jrxml_uri?: string | null;
  label?: string | null;
  datasource_uri?: string | null;
}

export interface JasperServerDeployExecutePayload {
  deploy_token: string;
}

export interface JasperServerListResourcesParams {
  folder_uri?: string;
  q?: string;
  recursive?: boolean;
  types?: string[];
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
      if (text) {
        message = text;
      }
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const jasperServerApi = {
  listProfiles: () =>
    requestJson<JasperServerProfileRead[]>("/api/jasperserver/profiles"),

  getProfile: (profileId: string) =>
    requestJson<JasperServerProfileRead>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}`,
    ),

  createProfile: (payload: JasperServerProfileCreatePayload) =>
    requestJson<JasperServerProfileRead>("/api/jasperserver/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateProfile: (
    profileId: string,
    payload: JasperServerProfileUpdatePayload,
  ) =>
    requestJson<JasperServerProfileRead>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  deleteProfile: (profileId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}`,
      { method: "DELETE" },
    ),

  testProfile: (profileId: string) =>
    requestJson<JasperServerTestResult>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),

  listResources: (
    profileId: string,
    params?: JasperServerListResourcesParams,
  ) => {
    const query = new URLSearchParams();
    if (params?.folder_uri) query.set("folder_uri", params.folder_uri);
    if (params?.q) query.set("q", params.q);
    if (params?.recursive) query.set("recursive", "true");
    if (params?.types && params.types.length > 0) {
      for (const t of params.types) {
        query.append("types", t);
      }
    }
    const qs = query.toString();
    return requestJson<JasperServerResourceItem[]>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}/resources${qs ? `?${qs}` : ""}`,
    );
  },

  inspectReportUnit: (profileId: string, uri: string) => {
    const query = new URLSearchParams({ uri });
    return requestJson<JasperServerReportUnitDetail>(
      `/api/jasperserver/profiles/${encodeURIComponent(profileId)}/report-unit?${query.toString()}`,
    );
  },

  importReport: (payload: JasperServerImportPayload) =>
    requestJson<ProjectRead>("/api/jasperserver/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  prepareDeploy: (
    projectId: string,
    payload: JasperServerDeployPreparePayload,
  ) =>
    requestJson<JasperServerDeployPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/deploy/jasperserver/prepare`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  executeDeploy: (
    projectId: string,
    payload: JasperServerDeployExecutePayload,
  ) =>
    requestJson<JasperServerDeployResult>(
      `/api/projects/${encodeURIComponent(projectId)}/deploy/jasperserver/execute`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
};
