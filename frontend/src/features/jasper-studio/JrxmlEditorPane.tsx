import { useState } from "react";
import {
  FileCode2,
  Hammer,
  Save,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  Badge,
  Button,
  CodeEditor,
  Dialog,
  EmptyState,
  FieldLabel,
  Select,
  Switch,
} from "@/components/ui";
import type {
  ClinicalOrientation,
  JasperCompileResponse,
  JrxmlLintReport,
} from "@/types/studio";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { detectJrxmlOrientation, getPageDimensions } from "./utils";

export interface JrxmlEditorPaneProps {
  loading: boolean;
  hasJrxml: boolean;
  jrxmlContent: string;
  versionNum: number | null;
  dirty: boolean;
  scaffolding: boolean;
  linting: boolean;
  compiling: boolean;
  saving: boolean;
  liveReload: boolean;
  onToggleLiveReload: (enabled: boolean) => void;
  onChangeJrxml: (next: string) => void;
  onScaffold: (orientation: ClinicalOrientation) => Promise<void>;
  onLint: () => Promise<void>;
  onCompile: () => Promise<void>;
  onSave: () => Promise<void>;
  lintReport: JrxmlLintReport | null;
  compileResult: JasperCompileResponse | null;
  compileError: string | null;
  diagnosticsOpen: boolean;
  onToggleDiagnostics: () => void;
  selectedLine: number | null;
  onSelectLine: (line: number) => void;
}

export function JrxmlEditorPane({
  loading,
  hasJrxml,
  jrxmlContent,
  versionNum,
  dirty,
  scaffolding,
  linting,
  compiling,
  saving,
  liveReload,
  onToggleLiveReload,
  onChangeJrxml,
  onScaffold,
  onLint,
  onCompile,
  onSave,
  lintReport,
  compileResult,
  compileError,
  diagnosticsOpen,
  onToggleDiagnostics,
  selectedLine,
  onSelectLine,
}: JrxmlEditorPaneProps) {
  const [emptyOrientation, setEmptyOrientation] =
    useState<ClinicalOrientation>("RETRATO");
  const [scaffoldDialogOpen, setScaffoldDialogOpen] = useState(false);
  const [dialogOrientation, setDialogOrientation] =
    useState<ClinicalOrientation>("RETRATO");

  const detectedOrientation = detectJrxmlOrientation(jrxmlContent);
  const pageDims = getPageDimensions(detectedOrientation);

  const openScaffoldDialog = () => {
    setDialogOrientation(detectedOrientation);
    setScaffoldDialogOpen(true);
  };

  const handleConfirmScaffold = async () => {
    setScaffoldDialogOpen(false);
    await onScaffold(dialogOrientation);
  };

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-surface p-6 text-xs text-ink-muted">
        Carregando revisão atual do artefato .jrxml...
      </div>
    );
  }

  if (!hasJrxml) {
    return (
      <div className="flex h-full flex-col justify-center bg-canvas/50 p-6">
        <EmptyState
          icon={<FileCode2 className="h-5 w-5 text-accent" />}
          title="Nenhum arquivo .jrxml encontrado neste projeto"
          description="Gere o scaffold oficial do Salutem com cabeçalho, dados do paciente, rodapé e banda <detail> já configurados para A4."
          action={
            <div className="flex flex-col items-center gap-3">
              <div className="w-56 text-left">
                <FieldLabel htmlFor="scaffold-empty-orientation">
                  Orientação da folha A4
                </FieldLabel>
                <Select
                  id="scaffold-empty-orientation"
                  aria-label="Orientação do scaffold"
                  value={emptyOrientation}
                  onChange={(e) =>
                    setEmptyOrientation(e.target.value as ClinicalOrientation)
                  }
                >
                  <option value="RETRATO">Retrato (595 × 842 pt)</option>
                  <option value="PAISAGEM">Paisagem (842 × 595 pt)</option>
                </Select>
              </div>

              <Button
                variant="primary"
                size="md"
                loading={scaffolding}
                icon={<Sparkles className="h-4 w-4" />}
                onClick={() => void onScaffold(emptyOrientation)}
              >
                Gerar scaffold base (.jrxml)
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      {/* Toolbar superior do editor XML */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-subtle/60 px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="mr-1 flex items-center gap-1.5">
            <FileCode2 className="h-4 w-4 text-accent" />
            <span className="text-xs font-semibold text-ink">Editor JRXML</span>
          </div>

          {versionNum !== null && (
            <Badge tone="neutral" className="font-mono tabular-nums">
              v{versionNum}
            </Badge>
          )}

          <Badge tone="blueprint" className="tabular-nums">
            {detectedOrientation === "PAISAGEM" ? "Paisagem" : "Retrato"}{" "}
            {pageDims.width}×{pageDims.height}
          </Badge>

          {dirty && (
            <Badge tone="warning" dot>
              Alterações não salvas
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="outline"
            size="xs"
            loading={scaffolding}
            icon={<Sparkles className="h-3.5 w-3.5" />}
            onClick={openScaffoldDialog}
          >
            Scaffold Base
          </Button>

          <Button
            variant="outline"
            size="xs"
            loading={linting}
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            onClick={() => void onLint()}
          >
            Auditar
          </Button>

          <Button
            variant="blueprint"
            size="xs"
            loading={compiling}
            icon={<Hammer className="h-3.5 w-3.5" />}
            onClick={() => void onCompile()}
          >
            Compilar (.jasper)
          </Button>

          <Button
            variant="primary"
            size="xs"
            loading={saving}
            icon={<Save className="h-3.5 w-3.5" />}
            onClick={() => void onSave()}
          >
            Salvar revisão
          </Button>

          <div className="ml-1 border-l border-border pl-2">
            <Switch
              id="jasper-live-reload-switch"
              checked={liveReload}
              onChange={onToggleLiveReload}
              label="Live-reload"
            />
          </div>
        </div>
      </div>

      {/* Editor Monaco / XML */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <CodeEditor
          language="xml"
          value={jrxmlContent}
          onChange={onChangeJrxml}
          revealLine={selectedLine}
          ariaLabel="Editor XML JRXML"
        />
      </div>

      {/* Painel inferior colapsável de diagnósticos */}
      <DiagnosticsPanel
        expanded={diagnosticsOpen}
        onToggleExpanded={onToggleDiagnostics}
        lintReport={lintReport}
        compileResult={compileResult}
        compileError={compileError}
        selectedLine={selectedLine}
        onJumpToLine={onSelectLine}
      />

      {/* Diálogo de confirmação para regerar Scaffold Base */}
      <Dialog
        open={scaffoldDialogOpen}
        onClose={() => setScaffoldDialogOpen(false)}
        title="Gerar novo Scaffold Base (.jrxml)"
        description="A geração do scaffold cria uma nova revisão .jrxml baseada no JSON clínico e substitui o conteúdo atual no editor."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setScaffoldDialogOpen(false)}
            >
              Cancelar
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={scaffolding}
              icon={<Sparkles className="h-3.5 w-3.5" />}
              onClick={() => void handleConfirmScaffold()}
            >
              Confirmar e gerar scaffold
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="rounded-md border border-warning/35 bg-warning-soft/60 px-3 py-2 text-xs text-warning">
            Este projeto já possui um arquivo <code>.jrxml</code>. A versão
            anterior permanecerá salva no histórico de revisões, mas o conteúdo
            atual do editor será substituído.
          </div>

          <div>
            <FieldLabel htmlFor="scaffold-dialog-orientation">
              Orientação da página A4
            </FieldLabel>
            <Select
              id="scaffold-dialog-orientation"
              value={dialogOrientation}
              onChange={(e) =>
                setDialogOrientation(e.target.value as ClinicalOrientation)
              }
            >
              <option value="RETRATO">Retrato (595 × 842 pt)</option>
              <option value="PAISAGEM">Paisagem (842 × 595 pt)</option>
            </Select>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
