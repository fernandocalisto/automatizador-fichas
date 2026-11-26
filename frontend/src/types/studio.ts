export type ProjectStage =
  | "landing"
  | "extraction"
  | "form_builder"
  | "sql_db"
  | "jrxml_design"
  | "completed";

export type EntryMode = "pdf" | "json" | "jrxml";
export type ArtifactType = "json" | "sql_insert" | "sql_select" | "jrxml";
export type CreatedBy = "user" | "agent" | "system";
export type ChatPhase = "extraction" | "jrxml";
export type ChatRole = "user" | "assistant" | "tool" | "system";
export type GateName = "gate1_json" | "gate2_sql_insert" | "gate3_jrxml";
export type GateStatus = "pending" | "approved" | "rejected";
export type SubreportSource = "builtin" | "custom_override" | "custom_extra";
export type ScenarioType = "full" | "stress" | "blank";
export type PreviewMode = "auto" | "offline" | "db_hybrid";
export type SslMode =
  | "disable"
  | "allow"
  | "prefer"
  | "require"
  | "verify-ca"
  | "verify-full";

export const SALUTEM_FIELD_TYPES = [
  "BOOLEANO",
  "BOOLEANO_RADIO",
  "CID",
  "COMBOBOX",
  "DATA",
  "EXAME",
  "HORA",
  "NUMERICO",
  "PROCEDIMENTO",
  "PROCEDIMENTO_CID",
  "TEXTO",
] as const;

export type SalutemFieldType = (typeof SALUTEM_FIELD_TYPES)[number];

export type ClinicalOrientation = "RETRATO" | "PAISAGEM";
export type SignaturePosition = "RODAPE" | "LATERAL";

export interface ClinicalAnswer {
  label: string;
  tipo_campo: SalutemFieldType | string;
  ordenacao?: number;
  obrigatorio?: boolean;
  observacao?: boolean;
  quantidade_linhas?: number;
  tamanho_campo?: number;
  valor_padrao?: string | boolean | number | null;
  opcoes?: string[];
  [key: string]: unknown;
}

export interface ClinicalQuestion {
  nome: string;
  titulo?: boolean;
  ordenacao?: number;
  observacao?: boolean;
  obrigatorio?: boolean;
  respostas: ClinicalAnswer[];
  [key: string]: unknown;
}

export interface ClinicalTemplateMeta {
  nome: string;
  descricao?: string;
  ativo?: boolean;
  layout?: string;
  orientacao?: ClinicalOrientation;
  posicao_assinatura?: SignaturePosition;
  quantidade_pagina?: number;
  importa_historico_ficha_clinica?: boolean;
  [key: string]: unknown;
}

export interface ClinicalFormJson {
  template: ClinicalTemplateMeta;
  perguntas: ClinicalQuestion[];
  [key: string]: unknown;
}

export interface GateApprovalRead {
  project_id: string;
  gate_name: GateName;
  status: GateStatus;
  decided_by: string | null;
  notes: string;
  updated_at: string;
}

export interface ProjectRead {
  id: string;
  slug: string;
  name: string;
  description: string;
  current_stage: ProjectStage;
  entry_mode: EntryMode;
  preferred_harness: string;
  template_db_id: number | null;
  workspace_dir: string;
  has_pdf: boolean;
  gates: GateApprovalRead[];
  latest_artifacts: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreatePayload {
  name: string;
  slug?: string | null;
  description?: string;
  entry_mode?: EntryMode;
  preferred_harness?: string;
  template_db_id?: number | null;
  current_stage?: ProjectStage | null;
  initial_json?: string | Record<string, unknown> | null;
  initial_jrxml?: string | null;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
  current_stage?: ProjectStage;
  preferred_harness?: string;
  template_db_id?: number | null;
}

export interface ArtifactRevisionRead {
  id: number;
  project_id: string;
  artifact_type: ArtifactType;
  version_num: number;
  content: string;
  summary: string;
  created_by: CreatedBy;
  created_at: string;
}

export interface ArtifactSavePayload {
  content: string;
  summary?: string;
  created_by?: CreatedBy;
  auto_regenerate_sql?: boolean;
  apply_uppercase?: boolean;
  sql_options?: Record<string, unknown> | null;
}

export interface ArtifactSaveResponse {
  artifact: ArtifactRevisionRead;
  generated_sql_insert: ArtifactRevisionRead | null;
  generated_sql_select: ArtifactRevisionRead | null;
}

export interface SqlRegeneratePayload {
  insert_options?: Record<string, unknown> | null;
  select_options?: Record<string, unknown> | null;
  created_by?: CreatedBy;
  summary?: string;
}

export interface SqlRegenerateResponse {
  sql_insert: ArtifactRevisionRead;
  sql_select: ArtifactRevisionRead;
}

export interface SqlValidateResponse {
  valid: boolean;
  message: string;
  artifact_type: string | null;
  unknown_field_types: string[];
}

export interface ChatMessageRead {
  id: number;
  project_id: string;
  phase: ChatPhase;
  role: ChatRole;
  content: string;
  metadata: Record<string, unknown>;
  metadata_json: string;
  created_at: string;
}

export interface ChatMessageCreatePayload {
  phase?: ChatPhase;
  role?: ChatRole;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface SubreportInfo {
  filename: string;
  name: string;
  source: SubreportSource;
  is_builtin_standard: boolean;
  is_overridden: boolean;
  size_bytes: number;
  sha256: string;
  path: string;
  updated_at: string;
}

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  path: string;
}

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  database: Record<string, unknown>;
  paths: Record<string, string>;
  builtin_subreports_count: number;
  custom_subreports_count: number;
  effective_subreports_count: number;
  frontend_built: boolean;
}

export interface HarnessStatus {
  id: string;
  display_name: string;
  installed: boolean;
  executable_path: string | null;
  sdk_available: boolean;
  version: string | null;
  auth_hint: string;
  supports_vision: boolean;
  supports_mcp: boolean;
}

export interface ClinicalWarningItem {
  code?: string;
  severity?: string;
  message: string;
  path?: string;
  [key: string]: unknown;
}

export interface JsonWarningsResponse {
  project_id: string;
  version_num: number;
  warnings_count: number;
  warnings: (string | ClinicalWarningItem)[];
}

export interface FormBuilderMutatePayload {
  action:
    | "add_question"
    | "update_question"
    | "delete_question"
    | "reorder_questions"
    | "add_answer"
    | "update_answer"
    | "delete_answer"
    | "reorder_answers";
  question_index?: number | null;
  answer_index?: number | null;
  data?: Record<string, unknown>;
  new_order?: number[] | null;
  auto_regenerate_sql?: boolean;
}

export interface DbProfileRead {
  id: string;
  name: string;
  host: string;
  port: number;
  dbname: string;
  user: string;
  sslmode: SslMode;
  read_only: boolean;
  is_default: boolean;
  has_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface DbProfileCreatePayload {
  name: string;
  host: string;
  port?: number;
  dbname: string;
  user: string;
  password?: string | null;
  sslmode?: SslMode;
  read_only?: boolean;
  is_default?: boolean;
}

export interface DbProfileUpdatePayload {
  name?: string;
  host?: string;
  port?: number;
  dbname?: string;
  user?: string;
  password?: string | null;
  sslmode?: SslMode;
  read_only?: boolean;
  is_default?: boolean;
}

export interface DbConnectionTestResult {
  profile_id: string;
  ok: boolean;
  latency_ms: number;
  server_version: string | null;
  current_database: string | null;
  current_user: string | null;
  read_only: boolean;
  message: string;
  error: string | null;
}

export interface DryRunInsertResult {
  ok: boolean;
  project_id: string;
  profile_id: string;
  rolled_back: boolean;
  template_id: number | null;
  simulated_template_id: number | null;
  notices: string[];
  sql_sha256: string;
  dry_run_token: string;
  latency_ms: number;
  message: string;
}

export interface CommitInsertResult {
  ok: boolean;
  committed: boolean;
  project_id: string;
  profile_id: string;
  template_id: number | null;
  notices: string[];
  sql_sha256: string;
  artifact_version: number | null;
  gate2_status: string;
  latency_ms: number;
  message: string;
}

export interface SelectColumnMeta {
  name: string;
  type_oid: number | null;
  pg_type: string;
  java_class: string;
  nullable: boolean | null;
}

export interface InspectSelectResult {
  ok: boolean;
  profile_id: string;
  columns: SelectColumnMeta[];
  sample_id_used: number;
  sample_atendimento_id: number | null;
  parameter_placeholders_replaced: number;
  latency_ms: number;
  message: string;
}

export interface JrxmlLintIssue {
  rule: string;
  severity: "error" | "warning" | string;
  message: string;
  line?: number | null;
  element?: string | null;
  [key: string]: unknown;
}

export interface JrxmlLintReport {
  valid?: boolean;
  ok?: boolean;
  errors: JrxmlLintIssue[];
  warnings: JrxmlLintIssue[];
  summary?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface JrxmlScaffoldResponse {
  project_id: string;
  jrxml: string;
  lint: JrxmlLintReport;
  saved_revision: ArtifactRevisionRead | null;
}

export interface JasperCompileResponse {
  ok: boolean;
  compiled: boolean;
  project_id: string;
  slug: string;
  jrxml_path: string;
  jasper_path: string;
  lint: JrxmlLintReport | null;
  daemon: Record<string, unknown>;
}

export interface PreviewPageInfo {
  page_number: number;
  url: string;
  filename: string;
  size_bytes: number;
}

export interface JasperPreviewResponse {
  ok: boolean;
  project_id: string;
  slug: string;
  scenario: ScenarioType;
  requested_mode: PreviewMode;
  effective_mode: "offline" | "db_hybrid";
  fallback_reason: string | null;
  atendimento_id: number;
  dpi: number;
  page_count: number;
  single_page_ok: boolean;
  pdf_path: string;
  pdf_size_bytes: number;
  pdf_url: string;
  page_urls: string[];
  pages: PreviewPageInfo[];
  subreport_dir: string;
  lint: JrxmlLintReport;
  daemon: Record<string, unknown>;
}

export type StudioSection =
  | "projects"
  | "workspace"
  | "form_builder"
  | "sql_db"
  | "jasper_studio"
  | "settings";
