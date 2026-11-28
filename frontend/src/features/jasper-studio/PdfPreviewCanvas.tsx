import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Eye,
  EyeOff,
  FileImage,
  FileText,
  Maximize2,
  MessageSquare,
  Minimize2,
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
  suppressFetch?: boolean;
  cacheBuster: number;
  annotations: VisualRegionAnnotation[];
  submittingAnnotation: boolean;
  resolvingAnnotations?: boolean;
  onSubmitAnnotation: (payload: RegionAnnotationSubmitPayload) => Promise<void>;
  onResolveAnnotations?: (messageIds?: number[]) => Promise<void>;
  onGeneratePreview: () => void;
  onOpenAgentChat?: () => void;
}

const NUMERIC_ZOOMS: Exclude<ZoomPreset, "fit-width" | "fit-page">[] = [
  0.75, 1, 1.25, 1.5, 2,
];

export function PdfPreviewCanvas({
  projectId,
  hasJrxml,
  scenario,
  orientation,
  previewResult,
  previewLoading,
  suppressFetch = false,
  cacheBuster,
  annotations,
  submittingAnnotation,
  resolvingAnnotations = false,
  onSubmitAnnotation,
  onResolveAnnotations,
  onGeneratePreview,
  onOpenAgentChat,
}: PdfPreviewCanvasProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const annotationsMenuRef = useRef<HTMLDivElement | null>(null);

  const [zoom, setZoom] = useState<ZoomPreset>("fit-width");
  const [containerSize, setContainerSize] = useState<{
    width: number;
    height: number;
  }>({ width: 640, height: 760 });
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pdfNumPages, setPdfNumPages] = useState<number | null>(null);
  const [rendererMode, setRendererMode] =
    useState<PreviewRendererMode>("pdfjs");
  const [selectionMode, setSelectionMode] = useState<boolean>(false);
  const [pdfRenderError, setPdfRenderError] = useState<string | null>(null);
  const [renderingPage, setRenderingPage] = useState<boolean>(false);

  // Controle de popover e visibilidade das anotações visuais
  const [annotationsPopoverOpen, setAnnotationsPopoverOpen] =
    useState<boolean>(false);
  const [showBoxesOnPdf, setShowBoxesOnPdf] = useState<boolean>(true);
  const [showResolvedHistory, setShowResolvedHistory] =
    useState<boolean>(false);
  const [showResolvedOnPdf, setShowResolvedOnPdf] = useState<boolean>(false);

  // Nunca usar o cenário recém-clicado antes do POST /jasper/preview retornar o PDF dele
  const effectiveScenario = previewResult?.scenario ?? scenario;
  const isWaitingScenarioPreview =
    suppressFetch ||
    (previewLoading && previewResult?.scenario !== scenario);

  const pageDims = getPageDimensions(orientation);
  const totalPages = Math.max(
    1,
    pdfNumPages ?? previewResult?.page_count ?? 1,
  );

  const pendingAnnotations = useMemo(
    () => annotations.filter((ann) => ann.resolved !== true),
    [annotations],
  );
  const resolvedAnnotations = useMemo(
    () => annotations.filter((ann) => ann.resolved === true),
    [annotations],
  );
  const visibleAnnotations = useMemo(() => {
    if (!showBoxesOnPdf) return [];
    if (showResolvedOnPdf) return annotations;
    return pendingAnnotations;
  }, [annotations, pendingAnnotations, showBoxesOnPdf, showResolvedOnPdf]);

  useEffect(() => {
    setCurrentPage((prev) => Math.min(Math.max(1, prev), totalPages));
  }, [totalPages]);

  useEffect(() => {
    setCurrentPage(1);
    setPdfNumPages(null);
    setPdfRenderError(null);
  }, [projectId, effectiveScenario, cacheBuster]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const updateSize = () => {
      const nextW = el.clientWidth;
      const nextH = el.clientHeight;
      if (nextW > 0 || nextH > 0) {
        setContainerSize((prev) => ({
          width: nextW > 0 ? nextW : prev.width,
          height: nextH > 0 ? nextH : prev.height,
        }));
      }
    };
    updateSize();
    const obs = new ResizeObserver(updateSize);
    obs.observe(el);
    return () => obs.disconnect();
  }, [isFullscreen]);

  // Fecha popover de ajustes com clique fora ou Escape
  useEffect(() => {
    if (!annotationsPopoverOpen) return;
    const handleOutside = (event: MouseEvent) => {
      if (
        annotationsMenuRef.current &&
        !annotationsMenuRef.current.contains(event.target as Node)
      ) {
        setAnnotationsPopoverOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAnnotationsPopoverOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [annotationsPopoverOpen]);

  // Tecla Escape sai do modo tela cheia quando não está em modo de seleção ou popover aberto
  useEffect(() => {
    if (!isFullscreen) return;
    const handleKey = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !selectionMode &&
        !annotationsPopoverOpen
      ) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [annotationsPopoverOpen, isFullscreen, selectionMode]);

  const effectiveScale = useMemo(() => {
    if (zoom === "fit-page") {
      const availW = Math.max(240, containerSize.width - 24);
      const availH = Math.max(240, containerSize.height - 24);
      const fit = Math.min(availW / pageDims.width, availH / pageDims.height);
      return Math.min(2.2, Math.max(0.35, Number(fit.toFixed(3))));
    }
    if (zoom === "fit-width") {
      const availW = Math.max(240, containerSize.width - 24);
      const fit = availW / pageDims.width;
      return Math.min(2.2, Math.max(0.5, Number(fit.toFixed(3))));
    }
    return zoom;
  }, [zoom, containerSize.width, containerSize.height, pageDims.width, pageDims.height]);

  const pdfUrl = useMemo(
    () => api.getPreviewPdfUrl(projectId, effectiveScenario, cacheBuster),
    [projectId, effectiveScenario, cacheBuster],
  );

  const pngUrl = useMemo(
    () =>
      api.getPreviewPageUrl(
        projectId,
        currentPage,
        effectiveScenario,
        cacheBuster,
      ),
    [projectId, currentPage, effectiveScenario, cacheBuster],
  );

  // Renderização PDF.js no navegador real (ignorada com fallback limpo em jsdom)
  useEffect(() => {
    if (!previewResult || rendererMode !== "pdfjs") return;
    if (isWaitingScenarioPreview) return;
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
  }, [
    previewResult,
    rendererMode,
    pdfUrl,
    currentPage,
    effectiveScale,
    isWaitingScenarioPreview,
  ]);

  const handleStepZoom = (direction: -1 | 1) => {
    const currentNum = typeof zoom === "number" ? zoom : effectiveScale;
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

  const handleSubmitAndExitSelection = useCallback(
    async (payload: RegionAnnotationSubmitPayload) => {
      await onSubmitAnnotation(payload);
      setSelectionMode(false);
    },
    [onSubmitAnnotation],
  );

  const displayWidth = Math.round(pageDims.width * effectiveScale);
  const displayHeight = Math.round(pageDims.height * effectiveScale);

  return (
    <div
      data-testid="pdf-preview-root"
      data-fullscreen={isFullscreen ? "true" : "false"}
      className={cn(
        "flex min-h-0 flex-1 flex-col bg-canvas",
        isFullscreen && "fixed inset-0 z-50 h-screen w-screen shadow-2xl",
      )}
    >
      {/* Barra de controles do visualizador (zoom, fit-page/width, páginas, PDF.js/PNG, ajustes, seleção, tela cheia) */}
      <div className="flex flex-wrap items-center justify-between gap-1.5 border-b border-border bg-surface px-2.5 py-1">
        {/* Zoom + atalhos 1-clique Página inteira / Largura */}
        <div className="flex flex-wrap items-center gap-1">
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
              if (raw === "fit-width" || raw === "fit-page") {
                setZoom(raw);
              } else {
                setZoom(Number(raw) as ZoomPreset);
              }
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

          <div
            role="group"
            aria-label="Ajuste rápido de zoom"
            className="ml-0.5 inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-subtle p-0.5"
          >
            <button
              type="button"
              disabled={!previewResult}
              aria-pressed={zoom === "fit-page"}
              onClick={() => setZoom("fit-page")}
              title="Ajustar página inteira na tela"
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors cursor-pointer disabled:pointer-events-none disabled:opacity-50",
                zoom === "fit-page"
                  ? "bg-surface text-ink shadow-xs"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              Página inteira
            </button>
            <button
              type="button"
              disabled={!previewResult}
              aria-pressed={zoom === "fit-width"}
              onClick={() => setZoom("fit-width")}
              title="Ajustar à largura disponível"
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors cursor-pointer disabled:pointer-events-none disabled:opacity-50",
                zoom === "fit-width"
                  ? "bg-surface text-ink shadow-xs"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              Largura
            </button>
          </div>
        </div>

        {/* Navegação de páginas */}
        <div className="flex items-center gap-1">
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
            className="min-w-[82px] text-center text-xs font-medium text-ink-secondary tabular-nums"
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

        {/* Alternância PDF.js / PNG + Ajustes (popover) + Selecionar área + Tela cheia */}
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

          {/* Botão compacto Ajustes (N) com popover */}
          {annotations.length > 0 && (
            <div ref={annotationsMenuRef} className="relative">
              <Button
                variant={pendingAnnotations.length > 0 ? "blueprint" : "outline"}
                size="xs"
                aria-haspopup="dialog"
                aria-expanded={annotationsPopoverOpen}
                aria-label={`Ajustes (${pendingAnnotations.length})`}
                icon={<MessageSquare className="h-3.5 w-3.5" />}
                onClick={() => setAnnotationsPopoverOpen((prev) => !prev)}
              >
                <span>Ajustes</span>
                <Badge
                  tone={pendingAnnotations.length > 0 ? "accent" : "neutral"}
                  className="ml-0.5 px-1.5 py-0 text-[10px] tabular-nums"
                >
                  {pendingAnnotations.length}
                </Badge>
              </Button>

              {annotationsPopoverOpen && (
                <div
                  data-testid="annotations-popover"
                  role="dialog"
                  aria-label="Ajustes visuais da sessão"
                  className="absolute right-0 z-50 mt-1.5 w-96 max-w-[92vw] overflow-hidden rounded-lg border border-border-strong bg-surface-elevated shadow-xl"
                >
                  {/* Cabeçalho do popover */}
                  <div className="flex items-center justify-between gap-2 border-b border-border bg-surface-subtle/70 px-3 py-2">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                      <MessageSquare className="h-3.5 w-3.5 text-accent" />
                      <span>Ajustes visuais</span>
                      <Badge tone="accent" className="py-0 text-[10px] tabular-nums">
                        {pendingAnnotations.length} pendente
                        {pendingAnnotations.length === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-1">
                      {pendingAnnotations.length > 0 && onResolveAnnotations && (
                        <Button
                          variant="outline"
                          size="xs"
                          loading={resolvingAnnotations}
                          disabled={resolvingAnnotations}
                          icon={<CheckCheck className="h-3 w-3" />}
                          onClick={() => void onResolveAnnotations()}
                        >
                          Limpar / Resolver
                        </Button>
                      )}
                      {onOpenAgentChat && (
                        <Button
                          variant="primary"
                          size="xs"
                          icon={<Bot className="h-3 w-3" />}
                          onClick={() => {
                            setAnnotationsPopoverOpen(false);
                            onOpenAgentChat();
                          }}
                        >
                          Abrir Chat IA
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Controles de visibilidade no PDF */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-3 py-1.5 text-[11px] text-ink-secondary">
                    <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={showBoxesOnPdf}
                        onChange={(e) => setShowBoxesOnPdf(e.target.checked)}
                        className="h-3.5 w-3.5 accent-accent cursor-pointer"
                      />
                      <span className="inline-flex items-center gap-1">
                        {showBoxesOnPdf ? (
                          <Eye className="h-3 w-3 text-blueprint" />
                        ) : (
                          <EyeOff className="h-3 w-3 text-ink-muted" />
                        )}
                        Mostrar caixas no PDF
                      </span>
                    </label>

                    {resolvedAnnotations.length > 0 && showBoxesOnPdf && (
                      <label className="inline-flex items-center gap-1.5 cursor-pointer select-none text-ink-muted">
                        <input
                          type="checkbox"
                          checked={showResolvedOnPdf}
                          onChange={(e) =>
                            setShowResolvedOnPdf(e.target.checked)
                          }
                          className="h-3 w-3 accent-accent cursor-pointer"
                        />
                        <span>Mostrar histórico no PDF</span>
                      </label>
                    )}
                  </div>

                  {/* Lista de ajustes pendentes */}
                  <div className="max-h-72 overflow-y-auto px-3 py-2">
                    {pendingAnnotations.length === 0 ? (
                      <p className="py-2 text-center text-xs text-ink-muted">
                        Nenhum ajuste pendente no momento.
                      </p>
                    ) : (
                      <ul className="divide-y divide-border/70 text-xs">
                        {pendingAnnotations.map((ann, idx) => (
                          <li
                            key={ann.id}
                            className="flex items-start justify-between gap-2 py-2 first:pt-0 last:pb-0"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <Badge
                                  tone="blueprint"
                                  className="font-mono text-[10px]"
                                >
                                  #{idx + 1} · Pág. {ann.page}
                                </Badge>
                                <span className="font-mono text-[10px] text-ink-muted tabular-nums">
                                  detail({ann.detailCoords.x},{" "}
                                  {ann.detailCoords.y},{" "}
                                  {ann.detailCoords.width}×
                                  {ann.detailCoords.height})
                                </span>
                                <Badge tone="neutral" className="text-[10px]">
                                  {ann.scenario}
                                </Badge>
                              </div>
                              <p className="mt-1 text-ink-secondary break-words">
                                {ann.content}
                              </p>
                            </div>
                            <div className="flex shrink-0 flex-col items-end gap-1">
                              {ann.page !== currentPage && (
                                <Button
                                  variant="ghost"
                                  size="xs"
                                  onClick={() => setCurrentPage(ann.page)}
                                >
                                  Ir pág. {ann.page}
                                </Button>
                              )}
                              {onResolveAnnotations &&
                                typeof ann.id === "number" && (
                                  <Button
                                    variant="ghost"
                                    size="xs"
                                    disabled={resolvingAnnotations}
                                    onClick={() =>
                                      void onResolveAnnotations([
                                        ann.id as number,
                                      ])
                                    }
                                    title="Marcar este ajuste como resolvido"
                                  >
                                    Resolver
                                  </Button>
                                )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}

                    {/* Histórico colapsável de ajustes resolvidos */}
                    {resolvedAnnotations.length > 0 && (
                      <div className="mt-2 border-t border-border pt-2">
                        <button
                          type="button"
                          aria-expanded={showResolvedHistory}
                          onClick={() => setShowResolvedHistory((v) => !v)}
                          className="flex w-full items-center justify-between text-[11px] font-medium text-ink-muted hover:text-ink cursor-pointer"
                        >
                          <span className="inline-flex items-center gap-1">
                            <ChevronDown
                              className={cn(
                                "h-3 w-3 transition-transform",
                                !showResolvedHistory && "-rotate-90",
                              )}
                            />
                            Histórico resolvido ({resolvedAnnotations.length})
                          </span>
                        </button>
                        {showResolvedHistory && (
                          <ul className="mt-1.5 space-y-1.5 text-[11px] text-ink-muted">
                            {resolvedAnnotations.map((ann) => (
                              <li
                                key={ann.id}
                                className="rounded border border-border/60 bg-surface-subtle/50 px-2 py-1.5"
                              >
                                <div className="flex items-center justify-between gap-1">
                                  <span className="font-mono text-[10px]">
                                    ✓ Pág. {ann.page} · {ann.scenario}
                                  </span>
                                  {ann.page !== currentPage && (
                                    <button
                                      type="button"
                                      onClick={() => setCurrentPage(ann.page)}
                                      className="text-[10px] text-blueprint hover:underline cursor-pointer"
                                    >
                                      Ir pág. {ann.page}
                                    </button>
                                  )}
                                </div>
                                <p className="mt-0.5 break-words line-through opacity-80">
                                  {ann.content}
                                </p>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

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

          <Button
            variant={isFullscreen ? "primary" : "outline"}
            size="icon"
            className="h-7 w-7"
            aria-label={
              isFullscreen ? "Sair da tela cheia" : "Expandir em tela cheia"
            }
            aria-pressed={isFullscreen}
            title={
              isFullscreen
                ? "Sair da tela cheia (Esc)"
                : "Expandir PDF em tela cheia"
            }
            disabled={!previewResult}
            onClick={() => setIsFullscreen((prev) => !prev)}
          >
            {isFullscreen ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </div>

      {/* Viewport rolável com a folha A4 renderizada (padding compacto p-2.5) */}
      <div
        ref={viewportRef}
        className="relative flex min-h-0 flex-1 flex-col items-center overflow-auto bg-surface-subtle/60 p-2.5"
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
                  alt={`Preview PNG da página ${currentPage} (${effectiveScenario})`}
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
                        Preview PDF.js ({effectiveScenario})
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
                scenario={effectiveScenario}
                orientation={orientation}
                annotations={visibleAnnotations}
                submitting={submittingAnnotation}
                onSubmitAnnotation={handleSubmitAndExitSelection}
                onRequestExitSelection={() => setSelectionMode(false)}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
