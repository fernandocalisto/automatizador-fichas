import { useEffect, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight, Play, RotateCcw, Sliders } from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { JrxmlParameterInfo } from "@/types/studio";

export interface ReportParamsBarProps {
  parameters: JrxmlParameterInfo[];
  values: Record<string, string>;
  onChangeValue: (name: string, value: string) => void;
  onClearAll: () => void;
  onApplyPreview?: () => void;
  previewLoading?: boolean;
  defaultOpen?: boolean;
  hasPreview?: boolean;
}

function shortJavaClass(javaClass: string): string {
  const parts = javaClass.split(".");
  return parts[parts.length - 1] || javaClass;
}

export function ReportParamsBar({
  parameters,
  values,
  onChangeValue,
  onClearAll,
  onApplyPreview,
  previewLoading = false,
  defaultOpen = false,
  hasPreview = true,
}: ReportParamsBarProps) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (defaultOpen) {
      setOpen(true);
    }
  }, [defaultOpen]);

  const userParams = parameters.filter((p) => !p.is_system);
  const filledCount = userParams.filter(
    (p) => (values[p.name] ?? "").trim().length > 0,
  ).length;
  const missingRequiredCount = userParams.filter(
    (p) => !p.default_expression && !(values[p.name] ?? "").trim(),
  ).length;

  if (userParams.length === 0) {
    return null;
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && onApplyPreview) {
      e.preventDefault();
      onApplyPreview();
    }
  };

  return (
    <div
      data-testid="report-params-bar"
      className="shrink-0 border-b border-border bg-surface-subtle/50 px-3 py-1.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={open}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-ink hover:text-accent cursor-pointer"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 text-ink-muted" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-ink-muted" />
          )}
          <Sliders className="h-3.5 w-3.5 text-blueprint" />
          <span>Parâmetros $P{"{}"} do Relatório</span>
          <Badge tone="neutral" className="text-[10px] tabular-nums">
            {userParams.length}
          </Badge>
          {filledCount > 0 && (
            <Badge tone="blueprint" className="text-[10px] tabular-nums">
              {filledCount} preenchido{filledCount > 1 ? "s" : ""}
            </Badge>
          )}
          {missingRequiredCount > 0 && (
            <Badge tone="warning" className="text-[10px] tabular-nums">
              {missingRequiredCount} pendente{missingRequiredCount > 1 ? "s" : ""}
            </Badge>
          )}
        </button>

        {open && (
          <div className="flex items-center gap-1.5">
            {filledCount > 0 && (
              <Button
                variant="ghost"
                size="xs"
                onClick={onClearAll}
                icon={<RotateCcw className="h-3 w-3" />}
              >
                Limpar
              </Button>
            )}
            {onApplyPreview && (
              <Button
                variant={hasPreview ? "blueprint" : "primary"}
                size="xs"
                loading={previewLoading}
                icon={!hasPreview ? <Play className="h-3 w-3" /> : undefined}
                onClick={onApplyPreview}
              >
                {hasPreview ? "Aplicar no preview" : "Gerar Preview"}
              </Button>
            )}
          </div>
        )}
      </div>

      {open && (
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {userParams.map((param) => {
            const val = values[param.name] ?? "";
            const isRequiredEmpty = !param.default_expression && !val.trim();
            const inputId = `jrxml-param-${param.name}`;

            return (
              <div key={param.name} className="flex flex-col gap-1">
                <label
                  htmlFor={inputId}
                  className="flex items-center justify-between gap-1 text-[11px] font-medium text-ink-secondary"
                >
                  <span className="inline-flex items-center gap-1 truncate font-mono text-ink">
                    <span>
                      $P{"{"}
                      {param.name}
                      {"}"}
                    </span>
                    {!param.default_expression && (
                      <span
                        title="Parâmetro sem valor padrão"
                        className="text-warning font-sans font-semibold"
                      >
                        *
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-ink-muted">
                    {shortJavaClass(param.java_class)}
                  </span>
                </label>

                {param.input_kind === "boolean" ? (
                  <Select
                    id={inputId}
                    aria-label={`Parâmetro ${param.name}`}
                    value={val}
                    onChange={(e) => onChangeValue(param.name, e.target.value)}
                    className={cn(
                      "h-7 text-xs",
                      isRequiredEmpty && "border-warning/60",
                    )}
                  >
                    <option value="">Padrão (não enviado)</option>
                    <option value="true">true (Sim)</option>
                    <option value="false">false (Não)</option>
                  </Select>
                ) : (
                  <Input
                    id={inputId}
                    aria-label={`Parâmetro ${param.name}`}
                    type={
                      param.input_kind === "integer" ||
                      param.input_kind === "number"
                        ? "number"
                        : param.input_kind === "date"
                          ? "date"
                          : param.input_kind === "datetime"
                            ? "datetime-local"
                            : "text"
                    }
                    step={param.input_kind === "number" ? "any" : undefined}
                    value={val}
                    onChange={(e) => onChangeValue(param.name, e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      param.default_expression
                        ? `Padrão: ${param.default_expression}`
                        : `Valor para ${param.name}...`
                    }
                    className={cn(
                      "h-7 font-mono text-xs",
                      isRequiredEmpty && "border-warning/60",
                    )}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
