import { Fragment, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Bot,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Crosshair,
  FileCheck2,
  Loader2,
  ShieldCheck,
  User,
} from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { StudioSection } from "@/types/studio";
import {
  getHarnessLabel,
  type ChatTimelineItem,
  type SyncedArtifactInfo,
} from "./sseClient";
import { ToolCallCard } from "./ToolCallCard";

export interface MessageBubbleProps {
  message: ChatTimelineItem;
  onNavigateSection: (section: StudioSection) => void;
}

interface ParsedVisualFeedback {
  page: number;
  scenario?: string;
  cropUrl?: string;
  pdfRect?: {
    x0: number;
    y0: number;
    x1: number;
    y1: number;
    width?: number;
    height?: number;
  };
  detailCoords?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

function parseVisualRegionFeedback(
  metadata?: Record<string, unknown>,
): ParsedVisualFeedback | null {
  if (!metadata || metadata.type !== "visual_region_feedback") {
    return null;
  }

  const rawRect =
    metadata.pdf_rect && typeof metadata.pdf_rect === "object"
      ? (metadata.pdf_rect as Record<string, unknown>)
      : null;
  const rawDetail =
    metadata.detail_coords && typeof metadata.detail_coords === "object"
      ? (metadata.detail_coords as Record<string, unknown>)
      : null;

  return {
    page: Number(metadata.page ?? 1),
    scenario:
      typeof metadata.scenario === "string" ? metadata.scenario : undefined,
    cropUrl:
      typeof metadata.crop_url === "string" && metadata.crop_url.trim()
        ? metadata.crop_url
        : undefined,
    pdfRect: rawRect
      ? {
          x0: Number(rawRect.x0 ?? 0),
          y0: Number(rawRect.y0 ?? 0),
          x1: Number(rawRect.x1 ?? 0),
          y1: Number(rawRect.y1 ?? 0),
          width:
            rawRect.width !== undefined ? Number(rawRect.width) : undefined,
          height:
            rawRect.height !== undefined ? Number(rawRect.height) : undefined,
        }
      : undefined,
    detailCoords: rawDetail
      ? {
          x: Number(rawDetail.x ?? 0),
          y: Number(rawDetail.y ?? 0),
          width: Number(rawDetail.width ?? 0),
          height: Number(rawDetail.height ?? 0),
        }
      : undefined,
  };
}

function formatTime(iso?: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderInlineFormatting(text: string) {
  // Suporta código inline (`...`) e negrito (**...**) sem dependências externas
  const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code
          key={idx}
          className="rounded border border-border/80 bg-surface-subtle px-1 py-0.5 font-mono text-[11px] text-ink"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return (
        <strong key={idx} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <Fragment key={idx}>{part}</Fragment>;
  });
}

function FormattedMessageText({ content }: { content: string }) {
  // Divide blocos de código cercados por ```lang ... ```
  const segments: Array<
    | { kind: "text"; value: string }
    | { kind: "code"; lang: string; value: string }
  > = [];

  const fenceRegex = /```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = fenceRegex.exec(content);

  while (match !== null) {
    if (match.index > lastIndex) {
      segments.push({
        kind: "text",
        value: content.slice(lastIndex, match.index),
      });
    }
    segments.push({
      kind: "code",
      lang: match[1] || "",
      value: match[2].replace(/\n$/, ""),
    });
    lastIndex = fenceRegex.lastIndex;
    match = fenceRegex.exec(content);
  }

  if (lastIndex < content.length) {
    segments.push({ kind: "text", value: content.slice(lastIndex) });
  }

  return (
    <div className="space-y-2 text-xs leading-relaxed text-ink">
      {segments.map((seg, idx) => {
        if (seg.kind === "code") {
          return (
            <div
              key={idx}
              className="overflow-hidden rounded-md border border-border bg-surface-subtle/80"
            >
              {seg.lang && (
                <div className="border-b border-border/70 bg-surface-subtle px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-ink-muted">
                  {seg.lang}
                </div>
              )}
              <pre className="max-h-64 overflow-auto p-2.5 font-mono text-[11px] leading-relaxed text-ink-secondary">
                <code>{seg.value}</code>
              </pre>
            </div>
          );
        }

        const trimmed = seg.value;
        if (!trimmed) return null;
        return (
          <div key={idx} className="whitespace-pre-wrap break-words">
            {renderInlineFormatting(trimmed)}
          </div>
        );
      })}
    </div>
  );
}

function getArtifactDisplayMeta(artifact: SyncedArtifactInfo): {
  label: string;
  actionLabel: string;
  section: StudioSection;
} {
  switch (artifact.artifact_type) {
    case "json":
      return {
        label: "JSON Clínico",
        actionLabel: "Abrir Form Builder",
        section: "form_builder",
      };
    case "jrxml":
      return {
        label: "Layout JRXML",
        actionLabel: "Abrir Jasper Studio",
        section: "jasper_studio",
      };
    case "sql_insert":
      return {
        label: "SQL INSERT",
        actionLabel: "Abrir SQL & Banco",
        section: "sql_db",
      };
    case "sql_select":
      return {
        label: "SQL SELECT",
        actionLabel: "Abrir SQL & Banco",
        section: "sql_db",
      };
    default:
      return {
        label: artifact.artifact_type.toUpperCase(),
        actionLabel: "Abrir Form Builder",
        section: "form_builder",
      };
  }
}

export function MessageBubble({
  message,
  onNavigateSection,
}: MessageBubbleProps) {
  const [thoughtsOpen, setThoughtsOpen] = useState(false);

  const visualFeedback = parseVisualRegionFeedback(message.metadata);
  const timeLabel = formatTime(message.createdAt);

  // 1) Card de Anotação Visual originada do Jasper Studio
  if (visualFeedback) {
    return (
      <div
        data-testid="visual-region-feedback-card"
        className="rounded-lg border border-blueprint/35 bg-blueprint-soft/50 p-3 text-xs shadow-2xs"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 font-semibold text-blueprint">
            <Crosshair className="h-3.5 w-3.5 shrink-0" />
            <span>Anotação Visual · Jasper Studio</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge tone="blueprint" className="py-0 text-[10px] tabular-nums">
              Página {visualFeedback.page}
            </Badge>
            {visualFeedback.scenario && (
              <Badge tone="neutral" className="py-0 font-mono text-[10px]">
                {visualFeedback.scenario}
              </Badge>
            )}
          </div>
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[10px] tabular-nums">
          {visualFeedback.pdfRect && (
            <Badge tone="neutral" className="font-mono text-[10px]">
              PDF ({visualFeedback.pdfRect.x0}, {visualFeedback.pdfRect.y0}) → (
              {visualFeedback.pdfRect.x1}, {visualFeedback.pdfRect.y1})
            </Badge>
          )}
          {visualFeedback.detailCoords && (
            <Badge tone="accent" className="font-mono text-[10px]">
              &lt;detail&gt; x={visualFeedback.detailCoords.x}, y=
              {visualFeedback.detailCoords.y} (
              {visualFeedback.detailCoords.width}×
              {visualFeedback.detailCoords.height})
            </Badge>
          )}
        </div>

        {visualFeedback.cropUrl && (
          <div className="mt-2 overflow-hidden rounded border border-blueprint/30 bg-surface p-1">
            <img
              src={visualFeedback.cropUrl}
              alt={`Recorte visual da página ${visualFeedback.page}`}
              className="max-h-36 w-auto max-w-full rounded object-contain"
              loading="lazy"
            />
          </div>
        )}

        <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-ink">
          {message.content}
        </p>

        {timeLabel && (
          <div className="mt-1.5 text-right text-[10px] text-ink-muted tabular-nums">
            {timeLabel}
          </div>
        )}
      </div>
    );
  }

  // 2) Mensagem de sistema / autorização de Gate
  if (message.role === "system") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-success/30 bg-success-soft/60 px-3 py-2 text-xs text-success">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 break-words font-medium">
          {message.content}
        </span>
        {timeLabel && (
          <span className="shrink-0 text-[10px] opacity-75 tabular-nums">
            {timeLabel}
          </span>
        )}
      </div>
    );
  }

  // 3) Mensagem do Usuário
  if (message.role === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[90%] rounded-lg border border-accent/25 bg-accent-soft/75 px-3 py-2 text-xs text-ink">
          <div className="mb-1 flex items-center justify-between gap-3 text-[10px] font-medium text-accent">
            <span className="inline-flex items-center gap-1">
              <User className="h-3 w-3" />
              Você
            </span>
            {timeLabel && (
              <span className="text-ink-muted tabular-nums">{timeLabel}</span>
            )}
          </div>
          <div className="whitespace-pre-wrap break-words leading-relaxed text-ink">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // 4) Mensagem do Assistente (persistida ou em streaming)
  const hasThoughts = Boolean(message.thoughts && message.thoughts.length > 0);
  const toolCalls = message.toolCalls ?? [];
  const syncedArtifacts = message.syncedArtifacts ?? [];

  return (
    <div
      data-testid={
        message.streaming ? "assistant-streaming-bubble" : "assistant-bubble"
      }
      className={cn(
        "rounded-lg border bg-surface p-3 text-xs shadow-2xs",
        message.streaming ? "border-accent/40" : "border-border",
      )}
    >
      {/* Header do assistente */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-accent-soft text-accent">
            <Bot className="h-3.5 w-3.5" />
          </span>
          <span className="font-semibold text-ink">
            {getHarnessLabel(message.harness)}
          </span>
          {message.streaming && (
            <Badge tone="accent" className="py-0 text-[10px]">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Respondendo...
            </Badge>
          )}
        </div>
        {timeLabel && (
          <span className="text-[10px] text-ink-muted tabular-nums">
            {timeLabel}
          </span>
        )}
      </div>

      <div className="space-y-2.5">
        {/* Bloco colapsável de raciocínio (thought_delta) */}
        {hasThoughts && (
          <div className="rounded-md border border-border/80 bg-surface-subtle/60">
            <button
              type="button"
              aria-expanded={thoughtsOpen}
              onClick={() => setThoughtsOpen((prev) => !prev)}
              className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-[11px] font-medium text-ink-secondary hover:bg-surface-subtle transition-colors cursor-pointer rounded-md"
            >
              <span className="inline-flex items-center gap-1.5">
                {thoughtsOpen ? (
                  <ChevronDown className="h-3.5 w-3.5 text-ink-muted" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 text-ink-muted" />
                )}
                <Brain className="h-3.5 w-3.5 text-accent" />
                <span>Raciocínio</span>
              </span>
              <span className="font-mono text-[10px] text-ink-muted tabular-nums">
                {message.thoughts?.length ?? 0} caracteres
              </span>
            </button>
            {thoughtsOpen && (
              <div
                data-testid="thought-content"
                className="max-h-48 overflow-auto border-t border-border/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-ink-muted whitespace-pre-wrap break-words"
              >
                {message.thoughts}
              </div>
            )}
          </div>
        )}

        {/* Tool calls colapsáveis */}
        {toolCalls.length > 0 && (
          <div className="space-y-1.5">
            {toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} record={tc} />
            ))}
          </div>
        )}

        {/* Conteúdo textual formatado */}
        {message.content ? (
          <FormattedMessageText content={message.content} />
        ) : (
          message.streaming &&
          !hasThoughts &&
          toolCalls.length === 0 && (
            <div className="flex items-center gap-1.5 text-[11px] text-ink-muted">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Conectando ao agente...</span>
            </div>
          )
        )}

        {/* Cards de artefato sincronizado */}
        {syncedArtifacts.length > 0 && (
          <div className="space-y-1.5 pt-1">
            {syncedArtifacts.map((art, idx) => {
              const info = getArtifactDisplayMeta(art);
              return (
                <div
                  key={`${art.artifact_type}-${art.version_num ?? idx}`}
                  data-testid="synced-artifact-card"
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-success/35 bg-success-soft/60 px-2.5 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <FileCheck2 className="h-4 w-4 shrink-0 text-success" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11px] font-semibold text-success">
                          Artefato sincronizado
                        </span>
                        <Badge
                          tone="success"
                          className="py-0 text-[10px] tabular-nums"
                        >
                          <CheckCircle2 className="h-2.5 w-2.5" />
                          {info.label}
                          {art.version_num !== undefined
                            ? ` v${art.version_num}`
                            : ""}
                        </Badge>
                      </div>
                      {art.summary && (
                        <p className="truncate text-[10px] text-ink-secondary">
                          {art.summary}
                        </p>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="primary"
                    size="xs"
                    onClick={() => onNavigateSection(info.section)}
                    icon={<ArrowUpRight className="h-3 w-3" />}
                  >
                    {info.actionLabel}
                  </Button>
                </div>
              );
            })}
          </div>
        )}

        {/* Erro no stream */}
        {message.error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft/70 px-2.5 py-2 text-[11px] text-danger"
          >
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1 break-words">{message.error}</span>
          </div>
        )}
      </div>
    </div>
  );
}
