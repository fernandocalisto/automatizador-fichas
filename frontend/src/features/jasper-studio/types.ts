import type {
  ChatMessageRead,
  ClinicalOrientation,
  PreviewMode,
  ScenarioType,
} from "@/types/studio";

export interface PdfRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  width: number;
  height: number;
}

export interface DetailCoords {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface VisualRegionFeedbackMetadata {
  type: "visual_region_feedback";
  page: number;
  pdf_rect: PdfRect;
  detail_coords: DetailCoords;
  scenario: ScenarioType;
}

export interface VisualRegionAnnotation {
  id: number | string;
  content: string;
  createdAt: string;
  page: number;
  scenario: ScenarioType;
  pdfRect: PdfRect;
  detailCoords: DetailCoords;
}

export type ZoomPreset = 0.75 | 1 | 1.25 | 1.5 | "fit-width";
export type PreviewRendererMode = "pdfjs" | "png";

export const SCENARIO_OPTIONS: {
  id: ScenarioType;
  label: string;
  shortLabel: string;
  description: string;
}[] = [
  {
    id: "full",
    label: "Preenchido completo",
    shortLabel: "Completo",
    description: "Simula ficha clínica com todos os campos preenchidos.",
  },
  {
    id: "stress",
    label: "Estresse de texto",
    shortLabel: "Estresse",
    description: "Testa textos extensos para detectar cortes e estouro de página.",
  },
  {
    id: "blank",
    label: "Ficha em branco",
    shortLabel: "Em branco",
    description: "Valida isBlankWhenNull e ausência de 'null' impresso.",
  },
];

export const PREVIEW_MODE_OPTIONS: {
  id: PreviewMode;
  label: string;
  description: string;
}[] = [
  {
    id: "auto",
    label: "Automático",
    description: "Usa Banco Híbrido quando disponível ou fallback Offline.",
  },
  {
    id: "offline",
    label: "Offline (Mock)",
    description: "Usa dados fictícios locais e subreports mock sem banco.",
  },
  {
    id: "db_hybrid",
    label: "Banco Híbrido (CTE)",
    description: "Consulta cabeçalho/paciente reais no PostgreSQL + CTE mock.",
  },
];

export const ZOOM_PRESETS: { value: ZoomPreset; label: string }[] = [
  { value: 0.75, label: "75%" },
  { value: 1, label: "100%" },
  { value: 1.25, label: "125%" },
  { value: 1.5, label: "150%" },
  { value: "fit-width", label: "Ajustar à largura" },
];

export function isVisualRegionChatMessage(
  msg: ChatMessageRead,
): msg is ChatMessageRead & { metadata: VisualRegionFeedbackMetadata } {
  const meta = msg.metadata as Record<string, unknown> | undefined;
  return Boolean(meta && meta.type === "visual_region_feedback");
}

export function chatMessageToAnnotation(
  msg: ChatMessageRead,
): VisualRegionAnnotation | null {
  if (!isVisualRegionChatMessage(msg)) return null;
  const meta = msg.metadata;
  const rawRect = meta.pdf_rect as Partial<PdfRect> | undefined;
  const rawDetail = meta.detail_coords as Partial<DetailCoords> | undefined;
  if (!rawRect || !rawDetail) return null;

  const x0 = Number(rawRect.x0 ?? 0);
  const y0 = Number(rawRect.y0 ?? 0);
  const x1 = Number(rawRect.x1 ?? x0);
  const y1 = Number(rawRect.y1 ?? y0);

  return {
    id: msg.id,
    content: msg.content,
    createdAt: msg.created_at,
    page: Number(meta.page ?? 1),
    scenario: (meta.scenario as ScenarioType) || "full",
    pdfRect: {
      x0,
      y0,
      x1,
      y1,
      width: Number(rawRect.width ?? Math.max(0, x1 - x0)),
      height: Number(rawRect.height ?? Math.max(0, y1 - y0)),
    },
    detailCoords: {
      x: Number(rawDetail.x ?? 0),
      y: Number(rawDetail.y ?? 0),
      width: Number(rawDetail.width ?? Math.max(0, x1 - x0)),
      height: Number(rawDetail.height ?? Math.max(0, y1 - y0)),
    },
  };
}
