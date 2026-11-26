import { useMemo, useRef, useState } from "react";
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
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import {
  ChevronsDownUp,
  ChevronsUpDown,
  Heading,
  Plus,
  Search,
  X,
} from "lucide-react";
import { Badge, Button, EmptyState, Input } from "@/components/ui";
import type { ClinicalQuestion } from "@/types/studio";
import { cloneQuestion, createDefaultQuestion, reorderArray } from "./model";
import { QuestionCard } from "./QuestionCard";

export interface QuestionsListProps {
  perguntas: ClinicalQuestion[];
  onChange: (nextPerguntas: ClinicalQuestion[]) => void;
}

export function QuestionsList({ perguntas, onChange }: QuestionsListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const nextUidRef = useRef(1);
  const [questionKeys, setQuestionKeys] = useState<string[]>(() =>
    perguntas.map(() => `q-${nextUidRef.current++}`),
  );
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(
    () => new Set(),
  );

  // Keep key array length synchronized when perguntas changes externally (e.g. Monaco edit)
  const effectiveKeys = useMemo(() => {
    if (questionKeys.length === perguntas.length) {
      return questionKeys;
    }
    if (questionKeys.length > perguntas.length) {
      return questionKeys.slice(0, perguntas.length);
    }
    const next = [...questionKeys];
    for (let i = questionKeys.length; i < perguntas.length; i++) {
      next.push(`q-ext-${i}`);
    }
    return next;
  }, [questionKeys, perguntas.length]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const isFiltering = normalizedQuery.length > 0;

  const visibleEntries = useMemo(() => {
    return perguntas
      .map((question, originalIndex) => ({
        question,
        originalIndex,
        key: effectiveKeys[originalIndex],
      }))
      .filter(({ question }) => {
        if (!normalizedQuery) return true;
        if ((question.nome || "").toLowerCase().includes(normalizedQuery)) {
          return true;
        }
        return (question.respostas ?? []).some(
          (ans) =>
            (ans.label || "").toLowerCase().includes(normalizedQuery) ||
            String(ans.tipo_campo || "")
              .toLowerCase()
              .includes(normalizedQuery),
        );
      });
  }, [perguntas, effectiveKeys, normalizedQuery]);

  const totalAnswers = useMemo(
    () =>
      perguntas.reduce(
        (sum, q) => sum + (Array.isArray(q.respostas) ? q.respostas.length : 0),
        0,
      ),
    [perguntas],
  );

  const commit = (nextPerguntas: ClinicalQuestion[], nextKeys: string[]) => {
    setQuestionKeys(nextKeys);
    onChange(
      nextPerguntas.map((q, idx) => ({
        ...q,
        ordenacao: idx + 1,
      })),
    );
  };

  const handleAddQuestion = (isTitle: boolean) => {
    const newKey = `q-${nextUidRef.current++}`;
    const created = createDefaultQuestion({
      isTitle,
      ordenacao: perguntas.length + 1,
    });
    commit([...perguntas, created], [...effectiveKeys, newKey]);
  };

  const handleUpdateQuestion = (index: number, nextQ: ClinicalQuestion) => {
    const next = perguntas.map((item, idx) => (idx === index ? nextQ : item));
    commit(next, effectiveKeys);
  };

  const handleDuplicateQuestion = (index: number) => {
    const target = perguntas[index];
    if (!target) return;
    const newKey = `q-${nextUidRef.current++}`;
    const nextPerguntas = [...perguntas];
    nextPerguntas.splice(index + 1, 0, cloneQuestion(target));
    const nextKeys = [...effectiveKeys];
    nextKeys.splice(index + 1, 0, newKey);
    commit(nextPerguntas, nextKeys);
  };

  const handleDeleteQuestion = (index: number) => {
    const removedKey = effectiveKeys[index];
    const nextPerguntas = perguntas.filter((_, idx) => idx !== index);
    const nextKeys = effectiveKeys.filter((_, idx) => idx !== index);
    if (removedKey) {
      setCollapsedKeys((prev) => {
        if (!prev.has(removedKey)) return prev;
        const next = new Set(prev);
        next.delete(removedKey);
        return next;
      });
    }
    commit(nextPerguntas, nextKeys);
  };

  const handleMoveQuestion = (fromIdx: number, toIdx: number) => {
    if (
      fromIdx === toIdx ||
      fromIdx < 0 ||
      toIdx < 0 ||
      fromIdx >= perguntas.length ||
      toIdx >= perguntas.length
    ) {
      return;
    }
    commit(
      reorderArray(perguntas, fromIdx, toIdx),
      reorderArray(effectiveKeys, fromIdx, toIdx),
    );
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = effectiveKeys.indexOf(String(active.id));
    const newIndex = effectiveKeys.indexOf(String(over.id));
    if (oldIndex >= 0 && newIndex >= 0 && oldIndex !== newIndex) {
      handleMoveQuestion(oldIndex, newIndex);
    }
  };

  const toggleCollapse = (key: string) => {
    setCollapsedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleExpandAll = () => {
    setCollapsedKeys(new Set());
  };

  const handleCollapseAll = () => {
    setCollapsedKeys(new Set(effectiveKeys));
  };

  return (
    <section aria-label="Perguntas e respostas" className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-2.5">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
          <Input
            aria-label="Buscar perguntas ou respostas"
            value={searchQuery}
            placeholder="Filtrar por pergunta, rótulo ou tipo..."
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 pl-8 pr-7 text-xs"
          />
          {searchQuery && (
            <button
              type="button"
              aria-label="Limpar busca"
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="neutral" className="tabular-nums">
            {perguntas.length} {perguntas.length === 1 ? "pergunta" : "perguntas"} •{" "}
            {totalAnswers} {totalAnswers === 1 ? "resposta" : "respostas"}
          </Badge>

          <Button
            variant="ghost"
            size="xs"
            icon={<ChevronsUpDown className="h-3.5 w-3.5" />}
            onClick={handleExpandAll}
            disabled={perguntas.length === 0}
          >
            Expandir todas
          </Button>
          <Button
            variant="ghost"
            size="xs"
            icon={<ChevronsDownUp className="h-3.5 w-3.5" />}
            onClick={handleCollapseAll}
            disabled={perguntas.length === 0}
          >
            Recolher todas
          </Button>

          <Button
            variant="secondary"
            size="xs"
            icon={<Heading className="h-3.5 w-3.5" />}
            onClick={() => handleAddQuestion(true)}
          >
            Título de seção
          </Button>
          <Button
            variant="primary"
            size="xs"
            icon={<Plus className="h-3.5 w-3.5" />}
            onClick={() => handleAddQuestion(false)}
          >
            Nova pergunta
          </Button>
        </div>
      </div>

      {isFiltering && (
        <p className="text-xs text-ink-muted px-1">
          Mostrando {visibleEntries.length} de {perguntas.length} perguntas
          (arraste desativado durante filtro).
        </p>
      )}

      {/* List */}
      {perguntas.length === 0 ? (
        <EmptyState
          title="Nenhuma pergunta na ficha"
          description="Adicione uma pergunta clínica ou um título de seção para começar a estruturar o formulário."
          action={
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Heading className="h-3.5 w-3.5" />}
                onClick={() => handleAddQuestion(true)}
              >
                Adicionar título de seção
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() => handleAddQuestion(false)}
              >
                Adicionar pergunta
              </Button>
            </div>
          }
        />
      ) : visibleEntries.length === 0 ? (
        <EmptyState
          title="Nenhum resultado encontrado"
          description={`Nenhuma pergunta ou resposta corresponde a "${searchQuery}".`}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSearchQuery("")}
            >
              Limpar filtro
            </Button>
          }
        />
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={effectiveKeys}
            strategy={verticalListSortingStrategy}
          >
            <div className="space-y-2.5">
              {visibleEntries.map(({ question, originalIndex, key }) => (
                <QuestionCard
                  key={key}
                  sortableId={key}
                  question={question}
                  index={originalIndex}
                  total={perguntas.length}
                  collapsed={collapsedKeys.has(key)}
                  dragDisabled={isFiltering}
                  onToggleCollapse={() => toggleCollapse(key)}
                  onChange={(nextQ) =>
                    handleUpdateQuestion(originalIndex, nextQ)
                  }
                  onDuplicate={() => handleDuplicateQuestion(originalIndex)}
                  onDelete={() => handleDeleteQuestion(originalIndex)}
                  onMoveUp={() =>
                    handleMoveQuestion(originalIndex, originalIndex - 1)
                  }
                  onMoveDown={() =>
                    handleMoveQuestion(originalIndex, originalIndex + 1)
                  }
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </section>
  );
}
