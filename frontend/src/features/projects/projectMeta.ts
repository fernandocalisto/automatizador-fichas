import type { BadgeTone } from "@/components/ui";
import type {
  ArtifactType,
  EntryMode,
  GateApprovalRead,
  GateName,
  GateStatus,
  ProjectStage,
} from "@/types/studio";

export interface StageDescriptor {
  id: ProjectStage;
  label: string;
  shortLabel: string;
  description: string;
  tone: BadgeTone;
}

export const PROJECT_STAGES: StageDescriptor[] = [
  {
    id: "landing",
    label: "Inicialização",
    shortLabel: "Início",
    description: "Projeto criado aguardando PDF ou artefato inicial.",
    tone: "neutral",
  },
  {
    id: "extraction",
    label: "Extração Clínica",
    shortLabel: "Extração",
    description: "Análise do PDF de origem para estruturar perguntas e respostas.",
    tone: "blueprint",
  },
  {
    id: "form_builder",
    label: "Form Builder",
    shortLabel: "Formulário",
    description: "Edição e validação do JSON clínico Salutem (Gate 1).",
    tone: "accent",
  },
  {
    id: "sql_db",
    label: "SQL & Banco",
    shortLabel: "SQL & PG",
    description: "Geração de SQL INSERT/SELECT, Dry-Run e Commit no PostgreSQL (Gate 2).",
    tone: "warning",
  },
  {
    id: "jrxml_design",
    label: "Jasper Studio",
    shortLabel: "JRXML",
    description: "Layout JRXML, lint XSD e preview em página única (Gate 3).",
    tone: "blueprint",
  },
  {
    id: "completed",
    label: "Concluído",
    shortLabel: "Concluído",
    description: "Ficha homologada e pronta para entrega.",
    tone: "success",
  },
];

export const STAGE_MAP: Record<ProjectStage, StageDescriptor> =
  PROJECT_STAGES.reduce(
    (acc, stage) => {
      acc[stage.id] = stage;
      return acc;
    },
    {} as Record<ProjectStage, StageDescriptor>,
  );

export const ENTRY_MODE_META: Record<
  EntryMode,
  { label: string; shortLabel: string; tone: BadgeTone }
> = {
  pdf: { label: "PDF Clínico", shortLabel: "PDF", tone: "blueprint" },
  json: { label: "Importação JSON", shortLabel: "JSON", tone: "accent" },
  jrxml: { label: "Importação JRXML", shortLabel: "JRXML", tone: "warning" },
  blank_report: {
    label: "Relatório Livre",
    shortLabel: "Livre",
    tone: "success",
  },
  sftp_import: {
    label: "Importação SFTP",
    shortLabel: "SFTP",
    tone: "blueprint",
  },
  jasperserver_import: {
    label: "JasperServer",
    shortLabel: "JS Server",
    tone: "accent",
  },
};

export interface GateDescriptor {
  name: GateName;
  shortLabel: string;
  title: string;
  description: string;
}

export const GATE_DESCRIPTORS: GateDescriptor[] = [
  {
    name: "gate1_json",
    shortLabel: "G1 JSON",
    title: "Gate 1 — Estrutura JSON Clínica",
    description: "Validação humana das perguntas, tipos Salutem e obrigatoriedade.",
  },
  {
    name: "gate2_sql_insert",
    shortLabel: "G2 SQL",
    title: "Gate 2 — SQL INSERT & PostgreSQL",
    description: "Conferência do script transacional e registro do template_db_id.",
  },
  {
    name: "gate3_jrxml",
    shortLabel: "G3 JRXML",
    title: "Gate 3 — Layout JasperReports",
    description: "Aprovação visual do PDF gerado, alinhamento e página única.",
  },
];

export const GATE_STATUS_META: Record<
  GateStatus,
  { label: string; tone: BadgeTone }
> = {
  pending: { label: "Pendente", tone: "neutral" },
  approved: { label: "Aprovado", tone: "success" },
  rejected: { label: "Rejeitado", tone: "danger" },
};

export const ARTIFACT_LABELS: Record<ArtifactType, string> = {
  json: "JSON Clínico",
  sql_insert: "SQL INSERT",
  sql_select: "SQL SELECT",
  jrxml: "JRXML",
};

export const HARNESS_OPTIONS = [
  { value: "agy", label: "AGY (Antigravity)" },
  { value: "opencode", label: "OpenCode" },
  { value: "claude", label: "Claude Code" },
  { value: "codex", label: "Codex CLI" },
] as const;

export function getGateStatus(
  gates: GateApprovalRead[] | undefined,
  gateName: GateName,
): GateApprovalRead | undefined {
  return gates?.find((g) => g.gate_name === gateName);
}

export function formatDateTimeBr(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
