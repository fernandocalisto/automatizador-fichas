import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronDown,
  CloudDownload,
  Code2,
  Columns2,
  Database,
  Download,
  ExternalLink,
  Eye,
  FileText,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import {
  Badge,
  Button,
  Input,
  SearchableSelect,
  Select,
  type SearchableSelectOption,
} from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type {
  DbProfileRead,
  JasperPreviewResponse,
  PreviewMode,
  ProjectKind,
  RepoResourcesStatus,
  ScenarioType,
} from "@/types/studio";
import {
  JASPER_LAYOUT_MODE_OPTIONS,
  PREVIEW_MODE_OPTIONS,
  SCENARIO_OPTIONS,
  type JasperLayoutMode,
} from "./types";

export interface PreviewControlBarProps {
  projectId: string;
  projectSlug: string;
  projectKind?: ProjectKind;
  sourceOrigin?: Record<string, unknown>;
  hasJrxml: boolean;
  scenario: ScenarioType;
  onChangeScenario: (scenario: ScenarioType) => void;
  mode: PreviewMode;
  onChangeMode: (mode: PreviewMode) => void;
  dbProfiles: DbProfileRead[];
  selectedDbProfileId: string;
  onChangeDbProfileId: (profileId: string) => void;
  atendimentoIdInput: string;
  onChangeAtendimentoIdInput: (value: string) => void;
  previewLoading: boolean;
  previewResult: JasperPreviewResponse | null;
  previewError: string | null;
  cacheBuster: number;
  onRefreshPreview: () => void;
  onDownloadJrxml: () => void;
  layoutMode?: JasperLayoutMode;
  onChangeLayoutMode?: (mode: JasperLayoutMode) => void;
  repoStatus?: RepoResourcesStatus | null;
  syncingRepo?: boolean;
  onSyncRepoResources?: () => void;
  onOpenAgentChat?: () => void;
  headerExtraActions?: ReactNode;
}

const LAYOUT_ICONS: Record<JasperLayoutMode, ReactNode> = {
  visual: <Eye className="h-3.5 w-3.5" />,
  split: <Columns2 className="h-3.5 w-3.5" />,
  code: <Code2 className="h-3.5 w-3.5" />,
};

export function LayoutModeSwitcher({
  layoutMode,
  onChangeLayoutMode,
}: {
  layoutMode: JasperLayoutMode;
  onChangeLayoutMode: (mode: JasperLayoutMode) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Modo de visualização do Jasper Studio"
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-subtle p-0.5"
    >
      {JASPER_LAYOUT_MODE_OPTIONS.map((opt) => {
        const active = opt.id === layoutMode;
        return (
          <button
            key={opt.id}
            type="button"
            title={opt.description}
            aria-label={opt.label}
            aria-pressed={active}
            onClick={() => onChangeLayoutMode(opt.id)}
            className={cn(
              "inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors cursor-pointer",
              active
                ? "bg-surface text-ink shadow-xs"
                : "text-ink-muted hover:text-ink",
            )}
          >
            {LAYOUT_ICONS[opt.id]}
            <span>{opt.shortLabel}</span>
          </button>
        );
      })}
    </div>
  );
}

export function RepoResourcesChip({
  repoStatus,
  syncingRepo = false,
  onSyncRepoResources,
}: {
  repoStatus?: RepoResourcesStatus | null;
  syncingRepo?: boolean;
  onSyncRepoResources?: () => void;
}) {
  if (!repoStatus || repoStatus.total <= 0) {
    return null;
  }

  const allResolved = repoStatus.missing_count === 0;
  const tooltipLines = repoStatus.items
    .slice(0, 8)
    .map((item) => `${item.resolved ? "✓" : "✗"} ${item.uri}`)
    .join("\n");

  return (
    <div className="inline-flex items-center gap-1.5" data-testid="repo-resources-chip">
      {allResolved ? (
        <Badge
          tone="success"
          dot
          title={tooltipLines || "Todos os recursos repo: foram resolvidos."}
        >
          repo: {repoStatus.resolved_count} OK
        </Badge>
      ) : (
        <>
          <Badge
            tone="warning"
            dot
            title={
              tooltipLines ||
              `${repoStatus.missing_count} recurso(s) repo: pendente(s) de sincronização.`
            }
          >
            repo: {repoStatus.missing_count} pendente(s)
          </Badge>
          {onSyncRepoResources && (
            <Button
              variant="outline"
              size="xs"
              loading={syncingRepo}
              disabled={syncingRepo}
              icon={<CloudDownload className="h-3.5 w-3.5" />}
              onClick={onSyncRepoResources}
              title={
                repoStatus.can_sync_remote
                  ? "Baixar e compilar automaticamente os recursos repo: do JasperReports Server"
                  : "Tentar sincronizar recursos repo: referenciados no JRXML"
              }
            >
              Sincronizar repo:
            </Button>
          )}
        </>
      )}
    </div>
  );
}

export function PreviewControlBar({
  projectId,
  projectSlug,
  projectKind,
  sourceOrigin,
  hasJrxml,
  scenario,
  onChangeScenario,
  mode,
  onChangeMode,
  dbProfiles,
  selectedDbProfileId,
  onChangeDbProfileId,
  atendimentoIdInput,
  onChangeAtendimentoIdInput,
  previewLoading,
  previewResult,
  previewError,
  cacheBuster,
  onRefreshPreview,
  onDownloadJrxml,
  layoutMode,
  onChangeLayoutMode,
  repoStatus,
  syncingRepo = false,
  onSyncRepoResources,
  onOpenAgentChat,
  headerExtraActions,
}: PreviewControlBarProps) {
  const isFreeReport = projectKind === "free_report";
  const [exportOpen, setExportOpen] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!exportOpen) return;
    const handleOutside = (event: MouseEvent) => {
      if (
        exportMenuRef.current &&
        !exportMenuRef.current.contains(event.target as Node)
      ) {
        setExportOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExportOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [exportOpen]);

  const effectiveProfileId =
    mode === "db_hybrid" || mode === "db_live" || mode === "auto"
      ? selectedDbProfileId || null
      : null;

  const exportBundleUrl = api.getExportBundleUrl(projectId, {
    scenario,
    mode,
    db_profile_id: effectiveProfileId,
  });

  const pdfUrl = api.getPreviewPdfUrl(
    projectId,
    previewResult?.scenario ?? scenario,
    cacheBuster,
  );

  const dbProfileOptions = useMemo<SearchableSelectOption[]>(
    () =>
      dbProfiles.map((profile) => ({
        value: profile.id,
        label: profile.name,
        sublabel: `${profile.host}/${profile.dbname}`,
        badge: profile.environment ?? (profile.is_default ? "Padrão" : undefined),
        keywords: `${profile.name} ${profile.host} ${profile.dbname} ${profile.environment ?? ""}`,
      })),
    [dbProfiles],
  );

  const originLabel = useMemo(() => {
    const provider = String(sourceOrigin?.provider ?? "").toLowerCase();
    if (provider === "jasperserver") return "JasperServer";
    if (provider === "sftp") return "SFTP";
    return null;
  }, [sourceOrigin]);

  const renderExportDropdown = () => (
    <div ref={exportMenuRef} className="relative">
      <Button
        variant="outline"
        size="xs"
        aria-haspopup="menu"
        aria-expanded={exportOpen}
        icon={<Download className="h-3.5 w-3.5" />}
        onClick={() => setExportOpen((prev) => !prev)}
      >
        <span>Exportar</span>
        <ChevronDown className="h-3 w-3 text-ink-muted" />
      </Button>

      {exportOpen && (
        <div
          role="menu"
          aria-label="Opções de exportação"
          className="absolute right-0 z-50 mt-1 w-52 overflow-hidden rounded-lg border border-border-strong bg-surface-elevated p-1 shadow-xl"
        >
          <button
            type="button"
            role="menuitem"
            disabled={!hasJrxml}
            onClick={() => {
              setExportOpen(false);
              onDownloadJrxml();
            }}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-xs text-ink transition-colors hover:bg-surface-subtle cursor-pointer",
              !hasJrxml && "pointer-events-none opacity-50",
            )}
          >
            <Download className="h-3.5 w-3.5 text-ink-muted" />
            <span>Baixar .jrxml</span>
          </button>

          <a
            role="menuitem"
            href={pdfUrl}
            target="_blank"
            rel="noreferrer"
            aria-disabled={!previewResult}
            onClick={() => setExportOpen(false)}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-xs text-ink transition-colors hover:bg-surface-subtle",
              !previewResult && "pointer-events-none opacity-50",
            )}
          >
            <ExternalLink className="h-3.5 w-3.5 text-ink-muted" />
            <span>Abrir .pdf</span>
          </a>

          <a
            role="menuitem"
            href={exportBundleUrl}
            download={`${projectSlug}_entrega_salutem.zip`}
            aria-disabled={!hasJrxml}
            onClick={() => setExportOpen(false)}
            className={cn(
              "flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-xs font-medium text-accent transition-colors hover:bg-accent-soft/60",
              !hasJrxml && "pointer-events-none opacity-50",
            )}
          >
            <Archive className="h-3.5 w-3.5" />
            <span>Pacote .zip</span>
          </a>
        </div>
      )}
    </div>
  );

  if (isFreeReport) {
    return (
      <div
        data-testid="preview-control-bar-free-report"
        className="flex shrink-0 flex-col gap-1.5 border-b border-border bg-surface px-3 py-1.5"
      >
        {/* Barra única contextual para Relatório Livre */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {layoutMode && onChangeLayoutMode && (
              <LayoutModeSwitcher
                layoutMode={layoutMode}
                onChangeLayoutMode={onChangeLayoutMode}
              />
            )}

            <Select
              aria-label="Modo de preview"
              value={mode}
              onChange={(e) => onChangeMode(e.target.value as PreviewMode)}
              className="h-7 w-40 text-xs"
            >
              {PREVIEW_MODE_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label}
                </option>
              ))}
            </Select>

            {(mode === "db_live" || mode === "db_hybrid") && (
              <div className="flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5 shrink-0 text-blueprint" />
                <SearchableSelect
                  ariaLabel="Perfil PostgreSQL"
                  value={selectedDbProfileId}
                  onChange={onChangeDbProfileId}
                  options={dbProfileOptions}
                  placeholder={
                    dbProfiles.length === 0
                      ? "Nenhum perfil cadastrado"
                      : "Selecionar banco PostgreSQL..."
                  }
                  searchPlaceholder="Buscar por nome, host, banco ou ambiente..."
                  emptyLabel="Nenhum banco encontrado."
                  size="sm"
                  className="w-56"
                />
              </div>
            )}

            {originLabel && (
              <Badge tone="neutral" className="text-[10px]">
                {originLabel}
              </Badge>
            )}

            {previewResult && (
              <Badge tone="neutral" className="tabular-nums">
                <FileText className="h-3 w-3" />
                {previewResult.page_count}{" "}
                {previewResult.page_count === 1 ? "página" : "páginas"}
              </Badge>
            )}

            <RepoResourcesChip
              repoStatus={repoStatus}
              syncingRepo={syncingRepo}
              onSyncRepoResources={onSyncRepoResources}
            />

            {previewResult?.fallback_reason && (
              <Badge
                tone="warning"
                title={previewResult.fallback_reason}
                className="max-w-full whitespace-normal break-words text-left leading-snug"
              >
                Fallback: {previewResult.fallback_reason}
              </Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              variant="primary"
              size="xs"
              loading={previewLoading}
              disabled={!hasJrxml}
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={onRefreshPreview}
            >
              {previewResult ? "Atualizar preview" : "Gerar Preview"}
            </Button>

            {onOpenAgentChat && (
              <Button
                variant="blueprint"
                size="xs"
                icon={<Sparkles className="h-3.5 w-3.5" />}
                onClick={onOpenAgentChat}
              >
                Pedir ajuste à IA
              </Button>
            )}

            {renderExportDropdown()}

            {headerExtraActions}
          </div>
        </div>

        {/* Erro de geração de preview */}
        {previewError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{previewError}</span>
          </div>
        )}
      </div>
    );
  }

  // Barra única compacta para Ficha Clínica (maximiza área útil do PDF)
  return (
    <div
      data-testid="preview-control-bar-clinical"
      className="flex shrink-0 flex-col gap-1.5 border-b border-border bg-surface px-3 py-1.5"
    >
      {/* Linha única principal: Cenários compactos + Modo + Layout + Status + Ações + Exportar */}
      <div className="flex flex-wrap items-center justify-between gap-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Seletor compacto de cenários fictícios */}
          <div
            role="group"
            aria-label="Cenário fictício de preview"
            className="inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-subtle p-0.5"
          >
            {SCENARIO_OPTIONS.map((opt) => {
              const active = opt.id === scenario;
              return (
                <button
                  key={opt.id}
                  type="button"
                  aria-label={opt.label}
                  title={`${opt.label} — ${opt.description}`}
                  aria-pressed={active}
                  onClick={() => onChangeScenario(opt.id)}
                  className={cn(
                    "rounded px-2 py-0.5 text-xs font-medium transition-colors cursor-pointer",
                    active
                      ? "bg-surface text-ink shadow-xs"
                      : "text-ink-muted hover:text-ink",
                  )}
                >
                  {opt.shortLabel}
                </button>
              );
            })}
          </div>

          {/* Seletor de modo */}
          <Select
            aria-label="Modo de preview"
            value={mode}
            onChange={(e) => onChangeMode(e.target.value as PreviewMode)}
            className="h-7 w-40 text-xs"
          >
            {PREVIEW_MODE_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </Select>

          {layoutMode && onChangeLayoutMode && (
            <LayoutModeSwitcher
              layoutMode={layoutMode}
              onChangeLayoutMode={onChangeLayoutMode}
            />
          )}

          {/* Badges compactos de status do preview */}
          {previewResult && (
            <>
              {previewResult.single_page_ok ? (
                <Badge tone="success" dot>
                  <CheckCircle2 className="h-3 w-3" />1 página OK
                </Badge>
              ) : (
                <Badge tone="danger" dot>
                  <AlertTriangle className="h-3 w-3" />
                  Estouro de página ({previewResult.page_count} páginas)
                </Badge>
              )}

              <Badge
                tone={
                  previewResult.effective_mode === "db_hybrid" ||
                  previewResult.effective_mode === "db_live"
                    ? "blueprint"
                    : "neutral"
                }
              >
                Modo:{" "}
                {previewResult.effective_mode === "db_live"
                  ? "Live (Banco Real)"
                  : previewResult.effective_mode === "db_hybrid"
                    ? "Banco Híbrido (CTE)"
                    : "Offline (Mock)"}
              </Badge>

              {previewResult.fallback_reason && (
                <Badge
                  tone="warning"
                  title={previewResult.fallback_reason}
                  className="max-w-xs truncate text-left"
                >
                  Fallback: {previewResult.fallback_reason}
                </Badge>
              )}
            </>
          )}

          <RepoResourcesChip
            repoStatus={repoStatus}
            syncingRepo={syncingRepo}
            onSyncRepoResources={onSyncRepoResources}
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {layoutMode === "visual" && onOpenAgentChat && (
            <Button
              variant="blueprint"
              size="xs"
              icon={<Sparkles className="h-3.5 w-3.5" />}
              onClick={onOpenAgentChat}
            >
              Pedir ajuste à IA
            </Button>
          )}
          <Button
            variant="primary"
            size="xs"
            loading={previewLoading}
            disabled={!hasJrxml}
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={onRefreshPreview}
          >
            Atualizar preview
          </Button>
          {renderExportDropdown()}
          {headerExtraActions}
        </div>
      </div>

      {/* Linha condicional compacta para Banco Híbrido (CTE) ou Live (Banco Real) */}
      {(mode === "db_hybrid" || mode === "db_live") && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-blueprint/25 bg-blueprint-soft/45 px-2.5 py-1">
          <div className="flex items-center gap-1.5 text-xs font-medium text-blueprint">
            <Database className="h-3.5 w-3.5" />
            <span>PostgreSQL:</span>
          </div>

          <Select
            aria-label="Perfil PostgreSQL"
            value={selectedDbProfileId}
            onChange={(e) => onChangeDbProfileId(e.target.value)}
            className="h-7 w-52 text-xs"
          >
            {dbProfiles.length === 0 ? (
              <option value="">Nenhum perfil cadastrado</option>
            ) : (
              dbProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} ({profile.host}/{profile.dbname})
                </option>
              ))
            )}
          </Select>

          {mode === "db_hybrid" && (
            <Input
              type="number"
              min={1}
              aria-label="atendimento_id (opcional)"
              placeholder="atendimento_id (opcional)"
              value={atendimentoIdInput}
              onChange={(e) => onChangeAtendimentoIdInput(e.target.value)}
              className="h-7 w-44 text-xs font-mono tabular-nums"
            />
          )}

          {mode === "db_live" && (
            <Badge tone="blueprint" className="text-[10px]">
              Query original · sem CTE mock
            </Badge>
          )}
        </div>
      )}

      {/* Erro de geração de preview */}
      {previewError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft px-2.5 py-1.5 text-xs text-danger"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span className="break-words">{previewError}</span>
        </div>
      )}
    </div>
  );
}
