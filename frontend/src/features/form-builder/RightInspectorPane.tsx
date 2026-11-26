import { useState } from "react";
import {
  AlertCircle,
  CaseUpper,
  Check,
  Code2,
  Copy,
  ExternalLink,
  FileText,
  Sparkles,
} from "lucide-react";
import {
  Badge,
  Button,
  CodeEditor,
  EmptyState,
  Tabs,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";

export type InspectorTab = "json" | "pdf";

export interface RightInspectorPaneProps {
  projectId: string;
  hasPdf: boolean;
  jsonText: string;
  jsonError: string | null;
  onJsonTextChange: (nextText: string) => void;
  onFormatJson: () => void;
  onApplyUppercaseLocal: () => void;
}

export function RightInspectorPane({
  projectId,
  hasPdf,
  jsonText,
  jsonError,
  onJsonTextChange,
  onFormatJson,
  onApplyUppercaseLocal,
}: RightInspectorPaneProps) {
  const { pushToast } = useToast();
  const [activeTab, setActiveTab] = useState<InspectorTab>("json");
  const [copied, setCopied] = useState(false);

  const effectiveTab: InspectorTab =
    activeTab === "pdf" && !hasPdf ? "json" : activeTab;

  const pdfUrl = api.getProjectPdfUrl(projectId);

  const handleCopyJson = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(jsonText);
      }
      setCopied(true);
      pushToast({
        tone: "success",
        title: "JSON copiado",
        description: "Conteúdo copiado para a área de transferência.",
      });
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      pushToast({
        tone: "error",
        title: "Não foi possível copiar o JSON",
      });
    }
  };

  return (
    <div className="flex h-full flex-col bg-surface">
      {/* Inspector Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-subtle/60 px-3 py-2">
        <Tabs<InspectorTab>
          value={effectiveTab}
          onChange={setActiveTab}
          options={[
            {
              id: "json",
              label: "JSON (Monaco)",
              icon: <Code2 className="h-3.5 w-3.5" />,
            },
            {
              id: "pdf",
              label: "PDF Original",
              icon: <FileText className="h-3.5 w-3.5" />,
              disabled: !hasPdf,
            },
          ]}
        />

        {effectiveTab === "json" ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={jsonError ? "danger" : "success"} dot>
              {jsonError ? "JSON inválido" : "JSON válido"}
            </Badge>
            <Button
              variant="outline"
              size="xs"
              icon={<Sparkles className="h-3.5 w-3.5" />}
              disabled={Boolean(jsonError)}
              onClick={onFormatJson}
              title="Formatar JSON com indentação de 2 espaços"
            >
              Formatar
            </Button>
            <Button
              variant="outline"
              size="xs"
              icon={<CaseUpper className="h-3.5 w-3.5" />}
              disabled={Boolean(jsonError)}
              onClick={onApplyUppercaseLocal}
              title="Converter nomes e labels para UPPERCASE localmente"
            >
              Converter UPPERCASE
            </Button>
            <Button
              variant="outline"
              size="xs"
              icon={
                copied ? (
                  <Check className="h-3.5 w-3.5 text-success" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )
              }
              onClick={() => void handleCopyJson()}
            >
              {copied ? "Copiado" : "Copiar"}
            </Button>
          </div>
        ) : (
          <a
            href={pdfUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-xs font-medium text-ink-secondary hover:border-border-strong hover:text-ink transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            <span>Abrir em nova aba</span>
          </a>
        )}
      </div>

      {/* Body */}
      {effectiveTab === "json" ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {jsonError && (
            <div
              role="alert"
              className="flex items-start gap-2 border-b border-danger/35 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">
                  JSON temporariamente inválido (Form Builder preservado)
                </p>
                <p className="mt-0.5 font-mono text-[11px] break-words">
                  {jsonError}
                </p>
              </div>
            </div>
          )}

          <div className="min-h-0 flex-1">
            <CodeEditor
              language="json"
              value={jsonText}
              onChange={onJsonTextChange}
              ariaLabel="Editor JSON da ficha clínica"
            />
          </div>
        </div>
      ) : hasPdf ? (
        <div className="min-h-0 flex-1 bg-surface-subtle">
          <iframe
            src={pdfUrl}
            title="PDF original da ficha clínica"
            className="h-full w-full border-0"
          />
        </div>
      ) : (
        <div className="p-6">
          <EmptyState
            icon={<FileText className="h-5 w-5" />}
            title="Nenhum PDF anexado"
            description="Este projeto ainda não possui um arquivo source.pdf enviado para conferência lado a lado."
          />
        </div>
      )}
    </div>
  );
}
