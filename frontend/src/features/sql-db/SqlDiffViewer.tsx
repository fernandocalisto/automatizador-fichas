import { useMemo, useState } from "react";
import { RotateCcw, X } from "lucide-react";
import { Badge, Button, Switch } from "@/components/ui";
import { cn } from "@/lib/cn";
import { computeLineDiff, type DiffLine } from "./sqlDiff";

export interface SqlDiffViewerProps {
  savedContent: string;
  currentContent: string;
  savedVersion: number | null;
  artifactLabel: string;
  onClose: () => void;
  onRevertToSaved?: () => void;
}

const CONTEXT_RADIUS = 3;

function filterChangedContext(lines: DiffLine[]): Array<DiffLine | { separator: true; skipped: number }> {
  const changedIndices = new Set<number>();
  lines.forEach((line, idx) => {
    if (line.kind !== "equal") {
      for (
        let k = Math.max(0, idx - CONTEXT_RADIUS);
        k <= Math.min(lines.length - 1, idx + CONTEXT_RADIUS);
        k++
      ) {
        changedIndices.add(k);
      }
    }
  });

  if (changedIndices.size === 0) return [];

  const output: Array<DiffLine | { separator: true; skipped: number }> = [];
  let skipped = 0;

  lines.forEach((line, idx) => {
    if (changedIndices.has(idx)) {
      if (skipped > 0) {
        output.push({ separator: true, skipped });
        skipped = 0;
      }
      output.push(line);
    } else {
      skipped++;
    }
  });

  if (skipped > 0) {
    output.push({ separator: true, skipped });
  }

  return output;
}

export function SqlDiffViewer({
  savedContent,
  currentContent,
  savedVersion,
  artifactLabel,
  onClose,
  onRevertToSaved,
}: SqlDiffViewerProps) {
  const [onlyChanges, setOnlyChanges] = useState(false);

  const diff = useMemo(
    () => computeLineDiff(savedContent, currentContent),
    [savedContent, currentContent],
  );

  const visibleRows = useMemo(() => {
    if (!onlyChanges) return diff.lines;
    return filterChangedContext(diff.lines);
  }, [diff.lines, onlyChanges]);

  return (
    <div
      className="flex h-full flex-col bg-surface"
      aria-label={`Diff de ${artifactLabel}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-subtle/70 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-ink">
            Diff — {artifactLabel}
          </span>
          <Badge tone="neutral" className="tabular-nums">
            {savedVersion !== null ? `Salvo v${savedVersion}` : "Sem revisão salva"}
            {" → "}
            Editor atual
          </Badge>
          {diff.hasChanges ? (
            <>
              <Badge tone="success" className="tabular-nums">
                +{diff.addedCount} {diff.addedCount === 1 ? "linha" : "linhas"}
              </Badge>
              <Badge tone="danger" className="tabular-nums">
                -{diff.removedCount} {diff.removedCount === 1 ? "linha" : "linhas"}
              </Badge>
            </>
          ) : (
            <Badge tone="accent">Sem diferenças</Badge>
          )}
        </div>

        <div className="flex items-center gap-2">
          {diff.hasChanges && (
            <Switch
              id="sql-diff-only-changes"
              checked={onlyChanges}
              onChange={setOnlyChanges}
              label="Apenas alterações"
            />
          )}
          {diff.hasChanges && onRevertToSaved && (
            <Button
              size="xs"
              variant="outline"
              onClick={onRevertToSaved}
              icon={<RotateCcw className="h-3 w-3" />}
            >
              Descartar edições
            </Button>
          )}
          <Button
            size="xs"
            variant="ghost"
            onClick={onClose}
            icon={<X className="h-3.5 w-3.5" />}
          >
            Voltar ao editor
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto font-mono text-xs">
        {!diff.hasChanges ? (
          <div className="flex h-full items-center justify-center p-6 text-center text-ink-muted">
            O conteúdo do editor está idêntico à revisão salva
            {savedVersion !== null ? ` (v${savedVersion})` : ""}.
          </div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {visibleRows.map((row, index) => {
                if ("separator" in row) {
                  return (
                    <tr
                      key={`sep-${index}`}
                      className="border-y border-border/60 bg-surface-subtle/50 text-ink-muted"
                    >
                      <td colSpan={4} className="px-3 py-1 text-[11px] italic">
                        ··· {row.skipped}{" "}
                        {row.skipped === 1 ? "linha inalterada oculta" : "linhas inalteradas ocultas"}{" "}
                        ···
                      </td>
                    </tr>
                  );
                }

                const prefix =
                  row.kind === "added" ? "+" : row.kind === "removed" ? "-" : " ";

                return (
                  <tr
                    key={`${row.kind}-${row.oldLineNumber ?? "n"}-${row.newLineNumber ?? "n"}-${index}`}
                    className={cn(
                      row.kind === "added" && "bg-success-soft/75 text-ink",
                      row.kind === "removed" && "bg-danger-soft/75 text-ink",
                      row.kind === "equal" && "text-ink-secondary",
                    )}
                  >
                    <td className="w-10 select-none border-r border-border/50 px-2 py-0.5 text-right text-[11px] text-ink-muted tabular-nums">
                      {row.oldLineNumber ?? ""}
                    </td>
                    <td className="w-10 select-none border-r border-border/50 px-2 py-0.5 text-right text-[11px] text-ink-muted tabular-nums">
                      {row.newLineNumber ?? ""}
                    </td>
                    <td
                      className={cn(
                        "w-5 select-none px-1.5 py-0.5 text-center font-bold",
                        row.kind === "added" && "text-success",
                        row.kind === "removed" && "text-danger",
                        row.kind === "equal" && "text-ink-muted",
                      )}
                    >
                      {prefix}
                    </td>
                    <td className="whitespace-pre-wrap break-all px-2 py-0.5 leading-relaxed">
                      {row.text || " "}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
