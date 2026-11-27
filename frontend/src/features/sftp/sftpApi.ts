import { ApiError } from "@/lib/api";
import type {
  ProjectRead,
  SftpConnectionTestResult,
  SftpDeployPreview,
  SftpDeployResult,
  SftpListResult,
  SftpProfileCreatePayload,
  SftpProfileRead,
  SftpProfileUpdatePayload,
  SftpPublishMode,
} from "@/types/studio";

export interface SftpImportPayload {
  profile_id: string;
  remote_path: string;
  project_name?: string | null;
  db_profile_id?: string | null;
  sync_subreports?: boolean;
}

export interface SftpDeployPreparePayload {
  profile_id: string;
  remote_dir: string;
  base_filename: string;
  publish_mode?: SftpPublishMode;
}

export interface SftpDeployExecutePayload {
  deploy_token: string;
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

export const sftpApi = {
  listProfiles: () => requestJson<SftpProfileRead[]>("/api/sftp/profiles"),

  getProfile: (profileId: string) =>
    requestJson<SftpProfileRead>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}`,
    ),

  createProfile: (payload: SftpProfileCreatePayload) =>
    requestJson<SftpProfileRead>("/api/sftp/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateProfile: (profileId: string, payload: SftpProfileUpdatePayload) =>
    requestJson<SftpProfileRead>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    ),

  deleteProfile: (profileId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}`,
      { method: "DELETE" },
    ),

  testProfile: (profileId: string) =>
    requestJson<SftpConnectionTestResult>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),

  browse: (
    profileId: string,
    params?: { path?: string | null; search?: string | null },
  ) => {
    const query = new URLSearchParams();
    if (params?.path) query.set("path", params.path);
    if (params?.search) query.set("search", params.search);
    const qs = query.toString();
    return requestJson<SftpListResult>(
      `/api/sftp/profiles/${encodeURIComponent(profileId)}/browse${qs ? `?${qs}` : ""}`,
    );
  },

  importReport: (payload: SftpImportPayload) =>
    requestJson<ProjectRead>("/api/sftp/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  prepareDeploy: (projectId: string, payload: SftpDeployPreparePayload) =>
    requestJson<SftpDeployPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/deploy/sftp/prepare`,
      {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          publish_mode: payload.publish_mode ?? "jrxml_only",
        }),
      },
    ),

  executeDeploy: (projectId: string, payload: SftpDeployExecutePayload) =>
    requestJson<SftpDeployResult>(
      `/api/projects/${encodeURIComponent(projectId)}/deploy/sftp/execute`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
};
