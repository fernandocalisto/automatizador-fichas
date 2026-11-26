import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  FileImage,
  FileText,
  MessageSquare,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Badge, Button, EmptyState, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type {
  ClinicalOrientation,
  JasperPreviewResponse,
  ScenarioType,
} from "@/types/studio";
import {
  RegionAnnotationOverlay,
  type RegionAnnotationSubmitPayload,
} from "./RegionAnnotationOverlay";
import {
  ZOOM_PRESETS,
  type PreviewRendererMode,
  type VisualRegionAnnotation,
  type ZoomPreset,
} from "./types";
import { getPageDimensions, isJsdomRuntime } from "./utils";

export interface PdfPreviewCanvasProps {
  projectId: string;
  hasJrxml: boolean;
  scenario: ScenarioType;
  orientation: ClinicalOrientation;
  previewResult: JasperPreviewResponse | null;
  previewLoading: boolean;
  cacheBuster: number;
  annotations: VisualRegionAnnotation[];
  submittingAnnotation: boolean;
  onSubmitAnnotation: (payload: RegionAnnotationSubmitPayload) => Promise<void>;
  onGeneratePreview: () => void;
}

const NUMERIC_ZOOMS: number[] = [0.75, 1, 1.25, 1.5];

export function PdfPreviewCanvas({
  projectId,
  hasJrxml,
  scenario,
  orientation,
  previewResult,
  previewLoading,
  cacheBuster,
  annotations,
  submittingAnnotation,
  onSubmitAnnotation,
  onGeneratePreview,
}: PdfPreviewCanvasProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [zoom, setZoom] = useState<ZoomPreset>("fit-width");
  const [containerWidth, setContainerWidth] = useState<number>(640);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pdfNumPages, setPdfNumPages] = useState<number | null>(null);
  const [rendererMode, setRendererMode] =
    useState<PreviewRendererMode>("pdfjs");
  const [selectionMode, setSelectionMode] = useState<boolean>(false);
  const [pdfRenderError, setPdfRenderError] = useState<string | null>(null);
  const [renderingPage, setRenderingPage] = useState<boolean>(false);
  const [annotationsExpanded, setAnnotationsExpanded] = useState<boolean>(true);

  const pageDims = getPageDimensions(orientation);
  const totalPages = Math.max(
    1,
    pdfNumPages ?? previewResult?.page_count ?? 1,
  );

  useEffect(() => {
    setCurrentPage((prev) => Math.min(Math.max(1, prev), totalPages));
  }, [totalPages]);

  useEffect(() => {
    setCurrentPage(1);
    setPdfNumPages(null);
    setPdfRenderError(null);
  }, [projectId, scenario, cacheBuster]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const updateWidth = () => {
      const next = el.clientWidth;
      if (next > 0) setContainerWidth(next);
    };
    updateWidth();
    const obs = new ResizeObserver(updateWidth);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const effectiveScale = useMemo(() => {
    if (zoom === "fit-width") {
      const available = Math.max(280, containerWidth - 48);
      const fit = available / pageDims.width;
      return Math.min(1.5, Math.max(0.45, Number(fit.toFixed(3))));
    }
    return zoom;
  }, [zoom, containerWidth, pageDims.width]);

  const pdfUrl = useMemo(
    () => api.getPreviewPdfUrl(projectId, scenario, cacheBuster),
    [projectId, scenario, cacheBuster],
  );

  const pngUrl = useMemo(
    () => api.getPreviewPageUrl(projectId, currentPage, scenario, cacheBuster),
    [projectId, currentPage, scenario, cacheBuster],
  );

  // Renderização PDF.js no navegador real (ignorada com fallback limpo em jsdom)
  useEffect(() => {
    if (!previewResult || rendererMode !== "pdfjs") return;
    if (isJsdomRuntime()) return;

    let cancelled = false;
    let activeRenderTask: { cancel?: () => void } | null = null;
    let loadingTask: {
      promise: Promise<unknown>;
      destroy?: () => Promise<void>;
    } | null = null;

    const renderPdfPage = async () => {
      setRenderingPage(true);
      setPdfRenderError(null);
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();

        loadingTask = pdfjs.getDocument({ url: pdfUrl }) as unknown as {
          promise: Promise<unknown>;
          destroy?: () => Promise<void>;
        };
        const pdfDoc = (await loadingTask.promise) as {
          numPages: number;
          getPage: (pageNumber: number) => Promise<{
            getViewport: (opts: { scale: number }) => {
              width: number;
              height: number;
            };
            render: (params: {
              canvas: HTMLCanvasElement;
              viewport: { width: number; height: number };
              transform?: number[];
            }) => { promise: Promise<void>; cancel?: () => void };
          }>;
          destroy?: () => Promise<void>;
        };

        if (cancelled) {
          await pdfDoc.destroy?.();
          return;
        }

        setPdfNumPages(pdfDoc.numPages);
        const safePage = Math.min(Math.max(1, currentPage), pdfDoc.numPages);
        const page = await pdfDoc.getPage(safePage);
        if (cancelled) {
          await pdfDoc.destroy?.();
          return;
        }

        const canvas = canvasRef.current;
        if (!canvas) {
          await pdfDoc.destroy?.();
          return;
        }

        const viewport = page.getViewport({ scale: effectiveScale });
        const dpr =
          typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;

        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        const renderTask = page.render({
          canvas,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        activeRenderTask = renderTask;
        await renderTask.promise;
        await pdfDoc.destroy?.();
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof Error
              ? err.message
              : "Falha ao renderizar o PDF com PDF.js.";
          setPdfRenderError(message);
        }
      } finally {
        if (!cancelled) {
          setRenderingPage(false);
        }
      }
    };

    void renderPdfPage();

    return () => {
      cancelled = true;
      activeRenderTask?.cancel?.();
      void loadingTask?.destroy?.();
    };
  }, [previewResult, rendererMode, pdfUrl, currentPage, effectiveScale]);

  const handleStepZoom = (direction: -1 | 1) => {
    const currentNum = zoom === "fit-width" ? effectiveScale : zoom;
    if (direction > 0) {
      const next =
        NUMERIC_ZOOMS.find((z) => z > currentNum + 0.01) ??
        NUMERIC_ZOOMS[NUMERIC_ZOOMS.length - 1];
      setZoom(next);
    } else {
      const reversed = [...NUMERIC_ZOOMS].reverse();
      const prev =
        reversed.find((z) => z < currentNum - 0.01) ?? NUMERIC_ZOOMS[0];
      setZoom(prev);
    }
  };

  const displayWidth = Math.round(pageDims.width * effectiveScale);
  const displayHeight = Math.round(pageDims.height * effectiveScale);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-canvas">
      {/* Barra de controles do visualizador (zoom, páginas, modo PDF.js/PNG, seleção de área) */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-3 py-1.5">
        {/* Zoom */}
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label="Diminuir zoom"
            onClick={() => handleStepZoom(-1)}
            disabled={!previewResult}
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
          <Select
            aria-label="Nível de zoom do preview"
            value={String(zoom)}
            onChange={(e) => {
              const raw = e.target.value;
              setZoom(raw === "fit-width" ? "fit-width" : (Number(raw) as ZoomPreset));
            }}
            className="h-7 w-36 text-xs"
            disabled={!previewResult}
          >
            {ZOOM_PRESETS.map((preset) => (
              <option key={String(preset.value)} value={String(preset.value)}>
                {preset.label}
              </option>
            ))}
          </Select>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label="Aumentar zoom"
            onClick={() => handleStepZoom(1)}
            disabled={!previewResult}
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Navegação de páginas */}
        <div className="flex items-center gap-1.5">
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7"
            aria-label="Página anterior"
            disabled={!previewResult || currentPage <= 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span
            data-testid="preview-page-indicator"
            className="min-w-[84px] text-center text-xs font-medium text-ink-secondary tabular-nums"
          >
            Página {currentPage} de {totalPages}
          </span>
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7"
            aria-label="Próxima página"
            disabled={!previewResult || currentPage >= totalPages}
            onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Alternância PDF.js / PNG + Selecionar área */}
        <div className="flex flex-wrap items-center gap-1.5">
          <div
            role="group"
            aria-label="Modo de renderização do preview"
            className="inline-flex rounded-md border border-border bg-surface-subtle p-0.5"
          >
            <button
              type="button"
              onClick={() => setRendererMode("pdfjs")}
              aria-pressed={rendererMode === "pdfjs"}
              className={cn(
                "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                rendererMode === "pdfjs"
                  ? "bg-surface text-ink shadow-xs"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              <FileText className="h-3 w-3" />
              PDF.js
            </button>
            <button
              type="button"
              onClick={() => setRendererMode("png")}
              aria-pressed={rendererMode === "png"}
              className={cn(
                "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                rendererMode === "png"
                  ? "bg-surface text-ink shadow-xs"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              <FileImage className="h-3 w-3" />
              PNG
            </button>
          </div>

          <Button
            variant={selectionMode ? "primary" : "outline"}
            size="xs"
            aria-pressed={selectionMode}
            disabled={!previewResult}
            icon={<Crosshair className="h-3.5 w-3.5" />}
            onClick={() => setSelectionMode((prev) => !prev)}
          >
            Selecionar área para ajuste
          </Button>
        </div>
      </div>

      {/* Viewport rolável com a folha A4 renderizada */}
      <div
        ref={viewportRef}
        className="relative flex min-h-0 flex-1 flex-col items-center overflow-auto bg-surface-subtle/60 p-5"
      >
        {!hasJrxml ? (
          <EmptyState
            className="my-auto max-w-md"
            icon={<FileText className="h-5 w-5 text-ink-muted" />}
            title="Aguardando arquivo .jrxml"
            description="Gere o scaffold base no painel esquerdo para habilitar a compilação e a pré-visualização PDF."
          />
        ) : !previewResult && !previewLoading ? (
          <EmptyState
            className="my-auto max-w-md"
            icon={<FileText className="h-5 w-5 text-blueprint" />}
            title="Preview PDF ainda não gerado"
            description="Escolha um cenário fictício acima e clique em Atualizar preview para renderizar a ficha clínica."
            action={
              <Button variant="primary" size="sm" onClick={onGeneratePreview}>
                Gerar preview agora
              </Button>
            }
          />
        ) : (
          <>
            {pdfRenderError && rendererMode === "pdfjs" && (
              <div
                role="alert"
                className="mb-3 flex max-w-xl items-center justify-between gap-3 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-xs text-warning"
              >
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>
                    PDF.js indisponível ({pdfRenderError}). Alterne para PNG
                    para inspecionar a página renderizada pelo servidor.
                  </span>
                </div>
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => setRendererMode("png")}
                >
                  Usar PNG
                </Button>
              </div>
            )}

            <div
              data-testid="preview-page-container"
              style={{ width: `${displayWidth}px`, height: `${displayHeight}px` }}
              className="relative shrink-0 overflow-visible rounded border border-border-strong bg-white shadow-md"
            >
              {rendererMode === "png" ? (
                <img
                  src={pngUrl}
                  alt={`Preview PNG da página ${currentPage} (${scenario})`}
                  className="h-full w-full select-none object-contain"
                  draggable={false}
                />
              ) : (
                <>
                  <canvas
                    ref={canvasRef}
                    data-testid="pdf-preview-canvas"
                    aria-label={`Preview PDF página ${currentPage} de ${totalPages}`}
                    className="block h-full w-full"
                  />
                  {isJsdomRuntime() && (
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center p-4 text-center text-xs text-ink-muted">
                      <span className="font-semibold text-ink">
                        Preview PDF.js ({scenario})
                      </span>
                      <span className="mt-1 font-mono text-[11px]">
                        Página {currentPage} de {totalPages} · {pageDims.width}×
                        {pageDims.height} pt
                      </span>
                    </div>
                  )}
                </>
              )}

              {(previewLoading || renderingPage) && (
                <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-surface/55 backdrop-blur-[1px]">
                  <span className="rounded-md border border-border bg-surface-elevated px-3 py-1.5 text-xs font-medium text-ink shadow-sm">
                    Renderizando preview...
                  </span>
                </div>
              )}

              <RegionAnnotationOverlay
                active={selectionMode}
                page={currentPage}
                scenario={scenario}
                orientation={orientation}
                annotations={annotations}
                submitting={submittingAnnotation}
                onSubmitAnnotation={onSubmitAnnotation}
              />
            </div>
          </>
        )}
      </div>

      {/* Lista de anotações visuais enviadas na sessão */}
      {annotations.length > 0 && (
        <section
          aria-label="Anotações visuais enviadas na sessão"
          className="shrink-0 border-t border-border bg-surface"
        >
          <button
            type="button"
            onClick={() => setAnnotationsExpanded((v) => !v)}
            className="flex w-full items-center justify-between bg-surface-subtle/60 px-3 py-1.5 text-left text-xs font-semibold text-ink hover:bg-surface-subtle cursor-pointer"
          >
            <span className="flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5 text-accent" />
              Ajustes visuais enviados ao agente
              <Badge tone="accent" className="tabular-nums">
                {annotations.length}
              </Badge>
            </span>
            <span className="text-[11px] font-normal text-ink-muted">
              {annotationsExpanded ? "Recolher" : "Expandir"}
            </span>
          </button>

          {annotationsExpanded && (
            <ul className="max-h-36 divide-y divide-border/70 overflow-y-auto px-3 py-1.5 text-xs">
              {annotations.map((ann, idx) => (
                <li
                  key={ann.id}
                  className="flex items-start justify-between gap-2 py-1.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone="blueprint" className="font-mono text-[10px]">
                        #{idx + 1} · Pág. {ann.page}
                      </Badge>
                      <span className="font-mono text-[10px] text-ink-muted tabular-nums">
                        detail({ann.detailCoords.x}, {ann.detailCoords.y},{" "}
                        {ann.detailCoords.width}×{ann.detailCoords.height})
                      </span>
                      <Badge tone="neutral" className="text-[10px]">
                        {ann.scenario}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-ink-secondary break-words">
                      {ann.content}
                    </p>
                  </div>
                  {ann.page !== currentPage && (
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => setCurrentPage(ann.page)}
                    >
                      Ir pág. {ann.page}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
