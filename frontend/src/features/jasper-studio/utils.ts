import type { ClinicalOrientation } from "@/types/studio";
import type { DetailCoords, PdfRect } from "./types";

export interface PageDimensions {
  width: number;
  height: number;
  leftMargin: number;
  detailTopOffset: number;
}

export const A4_PORTRAIT_DIMENSIONS: PageDimensions = {
  width: 595,
  height: 842,
  leftMargin: 20,
  detailTopOffset: 182,
};

export const A4_LANDSCAPE_DIMENSIONS: PageDimensions = {
  width: 842,
  height: 595,
  leftMargin: 20,
  detailTopOffset: 182,
};

export function getPageDimensions(
  orientation: ClinicalOrientation,
): PageDimensions {
  return orientation === "PAISAGEM"
    ? A4_LANDSCAPE_DIMENSIONS
    : A4_PORTRAIT_DIMENSIONS;
}

/**
 * Detecta orientação A4 a partir dos atributos do elemento raiz `<jasperReport>`.
 */
export function detectJrxmlOrientation(jrxml: string): ClinicalOrientation {
  if (!jrxml) return "RETRATO";
  if (/orientation\s*=\s*["']Landscape["']/i.test(jrxml)) {
    return "PAISAGEM";
  }
  const widthMatch = jrxml.match(/pageWidth\s*=\s*["'](\d+)["']/i);
  const heightMatch = jrxml.match(/pageHeight\s*=\s*["'](\d+)["']/i);
  if (widthMatch && heightMatch) {
    const w = Number(widthMatch[1]);
    const h = Number(heightMatch[1]);
    if (w > h) return "PAISAGEM";
  }
  return "RETRATO";
}

export interface NormalizedRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/**
 * Converte retângulo normalizado (0..1 sobre a página renderizada) em pontos PDF
 * e coordenadas estimadas dentro da banda `<detail>` do Salutem.
 */
export function convertNormalizedRectToPdfAndDetail(
  rect: NormalizedRect,
  orientation: ClinicalOrientation,
): { pdfRect: PdfRect; detailCoords: DetailCoords } {
  const dims = getPageDimensions(orientation);

  const clamp01 = (val: number) => Math.min(1, Math.max(0, val));
  const nx0 = clamp01(Math.min(rect.x0, rect.x1));
  const ny0 = clamp01(Math.min(rect.y0, rect.y1));
  const nx1 = clamp01(Math.max(rect.x0, rect.x1));
  const ny1 = clamp01(Math.max(rect.y0, rect.y1));

  const x0 = Math.round(nx0 * dims.width);
  const y0 = Math.round(ny0 * dims.height);
  const x1 = Math.round(nx1 * dims.width);
  const y1 = Math.round(ny1 * dims.height);
  const width = Math.max(1, x1 - x0);
  const height = Math.max(1, y1 - y0);

  const pdfRect: PdfRect = { x0, y0, x1, y1, width, height };
  const detailCoords: DetailCoords = {
    x: Math.max(0, Math.round(x0 - dims.leftMargin)),
    y: Math.max(0, Math.round(y0 - dims.detailTopOffset)),
    width,
    height,
  };

  return { pdfRect, detailCoords };
}

export function extractDaemonError(
  daemon?: Record<string, unknown> | null,
): string | null {
  if (!daemon || typeof daemon !== "object") return null;
  const directError = daemon.error ?? daemon.message ?? daemon.stderr;
  if (typeof directError === "string" && directError.trim()) {
    return directError.trim();
  }
  if (daemon.ok === false || daemon.status === "error") {
    try {
      return JSON.stringify(daemon, null, 2);
    } catch {
      return "Erro desconhecido retornado pelo compilador JasperReports (JVM).";
    }
  }
  return null;
}

export function isJsdomRuntime(): boolean {
  return (
    typeof navigator !== "undefined" &&
    navigator.userAgent.toLowerCase().includes("jsdom")
  );
}

export function triggerTextDownload(
  filename: string,
  content: string,
  mimeType = "application/xml;charset=utf-8",
): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Gera um template JRXML mínimo e válido (sem dependência de ficha.json),
 * ideal para relatórios livres (free_report) ou início rápido a partir do zero.
 */
export function createBlankJrxmlTemplate(
  orientation: ClinicalOrientation,
  reportName = "relatorio_salutem",
): string {
  const safeName =
    reportName
      .trim()
      .replace(/[^a-zA-Z0-9_]+/g, "_")
      .replace(/^_+|_+$/g, "") || "relatorio_salutem";
  const isLandscape = orientation === "PAISAGEM";
  const pageWidth = isLandscape ? 842 : 595;
  const pageHeight = isLandscape ? 595 : 842;
  const columnWidth = pageWidth - 40;
  const orientationAttr = isLandscape ? ' orientation="Landscape"' : "";

  return `<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
  name="${safeName}"${orientationAttr}
  pageWidth="${pageWidth}" pageHeight="${pageHeight}" columnWidth="${columnWidth}"
  leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
  <queryString><![CDATA[SELECT 1 AS exemplo]]></queryString>
  <field name="exemplo" class="java.lang.Integer"/>
  <title>
    <band height="40">
      <staticText>
        <reportElement x="0" y="6" width="${columnWidth}" height="24"/>
        <textElement verticalAlignment="Middle">
          <font fontName="DejaVu Sans" size="14" isBold="true"/>
        </textElement>
        <text><![CDATA[${safeName}]]></text>
      </staticText>
    </band>
  </title>
  <detail>
    <band height="24">
      <textField isBlankWhenNull="true">
        <reportElement x="0" y="2" width="${columnWidth}" height="18"/>
        <textElement verticalAlignment="Middle">
          <font fontName="DejaVu Sans" size="10"/>
        </textElement>
        <textFieldExpression><![CDATA[$F{exemplo}]]></textFieldExpression>
      </textField>
    </band>
  </detail>
</jasperReport>
`;
}
