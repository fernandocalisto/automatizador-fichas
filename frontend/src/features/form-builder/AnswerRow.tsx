import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  GripVertical,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { SALUTEM_FIELD_TYPES, type ClinicalAnswer } from "@/types/studio";
import {
  getAnswerRequired,
  isOfficialSalutemFieldType,
  SALUTEM_FIELD_TYPE_LABELS,
} from "./model";

export interface AnswerRowProps {
  sortableId: string;
  answer: ClinicalAnswer;
  index: number;
  total: number;
  questionIndex: number;
  dragDisabled?: boolean;
  onChange: (next: ClinicalAnswer) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

export function AnswerRow({
  sortableId,
  answer,
  index,
  total,
  questionIndex,
  dragDisabled = false,
  onChange,
  onDuplicate,
  onDelete,
  onMoveUp,
  onMoveDown,
}: AnswerRowProps) {
  const [newOption, setNewOption] = useState("");

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sortableId, disabled: dragDisabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const tipoCampo = String(answer.tipo_campo || "TEXTO");
  const isKnownType = isOfficialSalutemFieldType(tipoCampo);
  const isCombobox = tipoCampo === "COMBOBOX";
  const opcoes = Array.isArray(answer.opcoes) ? answer.opcoes : [];
  const obrigatorio = getAnswerRequired(answer);
  const observacao = Boolean(answer.observacao);
  const quantidadeLinhas =
    typeof answer.quantidade_linhas === "number" ? answer.quantidade_linhas : 1;

  const update = (patch: Partial<ClinicalAnswer>) => {
    onChange({
      ...answer,
      ...patch,
    });
  };

  const handleAddOption = () => {
    const trimmed = newOption.trim();
    if (!trimmed) return;
    update({ opcoes: [...opcoes, trimmed] });
    setNewOption("");
  };

  const handleRemoveOption = (optIndex: number) => {
    update({ opcoes: opcoes.filter((_, idx) => idx !== optIndex) });
  };

  const qNum = questionIndex + 1;
  const aNum = index + 1;

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`answer-row-${questionIndex}-${index}`}
      className={cn(
        "rounded-md border border-border bg-surface-subtle/50 p-2 transition-colors",
        isDragging && "z-20 opacity-85 shadow-md ring-2 ring-accent/40",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          aria-label={`Arrastar resposta ${aNum} da pergunta ${qNum}`}
          disabled={dragDisabled}
          className={cn(
            "flex h-7 w-6 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-surface hover:text-ink",
            dragDisabled ? "cursor-not-allowed opacity-40" : "cursor-grab active:cursor-grabbing",
          )}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>

        <span className="w-6 shrink-0 text-center font-mono text-[11px] font-semibold text-ink-muted tabular-nums">
          #{aNum}
        </span>

        <div className="min-w-[140px] flex-1">
          <Input
            aria-label={`Rótulo da resposta ${aNum} da pergunta ${qNum}`}
            value={answer.label ?? ""}
            placeholder="Rótulo da resposta (ex.: SIM, OBSERVAÇÕES...)"
            onChange={(e) => update({ label: e.target.value })}
            className="h-7 text-xs"
          />
        </div>

        <div className="w-44 shrink-0">
          <Select
            aria-label={`Tipo de campo da resposta ${aNum} da pergunta ${qNum}`}
            value={tipoCampo}
            onChange={(e) => {
              const nextType = e.target.value;
              const patch: Partial<ClinicalAnswer> = { tipo_campo: nextType };
              if (nextType === "COMBOBOX" && !Array.isArray(answer.opcoes)) {
                patch.opcoes = [];
              }
              update(patch);
            }}
            className={cn(
              "h-7 text-xs",
              !isKnownType && "border-warning text-warning",
            )}
          >
            {!isKnownType && (
              <option value={tipoCampo}>
                {tipoCampo} (tipo não oficial)
              </option>
            )}
            {SALUTEM_FIELD_TYPES.map((ft) => (
              <option key={ft} value={ft} title={SALUTEM_FIELD_TYPE_LABELS[ft]}>
                {ft}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex items-center gap-1 shrink-0" title="Quantidade de linhas">
          <label
            htmlFor={`ans-lines-${sortableId}`}
            className="text-[11px] text-ink-muted"
          >
            Linhas
          </label>
          <Input
            id={`ans-lines-${sortableId}`}
            aria-label={`Linhas da resposta ${aNum} da pergunta ${qNum}`}
            type="number"
            min={1}
            max={20}
            value={quantidadeLinhas}
            onChange={(e) => {
              const val = Number.parseInt(e.target.value, 10);
              update({
                quantidade_linhas: Number.isNaN(val) || val < 1 ? 1 : val,
              });
            }}
            className="h-7 w-14 px-1.5 text-center font-mono text-xs tabular-nums"
          />
        </div>

        <label className="inline-flex items-center gap-1 rounded border border-border/80 bg-surface px-1.5 py-1 text-[11px] text-ink-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            aria-label={`Resposta ${aNum} da pergunta ${qNum} obrigatória`}
            checked={obrigatorio}
            onChange={(e) => {
              const checked = e.target.checked;
              const patch: Partial<ClinicalAnswer> = { obrigatorio: checked };
              if ("campo_obrigatorio" in answer) {
                patch.campo_obrigatorio = checked;
              }
              update(patch);
            }}
            className="h-3 w-3 accent-accent cursor-pointer"
          />
          <span>Obrig.</span>
        </label>

        <label className="inline-flex items-center gap-1 rounded border border-border/80 bg-surface px-1.5 py-1 text-[11px] text-ink-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            aria-label={`Resposta ${aNum} da pergunta ${qNum} possui observação`}
            checked={observacao}
            onChange={(e) => update({ observacao: e.target.checked })}
            className="h-3 w-3 accent-accent cursor-pointer"
          />
          <span>Obs.</span>
        </label>

        <div className="ml-auto flex items-center gap-0.5 shrink-0">
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Subir resposta ${aNum} da pergunta ${qNum}`}
            title="Subir resposta"
            disabled={index === 0}
            onClick={onMoveUp}
            className="h-7 w-6 px-0"
          >
            <ArrowUp className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Descer resposta ${aNum} da pergunta ${qNum}`}
            title="Descer resposta"
            disabled={index === total - 1}
            onClick={onMoveDown}
            className="h-7 w-6 px-0"
          >
            <ArrowDown className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Duplicar resposta ${aNum} da pergunta ${qNum}`}
            title="Duplicar resposta"
            onClick={onDuplicate}
            className="h-7 w-6 px-0"
          >
            <Copy className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Excluir resposta ${aNum} da pergunta ${qNum}`}
            title="Excluir resposta"
            onClick={onDelete}
            className="h-7 w-6 px-0 text-danger hover:bg-danger-soft hover:text-danger"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {isCombobox && (
        <div className="mt-2 ml-8 rounded border border-border bg-surface p-2 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium text-ink-secondary">
              Opções do COMBOBOX ({opcoes.length})
            </span>
            {opcoes.length === 0 && (
              <span className="text-[11px] text-ink-muted">
                Adicione opções para a lista suspensa
              </span>
            )}
          </div>

          {opcoes.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {opcoes.map((opt, optIdx) => (
                <Badge
                  key={`${opt}-${optIdx}`}
                  tone="accent"
                  className="gap-1 pr-1 text-[11px]"
                >
                  <span>{opt}</span>
                  <button
                    type="button"
                    aria-label={`Remover opção ${opt}`}
                    onClick={() => handleRemoveOption(optIdx)}
                    className="rounded p-0.5 hover:bg-accent/20 cursor-pointer"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </Badge>
              ))}
            </div>
          )}

          <div className="flex items-center gap-1.5">
            <Input
              aria-label={`Nova opção do combobox da resposta ${aNum} da pergunta ${qNum}`}
              value={newOption}
              placeholder="Digite uma opção e pressione Enter"
              onChange={(e) => setNewOption(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAddOption();
                }
              }}
              className="h-7 text-xs"
            />
            <Button
              variant="secondary"
              size="xs"
              icon={<Plus className="h-3 w-3" />}
              disabled={!newOption.trim()}
              onClick={handleAddOption}
            >
              Adicionar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
