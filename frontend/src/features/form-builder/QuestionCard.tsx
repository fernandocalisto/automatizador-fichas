import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Copy,
  GripVertical,
  Heading,
  Plus,
  Trash2,
} from "lucide-react";
import { Badge, Button, Input, Switch } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ClinicalAnswer, ClinicalQuestion } from "@/types/studio";
import { AnswerRow } from "./AnswerRow";
import { cloneAnswer, createDefaultAnswer, reorderArray } from "./model";

export interface QuestionCardProps {
  sortableId: string;
  question: ClinicalQuestion;
  index: number;
  total: number;
  collapsed: boolean;
  dragDisabled?: boolean;
  onToggleCollapse: () => void;
  onChange: (next: ClinicalQuestion) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

export function QuestionCard({
  sortableId,
  question,
  index,
  total,
  collapsed,
  dragDisabled = false,
  onToggleCollapse,
  onChange,
  onDuplicate,
  onDelete,
  onMoveUp,
  onMoveDown,
}: QuestionCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sortableId, disabled: dragDisabled });

  const answerSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const isTitulo = Boolean(question.titulo);
  const respostas = Array.isArray(question.respostas) ? question.respostas : [];
  const qNum = index + 1;

  const updateQuestion = (patch: Partial<ClinicalQuestion>) => {
    onChange({
      ...question,
      ...patch,
    });
  };

  const updateAnswers = (nextRespostas: ClinicalAnswer[]) => {
    onChange({
      ...question,
      respostas: nextRespostas.map((ans, idx) => ({
        ...ans,
        ordenacao: idx + 1,
      })),
    });
  };

  const handleAddAnswer = () => {
    updateAnswers([...respostas, createDefaultAnswer(respostas.length + 1)]);
  };

  const handleUpdateAnswer = (ansIndex: number, nextAns: ClinicalAnswer) => {
    const next = respostas.map((item, idx) =>
      idx === ansIndex ? nextAns : item,
    );
    updateAnswers(next);
  };

  const handleDuplicateAnswer = (ansIndex: number) => {
    const target = respostas[ansIndex];
    if (!target) return;
    const next = [...respostas];
    next.splice(ansIndex + 1, 0, cloneAnswer(target));
    updateAnswers(next);
  };

  const handleDeleteAnswer = (ansIndex: number) => {
    updateAnswers(respostas.filter((_, idx) => idx !== ansIndex));
  };

  const handleMoveAnswer = (fromIdx: number, toIdx: number) => {
    updateAnswers(reorderArray(respostas, fromIdx, toIdx));
  };

  const answerSortableIds = respostas.map(
    (_, aIdx) => `${sortableId}::ans::${aIdx}`,
  );

  const handleAnswerDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = answerSortableIds.indexOf(String(active.id));
    const newIndex = answerSortableIds.indexOf(String(over.id));
    if (oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {
      handleMoveAnswer(oldIndex, newIndex);
    }
  };

  return (
    <article
      ref={setNodeRef}
      style={style}
      data-testid={`question-card-${index}`}
      className={cn(
        "rounded-lg border bg-surface transition-shadow",
        isTitulo
          ? "border-blueprint/45 bg-blueprint-soft/25"
          : "border-border",
        isDragging && "z-30 opacity-90 shadow-lg ring-2 ring-accent/40",
      )}
    >
      {/* Question Header */}
      <div className="flex flex-wrap items-center gap-1.5 px-2.5 py-2">
        <button
          type="button"
          aria-label={`Arrastar pergunta ${qNum}`}
          disabled={dragDisabled}
          className={cn(
            "flex h-7 w-6 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-surface-subtle hover:text-ink",
            dragDisabled
              ? "cursor-not-allowed opacity-40"
              : "cursor-grab active:cursor-grabbing",
          )}
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={onToggleCollapse}
          aria-expanded={!collapsed}
          aria-label={
            collapsed
              ? `Expandir pergunta ${qNum}`
              : `Recolher pergunta ${qNum}`
          }
          className="flex h-7 w-6 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-surface-subtle hover:text-ink cursor-pointer"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>

        <Badge
          tone={isTitulo ? "blueprint" : "neutral"}
          className="font-mono tabular-nums"
        >
          {isTitulo && <Heading className="h-3 w-3" />}
          {qNum}
        </Badge>

        <div className="min-w-[160px] flex-1">
          <Input
            aria-label={`Nome da pergunta ${qNum}`}
            value={question.nome ?? ""}
            placeholder={
              isTitulo
                ? "Título da seção (ex.: EXAME FÍSICO)"
                : "Texto da pergunta"
            }
            onChange={(e) => updateQuestion({ nome: e.target.value })}
            className={cn(
              "h-7 text-xs font-medium",
              isTitulo && "font-semibold tracking-wide",
            )}
          />
        </div>

        <Badge tone={isTitulo ? "blueprint" : "accent"} className="text-[11px]">
          {isTitulo
            ? "Seção"
            : `${respostas.length} ${respostas.length === 1 ? "resp." : "resps."}`}
        </Badge>

        <div className="flex items-center gap-0.5 shrink-0">
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Subir pergunta ${qNum}`}
            title="Subir pergunta"
            disabled={index === 0}
            onClick={onMoveUp}
            className="h-7 w-6 px-0"
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Descer pergunta ${qNum}`}
            title="Descer pergunta"
            disabled={index === total - 1}
            onClick={onMoveDown}
            className="h-7 w-6 px-0"
          >
            <ArrowDown className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Duplicar pergunta ${qNum}`}
            title="Duplicar pergunta"
            onClick={onDuplicate}
            className="h-7 w-6 px-0"
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            aria-label={`Excluir pergunta ${qNum}`}
            title="Excluir pergunta"
            onClick={onDelete}
            className="h-7 w-6 px-0 text-danger hover:bg-danger-soft hover:text-danger"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Question Body */}
      {!collapsed && (
        <div className="border-t border-border/70 px-3 py-2.5 space-y-2.5">
          {/* Question flags */}
          <div className="flex flex-wrap items-center gap-4">
            <Switch
              id={`q-titulo-${sortableId}`}
              checked={isTitulo}
              onChange={(checked) => updateQuestion({ titulo: checked })}
              label="Título (seção)"
            />
            <Switch
              id={`q-obrigatorio-${sortableId}`}
              checked={Boolean(question.obrigatorio)}
              onChange={(checked) => updateQuestion({ obrigatorio: checked })}
              label="Obrigatória"
            />
            <Switch
              id={`q-observacao-${sortableId}`}
              checked={Boolean(question.observacao)}
              onChange={(checked) => updateQuestion({ observacao: checked })}
              label="Observação"
            />
          </div>

          {isTitulo && respostas.length > 0 && (
            <div className="flex items-center gap-2 rounded border border-warning/40 bg-warning-soft/70 px-2.5 py-1.5 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>
                Perguntas marcadas como título de seção não devem conter
                respostas no padrão Salutem.
              </span>
            </div>
          )}

          {isTitulo && respostas.length === 0 ? (
            <p className="text-xs text-ink-muted italic">
              Divisor visual de seção (sem respostas vinculadas).
            </p>
          ) : (
            <div className="space-y-1.5">
              {respostas.length === 0 ? (
                <div className="rounded border border-dashed border-border-strong px-3 py-2 text-xs text-ink-muted">
                  Nenhuma resposta configurada. Adicione ao menos uma resposta
                  para esta pergunta.
                </div>
              ) : (
                <DndContext
                  sensors={answerSensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleAnswerDragEnd}
                >
                  <SortableContext
                    items={answerSortableIds}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="space-y-1.5">
                      {respostas.map((ans, aIdx) => (
                        <AnswerRow
                          key={answerSortableIds[aIdx]}
                          sortableId={answerSortableIds[aIdx]}
                          answer={ans}
                          index={aIdx}
                          total={respostas.length}
                          questionIndex={index}
                          onChange={(nextAns) =>
                            handleUpdateAnswer(aIdx, nextAns)
                          }
                          onDuplicate={() => handleDuplicateAnswer(aIdx)}
                          onDelete={() => handleDeleteAnswer(aIdx)}
                          onMoveUp={() => handleMoveAnswer(aIdx, aIdx - 1)}
                          onMoveDown={() => handleMoveAnswer(aIdx, aIdx + 1)}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}

              {!isTitulo && (
                <div className="pt-1">
                  <Button
                    variant="secondary"
                    size="xs"
                    icon={<Plus className="h-3.5 w-3.5" />}
                    onClick={handleAddAnswer}
                  >
                    Adicionar resposta
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
