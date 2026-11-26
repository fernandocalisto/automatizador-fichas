import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type {
  DbProfileRead,
  JasperPreviewResponse,
  PreviewMode,
  ScenarioType,
} from "@/types/studio";
import { PREVIEW_MODE_OPTIONS, SCENARIO_OPTIONS } from "./types";

export interface PreviewControlBarProps {
  projectId: string;
  projectSlug: string;
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
}

export function PreviewControlBar({
  projectId,
  projectSlug,
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
}: PreviewControlBarProps) {
  const effectiveProfileId =
    mode === "db_hybrid" || mode === "auto"
      ? selectedDbProfileId || null
      : null;

  const exportBundleUrl = api.getExportBundleUrl(projectId, {
    scenario,
    mode,
    db_profile_id: effectiveProfileId,
  });

  const pdfUrl = api.getPreviewPdfUrl(projectId, scenario, cacheBuster);

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-border bg-surface px-3 py-2">
      {/* Linha 1: Cenários fictícios + Modo + Botão Atualizar preview */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* Seletor de cenários fictícios */}
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
                  title={opt.description}
                  aria-pressed={active}
                  onClick={() => onChangeScenario(opt.id)}
                  className={cn(
                    "rounded px-2 py-1 text-xs font-medium transition-colors cursor-pointer",
                    active
                      ? "bg-surface text-ink shadow-xs"
                      : "text-ink-muted hover:text-ink",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>

          {/* Seletor de modo */}
          <Select
            aria-label="Modo de preview"
            value={mode}
            onChange={(e) => onChangeMode(e.target.value as PreviewMode)}
            className="h-8 w-44 text-xs"
          >
            {PREVIEW_MODE_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </Select>
        </div>

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
      </div>

      {/* Linha condicional para Banco Híbrido (CTE): perfil PostgreSQL + atendimento_id opcional */}
      {mode === "db_hybrid" && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-blueprint/25 bg-blueprint-soft/45 px-2.5 py-1.5">
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

          <Input
            type="number"
            min={1}
            aria-label="atendimento_id (opcional)"
            placeholder="atendimento_id (opcional)"
            value={atendimentoIdInput}
            onChange={(e) => onChangeAtendimentoIdInput(e.target.value)}
            className="h-7 w-44 text-xs font-mono tabular-nums"
          />
        </div>
      )}

      {/* Linha 2: Badges de resultado + Exportação Final */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
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
                  previewResult.effective_mode === "db_hybrid"
                    ? "blueprint"
                    : "neutral"
                }
              >
                Modo:{" "}
                {previewResult.effective_mode === "db_hybrid"
                  ? "Banco Híbrido (CTE)"
                  : "Offline (Mock)"}
              </Badge>

              {previewResult.fallback_reason && (
                <Badge
                  tone="warning"
                  title={previewResult.fallback_reason}
                  className="max-w-xs truncate"
                >
                  Fallback: {previewResult.fallback_reason}
                </Badge>
              )}
            </>
          )}
        </div>

        {/* Barra de Exportação Final */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="outline"
            size="xs"
            disabled={!hasJrxml}
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={onDownloadJrxml}
          >
            Baixar .jrxml
          </Button>

          <a
            href={pdfUrl}
            target="_blank"
            rel="noreferrer"
            aria-disabled={!previewResult}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded border border-border bg-surface px-2 text-xs font-medium text-ink transition-colors hover:border-border-strong hover:bg-surface-subtle/60",
              !previewResult && "pointer-events-none opacity-50",
            )}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Abrir .pdf
          </a>

          <a
            href={exportBundleUrl}
            download={`${projectSlug}_entrega_salutem.zip`}
            aria-disabled={!hasJrxml}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded border border-accent bg-accent px-2.5 text-xs font-semibold text-accent-ink shadow-xs transition-colors hover:bg-accent-hover",
              !hasJrxml && "pointer-events-none opacity-50",
            )}
          >
            <Archive className="h-3.5 w-3.5" />
            Baixar pacote de entrega (.zip)
          </a>
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
