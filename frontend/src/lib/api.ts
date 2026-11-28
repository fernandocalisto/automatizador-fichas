import type {
  ArtifactRevisionRead,
  ArtifactSavePayload,
  ArtifactSaveResponse,
  ArtifactType,
  ChatMessageCreatePayload,
  ChatMessageRead,
  ChatPhase,
  CommitInsertResult,
  DbConnectionTestResult,
  DbProfileCreatePayload,
  DbProfileDatabasesResult,
  DbProfileRead,
  DbProfileUpdatePayload,
  DryRunInsertResult,
  FormBuilderMutatePayload,
  GateApprovalRead,
  GateName,
  GateStatus,
  HarnessStatus,
  HealthResponse,
  InspectSelectResult,
  JasperCompileResponse,
  JasperPreviewResponse,
  JrxmlLintReport,
  JrxmlScaffoldResponse,
  JsonWarningsResponse,
  PreviewMode,
  ProjectCreatePayload,
  ProjectRead,
  ProjectUpdatePayload,
  ScenarioType,
  SkillInfo,
  SqlRegeneratePayload,
  SqlRegenerateResponse,
  SqlValidateResponse,
  SubreportInfo,
} from "@/types/studio";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
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

export const api = {
  // System & Health
  getHealth: () => requestJson<HealthResponse>("/api/health"),
  getJasperHealth: () => requestJson<Record<string, unknown>>("/api/jasper/health"),
  getSettings: () => requestJson<Record<string, unknown>>("/api/settings"),
  updateSettings: (payload: Record<string, unknown>) =>
    requestJson<Record<string, unknown>>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  listSkills: () => requestJson<SkillInfo[]>("/api/skills"),
  listHarnesses: () => requestJson<HarnessStatus[]>("/api/harnesses"),
  listMcpTools: () => requestJson<Record<string, unknown>[]>("/api/mcp-tools"),

  // Projects
  listProjects: () => requestJson<ProjectRead[]>("/api/projects"),
  createProject: (payload: ProjectCreatePayload) =>
    requestJson<ProjectRead>("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getProject: (projectId: string) =>
    requestJson<ProjectRead>(`/api/projects/${encodeURIComponent(projectId)}`),
  updateProject: (projectId: string, payload: ProjectUpdatePayload) =>
    requestJson<ProjectRead>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteProject: (projectId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/projects/${encodeURIComponent(projectId)}`,
      { method: "DELETE" },
    ),

  // Project PDF
  uploadProjectPdf: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return requestJson<ProjectRead>(
      `/api/projects/${encodeURIComponent(projectId)}/pdf`,
      { method: "POST", body: form },
    );
  },
  getProjectPdfUrl: (projectId: string) =>
    `/api/projects/${encodeURIComponent(projectId)}/pdf`,
  getProjectPdfGeometry: (projectId: string) =>
    requestJson<Record<string, unknown>>(
      `/api/projects/${encodeURIComponent(projectId)}/pdf/geometry`,
    ),

  // Artifacts & Revisions
  getArtifact: (projectId: string, type: ArtifactType, version?: number) => {
    const query = version !== undefined ? `?version=${version}` : "";
    return requestJson<ArtifactRevisionRead>(
      `/api/projects/${encodeURIComponent(projectId)}/artifacts/${type}${query}`,
    );
  },
  saveArtifact: (
    projectId: string,
    type: ArtifactType,
    payload: ArtifactSavePayload,
  ) =>
    requestJson<ArtifactSaveResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/artifacts/${type}`,
      { method: "PUT", body: JSON.stringify(payload) },
    ),
  restoreArtifact: (
    projectId: string,
    type: ArtifactType,
    payload: {
      version_num?: number;
      revision_id?: number;
      created_by?: "user" | "agent" | "system";
      auto_regenerate_sql?: boolean;
    },
  ) =>
    requestJson<ArtifactSaveResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/artifacts/${type}/restore`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  listRevisions: (projectId: string, artifactType?: ArtifactType) => {
    const query = artifactType ? `?artifact_type=${artifactType}` : "";
    return requestJson<ArtifactRevisionRead[]>(
      `/api/projects/${encodeURIComponent(projectId)}/revisions${query}`,
    );
  },

  // Form Builder & JSON Warnings
  getJsonWarnings: (projectId: string) =>
    requestJson<JsonWarningsResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/json/warnings`,
    ),
  mutateFormBuilder: (projectId: string, payload: FormBuilderMutatePayload) =>
    requestJson<{
      saved: ArtifactSaveResponse;
      warnings: (string | Record<string, unknown>)[];
    }>(`/api/projects/${encodeURIComponent(projectId)}/form-builder/mutate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // SQL Tools
  regenerateSql: (projectId: string, payload: SqlRegeneratePayload = {}) =>
    requestJson<SqlRegenerateResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/sql/regenerate`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  validateSql: (
    projectId: string,
    payload: { sql?: string; artifact_type?: "sql_insert" | "sql_select" },
  ) =>
    requestJson<SqlValidateResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/sql/validate`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  // Gates & Chat
  listGates: (projectId: string) =>
    requestJson<GateApprovalRead[]>(
      `/api/projects/${encodeURIComponent(projectId)}/gates`,
    ),
  updateGate: (
    projectId: string,
    gateName: GateName,
    payload: { status: GateStatus; decided_by?: string; notes?: string },
  ) =>
    requestJson<GateApprovalRead>(
      `/api/projects/${encodeURIComponent(projectId)}/gates/${gateName}`,
      { method: "PUT", body: JSON.stringify(payload) },
    ),
  listChat: (projectId: string, phase?: ChatPhase) => {
    const query = phase ? `?phase=${phase}` : "";
    return requestJson<ChatMessageRead[]>(
      `/api/projects/${encodeURIComponent(projectId)}/chat${query}`,
    );
  },
  appendChat: (projectId: string, payload: ChatMessageCreatePayload) =>
    requestJson<ChatMessageRead>(
      `/api/projects/${encodeURIComponent(projectId)}/chat`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  // Database Profiles & Execution
  listDbProfiles: () => requestJson<DbProfileRead[]>("/api/db/profiles"),
  createDbProfile: (payload: DbProfileCreatePayload) =>
    requestJson<DbProfileRead>("/api/db/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateDbProfile: (profileId: string, payload: DbProfileUpdatePayload) =>
    requestJson<DbProfileRead>(
      `/api/db/profiles/${encodeURIComponent(profileId)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
  deleteDbProfile: (profileId: string) =>
    requestJson<{ status: string; deleted: string }>(
      `/api/db/profiles/${encodeURIComponent(profileId)}`,
      { method: "DELETE" },
    ),
  testDbProfile: (profileId: string) =>
    requestJson<DbConnectionTestResult>(
      `/api/db/profiles/${encodeURIComponent(profileId)}/test`,
      { method: "POST" },
    ),
  listDbProfileDatabases: (profileId: string) =>
    requestJson<DbProfileDatabasesResult>(
      `/api/db/profiles/${encodeURIComponent(profileId)}/databases`,
    ),
  getSampleAtendimento: (profileId: string) =>
    requestJson<{ profile_id: string; sample_atendimento_id: number | null }>(
      `/api/db/profiles/${encodeURIComponent(profileId)}/sample-atendimento`,
    ),
  dryRunInsert: (
    projectId: string,
    payload: { profile_id: string; sql_text?: string },
  ) =>
    requestJson<DryRunInsertResult>(
      `/api/projects/${encodeURIComponent(projectId)}/db/dry-run-insert`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  commitInsert: (
    projectId: string,
    payload: { profile_id: string; dry_run_token: string; sql_text?: string },
  ) =>
    requestJson<CommitInsertResult>(
      `/api/projects/${encodeURIComponent(projectId)}/db/commit-insert`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  inspectSelect: (
    projectId: string,
    payload: {
      profile_id: string;
      sql_select?: string;
      sample_id?: number;
      lookup_sample_id?: boolean;
    },
  ) =>
    requestJson<InspectSelectResult>(
      `/api/projects/${encodeURIComponent(projectId)}/db/inspect-select`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  // JRXML & Jasper Preview
  scaffoldJrxml: (
    projectId: string,
    payload: { save_artifact?: boolean; options?: Record<string, unknown> } = {},
  ) =>
    requestJson<JrxmlScaffoldResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/jrxml/scaffold`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  lintJrxml: (projectId: string, jrxml?: string) =>
    requestJson<JrxmlLintReport>(
      `/api/projects/${encodeURIComponent(projectId)}/jrxml/lint`,
      { method: "POST", body: JSON.stringify(jrxml !== undefined ? { jrxml } : {}) },
    ),
  compileJasper: (
    projectId: string,
    payload: { inline_jrxml?: string; run_linter?: boolean } = {},
  ) =>
    requestJson<JasperCompileResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/jasper/compile`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  generatePreview: (
    projectId: string,
    payload: {
      scenario?: ScenarioType;
      mode?: PreviewMode;
      db_profile_id?: string | null;
      atendimento_id?: number | null;
      inline_jrxml?: string | null;
      dpi?: number;
      unit_name?: string;
    } = {},
  ) =>
    requestJson<JasperPreviewResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/jasper/preview`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getPreviewPdfUrl: (
    projectId: string,
    scenario?: ScenarioType,
    cacheBuster?: number,
  ) => {
    const params = new URLSearchParams();
    if (scenario) params.set("scenario", scenario);
    if (cacheBuster !== undefined) params.set("t", String(cacheBuster));
    const qs = params.toString();
    return `/api/projects/${encodeURIComponent(projectId)}/jasper/preview/pdf${qs ? `?${qs}` : ""}`;
  },
  getPreviewPageUrl: (
    projectId: string,
    pageNum: number,
    scenario?: ScenarioType,
    cacheBuster?: number,
  ) => {
    const params = new URLSearchParams();
    if (scenario) params.set("scenario", scenario);
    if (cacheBuster !== undefined) params.set("t", String(cacheBuster));
    const qs = params.toString();
    return `/api/projects/${encodeURIComponent(projectId)}/jasper/preview/pages/${pageNum}${qs ? `?${qs}` : ""}`;
  },
  getExportBundleUrl: (
    projectId: string,
    options?: {
      scenario?: ScenarioType;
      mode?: PreviewMode;
      db_profile_id?: string | null;
    },
  ) => {
    const params = new URLSearchParams();
    if (options?.scenario) params.set("scenario", options.scenario);
    if (options?.mode) params.set("mode", options.mode);
    if (options?.db_profile_id) params.set("db_profile_id", options.db_profile_id);
    const qs = params.toString();
    return `/api/projects/${encodeURIComponent(projectId)}/jasper/export-bundle${qs ? `?${qs}` : ""}`;
  },
  submitVisualRegionFeedback: (
    projectId: string,
    payload: {
      page: number;
      pdf_rect: {
        x0: number;
        y0: number;
        x1: number;
        y1: number;
        width?: number;
        height?: number;
      };
      detail_coords?:
        | { x: number; y: number; width: number; height: number }
        | Record<string, unknown>;
      scenario?: ScenarioType;
      content: string;
      dpi?: number;
    },
  ) =>
    requestJson<{
      ok: boolean;
      project_id: string;
      message: ChatMessageRead;
      crop_png_path: string | null;
      crop_url: string | null;
    }>(
      `/api/projects/${encodeURIComponent(projectId)}/jasper/preview/crop-feedback`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  // Subreports
  listSubreports: () => requestJson<SubreportInfo[]>("/api/subreports"),
  uploadSubreport: (file: File, filename?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (filename) form.append("filename", filename);
    return requestJson<SubreportInfo>("/api/subreports", {
      method: "POST",
      body: form,
    });
  },
  deleteSubreport: (filename: string) =>
    requestJson<Record<string, unknown>>(
      `/api/subreports/${encodeURIComponent(filename)}`,
      { method: "DELETE" },
    ),
};
