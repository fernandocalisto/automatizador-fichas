import { AlertTriangle, Clock, ShieldCheck, Table2 } from "lucide-react";
import { Badge } from "@/components/ui";
import type { SelectPreviewResult } from "@/types/studio";

export interface SelectPreviewGridProps {
  result: SelectPreviewResult | null;
  error: string | null;
  loading?: boolean;
}

function formatCellValue(value: unknown): { text: string; isNull: boolean } {
  if (value === null || value === undefined) {
    return { text: "NULL", isNull: true };
  }
  if (typeof value === "boolean") {
    return { text: value ? "true" : "false", isNull: false };
  }
  if (typeof value === "object") {
    try {
      return { text: JSON.stringify(value), isNull: false };
    } catch {
      return { text: String(value), isNull: false };
    }
  }
  return { text: String(value), isNull: false };
}

export function SelectPreviewGrid({
  result,
  error,
  loading = false,
}: SelectPreviewGridProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-md border border-border bg-surface p-6 text-xs text-ink-muted">
        Executando consulta em transação READ ONLY...
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft/75 p-3 text-xs text-ink"
      >
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-danger">
            Erro ao executar Preview SELECT
          </p>
          <p className="mt-0.5 break-words font-mono text-[11px] text-ink-secondary">
            {error}
          </p>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-border bg-surface-subtle/40 p-6 text-center text-xs text-ink-muted">
        <Table2 className="h-5 w-5 text-ink-muted/70" />
        <p>
          Execute <strong>Preview SELECT (READ ONLY)</strong> para visualizar
          amostras reais de dados com segurança.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface-subtle/60 px-2.5 py-1.5 text-[11px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="success" dot>
            <ShieldCheck className="h-3 w-3" />
            READ ONLY
          </Badge>
          <Badge tone="blueprint" className="tabular-nums">
            {result.row_count} {result.row_count === 1 ? "linha" : "linhas"}
          </Badge>
          <Badge tone="neutral" className="tabular-nums">
            {result.columns.length}{" "}
            {result.columns.length === 1 ? "coluna" : "colunas"}
          </Badge>
          {result.truncated && (
            <Badge tone="warning">Limitado a {result.limit} linhas</Badge>
          )}
        </div>

        <span className="inline-flex items-center gap-1 font-mono text-ink-muted tabular-nums">
          <Clock className="h-3 w-3" />
          {result.latency_ms} ms
        </span>
      </div>

      <div className="max-h-80 overflow-auto rounded-md border border-border bg-surface">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 z-10 border-b border-border bg-surface-subtle">
            <tr>
              <th className="w-10 border-r border-border/60 px-2 py-1.5 text-right font-mono text-[10px] font-semibold text-ink-muted">
                #
              </th>
              {result.columns.map((col, idx) => (
                <th
                  key={`${col.name}-${idx}`}
                  title={`${col.pg_type} → ${col.java_class}`}
                  className="whitespace-nowrap border-r border-border/60 px-2.5 py-1.5 font-mono text-[11px] font-semibold text-ink last:border-r-0"
                >
                  <div>{col.name}</div>
                  <div className="text-[10px] font-normal text-ink-muted">
                    {col.pg_type}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {result.rows.length === 0 ? (
              <tr>
                <td
                  colSpan={Math.max(1, result.columns.length + 1)}
                  className="px-3 py-5 text-center text-ink-muted"
                >
                  A consulta não retornou nenhuma linha.
                </td>
              </tr>
            ) : (
              result.rows.map((row, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-surface-subtle/40">
                  <td className="border-r border-border/50 px-2 py-1 text-right font-mono text-[10px] text-ink-muted tabular-nums">
                    {rowIdx + 1}
                  </td>
                  {result.columns.map((col, colIdx) => {
                    const { text, isNull } = formatCellValue(row[col.name]);
                    return (
                      <td
                        key={`${rowIdx}-${col.name}-${colIdx}`}
                        title={text}
                        className="max-w-[260px] truncate border-r border-border/50 px-2.5 py-1 font-mono text-[11px] last:border-r-0"
                      >
                        {isNull ? (
                          <span className="italic text-ink-muted/70">NULL</span>
                        ) : (
                          <span className="text-ink">{text}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
