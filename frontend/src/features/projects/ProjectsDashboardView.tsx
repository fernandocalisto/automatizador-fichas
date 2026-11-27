import { useMemo, useState } from "react";
import {
  CheckCircle2,
  Clock,
  CloudDownload,
  Database,
  FileCode2,
  FileText,
  FolderKanban,
  FolderOpen,
  LayoutList,
  Plus,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Input,
  Select,
  useToast,
  type BadgeTone,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ProjectsDashboardProps } from "@/types/feature-props";
import type {
  ArtifactType,
  GateStatus,
  ProjectKind,
  ProjectRead,
  ProjectStage,
} from "@/types/studio";
import { CreateProjectDialog } from "./CreateProjectDialog";
import {
  ARTIFACT_LABELS,
  ENTRY_MODE_META,
  formatDateTimeBr,
  GATE_DESCRIPTORS,
  GATE_STATUS_META,
  getGateStatus,
  PROJECT_STAGES,
  STAGE_MAP,
} from "./projectMeta";

const ARTIFACT_KEYS: ArtifactType[] = [
  "json",
  "sql_insert",
  "sql_select",
  "jrxml",
];

type KindFilter = "all" | ProjectKind;

function isFreeReportProject(project: ProjectRead): boolean {
  return project.project_kind === "free_report";
}

function getFreeReportOriginMeta(project: ProjectRead): {
  label: string;
  tone: BadgeTone;
  icon: React.ReactNode;
} {
  const provider = String(project.source_origin?.provider ?? "").toLowerCase();
  if (
    project.entry_mode === "jasperserver_import" ||
    provider === "jasperserver"
  ) {
    return {
      label: "JasperServer",
      tone: "accent",
      icon: <CloudDownload className="h-3 w-3" />,
    };
  }
  if (project.entry_mode === "sftp_import" || provider === "sftp") {
    return {
      label: "SFTP",
      tone: "blueprint",
      icon: <Server className="h-3 w-3" />,
    };
  }
  return {
    label: "Relatório Livre",
    tone: "success",
    icon: <Sparkles className="h-3 w-3" />,
  };
}

function GateIndicator({ status }: { status: GateStatus }) {
  if (status === "approved") {
    return <CheckCircle2 className="h-3 w-3 text-success" />;
  }
  if (status === "rejected") {
    return <XCircle className="h-3 w-3 text-danger" />;
  }
  return <Clock className="h-3 w-3 text-ink-muted" />;
}

export function ProjectsDashboardView({
  projects,
  loading,
  onRefreshProjects,
  onSelectProject,
  onDeleteProject,
}: ProjectsDashboardProps) {
  const { pushToast } = useToast();

  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [stageFilter, setStageFilter] = useState<"all" | ProjectStage>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ProjectRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const safeProjects = Array.isArray(projects) ? projects : [];

  const counts = useMemo(() => {
    let reports = 0;
    let clinical = 0;
    for (const p of safeProjects) {
      if (isFreeReportProject(p)) reports += 1;
      else clinical += 1;
    }
    return { all: safeProjects.length, free_report: reports, clinical_form: clinical };
  }, [safeProjects]);

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    return safeProjects.filter((project) => {
      if (kindFilter === "free_report" && !isFreeReportProject(project)) {
        return false;
      }
      if (kindFilter === "clinical_form" && isFreeReportProject(project)) {
        return false;
      }
      if (stageFilter !== "all" && project.current_stage !== stageFilter) {
        return false;
      }
      if (!q) return true;
      return (
        project.name.toLowerCase().includes(q) ||
        project.slug.toLowerCase().includes(q) ||
        (project.description && project.description.toLowerCase().includes(q))
      );
    });
  }, [safeProjects, query, kindFilter, stageFilter]);

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await onDeleteProject(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao excluir projeto",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-canvas">
      {/* Top toolbar */}
      <div className="shrink-0 border-b border-border bg-surface px-5 py-3.5">
        <div className="mx-auto flex max-w-7xl flex-col gap-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <FolderKanban className="h-4.5 w-4.5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold tracking-tight text-ink">
                    Projetos &amp; Relatórios
                  </h1>
                  <Badge tone="neutral" className="tabular-nums">
                    {filteredProjects.length}
                    {filteredProjects.length !== safeProjects.length
                      ? ` / ${safeProjects.length}`
                      : ""}
                  </Badge>
                </div>
                <p className="text-xs text-ink-muted">
                  Gerencie relatórios Jasper, fichas clínicas Salutem e acesse
                  diretamente cada área de trabalho.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[220px] flex-1 sm:w-64 sm:flex-none">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Buscar por nome ou slug..."
                  aria-label="Buscar projetos por nome ou slug"
                  className="pl-8 pr-7"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    aria-label="Limpar busca"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink cursor-pointer"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <Select
                aria-label="Filtrar por etapa"
                value={stageFilter}
                onChange={(e) =>
                  setStageFilter(e.target.value as "all" | ProjectStage)
                }
                className="w-44"
              >
                <option value="all">Todas as etapas</option>
                {PROJECT_STAGES.map((stage) => (
                  <option key={stage.id} value={stage.id}>
                    {stage.label}
                  </option>
                ))}
              </Select>

              <Button
                variant="outline"
                size="sm"
                loading={loading}
                onClick={() => void onRefreshProjects()}
                icon={<RefreshCw className="h-3.5 w-3.5" />}
              >
                Atualizar
              </Button>

              <Button
                variant="primary"
                size="sm"
                onClick={() => setCreateOpen(true)}
                icon={<Plus className="h-3.5 w-3.5" />}
              >
                Novo projeto
              </Button>
            </div>
          </div>

          {/* Filter pills by project kind */}
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="group"
              aria-label="Filtrar por tipo de projeto"
              className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-subtle p-0.5"
            >
              {(
                [
                  { id: "all", label: "Todos", count: counts.all },
                  {
                    id: "free_report",
                    label: "Relatórios",
                    count: counts.free_report,
                  },
                  {
                    id: "clinical_form",
                    label: "Fichas Clínicas",
                    count: counts.clinical_form,
                  },
                ] as { id: KindFilter; label: string; count: number }[]
              ).map((pill) => {
                const active = kindFilter === pill.id;
                return (
                  <button
                    key={pill.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setKindFilter(pill.id)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                      active
                        ? "bg-surface text-ink shadow-xs"
                        : "text-ink-muted hover:text-ink",
                    )}
                  >
                    <span>{pill.label}</span>
                    <span
                      className={cn(
                        "rounded px-1 py-0.2 text-[10px] tabular-nums",
                        active
                          ? "bg-accent-soft text-accent"
                          : "bg-surface text-ink-muted",
                      )}
                    >
                      {pill.count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="mx-auto max-w-7xl">
          {loading && safeProjects.length === 0 ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {[0, 1, 2, 3].map((idx) => (
                <Card key={idx} className="p-4 animate-pulse">
                  <div className="h-4 w-1/2 rounded bg-surface-subtle" />
                  <div className="mt-2 h-3 w-1/3 rounded bg-surface-subtle" />
                  <div className="mt-4 h-6 w-full rounded bg-surface-subtle" />
                </Card>
              ))}
            </div>
          ) : safeProjects.length === 0 ? (
            <EmptyState
              icon={<FolderKanban className="h-5 w-5" />}
              title="Nenhum projeto cadastrado"
              description="Crie um novo projeto a partir de um PDF clínico, importe um relatório via JasperServer/SFTP ou crie um relatório livre."
              action={
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => setCreateOpen(true)}
                  icon={<Plus className="h-4 w-4" />}
                >
                  Criar primeiro projeto
                </Button>
              }
            />
          ) : filteredProjects.length === 0 ? (
            <EmptyState
              icon={<Search className="h-5 w-5" />}
              title="Nenhum projeto corresponde aos filtros"
              description="Ajuste o termo de busca, tipo ou etapa para visualizar os projetos disponíveis."
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setKindFilter("all");
                    setStageFilter("all");
                  }}
                >
                  Limpar filtros
                </Button>
              }
            />
          ) : (
            <div className="space-y-2.5">
              {filteredProjects.map((project) => {
                const freeReport = isFreeReportProject(project);
                const stage =
                  STAGE_MAP[project.current_stage] ?? PROJECT_STAGES[0];
                const entry =
                  ENTRY_MODE_META[project.entry_mode] ?? ENTRY_MODE_META.pdf;
                const originMeta = freeReport
                  ? getFreeReportOriginMeta(project)
                  : null;
                const artifactEntries = ARTIFACT_KEYS.filter(
                  (key) => (project.latest_artifacts?.[key] ?? 0) > 0,
                );

                return (
                  <Card
                    key={project.id}
                    className="transition-colors hover:border-border-strong"
                  >
                    <div className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
                      {/* Left: Identity & metadata */}
                      <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              onSelectProject(
                                project,
                                freeReport ? "jasper_studio" : "workspace",
                              )
                            }
                            className="truncate text-left text-sm font-semibold text-ink hover:text-accent transition-colors cursor-pointer"
                          >
                            {project.name}
                          </button>

                          <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                            {project.slug}
                          </span>

                          {freeReport && originMeta ? (
                            <Badge tone={originMeta.tone}>
                              {originMeta.icon}
                              {originMeta.label}
                            </Badge>
                          ) : (
                            <>
                              <Badge tone={stage.tone} dot>
                                {stage.label}
                              </Badge>
                              <Badge
                                tone={entry.tone}
                                title={
                                  project.entry_mode === "pdf" && project.has_pdf
                                    ? "source.pdf anexado ao workspace"
                                    : undefined
                                }
                              >
                                {project.entry_mode === "pdf" &&
                                  project.has_pdf && (
                                    <FileText className="h-3 w-3" />
                                  )}
                                {entry.shortLabel}
                              </Badge>
                            </>
                          )}

                          {!freeReport &&
                            project.has_pdf &&
                            project.entry_mode !== "pdf" && (
                              <Badge
                                tone="neutral"
                                title="source.pdf anexado ao workspace"
                              >
                                <FileText className="h-3 w-3" />
                                PDF
                              </Badge>
                            )}

                          {!freeReport &&
                            project.template_db_id !== null &&
                            project.template_db_id !== undefined && (
                              <Badge tone="accent" className="tabular-nums">
                                ID #{project.template_db_id}
                              </Badge>
                            )}
                        </div>

                        {project.description && (
                          <p className="line-clamp-1 text-xs text-ink-secondary">
                            {project.description}
                          </p>
                        )}

                        {/* Gates (clinical_form only) + Artifacts + UpdatedAt row */}
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
                          {!freeReport && (
                            <div
                              className="flex flex-wrap items-center gap-1.5"
                              aria-label="Indicadores de gates"
                            >
                              {GATE_DESCRIPTORS.map((gate) => {
                                const found = getGateStatus(
                                  project.gates,
                                  gate.name,
                                );
                                const status: GateStatus =
                                  found?.status ?? "pending";
                                const statusMeta = GATE_STATUS_META[status];
                                return (
                                  <Badge
                                    key={gate.name}
                                    tone={statusMeta.tone}
                                    title={`${gate.title}: ${statusMeta.label}`}
                                    className="px-1.5 py-0.5 text-[11px]"
                                  >
                                    <GateIndicator status={status} />
                                    <span>{gate.shortLabel}</span>
                                  </Badge>
                                );
                              })}
                            </div>
                          )}

                          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-muted">
                            {artifactEntries.length > 0 ? (
                              artifactEntries.map((key) => (
                                <span
                                  key={key}
                                  className="rounded border border-border bg-surface-subtle/70 px-1.5 py-0.5 font-mono text-[10px] text-ink-secondary tabular-nums"
                                >
                                  {ARTIFACT_LABELS[key]} v
                                  {project.latest_artifacts[key]}
                                </span>
                              ))
                            ) : (
                              <span className="italic text-ink-muted">
                                Sem artefatos salvos
                              </span>
                            )}
                          </div>

                          <span className="text-[11px] text-ink-muted tabular-nums">
                            Atualizado em {formatDateTimeBr(project.updated_at)}
                          </span>
                        </div>
                      </div>

                      {/* Right: Action shortcuts */}
                      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-t border-border pt-2.5 lg:border-t-0 lg:pt-0">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() =>
                            onSelectProject(
                              project,
                              freeReport ? "jasper_studio" : "workspace",
                            )
                          }
                          icon={<FolderOpen className="h-3.5 w-3.5" />}
                        >
                          Abrir
                        </Button>

                        {!freeReport && (
                          <Button
                            variant="outline"
                            size="xs"
                            onClick={() =>
                              onSelectProject(project, "form_builder")
                            }
                            icon={<LayoutList className="h-3.5 w-3.5" />}
                            title="Abrir no Form Builder"
                          >
                            Form Builder
                          </Button>
                        )}

                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() => onSelectProject(project, "sql_db")}
                          icon={<Database className="h-3.5 w-3.5" />}
                          title="Abrir em SQL & Banco"
                        >
                          SQL
                        </Button>

                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() =>
                            onSelectProject(project, "jasper_studio")
                          }
                          icon={<FileCode2 className="h-3.5 w-3.5" />}
                          title="Abrir no Jasper Studio"
                        >
                          Jasper
                        </Button>

                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeleteTarget(project)}
                          aria-label={`Excluir projeto ${project.name}`}
                          title="Excluir projeto"
                          className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Create Project Dialog */}
      <CreateProjectDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(created) => {
          setCreateOpen(false);
          onSelectProject(created);
        }}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title="Excluir projeto"
        description="Esta ação remove permanentemente o projeto, revisões de artefatos, gates e pasta do workspace."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => void handleConfirmDelete()}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            >
              Confirmar exclusão
            </Button>
          </>
        }
      >
        {deleteTarget && (
          <div className="space-y-2 text-xs text-ink-secondary">
            <p>
              Tem certeza que deseja excluir o projeto{" "}
              <strong className="text-ink">{deleteTarget.name}</strong>?
            </p>
            <p className="rounded border border-border bg-surface-subtle px-2.5 py-1.5 font-mono text-[11px] text-ink-muted">
              slug: {deleteTarget.slug}
            </p>
          </div>
        )}
      </Dialog>
    </div>
  );
}
