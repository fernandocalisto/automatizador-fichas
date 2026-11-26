import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ToolCallRecord } from "./sseClient";

export interface ToolCallCardProps {
  record: ToolCallRecord;
  defaultExpanded?: boolean;
  className?: string;
}

function formatJsonValue(value: unknown): string {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function ToolCallCard({
  record,
  defaultExpanded = false,
  className,
}: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const hasArgs =
    record.tool_args !== null &&
    record.tool_args !== undefined &&
    Object.keys(record.tool_args).length > 0;
  const hasOutput =
    record.tool_output !== undefined && record.tool_output !== null;
  const hasError = Boolean(record.error_message);

  return (
    <div
      data-testid={`tool-call-card-${record.tool_name}`}
      className={cn(
        "rounded-md border bg-surface-subtle/70 text-xs transition-colors",
        record.status === "error"
          ? "border-danger/35"
          : record.status === "running"
            ? "border-blueprint/35"
            : "border-border",
        className,
      )}
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left hover:bg-surface-subtle transition-colors cursor-pointer rounded-md"
      >
        <div className="flex min-w-0 items-center gap-1.5">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
          )}
          <Wrench className="h-3 w-3 shrink-0 text-ink-muted" />
          <span className="truncate font-mono text-[11px] font-medium text-ink">
            {record.tool_name}
          </span>
        </div>

        <div className="shrink-0">
          {record.status === "running" && (
            <Badge tone="blueprint" className="py-0 text-[10px]">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Executando...
            </Badge>
          )}
          {record.status === "done" && (
            <Badge tone="success" className="py-0 text-[10px]">
              <CheckCircle2 className="h-2.5 w-2.5" />
              Concluído
            </Badge>
          )}
          {record.status === "error" && (
            <Badge tone="danger" className="py-0 text-[10px]">
              <AlertCircle className="h-2.5 w-2.5" />
              Erro
            </Badge>
          )}
        </div>
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-border/80 px-2.5 py-2">
          {hasArgs && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                Argumentos
              </div>
              <pre className="max-h-44 overflow-auto rounded border border-border/80 bg-surface p-2 font-mono text-[11px] leading-relaxed text-ink-secondary">
                {formatJsonValue(record.tool_args)}
              </pre>
            </div>
          )}

          {hasError && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-danger">
                Erro
              </div>
              <pre className="max-h-40 overflow-auto rounded border border-danger/30 bg-danger-soft/50 p-2 font-mono text-[11px] leading-relaxed text-danger whitespace-pre-wrap break-words">
                {record.error_message}
              </pre>
            </div>
          )}

          {hasOutput && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                Saída
              </div>
              <pre className="max-h-52 overflow-auto rounded border border-border/80 bg-surface p-2 font-mono text-[11px] leading-relaxed text-ink-secondary whitespace-pre-wrap break-words">
                {formatJsonValue(record.tool_output)}
              </pre>
            </div>
          )}

          {!hasArgs && !hasOutput && !hasError && (
            <p className="text-[11px] italic text-ink-muted">
              {record.status === "running"
                ? "Aguardando retorno da ferramenta..."
                : "Sem parâmetros ou saída detalhada."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
