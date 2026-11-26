import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Terminal,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  JasperCompileResponse,
  JrxmlLintIssue,
  JrxmlLintReport,
} from "@/types/studio";
import { extractDaemonError } from "./utils";

export interface DiagnosticsPanelProps {
  expanded: boolean;
  onToggleExpanded: () => void;
  lintReport: JrxmlLintReport | null;
  compileResult: JasperCompileResponse | null;
  compileError: string | null;
  selectedLine: number | null;
  onJumpToLine: (line: number) => void;
}

export function DiagnosticsPanel({
  expanded,
  onToggleExpanded,
  lintReport,
  compileResult,
  compileError,
  selectedLine,
  onJumpToLine,
}: DiagnosticsPanelProps) {
  const errors: JrxmlLintIssue[] = lintReport?.errors ?? [];
  const warnings: JrxmlLintIssue[] = lintReport?.warnings ?? [];
  const daemonError =
    compileError ||
    (compileResult && !compileResult.ok
      ? extractDaemonError(compileResult.daemon) ||
        "A compilação JasperReports falhou sem mensagem detalhada."
      : null);

  const totalErrors = errors.length + (daemonError ? 1 : 0);
  const totalWarnings = warnings.length;
  const compileSucceeded = Boolean(compileResult?.ok && !daemonError);

  const allIssues: Array<{ issue: JrxmlLintIssue; kind: "error" | "warning" }> =
    [
      ...errors.map((issue) => ({ issue, kind: "error" as const })),
      ...warnings.map((issue) => ({ issue, kind: "warning" as const })),
    ];

  return (
    <section
      aria-label="Diagnósticos do JRXML e Compilador JVM"
      className="flex shrink-0 flex-col border-t border-border bg-surface"
    >
      <button
        type="button"
        onClick={onToggleExpanded}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 bg-surface-subtle/70 px-3 py-1.5 text-left transition-colors hover:bg-surface-subtle cursor-pointer"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-ink-muted" />
          <span className="text-xs font-semibold text-ink">
            Diagnósticos (Linter + Compilador JVM)
          </span>

          {totalErrors > 0 ? (
            <Badge tone="danger" dot>
              {totalErrors} {totalErrors === 1 ? "erro" : "erros"}
            </Badge>
          ) : lintReport || compileResult ? (
            <Badge tone="success" dot>
              0 erros
            </Badge>
          ) : null}

          {totalWarnings > 0 && (
            <Badge tone="warning" dot>
              {totalWarnings} {totalWarnings === 1 ? "aviso" : "avisos"}
            </Badge>
          )}

          {compileSucceeded && (
            <Badge tone="blueprint">
              <Cpu className="h-3 w-3" />
              .jasper compilado
            </Badge>
          )}

          {selectedLine !== null && (
            <span className="text-[11px] font-mono text-ink-muted tabular-nums">
              Linha ativa: {selectedLine}
            </span>
          )}
        </div>

        <span className="text-ink-muted">
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronUp className="h-4 w-4" />
          )}
        </span>
      </button>

      {expanded && (
        <div className="max-h-52 overflow-y-auto border-t border-border bg-surface px-3 py-2 text-xs">
          {daemonError && (
            <div
              role="alert"
              className="mb-2 rounded-md border border-danger/35 bg-danger-soft/70 p-2.5 text-danger"
            >
              <div className="flex items-center gap-1.5 font-semibold">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span>Erro do Compilador JasperReports (JVM)</span>
              </div>
              <pre className="mt-1.5 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink">
                {daemonError}
              </pre>
            </div>
          )}

          {compileSucceeded && (
            <div className="mb-2 flex items-center gap-2 rounded-md border border-success/30 bg-success-soft/60 px-2.5 py-1.5 text-success">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
              <span className="font-medium">
                Compilação JVM concluída com sucesso
              </span>
              {compileResult?.jasper_path && (
                <span className="truncate font-mono text-[11px] text-ink-muted">
                  ({compileResult.jasper_path})
                </span>
              )}
            </div>
          )}

          {!lintReport && !compileResult && !daemonError && (
            <p className="py-3 text-center text-ink-muted">
              Clique em <strong>Auditar</strong> ou <strong>Compilar (.jasper)</strong> para
              verificar regras XSD, expressões e geometria do JRXML.
            </p>
          )}

          {lintReport && allIssues.length === 0 && !daemonError && (
            <div className="flex items-center gap-2 rounded-md border border-success/30 bg-success-soft/50 px-2.5 py-2 text-success">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>
                Auditoria Fase 4 aprovada: nenhum erro ou aviso encontrado no
                JRXML.
              </span>
            </div>
          )}

          {allIssues.length > 0 && (
            <ul className="divide-y divide-border/70">
              {allIssues.map(({ issue, kind }, idx) => {
                const isError = kind === "error";
                const lineNum =
                  typeof issue.line === "number" && issue.line > 0
                    ? issue.line
                    : null;

                return (
                  <li
                    key={`${kind}-${issue.rule}-${lineNum ?? "na"}-${idx}`}
                    className="flex items-start gap-2 py-1.5 first:pt-0.5 last:pb-0.5"
                  >
                    <Badge
                      tone={isError ? "danger" : "warning"}
                      className="mt-0.5 shrink-0 px-1.5 py-0 text-[10px]"
                    >
                      {isError ? (
                        <AlertCircle className="h-3 w-3" />
                      ) : (
                        <AlertTriangle className="h-3 w-3" />
                      )}
                      {isError ? "Erro" : "Aviso"}
                    </Badge>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] font-semibold text-ink">
                          {issue.rule}
                        </span>
                        {issue.element && (
                          <span className="rounded bg-surface-subtle px-1 py-0.2 font-mono text-[10px] text-ink-secondary">
                            &lt;{issue.element}&gt;
                          </span>
                        )}
                        {lineNum !== null && (
                          <button
                            type="button"
                            onClick={() => onJumpToLine(lineNum)}
                            className={cn(
                              "rounded border border-blueprint/30 bg-blueprint-soft px-1.5 py-0.2 font-mono text-[10px] font-semibold text-blueprint transition-colors hover:bg-blueprint hover:text-white cursor-pointer tabular-nums",
                              selectedLine === lineNum &&
                                "ring-1 ring-blueprint",
                            )}
                          >
                            Linha {lineNum}
                          </button>
                        )}
                      </div>
                      <p className="mt-0.5 leading-snug text-ink-secondary break-words">
                        {issue.message}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
