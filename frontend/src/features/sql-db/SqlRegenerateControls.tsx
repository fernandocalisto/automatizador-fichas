import { RefreshCw } from "lucide-react";
import { Button, FieldLabel, Select, Switch } from "@/components/ui";
import { cn } from "@/lib/cn";

export type BooleanStyleOption =
  | "coalesce_bool_or"
  | "x_empty"
  | "sim_nao"
  | "1_0";

export type NamingModeOption = "label_only" | "pergunta_label" | "label_sufixo";

export type ParamSyntaxOption = "jasper" | "salutem";

export interface SqlSelectRegenerateOptions {
  boolean_style: BooleanStyleOption;
  column_naming: NamingModeOption;
  param_syntax: ParamSyntaxOption;
  include_obs: boolean;
}

export const DEFAULT_SQL_SELECT_OPTIONS: SqlSelectRegenerateOptions = {
  boolean_style: "coalesce_bool_or",
  column_naming: "label_only",
  param_syntax: "jasper",
  include_obs: true,
};

export interface SqlRegenerateControlsProps {
  options: SqlSelectRegenerateOptions;
  onChange: (next: SqlSelectRegenerateOptions) => void;
  onRegenerate: () => void;
  loading?: boolean;
  actionLabel?: string;
  className?: string;
}

export function SqlRegenerateControls({
  options,
  onChange,
  onRegenerate,
  loading = false,
  actionLabel = "Regenerar SQL (INSERT + SELECT)",
  className,
}: SqlRegenerateControlsProps) {
  return (
    <div
      className={cn(
        "rounded-md border border-border bg-surface-subtle/60 p-3",
        className,
      )}
    >
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <div>
          <FieldLabel htmlFor="sql-opt-boolean-style">
            Estilo booleano
          </FieldLabel>
          <Select
            id="sql-opt-boolean-style"
            value={options.boolean_style}
            onChange={(e) =>
              onChange({
                ...options,
                boolean_style: e.target.value as BooleanStyleOption,
              })
            }
          >
            <option value="coalesce_bool_or">
              Boolean nativo (coalesce_bool_or)
            </option>
            <option value="x_empty">Marcação &apos;X&apos; / vazio (x_empty)</option>
            <option value="sim_nao">Texto SIM / NÃO (sim_nao)</option>
            <option value="1_0">Numérico 1 / 0 (1_0)</option>
          </Select>
        </div>

        <div>
          <FieldLabel htmlFor="sql-opt-naming-mode">
            Nomeação das colunas
          </FieldLabel>
          <Select
            id="sql-opt-naming-mode"
            value={options.column_naming}
            onChange={(e) =>
              onChange({
                ...options,
                column_naming: e.target.value as NamingModeOption,
              })
            }
          >
            <option value="label_only">Somente label (label_only)</option>
            <option value="pergunta_label">
              Pergunta + label (pergunta_label)
            </option>
            <option value="label_sufixo">
              Label + sufixo de tipo (label_sufixo)
            </option>
          </Select>
        </div>

        <div>
          <FieldLabel htmlFor="sql-opt-param-syntax">
            Sintaxe do parâmetro
          </FieldLabel>
          <Select
            id="sql-opt-param-syntax"
            value={options.param_syntax}
            onChange={(e) =>
              onChange({
                ...options,
                param_syntax: e.target.value as ParamSyntaxOption,
              })
            }
          >
            <option value="jasper">JasperReports ($P&#123;id&#125;) — padrão</option>
            <option value="salutem">Salutem ($&#123;id&#125;)</option>
          </Select>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-2.5">
        <Switch
          id="sql-opt-include-obs"
          checked={options.include_obs}
          onChange={(checked) => onChange({ ...options, include_obs: checked })}
          label="Incluir colunas _obs (observações)"
        />

        <Button
          variant="primary"
          size="sm"
          loading={loading}
          onClick={onRegenerate}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
        >
          {actionLabel}
        </Button>
      </div>
    </div>
  );
}
