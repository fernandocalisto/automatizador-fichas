import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { Crosshair, Send, X } from "lucide-react";
import { Badge, Button, FieldLabel, Textarea } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ClinicalOrientation, ScenarioType } from "@/types/studio";
import type {
  DetailCoords,
  PdfRect,
  VisualRegionAnnotation,
} from "./types";
import {
  convertNormalizedRectToPdfAndDetail,
  getPageDimensions,
  type NormalizedRect,
} from "./utils";

export interface RegionAnnotationSubmitPayload {
  page: number;
  pdfRect: PdfRect;
  detailCoords: DetailCoords;
  content: string;
}

export interface RegionAnnotationOverlayProps {
  active: boolean;
  page: number;
  scenario: ScenarioType;
  orientation: ClinicalOrientation;
  annotations: VisualRegionAnnotation[];
  submitting: boolean;
  onSubmitAnnotation: (payload: RegionAnnotationSubmitPayload) => Promise<void>;
  onRequestExitSelection?: () => void;
}

interface PendingSelection {
  normRect: NormalizedRect;
  pdfRect: PdfRect;
  detailCoords: DetailCoords;
}

export function RegionAnnotationOverlay({
  active,
  page,
  scenario,
  orientation,
  annotations,
  submitting,
  onSubmitAnnotation,
  onRequestExitSelection,
}: RegionAnnotationOverlayProps) {
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [noteText, setNoteText] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const pageDims = getPageDimensions(orientation);

  // Limpa drag/popover se o modo de seleção for desativado externamente
  useEffect(() => {
    if (!active) {
      setDragStart(null);
      setDragCurrent(null);
      setPending(null);
      setNoteText("");
      setValidationError(null);
    }
  }, [active]);

  // Tecla Escape cancela drag/popover ativo ou sai do modo de seleção
  useEffect(() => {
    if (!active && !pending && !dragStart) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (dragStart || pending) {
        event.preventDefault();
        event.stopPropagation();
        setDragStart(null);
        setDragCurrent(null);
        setPending(null);
        setNoteText("");
        setValidationError(null);
        return;
      }
      if (active) {
        event.preventDefault();
        event.stopPropagation();
        onRequestExitSelection?.();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [active, dragStart, onRequestExitSelection, pending]);

  const clientToNormalized = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } => {
      const el = surfaceRef.current;
      const rect = el?.getBoundingClientRect();
      const width = rect && rect.width > 0 ? rect.width : pageDims.width;
      const height = rect && rect.height > 0 ? rect.height : pageDims.height;
      const left = rect ? rect.left : 0;
      const top = rect ? rect.top : 0;

      const x = Math.min(1, Math.max(0, (clientX - left) / width));
      const y = Math.min(1, Math.max(0, (clientY - top) / height));
      return { x, y };
    },
    [pageDims.height, pageDims.width],
  );

  const handleMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    if (!active) return;
    if ((e.target as HTMLElement).closest("[data-annotation-popover='true']")) {
      return;
    }
    e.preventDefault();
    const point = clientToNormalized(e.clientX, e.clientY);
    setDragStart(point);
    setDragCurrent(point);
    setPending(null);
    setValidationError(null);
  };

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!active || !dragStart) return;
    const point = clientToNormalized(e.clientX, e.clientY);
    setDragCurrent(point);
  };

  const finalizeDrag = (e: MouseEvent<HTMLDivElement>) => {
    if (!active || !dragStart) return;
    const endPoint = clientToNormalized(e.clientX, e.clientY);
    const normRect: NormalizedRect = {
      x0: Math.min(dragStart.x, endPoint.x),
      y0: Math.min(dragStart.y, endPoint.y),
      x1: Math.max(dragStart.x, endPoint.x),
      y1: Math.max(dragStart.y, endPoint.y),
    };
    setDragStart(null);
    setDragCurrent(null);

    const { pdfRect, detailCoords } = convertNormalizedRectToPdfAndDetail(
      normRect,
      orientation,
    );

    // Ignora cliques acidentais muito pequenos (< 4 pt em ambos os eixos)
    if (pdfRect.width < 4 && pdfRect.height < 4) {
      return;
    }

    setPending({ normRect, pdfRect, detailCoords });
    setNoteText("");
    setValidationError(null);
  };

  const handleCancelPending = () => {
    setPending(null);
    setNoteText("");
    setValidationError(null);
  };

  const handleSend = async () => {
    if (!pending) return;
    const trimmed = noteText.trim();
    if (!trimmed) {
      setValidationError("Descreva o ajuste desejado antes de enviar.");
      return;
    }
    setValidationError(null);
    await onSubmitAnnotation({
      page,
      pdfRect: pending.pdfRect,
      detailCoords: pending.detailCoords,
      content: trimmed,
    });
    setPending(null);
    setNoteText("");
    onRequestExitSelection?.();
  };

  const activeBox: NormalizedRect | null =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : pending?.normRect ?? null;

  const pageAnnotations = annotations.filter((ann) => ann.page === page);

  return (
    <div
      ref={surfaceRef}
      data-testid="region-selection-surface"
      aria-label={
        active
          ? "Área de seleção visual de ajuste sobre a página"
          : "Camada de anotações visuais"
      }
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={finalizeDrag}
      className={cn(
        "absolute inset-0 z-10",
        active
          ? "cursor-crosshair select-none"
          : "pointer-events-none",
      )}
    >
      {/* Marcadores visíveis nesta página */}
      {pageAnnotations.map((ann, idx) => {
        const leftPct = (ann.pdfRect.x0 / pageDims.width) * 100;
        const topPct = (ann.pdfRect.y0 / pageDims.height) * 100;
        const widthPct = (ann.pdfRect.width / pageDims.width) * 100;
        const heightPct = (ann.pdfRect.height / pageDims.height) * 100;
        const isResolved = ann.resolved === true;

        return (
          <div
            key={ann.id}
            data-testid="region-annotation-box"
            data-resolved={isResolved ? "true" : "false"}
            title={`#${idx + 1}${isResolved ? " (Resolvido)" : ""}: ${ann.content}`}
            style={{
              left: `${leftPct}%`,
              top: `${topPct}%`,
              width: `${widthPct}%`,
              height: `${heightPct}%`,
            }}
            className={cn(
              "pointer-events-none absolute border-2",
              isResolved
                ? "border-dashed border-ink-muted/60 bg-ink-muted/10"
                : "border-blueprint bg-blueprint/12",
            )}
          >
            <span
              className={cn(
                "absolute -top-5 left-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white shadow-xs",
                isResolved ? "bg-ink-muted" : "bg-blueprint",
              )}
            >
              #{idx + 1}
              {isResolved ? " ✓" : ""}
            </span>
          </div>
        );
      })}

      {/* Dica flutuante quando modo de seleção está ligado */}
      {active && !pending && !dragStart && (
        <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-1.5 rounded-md border border-accent/40 bg-surface/95 px-2.5 py-1 text-[11px] font-medium text-accent shadow-sm">
          <Crosshair className="h-3.5 w-3.5" />
          <span>
            Arraste um retângulo sobre a área que deseja ajustar (Esc para sair)
          </span>
        </div>
      )}

      {/* Retângulo atual sendo desenhado ou aguardando texto */}
      {activeBox && (
        <div
          data-testid="region-selection-box"
          style={{
            left: `${activeBox.x0 * 100}%`,
            top: `${activeBox.y0 * 100}%`,
            width: `${Math.max(0.5, (activeBox.x1 - activeBox.x0) * 100)}%`,
            height: `${Math.max(0.5, (activeBox.y1 - activeBox.y0) * 100)}%`,
          }}
          className="pointer-events-none absolute border-2 border-dashed border-accent bg-accent/15 shadow-xs"
        />
      )}

      {/* Popover / Card de anotação após soltar o retângulo */}
      {pending && (
        <div
          data-annotation-popover="true"
          data-testid="region-annotation-popover"
          role="dialog"
          aria-label="Solicitar ajuste visual"
          style={{
            left: `${Math.min(52, Math.max(2, pending.normRect.x0 * 100))}%`,
            top: `${Math.min(62, Math.max(4, pending.normRect.y1 * 100 + 2))}%`,
          }}
          className="pointer-events-auto absolute z-20 w-80 max-w-[92%] cursor-default rounded-lg border border-border-strong bg-surface-elevated p-3 text-left shadow-xl"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <h4 className="text-xs font-semibold text-ink">
                Solicitar ajuste visual
              </h4>
              <p className="text-[11px] text-ink-muted">
                Página {page} · Cenário{" "}
                <span className="font-mono">{scenario}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={handleCancelPending}
              aria-label="Cancelar seleção de área"
              className="rounded p-0.5 text-ink-muted hover:bg-surface-subtle hover:text-ink cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[10px] tabular-nums">
            <Badge tone="neutral" className="font-mono text-[10px]">
              PDF ({pending.pdfRect.x0}, {pending.pdfRect.y0}) → (
              {pending.pdfRect.x1}, {pending.pdfRect.y1})
            </Badge>
            <Badge tone="accent" className="font-mono text-[10px]">
              &lt;detail&gt; x={pending.detailCoords.x}, y=
              {pending.detailCoords.y} ({pending.detailCoords.width}×
              {pending.detailCoords.height})
            </Badge>
          </div>

          <div className="mt-2.5">
            <FieldLabel htmlFor="region-annotation-input">
              Pedido de ajuste para o agente
            </FieldLabel>
            <Textarea
              id="region-annotation-input"
              aria-label="Pedido de ajuste visual"
              value={noteText}
              onChange={(e) => {
                setNoteText(e.target.value);
                if (validationError) setValidationError(null);
              }}
              placeholder="Ex.: esses 3 checkboxes ficaram colados, espaçar horizontalmente"
              className="min-h-[64px] text-xs"
              autoFocus
            />
            {validationError && (
              <p className="mt-1 text-[11px] text-danger">{validationError}</p>
            )}
          </div>

          <div className="mt-2.5 flex items-center justify-end gap-1.5">
            <Button
              variant="ghost"
              size="xs"
              onClick={handleCancelPending}
              disabled={submitting}
            >
              Cancelar
            </Button>
            <Button
              variant="primary"
              size="xs"
              loading={submitting}
              icon={<Send className="h-3 w-3" />}
              onClick={() => void handleSend()}
            >
              Enviar ajuste ao agente
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
