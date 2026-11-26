import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Code2,
  Copy,
  Download,
  FileCode2,
  FileDiff,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  Badge,
  Button,
  CodeEditor,
  EmptyState,
  Tabs,
  type TabOption,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  ArtifactRevisionRead,
  SqlValidateResponse,
} from "@/types/studio";
import { SqlDiffViewer } from "./SqlDiffViewer";
import {
  SqlRegenerateControls,
  type SqlSelectRegenerateOptions,
} from "./SqlRegenerateControls";

export type SqlTabId = "sql_insert" | "sql_select";

export interface SqlEditorPaneProps {
  projectSlug: string;
  loading: boolean;
  activeTab: SqlTabId;
  onTabChange: (tab: SqlTabId) => void;
  insertArtifact: ArtifactRevisionRead | null;
  selectArtifact: ArtifactRevisionRead | null;
  insertDraft: string;
  selectDraft: string;
  onInsertChange: (next: string) => void;
  onSelectChange: (next: string) => void;
  selectOptions: SqlSelectRegenerateOptions;
  onSelectOptionsChange: (next: SqlSelectRegenerateOptions) => void;
  regenerating: boolean;
  onRegenerateSql: () => void;
  validating: boolean;
  validationResult: SqlValidateResponse | null;
  onValidateSql: () => void;
  saving: boolean;
  onSaveRevision: () => void;
  onRevertCurrent: () => void;
  onCopySql: (text: string) => Promise<void> | void;
}

function downloadSqlFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/sql;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function SqlEditorPane({
  projectSlug,
  loading,
  activeTab,
  onTabChange,
  insertArtifact,
  selectArtifact,
  insertDraft,
  selectDraft,
  onInsertChange,
  onSelectChange,
  selectOptions,
  onSelectOptionsChange,
  regenerating,
  onRegenerateSql,
  validating,
  validationResult,
  onValidateSql,
  saving,
  onSaveRevision,
  onRevertCurrent,
  onCopySql,
}: SqlEditorPaneProps) {
  const [showRegeneratePanel, setShowRegeneratePanel] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [copied, setCopied] = useState(false);

  const insertDirty =
    insertArtifact !== null
      ? insertDraft !== insertArtifact.content
      : insertDraft.trim().length > 0;
  const selectDirty =
    selectArtifact !== null
      ? selectDraft !== selectArtifact.content
      : selectDraft.trim().length > 0;

  const activeArtifact =
    activeTab === "sql_insert" ? insertArtifact : selectArtifact;
  const activeDraft = activeTab === "sql_insert" ? insertDraft : selectDraft;
  const activeDirty = activeTab === "sql_insert" ? insertDirty : selectDirty;
  const activeLabel =
    activeTab === "sql_insert"
      ? "SQL INSERT (DO $$)"
      : "SQL SELECT Jasper ($P{id})";

  const hasAnySql =
    insertArtifact !== null ||
    selectArtifact !== null ||
    insertDraft.trim().length > 0 ||
    selectDraft.trim().length > 0;

  const tabOptions: TabOption<SqlTabId>[] = [
    {
      id: "sql_insert",
      label: "SQL INSERT (DO $$)",
      icon: <Code2 className="h-3.5 w-3.5" />,
      badge: insertArtifact ? `v${insertArtifact.version_num}` : undefined,
    },
    {
      id: "sql_select",
      label: "SQL SELECT Jasper ($P{id})",
      icon: <FileCode2 className="h-3.5 w-3.5" />,
      badge: selectArtifact ? `v${selectArtifact.version_num}` : undefined,
    },
  ];

  const handleCopy = async () => {
    if (!activeDraft) return;
    await onCopySql(activeDraft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const handleDownload = () => {
    if (!activeDraft) return;
    const suffix = activeTab === "sql_insert" ? "insert_template" : "select_jasper";
    downloadSqlFile(`${projectSlug}_${suffix}.sql`, activeDraft);
  };

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-surface p-6 text-xs text-ink-muted">
        Carregando artefatos SQL do projeto...
      </div>
    );
  }

  if (!hasAnySql) {
    return (
      <div className="flex h-full flex-col overflow-y-auto bg-surface p-5">
        <EmptyState
          icon={<Sparkles className="h-5 w-5 text-accent" />}
          title="Nenhum script SQL gerado ainda"
          description="Gere automaticamente os scripts SQL INSERT (DO $$) e SQL SELECT Jasper ($P{id}) a partir da revisão mais recente do JSON clínico deste projeto."
          action={
            <Button
              variant="primary"
              size="md"
              loading={regenerating}
              onClick={onRegenerateSql}
              icon={<Sparkles className="h-4 w-4" />}
            >
              Gerar SQL a partir do JSON
            </Button>
          }
          className="mb-4"
        />

        <div className="mx-auto w-full max-w-2xl">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
            Opções do SELECT Jasper
          </p>
          <SqlRegenerateControls
            options={selectOptions}
            onChange={onSelectOptionsChange}
            onRegenerate={onRegenerateSql}
            loading={regenerating}
            actionLabel="Gerar SQL a partir do JSON"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-surface">
      {/* Top tab header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <Tabs
            options={tabOptions}
            value={activeTab}
            onChange={(next) => {
              onTabChange(next);
            }}
          />
          {activeDirty && (
            <Badge tone="warning" dot>
              Modificado
            </Badge>
          )}
          {!activeDirty && activeArtifact && (
            <Badge tone="neutral" className="tabular-nums">
              Revisão v{activeArtifact.version_num} sincronizada
            </Badge>
          )}
        </div>

        <Button
          size="xs"
          variant={showRegeneratePanel ? "secondary" : "outline"}
          onClick={() => setShowRegeneratePanel((prev) => !prev)}
          icon={<SlidersHorizontal className="h-3.5 w-3.5" />}
          aria-expanded={showRegeneratePanel}
        >
          Regenerar do JSON
        </Button>
      </div>

      {/* Collapsible SQL Regenerate Options */}
      {showRegeneratePanel && (
        <div className="border-b border-border bg-surface px-3 py-2.5">
          <SqlRegenerateControls
            options={selectOptions}
            onChange={onSelectOptionsChange}
            onRegenerate={onRegenerateSql}
            loading={regenerating}
          />
        </div>
      )}

      {/* Action toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-subtle/50 px-3 py-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="xs"
            variant="outline"
            loading={validating}
            disabled={!activeDraft.trim()}
            onClick={onValidateSql}
            icon={<ShieldCheck className="h-3.5 w-3.5 text-blueprint" />}
          >
            Validar sintaxe
          </Button>

          <Button
            size="xs"
            variant={activeDirty ? "primary" : "outline"}
            loading={saving}
            disabled={!activeDraft.trim() || !activeDirty}
            onClick={onSaveRevision}
            icon={<Save className="h-3.5 w-3.5" />}
          >
            Salvar revisão
          </Button>

          <Button
            size="xs"
            variant={showDiff ? "blueprint" : "outline"}
            disabled={!activeArtifact && !activeDraft}
            onClick={() => setShowDiff((prev) => !prev)}
            icon={<FileDiff className="h-3.5 w-3.5" />}
          >
            Ver diff com revisão salva
          </Button>
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            size="xs"
            variant="ghost"
            disabled={!activeDraft}
            onClick={handleCopy}
            icon={
              copied ? (
                <Check className="h-3.5 w-3.5 text-success" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )
            }
          >
            {copied ? "Copiado" : "Copiar SQL"}
          </Button>

          <Button
            size="xs"
            variant="ghost"
            disabled={!activeDraft}
            onClick={handleDownload}
            icon={<Download className="h-3.5 w-3.5" />}
          >
            Baixar .sql
          </Button>
        </div>
      </div>

      {/* Inline syntax validation banner */}
      {validationResult && (
        <div
          role="status"
          className={cn(
            "flex flex-col gap-1.5 border-b px-3 py-2 text-xs",
            validationResult.valid
              ? "border-success/30 bg-success-soft/70 text-ink"
              : "border-danger/30 bg-danger-soft/80 text-ink",
          )}
        >
          <div className="flex items-start gap-2">
            {validationResult.valid ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            ) : (
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            )}
            <div className="min-w-0 flex-1">
              <span className="font-semibold">
                {validationResult.valid
                  ? "Sintaxe PostgreSQL válida"
                  : "Erro de sintaxe PostgreSQL"}
              </span>
              <span className="ml-1.5 text-ink-secondary">
                — {validationResult.message}
              </span>
            </div>
          </div>

          {validationResult.unknown_field_types.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pl-6 text-[11px] text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span className="font-medium">
                Tipos de campo desconhecidos detectados:
              </span>
              {validationResult.unknown_field_types.map((ft) => (
                <Badge key={ft} tone="warning" className="font-mono text-[10px]">
                  {ft}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Main Editor or Diff Viewer */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {showDiff ? (
          <SqlDiffViewer
            savedContent={activeArtifact?.content ?? ""}
            currentContent={activeDraft}
            savedVersion={activeArtifact?.version_num ?? null}
            artifactLabel={activeLabel}
            onClose={() => setShowDiff(false)}
            onRevertToSaved={
              activeDirty && activeArtifact
                ? () => {
                    onRevertCurrent();
                    setShowDiff(false);
                  }
                : undefined
            }
          />
        ) : (
          <CodeEditor
            key={activeTab}
            language="sql"
            value={activeDraft}
            onChange={(next) =>
              activeTab === "sql_insert"
                ? onInsertChange(next)
                : onSelectChange(next)
            }
            ariaLabel={`Editor ${activeLabel}`}
          />
        )}
      </div>
    </div>
  );
}
