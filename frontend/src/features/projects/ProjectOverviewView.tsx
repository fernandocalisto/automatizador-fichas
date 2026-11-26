import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
  FileCode2,
  FileText,
  History,
  LayoutList,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  Input,
  Select,
  SplitPane,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ProjectOverviewProps } from "@/types/feature-props";
import type {
  ArtifactRevisionRead,
  ArtifactType,
  GateApprovalRead,
  GateName,
  GateStatus,
} from "@/types/studio";
import {
  ARTIFACT_LABELS,
  ENTRY_MODE_META,
  formatDateTimeBr,
  GATE_DESCRIPTORS,
  GATE_STATUS_META,
  getGateStatus,
  HARNESS_OPTIONS,
  PROJECT_STAGES,
  STAGE_MAP,
} from "./projectMeta";

interface PdfGeometrySpan {
  text?: string;
  x?: number;
  y?: number;
  detail_x?: number;
  detail_y?: number;
  font?: string;
  size?: number;
}

interface PdfGeometryMarker {
  candidate_marker?: string;
  shape_type?: string;
  detail_x?: number;
  detail_y?: number;
  width?: number;
  height?: number;
}

interface PdfGeometryPage {
  page_number?: number;
  width?: number;
  height?: number;
  orientation?: string;
  max_detail_height?: number;
  text_spans?: PdfGeometrySpan[];
  candidate_markers?: PdfGeometryMarker[];
}

interface PdfGeometryData {
  page_count?: number;
  width?: number;
  height?: number;
  orientation?: string;
  summary?: {
    total_text_spans?: number;
    total_shapes?: number;
    checkbox_candidates?: number;
    radio_candidates?: number;
  };
  pages?: PdfGeometryPage[];
}

const ARTIFACT_FILTER_OPTIONS: { value: "all" | ArtifactType; label: string }[] =
  [
    { value: "all", label: "Todos os artefatos" },
    { value: "json", label: "JSON Clínico" },
    { value: "sql_insert", label: "SQL INSERT" },
    { value: "sql_select", label: "SQL SELECT" },
    { value: "jrxml", label: "JRXML" },
  ];

function mergeGateIntoList(
  existing: GateApprovalRead[] | undefined,
  updated: GateApprovalRead,
): GateApprovalRead[] {
  const list = Array.isArray(existing) ? [...existing] : [];
  const idx = list.findIndex((g) => g.gate_name === updated.gate_name);
  if (idx >= 0) {
    list[idx] = updated;
    return list;
  }
  return [...list, updated];
}

export function ProjectOverviewView({
  project,
  onProjectUpdated,
  onNavigateSection,
}: ProjectOverviewProps) {
  const { pushToast } = useToast();

  // Gate notes & loading state
  const [gateNotes, setGateNotes] = useState<Record<GateName, string>>(() => ({
    gate1_json: getGateStatus(project.gates, "gate1_json")?.notes ?? "",
    gate2_sql_insert:
      getGateStatus(project.gates, "gate2_sql_insert")?.notes ?? "",
    gate3_jrxml: getGateStatus(project.gates, "gate3_jrxml")?.notes ?? "",
  }));
  const [gateBusy, setGateBusy] = useState<GateName | null>(null);

  // Revisions state
  const [revisions, setRevisions] = useState<ArtifactRevisionRead[]>([]);
  const [loadingRevisions, setLoadingRevisions] = useState(false);
  const [artifactFilter, setArtifactFilter] = useState<"all" | ArtifactType>(
    "all",
  );
  const [restoringId, setRestoringId] = useState<number | null>(null);

  // PDF Upload & Geometry state
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [pdfDragActive, setPdfDragActive] = useState(false);
  const [pdfVersion, setPdfVersion] = useState(0);
  const [geometry, setGeometry] = useState<PdfGeometryData | null>(null);
  const [loadingGeometry, setLoadingGeometry] = useState(false);
  const [geometryOpen, setGeometryOpen] = useState(false);
  const [geometryError, setGeometryError] = useState<string | null>(null);

  const pdfFileInputRef = useRef<HTMLInputElement | null>(null);

  // Sync gate notes when switching active project
  useEffect(() => {
    setGateNotes({
      gate1_json: getGateStatus(project.gates, "gate1_json")?.notes ?? "",
      gate2_sql_insert:
        getGateStatus(project.gates, "gate2_sql_insert")?.notes ?? "",
      gate3_jrxml: getGateStatus(project.gates, "gate3_jrxml")?.notes ?? "",
    });
    setGeometry(null);
    setGeometryOpen(false);
    setGeometryError(null);
  }, [project.id, project.gates]);

  const loadRevisions = useCallback(async () => {
    setLoadingRevisions(true);
    try {
      const list = await api.listRevisions(
        project.id,
        artifactFilter === "all" ? undefined : artifactFilter,
      );
      setRevisions(Array.isArray(list) ? list : []);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao carregar revisões",
        description: err instanceof Error ? err.message : String(err),
      });
      setRevisions([]);
    } finally {
      setLoadingRevisions(false);
    }
  }, [project.id, artifactFilter, pushToast]);

  useEffect(() => {
    void loadRevisions();
  }, [loadRevisions]);

  const handleGateAction = async (gateName: GateName, status: GateStatus) => {
    setGateBusy(gateName);
    try {
      const notes = status === "pending" ? "" : (gateNotes[gateName] ?? "");
      const updatedGate = await api.updateGate(project.id, gateName, {
        status,
        decided_by: "user",
        notes,
      });

      if (status === "pending") {
        setGateNotes((prev) => ({ ...prev, [gateName]: "" }));
      }

      onProjectUpdated({
        ...project,
        gates: mergeGateIntoList(project.gates, updatedGate),
      });

      pushToast({
        tone: status === "rejected" ? "warning" : "success",
        title: `Gate atualizado: ${GATE_STATUS_META[status].label}`,
        description:
          GATE_DESCRIPTORS.find((g) => g.name === gateName)?.title ?? gateName,
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao atualizar gate",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setGateBusy(null);
    }
  };

  const handleRestoreRevision = async (rev: ArtifactRevisionRead) => {
    setRestoringId(rev.id);
    try {
      const saved = await api.restoreArtifact(project.id, rev.artifact_type, {
        version_num: rev.version_num,
        created_by: "user",
        auto_regenerate_sql: rev.artifact_type === "json",
      });

      const nextArtifacts: Record<string, number> = {
        ...(project.latest_artifacts ?? {}),
      };
      if (saved?.artifact) {
        nextArtifacts[saved.artifact.artifact_type] =
          saved.artifact.version_num;
      }
      if (saved?.generated_sql_insert) {
        nextArtifacts.sql_insert = saved.generated_sql_insert.version_num;
      }
      if (saved?.generated_sql_select) {
        nextArtifacts.sql_select = saved.generated_sql_select.version_num;
      }

      onProjectUpdated({
        ...project,
        latest_artifacts: nextArtifacts,
      });

      pushToast({
        tone: "success",
        title: "Revisão restaurada",
        description: `${ARTIFACT_LABELS[rev.artifact_type]} v${rev.version_num} restaurado como versão mais recente.`,
      });
      await loadRevisions();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao restaurar revisão",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRestoringId(null);
    }
  };

  const handleUploadPdf = async (file: File | null) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      pushToast({
        tone: "error",
        title: "Arquivo inválido",
        description: "Envie um arquivo com extensão .pdf.",
      });
      return;
    }

    setUploadingPdf(true);
    try {
      const updated = await api.uploadProjectPdf(project.id, file);
      onProjectUpdated(updated);
      setPdfVersion((v) => v + 1);
      setGeometry(null);
      setGeometryError(null);
      pushToast({
        tone: "success",
        title: project.has_pdf ? "PDF substituído" : "PDF anexado ao projeto",
        description: `${file.name} salvo como source.pdf.`,
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha no upload do PDF",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setUploadingPdf(false);
      if (pdfFileInputRef.current) {
        pdfFileInputRef.current.value = "";
      }
    }
  };

  const handlePdfDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setPdfDragActive(false);
    const file = e.dataTransfer.files?.[0] ?? null;
    void handleUploadPdf(file);
  };

  const handleInspectGeometry = async () => {
    setLoadingGeometry(true);
    setGeometryError(null);
    setGeometryOpen(true);
    try {
      const data = await api.getProjectPdfGeometry(project.id);
      setGeometry(data as PdfGeometryData);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Não foi possível inspecionar a geometria do PDF.";
      setGeometryError(message);
      pushToast({
        tone: "error",
        title: "Erro na inspeção geométrica",
        description: message,
      });
    } finally {
      setLoadingGeometry(false);
    }
  };

  const stageInfo = STAGE_MAP[project.current_stage] ?? PROJECT_STAGES[0];
  const currentStageIndex = PROJECT_STAGES.findIndex(
    (s) => s.id === project.current_stage,
  );
  const entryMeta = ENTRY_MODE_META[project.entry_mode] ?? ENTRY_MODE_META.pdf;
  const harnessLabel =
    HARNESS_OPTIONS.find((h) => h.value === project.preferred_harness)?.label ??
    project.preferred_harness;

  const basePdfUrl = api.getProjectPdfUrl(project.id);
  const pdfSrc =
    pdfVersion > 0 ? `${basePdfUrl}?v=${pdfVersion}` : basePdfUrl;

  const firstPage = geometry?.pages?.[0];

  const leftPane = (
    <div className="flex h-full flex-col overflow-y-auto bg-canvas p-4 space-y-4">
      {/* 1. Project Summary Card */}
      <Card>
        <CardHeader className="flex-wrap">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base font-semibold tracking-tight text-ink">
                {project.name}
              </h1>
              <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                {project.slug}
              </span>
            </div>
            {project.description && (
              <p className="text-xs text-ink-secondary">{project.description}</p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={stageInfo.tone} dot>
              {stageInfo.label}
            </Badge>
            <Badge tone={entryMeta.tone}>{entryMeta.label}</Badge>
            {project.template_db_id !== null &&
              project.template_db_id !== undefined && (
                <Badge tone="accent" className="tabular-nums">
                  ID #{project.template_db_id}
                </Badge>
              )}
          </div>
        </CardHeader>

        <CardBody className="grid grid-cols-1 gap-2.5 text-xs sm:grid-cols-3">
          <div>
            <span className="block text-[11px] text-ink-muted">
              Harness preferido
            </span>
            <span className="font-medium text-ink">{harnessLabel}</span>
          </div>
          <div>
            <span className="block text-[11px] text-ink-muted">
              Última atualização
            </span>
            <span className="font-medium text-ink tabular-nums">
              {formatDateTimeBr(project.updated_at)}
            </span>
          </div>
          <div>
            <span className="block text-[11px] text-ink-muted">Workspace</span>
            <span
              className="block truncate font-mono text-[11px] text-ink-secondary"
              title={project.workspace_dir}
            >
              {project.workspace_dir}
            </span>
          </div>
        </CardBody>
      </Card>

      {/* 2. Workflow Stepper + Direct Section Navigation */}
      <Card>
        <CardHeader className="flex-wrap">
          <CardTitle>Etapas do Pipeline Clínico</CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateSection("form_builder")}
              icon={<LayoutList className="h-3.5 w-3.5" />}
            >
              Form Builder
            </Button>
            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateSection("sql_db")}
              icon={<Database className="h-3.5 w-3.5" />}
            >
              SQL & Banco
            </Button>
            <Button
              variant="blueprint"
              size="xs"
              onClick={() => onNavigateSection("jasper_studio")}
              icon={<FileCode2 className="h-3.5 w-3.5" />}
            >
              Jasper Studio
            </Button>
          </div>
        </CardHeader>

        <CardBody>
          <ol
            aria-label="Progresso das etapas do projeto"
            className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6"
          >
            {PROJECT_STAGES.map((stage, idx) => {
              const isCompleted = idx < currentStageIndex;
              const isCurrent = idx === currentStageIndex;
              return (
                <li
                  key={stage.id}
                  className={cn(
                    "rounded-md border px-2.5 py-2 text-xs transition-colors",
                    isCurrent && "border-accent bg-accent-soft/60",
                    isCompleted && "border-success/30 bg-success-soft/40",
                    !isCurrent &&
                      !isCompleted &&
                      "border-border bg-surface-subtle/40",
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold tabular-nums",
                        isCurrent && "bg-accent text-accent-ink",
                        isCompleted && "bg-success text-white",
                        !isCurrent &&
                          !isCompleted &&
                          "bg-border text-ink-secondary",
                      )}
                    >
                      {isCompleted ? (
                        <Check className="h-2.5 w-2.5" />
                      ) : (
                        idx + 1
                      )}
                    </span>
                    <span
                      className={cn(
                        "truncate font-medium",
                        isCurrent ? "text-accent" : "text-ink",
                      )}
                    >
                      {stage.shortLabel}
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        </CardBody>
      </Card>

      {/* 3. Three Human Approval Gates */}
      <Card>
        <CardHeader>
          <CardTitle>Gates de Aprovação Humana</CardTitle>
          <span className="text-[11px] text-ink-muted">
            Controle de qualidade por marco
          </span>
        </CardHeader>
        <CardBody className="space-y-3">
          {GATE_DESCRIPTORS.map((descriptor) => {
            const gate = getGateStatus(project.gates, descriptor.name);
            const status: GateStatus = gate?.status ?? "pending";
            const statusMeta = GATE_STATUS_META[status];
            const busy = gateBusy === descriptor.name;

            return (
              <div
                key={descriptor.name}
                className="rounded-md border border-border bg-surface-subtle/40 p-3 space-y-2.5"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-xs font-semibold text-ink">
                        {descriptor.title}
                      </h4>
                      <Badge tone={statusMeta.tone} dot>
                        {statusMeta.label}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-[11px] text-ink-muted">
                      {descriptor.description}
                    </p>
                  </div>

                  {gate?.updated_at && status !== "pending" && (
                    <span className="text-[10px] text-ink-muted tabular-nums">
                      {gate.decided_by ? `${gate.decided_by} · ` : ""}
                      {formatDateTimeBr(gate.updated_at)}
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <Input
                    aria-label={`Observações para ${descriptor.shortLabel}`}
                    placeholder="Observações da decisão (opcional)..."
                    value={gateNotes[descriptor.name] ?? ""}
                    onChange={(e) =>
                      setGateNotes((prev) => ({
                        ...prev,
                        [descriptor.name]: e.target.value,
                      }))
                    }
                    className="h-7 text-xs flex-1"
                  />

                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button
                      variant={status === "approved" ? "primary" : "outline"}
                      size="xs"
                      loading={busy}
                      disabled={busy}
                      onClick={() =>
                        void handleGateAction(descriptor.name, "approved")
                      }
                      icon={<CheckCircle2 className="h-3 w-3" />}
                    >
                      Aprovar
                    </Button>
                    <Button
                      variant={status === "rejected" ? "danger" : "outline"}
                      size="xs"
                      loading={busy}
                      disabled={busy}
                      onClick={() =>
                        void handleGateAction(descriptor.name, "rejected")
                      }
                      icon={<XCircle className="h-3 w-3" />}
                    >
                      Rejeitar
                    </Button>
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={busy || status === "pending"}
                      onClick={() =>
                        void handleGateAction(descriptor.name, "pending")
                      }
                      icon={<RotateCcw className="h-3 w-3" />}
                    >
                      Resetar
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </CardBody>
      </Card>

      {/* 4. Upload / Replace source.pdf */}
      <Card>
        <CardHeader>
          <CardTitle>PDF de Referência (source.pdf)</CardTitle>
          <Badge tone={project.has_pdf ? "success" : "warning"} dot>
            {project.has_pdf ? "Anexado" : "Ausente"}
          </Badge>
        </CardHeader>
        <CardBody>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setPdfDragActive(true);
            }}
            onDragLeave={() => setPdfDragActive(false)}
            onDrop={handlePdfDrop}
            className={cn(
              "flex flex-col items-center justify-between gap-3 rounded-md border border-dashed px-4 py-3 sm:flex-row transition-colors",
              pdfDragActive
                ? "border-accent bg-accent-soft/60"
                : "border-border-strong bg-surface-subtle/40",
            )}
          >
            <input
              ref={pdfFileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              aria-label="Enviar ou substituir source.pdf"
              className="hidden"
              onChange={(e) =>
                void handleUploadPdf(e.target.files?.[0] ?? null)
              }
            />
            <div className="flex items-center gap-2.5 text-xs">
              <FileText className="h-4.5 w-4.5 shrink-0 text-blueprint" />
              <div>
                <p className="font-medium text-ink">
                  {project.has_pdf
                    ? "Substituir o source.pdf atual"
                    : "Enviar o PDF original da ficha clínica"}
                </p>
                <p className="text-[11px] text-ink-muted">
                  Arraste um arquivo .pdf ou clique para selecionar no disco.
                </p>
              </div>
            </div>
            <Button
              variant="outline"
              size="xs"
              loading={uploadingPdf}
              onClick={() => pdfFileInputRef.current?.click()}
              icon={<Upload className="h-3.5 w-3.5" />}
            >
              {project.has_pdf ? "Substituir PDF" : "Enviar PDF"}
            </Button>
          </div>
        </CardBody>
      </Card>

      {/* 5. Artifact Revision History */}
      <Card>
        <CardHeader className="flex-wrap">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-ink-muted" />
            <CardTitle>Histórico de Revisões</CardTitle>
            <Badge tone="neutral" className="tabular-nums">
              {revisions.length}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Select
              aria-label="Filtrar revisões por artefato"
              value={artifactFilter}
              onChange={(e) =>
                setArtifactFilter(e.target.value as "all" | ArtifactType)
              }
              className="h-7 w-44 text-xs"
            >
              {ARTIFACT_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
            <Button
              variant="ghost"
              size="icon"
              loading={loadingRevisions}
              onClick={() => void loadRevisions()}
              aria-label="Atualizar revisões"
              title="Atualizar revisões"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardHeader>

        <CardBody className="p-0">
          {revisions.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-ink-muted">
              {loadingRevisions
                ? "Carregando revisões..."
                : "Nenhuma revisão registrada para o filtro selecionado."}
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {revisions.map((rev) => {
                const isLatest =
                  project.latest_artifacts?.[rev.artifact_type] ===
                  rev.version_num;
                return (
                  <li
                    key={rev.id}
                    className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-xs hover:bg-surface-subtle/40"
                  >
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge tone="blueprint" className="text-[10px]">
                          {ARTIFACT_LABELS[rev.artifact_type]}
                        </Badge>
                        <span className="font-mono font-semibold text-ink tabular-nums">
                          v{rev.version_num}
                        </span>
                        {isLatest && (
                          <Badge tone="success" className="text-[10px]">
                            Atual
                          </Badge>
                        )}
                        <span className="text-[11px] text-ink-muted">
                          por {rev.created_by}
                        </span>
                        <span className="text-[11px] text-ink-muted tabular-nums">
                          · {formatDateTimeBr(rev.created_at)}
                        </span>
                      </div>
                      {rev.summary && (
                        <p className="truncate text-[11px] text-ink-secondary">
                          {rev.summary}
                        </p>
                      )}
                    </div>

                    <Button
                      variant="outline"
                      size="xs"
                      loading={restoringId === rev.id}
                      disabled={restoringId !== null}
                      onClick={() => void handleRestoreRevision(rev)}
                      icon={<RotateCcw className="h-3 w-3" />}
                    >
                      Restaurar revisão
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );

  const rightPane = (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      {/* PDF Viewer toolbar */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-4 py-2.5">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-blueprint" />
          <span className="text-xs font-semibold text-ink">
            Visualizador — source.pdf
          </span>
          {!project.has_pdf && (
            <Badge tone="neutral" className="text-[10px]">
              Sem arquivo
            </Badge>
          )}
        </div>

        {project.has_pdf && (
          <div className="flex items-center gap-1.5">
            <Button
              variant={geometryOpen ? "primary" : "outline"}
              size="xs"
              loading={loadingGeometry}
              onClick={() => void handleInspectGeometry()}
              icon={<ScanSearch className="h-3.5 w-3.5" />}
            >
              Inspecionar geometria
            </Button>
            <a
              href={basePdfUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-7 items-center gap-1 rounded border border-border bg-surface px-2 text-xs font-medium text-ink hover:bg-surface-subtle transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              <span>Abrir</span>
            </a>
          </div>
        )}
      </div>

      {/* Geometry inspector drawer when active */}
      {geometryOpen && project.has_pdf && (
        <div className="shrink-0 max-h-[44%] overflow-y-auto border-b border-border bg-surface-subtle/60 px-4 py-3 text-xs">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <ScanSearch className="h-3.5 w-3.5 text-accent" />
              <span className="font-semibold text-ink">
                Inspeção Geométrica do PDF (PyMuPDF)
              </span>
            </div>
            <button
              type="button"
              onClick={() => setGeometryOpen(false)}
              aria-label="Fechar inspeção geométrica"
              className="rounded p-1 text-ink-muted hover:bg-surface hover:text-ink cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {loadingGeometry ? (
            <div className="flex items-center gap-2 py-2 text-ink-muted">
              <Clock className="h-3.5 w-3.5 animate-spin" />
              <span>Extraindo coordenadas, fontes e marcadores...</span>
            </div>
          ) : geometryError ? (
            <div
              role="alert"
              className="flex items-center gap-2 rounded border border-danger/30 bg-danger-soft px-3 py-2 text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{geometryError}</span>
            </div>
          ) : geometry ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div className="rounded border border-border bg-surface px-2.5 py-1.5">
                  <span className="block text-[10px] text-ink-muted">
                    Páginas / Orientação
                  </span>
                  <span className="font-mono font-semibold text-ink tabular-nums">
                    {geometry.page_count ?? 0} · {geometry.orientation ?? "—"}
                  </span>
                </div>
                <div className="rounded border border-border bg-surface px-2.5 py-1.5">
                  <span className="block text-[10px] text-ink-muted">
                    Dimensões (pt)
                  </span>
                  <span className="font-mono font-semibold text-ink tabular-nums">
                    {geometry.width ?? 0} × {geometry.height ?? 0}
                  </span>
                </div>
                <div className="rounded border border-border bg-surface px-2.5 py-1.5">
                  <span className="block text-[10px] text-ink-muted">
                    Spans / Formas
                  </span>
                  <span className="font-mono font-semibold text-ink tabular-nums">
                    {geometry.summary?.total_text_spans ?? 0} /{" "}
                    {geometry.summary?.total_shapes ?? 0}
                  </span>
                </div>
                <div className="rounded border border-border bg-surface px-2.5 py-1.5">
                  <span className="block text-[10px] text-ink-muted">
                    Checkboxes / Rádios
                  </span>
                  <span className="font-mono font-semibold text-ink tabular-nums">
                    {geometry.summary?.checkbox_candidates ?? 0} /{" "}
                    {geometry.summary?.radio_candidates ?? 0}
                  </span>
                </div>
              </div>

              {firstPage?.text_spans && firstPage.text_spans.length > 0 && (
                <div>
                  <p className="mb-1 text-[11px] font-medium text-ink-secondary">
                    Primeiros spans da página 1 (coordenadas &lt;detail&gt;):
                  </p>
                  <div className="max-h-36 overflow-y-auto rounded border border-border bg-surface">
                    <table className="w-full text-left font-mono text-[11px]">
                      <thead className="sticky top-0 bg-surface-subtle text-ink-muted">
                        <tr>
                          <th className="px-2 py-1 font-medium">Texto</th>
                          <th className="px-2 py-1 font-medium">detail_x</th>
                          <th className="px-2 py-1 font-medium">detail_y</th>
                          <th className="px-2 py-1 font-medium">Fonte</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border tabular-nums">
                        {firstPage.text_spans.slice(0, 12).map((span, idx) => (
                          <tr key={idx}>
                            <td className="max-w-[180px] truncate px-2 py-1 font-sans text-ink">
                              {span.text}
                            </td>
                            <td className="px-2 py-1 text-ink-secondary">
                              {span.detail_x ?? span.x ?? "—"}
                            </td>
                            <td className="px-2 py-1 text-ink-secondary">
                              {span.detail_y ?? span.y ?? "—"}
                            </td>
                            <td className="px-2 py-1 text-ink-muted">
                              {span.size ? `${span.size}pt` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* PDF Canvas / Empty fallback */}
      <div className="min-h-0 flex-1 bg-surface-subtle/30">
        {project.has_pdf ? (
          <iframe
            title={`PDF original de ${project.name}`}
            src={pdfSrc}
            className="h-full w-full border-0 bg-white"
          />
        ) : (
          <div className="flex h-full items-center justify-center p-6">
            <EmptyState
              icon={<FileText className="h-5 w-5" />}
              title="Nenhum source.pdf anexado"
              description="Este projeto ainda não possui um PDF de referência. Envie um arquivo .pdf para visualizar a ficha clínica lado a lado e inspecionar sua geometria."
              action={
                <Button
                  variant="primary"
                  size="sm"
                  loading={uploadingPdf}
                  onClick={() => pdfFileInputRef.current?.click()}
                  icon={<Upload className="h-3.5 w-3.5" />}
                >
                  Anexar source.pdf
                </Button>
              }
            />
          </div>
        )}
      </div>
    </div>
  );

  return (
    <SplitPane
      left={leftPane}
      right={rightPane}
      initialRatio={0.52}
      minRatio={0.3}
      maxRatio={0.72}
      storageKey="salutem-project-overview-split"
    />
  );
}
