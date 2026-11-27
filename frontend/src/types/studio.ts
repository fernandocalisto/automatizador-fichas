export type ProjectStage =
  | "landing"
  | "extraction"
  | "form_builder"
  | "sql_db"
  | "jrxml_design"
  | "completed";

export type ProjectKind = "clinical_form" | "free_report";
export type EntryMode =
  | "pdf"
  | "json"
  | "jrxml"
  | "blank_report"
  | "sftp_import"
  | "jasperserver_import";
export type EnvironmentKind = "DEV" | "HML" | "PRD";
export type CredentialMode = "default" | "custom";
export type CredentialKind = "postgres" | "sftp" | "jasperserver";
export type SftpAuthType = "password" | "private_key";
export type SftpPublishMode = "jrxml_only" | "both" | "jasper_only";
export type ClientSystemType =
  | "ambulatorial"
  | "hospitalar"
  | "painel"
  | "compras"
  | "outro";
export type ArtifactType = "json" | "sql_insert" | "sql_select" | "jrxml";
export type CreatedBy = "user" | "agent" | "system";
export type ChatPhase = "extraction" | "jrxml";
export type ChatRole = "user" | "assistant" | "tool" | "system";
export type GateName = "gate1_json" | "gate2_sql_insert" | "gate3_jrxml";
export type GateStatus = "pending" | "approved" | "rejected";
export type SubreportSource = "builtin" | "custom_override" | "custom_extra";
export type ScenarioType = "full" | "stress" | "blank";
export type PreviewMode = "auto" | "offline" | "db_hybrid" | "db_live";
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
  project_kind?: ProjectKind;
  current_stage: ProjectStage;
  entry_mode: EntryMode;
  preferred_harness: string;
  template_db_id: number | null;
  default_db_profile_id?: string | null;
  client_system_id?: string | null;
  source_origin?: Record<string, unknown>;
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
  project_kind?: ProjectKind | null;
  entry_mode?: EntryMode;
  preferred_harness?: string;
  template_db_id?: number | null;
  default_db_profile_id?: string | null;
  client_system_id?: string | null;
  source_origin?: Record<string, unknown>;
  current_stage?: ProjectStage | null;
  initial_json?: string | Record<string, unknown> | null;
  initial_jrxml?: string | null;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
  project_kind?: ProjectKind;
  current_stage?: ProjectStage;
  preferred_harness?: string;
  template_db_id?: number | null;
  default_db_profile_id?: string | null;
  client_system_id?: string | null;
  source_origin?: Record<string, unknown>;
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
  credential_mode?: CredentialMode;
  environment?: EnvironmentKind;
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
  dbname?: string;
  user?: string;
  password?: string | null;
  sslmode?: SslMode;
  credential_mode?: CredentialMode;
  environment?: EnvironmentKind;
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
  credential_mode?: CredentialMode;
  environment?: EnvironmentKind;
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
  effective_mode: "offline" | "db_hybrid" | "db_live";
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

// -----------------------------------------------------------------------------
// v1.1 Shared Types: Default Credentials, SQL Workbench, JRXML Params,
// SFTP, JasperReports Server, and Clients Hub
// -----------------------------------------------------------------------------

export interface DefaultCredentialRead {
  kind: CredentialKind;
  username: string;
  organization: string;
  auth_type: SftpAuthType;
  default_dbname: string;
  default_dbname_ambulatorial: string;
  default_dbname_hospitalar: string;
  default_remote_base_dir: string;
  has_password: boolean;
  has_private_key: boolean;
  has_passphrase: boolean;
  configured: boolean;
  updated_at: string | null;
}

export interface DefaultCredentialUpdatePayload {
  username?: string | null;
  organization?: string | null;
  auth_type?: SftpAuthType | null;
  default_dbname?: string | null;
  default_dbname_ambulatorial?: string | null;
  default_dbname_hospitalar?: string | null;
  default_remote_base_dir?: string | null;
  password?: string | null;
  private_key?: string | null;
  passphrase?: string | null;
}

export interface TableSummary {
  schema_name: string;
  table_name: string;
  table_type: string;
  estimated_rows: number | null;
}

export interface TableColumnDetail {
  name: string;
  data_type: string;
  udt_name: string;
  is_nullable: boolean;
  default_value: string | null;
  java_class: string;
  is_primary_key: boolean;
}

export interface TableForeignKeyDetail {
  constraint_name: string;
  column_name: string;
  foreign_schema: string;
  foreign_table: string;
  foreign_column: string;
}

export interface TableSchemaDetail {
  schema_name: string;
  table_name: string;
  columns: TableColumnDetail[];
  primary_keys: string[];
  foreign_keys: TableForeignKeyDetail[];
}

export interface SelectPreviewResult {
  ok: boolean;
  profile_id: string;
  columns: SelectColumnMeta[];
  rows: Record<string, unknown>[];
  row_count: number;
  limit: number;
  truncated: boolean;
  latency_ms: number;
  message: string;
}

export interface JrxmlParameterInfo {
  name: string;
  java_class: string;
  default_expression: string | null;
  is_system: boolean;
  input_kind: "string" | "integer" | "number" | "boolean" | "date" | "datetime";
}

export interface AgentSessionRead {
  project_id: string;
  phase: ChatPhase;
  harness_id: string;
  external_session_id: string;
  updated_at: string;
}

// SFTP Connector
export interface SftpProfileRead {
  id: string;
  name: string;
  host: string;
  port: number;
  username: string;
  auth_type: SftpAuthType;
  credential_mode: CredentialMode;
  remote_base_dir: string;
  environment: EnvironmentKind;
  read_only: boolean;
  linked_db_profile_id: string | null;
  has_secret: boolean;
  created_at: string;
  updated_at: string;
}

export interface SftpProfileCreatePayload {
  name: string;
  host: string;
  port?: number;
  username?: string;
  auth_type?: SftpAuthType;
  credential_mode?: CredentialMode;
  password?: string | null;
  private_key?: string | null;
  passphrase?: string | null;
  remote_base_dir?: string;
  environment?: EnvironmentKind;
  read_only?: boolean;
  linked_db_profile_id?: string | null;
}

export interface SftpProfileUpdatePayload {
  name?: string;
  host?: string;
  port?: number;
  username?: string;
  auth_type?: SftpAuthType;
  credential_mode?: CredentialMode;
  password?: string | null;
  private_key?: string | null;
  passphrase?: string | null;
  remote_base_dir?: string;
  environment?: EnvironmentKind;
  read_only?: boolean;
  linked_db_profile_id?: string | null;
}

export interface SftpConnectionTestResult {
  profile_id: string;
  ok: boolean;
  latency_ms: number;
  remote_base_dir: string;
  item_count: number;
  message: string;
  error: string | null;
}

export interface SftpRemoteEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size_bytes: number;
  modified_at: string | null;
  kind: "dir" | "jrxml" | "jasper" | "other";
  has_paired_file: boolean;
}

export interface SftpListResult {
  profile_id: string;
  current_path: string;
  parent_path: string | null;
  entries: SftpRemoteEntry[];
}

export interface SftpDeployPreview {
  ok: boolean;
  project_id: string;
  profile_id: string;
  remote_dir: string;
  base_filename: string;
  publish_mode: SftpPublishMode;
  target_files: string[];
  remote_exists: boolean;
  unified_diff: string;
  local_sha256: string;
  remote_sha256: string | null;
  deploy_token: string;
  compiled_ok: boolean;
  message: string;
}

export interface SftpDeployResult {
  ok: boolean;
  project_id: string;
  profile_id: string;
  published_files: string[];
  backup_files: string[];
  local_backup_path: string | null;
  message: string;
}

// JasperReports Server Connector
export interface JasperServerProfileRead {
  id: string;
  name: string;
  base_url: string;
  organization: string;
  username: string;
  credential_mode: CredentialMode;
  default_folder_uri: string;
  environment: EnvironmentKind;
  read_only: boolean;
  linked_db_profile_id: string | null;
  has_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface JasperServerProfileCreatePayload {
  name: string;
  base_url: string;
  organization?: string;
  username?: string;
  password?: string | null;
  credential_mode?: CredentialMode;
  default_folder_uri?: string;
  environment?: EnvironmentKind;
  read_only?: boolean;
  linked_db_profile_id?: string | null;
}

export interface JasperServerProfileUpdatePayload {
  name?: string;
  base_url?: string;
  organization?: string;
  username?: string;
  password?: string | null;
  credential_mode?: CredentialMode;
  default_folder_uri?: string;
  environment?: EnvironmentKind;
  read_only?: boolean;
  linked_db_profile_id?: string | null;
}

export interface JasperServerTestResult {
  profile_id: string;
  ok: boolean;
  latency_ms: number;
  version: string | null;
  edition: string | null;
  build: string | null;
  message: string;
  error: string | null;
}

export interface JasperServerResourceItem {
  uri: string;
  label: string;
  description: string;
  resource_type: "folder" | "reportUnit" | "jrxml" | "jasper" | "datasource" | "other";
  updated_at: string | null;
}

export interface JasperServerReportUnitDetail {
  uri: string;
  label: string;
  description: string;
  main_jrxml_uri: string | null;
  datasource_uri: string | null;
  input_controls: string[];
  resources: Array<{ name: string; uri: string; type: string }>;
}

export interface JasperServerDeployPreview {
  ok: boolean;
  project_id: string;
  profile_id: string;
  mode: "update" | "create";
  target_uri: string;
  main_jrxml_uri: string;
  remote_exists: boolean;
  unified_diff: string;
  local_sha256: string;
  remote_sha256: string | null;
  deploy_token: string;
  compiled_ok: boolean;
  message: string;
}

export interface JasperServerDeployResult {
  ok: boolean;
  project_id: string;
  profile_id: string;
  mode: "update" | "create";
  target_uri: string;
  main_jrxml_uri: string;
  local_backup_path: string | null;
  message: string;
}

// Clients Hub (Multi-System)
export interface ClientSystemRead {
  id: string;
  client_unit_id: string;
  system_key: string;
  label: string;
  system_type: ClientSystemType;
  environment: EnvironmentKind;
  system_url: string;
  version_label: string;
  db_profile_id: string | null;
  sftp_profile_id: string | null;
  jasperserver_profile_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ClientUnitRead {
  id: string;
  external_id: string | null;
  unit_code: string;
  name: string;
  hosting: string;
  license_status: string;
  notes: string;
  tags: string[];
  integrations: string[];
  systems: ClientSystemRead[];
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientSyncDiffItem {
  unit_code: string;
  name: string;
  action: "create" | "update" | "unchanged";
  systems_count: number;
  changes: string[];
}

export interface ClientSyncPreviewResponse {
  ok: boolean;
  total_parsed: number;
  to_create: number;
  to_update: number;
  unchanged: number;
  warnings: string[];
  items: ClientSyncDiffItem[];
  normalized_units: Record<string, unknown>[];
}

export interface ClientSyncApplyResponse {
  ok: boolean;
  created_units: number;
  updated_units: number;
  created_systems: number;
  updated_systems: number;
  created_profiles: { postgres: number; sftp: number; jasperserver: number };
  warnings: string[];
}

export type StudioSection =
  | "projects"
  | "clients"
  | "workspace"
  | "form_builder"
  | "sql_db"
  | "jasper_studio"
  | "settings";
