import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ClinicalWarningItem } from "@/types/studio";

export interface WarningsBannerProps {
  warnings: ClinicalWarningItem[];
  loading?: boolean;
}

export function WarningsBanner({
  warnings,
  loading = false,
}: WarningsBannerProps) {
  const [expanded, setExpanded] = useState(true);

  if (loading) {
    return null;
  }

  if (warnings.length === 0) {
    return (
      <div
        role="status"
        className="flex items-center justify-between gap-2 border-b border-border bg-success-soft/50 px-4 py-1.5 text-xs text-success"
      >
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">
            Auditoria clínica: nenhum aviso pendente.
          </span>
        </div>
        <Badge tone="success">0 avisos</Badge>
      </div>
    );
  }

  return (
    <section
      aria-label="Avisos clínicos"
      className="border-b border-warning/35 bg-warning-soft/70 text-ink"
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-xs hover:bg-warning-soft cursor-pointer transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-warning" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-warning" />
          )}
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />
          <span className="font-semibold text-warning">
            Avisos clínicos ({warnings.length})
          </span>
          <span className="truncate text-ink-muted hidden sm:inline">
            Regras de auditoria Salutem — não bloqueantes, revise antes de gerar
            o SQL.
          </span>
        </div>

        <Badge tone="warning" className="tabular-nums">
          {warnings.length} {warnings.length === 1 ? "aviso" : "avisos"}
        </Badge>
      </button>

      {expanded && (
        <ul className="max-h-40 overflow-y-auto border-t border-warning/25 divide-y divide-warning/15 px-4 py-1">
          {warnings.map((w, idx) => (
            <li
              key={`${w.code ?? "warn"}-${w.path ?? idx}-${idx}`}
              className={cn(
                "flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5 text-xs",
              )}
            >
              {w.code && (
                <code className="rounded bg-warning/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-warning">
                  {w.code}
                </code>
              )}
              {w.path && (
                <code className="font-mono text-[11px] text-ink-muted">
                  {w.path}
                </code>
              )}
              <span className="text-ink-secondary">{w.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
