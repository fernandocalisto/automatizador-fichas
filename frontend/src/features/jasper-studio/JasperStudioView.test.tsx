import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type {
  ArtifactRevisionRead,
  DbProfileRead,
  JasperCompileResponse,
  JasperPreviewResponse,
  JrxmlLintReport,
  ProjectRead,
} from "@/types/studio";
import { JasperStudioView } from "./index";
import {
  convertNormalizedRectToPdfAndDetail,
  createBlankJrxmlTemplate,
  detectJrxmlOrientation,
} from "./utils";

const SAMPLE_PORTRAIT_JRXML = `<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="ficha_clinica" pageWidth="595" pageHeight="842" columnWidth="555" leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
  <detail>
    <band height="400"/>
  </detail>
</jasperReport>`;

const SAMPLE_LANDSCAPE_JRXML = `<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="ficha_paisagem" orientation="Landscape" pageWidth="842" pageHeight="595" columnWidth="802" leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
  <detail>
    <band height="320"/>
  </detail>
</jasperReport>`;

const MOCK_PROJECT: ProjectRead = {
  id: "proj-1",
  slug: "ficha_avaliacao_clinica",
  name: "Ficha Avaliação Clínica",
  description: "Ficha teste",
  current_stage: "jrxml_design",
  entry_mode: "pdf",
  preferred_harness: "agy",
  template_db_id: 99,
  workspace_dir: "/tmp/proj-1",
  has_pdf: true,
  gates: [],
  latest_artifacts: { json: 2, sql_insert: 1, jrxml: 1 },
  created_at: "2026-11-25T10:00:00Z",
  updated_at: "2026-11-25T10:00:00Z",
};

const MOCK_DB_PROFILES: DbProfileRead[] = [
  {
    id: "prof-homolog",
    name: "Homologação Salutem",
    host: "10.0.0.15",
    port: 5432,
    dbname: "salutem_hml",
    user: "salutem_ro",
    sslmode: "prefer",
    read_only: true,
    is_default: true,
    has_password: true,
    created_at: "2026-11-20T00:00:00Z",
    updated_at: "2026-11-20T00:00:00Z",
  },
  {
    id: "prof-dev",
    name: "Local Dev",
    host: "localhost",
    port: 5432,
    dbname: "salutem_dev",
    user: "postgres",
    sslmode: "disable",
    read_only: false,
    is_default: false,
    has_password: true,
    created_at: "2026-11-20T00:00:00Z",
    updated_at: "2026-11-20T00:00:00Z",
  },
];

function makePreviewResponse(
  overrides: Partial<JasperPreviewResponse> = {},
): JasperPreviewResponse {
  const scenario = overrides.scenario ?? "full";
  const pageCount = overrides.page_count ?? 1;
  return {
    ok: true,
    project_id: MOCK_PROJECT.id,
    slug: MOCK_PROJECT.slug,
    scenario,
    requested_mode: overrides.requested_mode ?? "auto",
    effective_mode: overrides.effective_mode ?? "offline",
    fallback_reason: overrides.fallback_reason ?? null,
    atendimento_id: overrides.atendimento_id ?? 10042,
    dpi: 150,
    page_count: pageCount,
    single_page_ok: overrides.single_page_ok ?? pageCount === 1,
    pdf_path: `/tmp/preview_${scenario}.pdf`,
    pdf_size_bytes: 24500,
    pdf_url: `/api/projects/${MOCK_PROJECT.id}/jasper/preview/pdf?scenario=${scenario}`,
    page_urls: Array.from(
      { length: pageCount },
      (_, idx) =>
        `/api/projects/${MOCK_PROJECT.id}/jasper/preview/pages/${idx + 1}?scenario=${scenario}`,
    ),
    pages: Array.from({ length: pageCount }, (_, idx) => ({
      page_number: idx + 1,
      url: `/api/projects/${MOCK_PROJECT.id}/jasper/preview/pages/${idx + 1}?scenario=${scenario}`,
      filename: `preview_${scenario}_page_${idx + 1}.png`,
      size_bytes: 12000,
    })),
    subreport_dir: "/tmp/subreports",
    lint: { ok: true, valid: true, errors: [], warnings: [] },
    daemon: { ok: true },
    ...overrides,
  };
}

function makeArtifactRevision(
  content = SAMPLE_PORTRAIT_JRXML,
  versionNum = 1,
): ArtifactRevisionRead {
  return {
    id: 10 + versionNum,
    project_id: MOCK_PROJECT.id,
    artifact_type: "jrxml",
    version_num: versionNum,
    content,
    summary: "JRXML inicial",
    created_by: "user",
    created_at: "2026-11-25T10:00:00Z",
  };
}

function renderView(onProjectUpdated = vi.fn()) {
  return render(
    <ToastProvider>
      <JasperStudioView
        project={MOCK_PROJECT}
        onProjectUpdated={onProjectUpdated}
        onNavigateSection={vi.fn()}
      />
    </ToastProvider>,
  );
}

describe("JasperStudio utils", () => {
  it("detects portrait and landscape orientations from JRXML", () => {
    expect(detectJrxmlOrientation(SAMPLE_PORTRAIT_JRXML)).toBe("RETRATO");
    expect(detectJrxmlOrientation(SAMPLE_LANDSCAPE_JRXML)).toBe("PAISAGEM");
  });

  it("converts normalized rect to PDF points and <detail> coordinates", () => {
    const portrait = convertNormalizedRectToPdfAndDetail(
      {
        x0: 100 / 595,
        y0: 250 / 842,
        x1: 320 / 595,
        y1: 310 / 842,
      },
      "RETRATO",
    );
    expect(portrait.pdfRect).toEqual({
      x0: 100,
      y0: 250,
      x1: 320,
      y1: 310,
      width: 220,
      height: 60,
    });
    expect(portrait.detailCoords).toEqual({
      x: 80,
      y: 68,
      width: 220,
      height: 60,
    });

    const landscape = convertNormalizedRectToPdfAndDetail(
      {
        x0: 10 / 842,
        y0: 100 / 595,
        x1: 210 / 842,
        y1: 250 / 595,
      },
      "PAISAGEM",
    );
    expect(landscape.pdfRect).toEqual({
      x0: 10,
      y0: 100,
      x1: 210,
      y1: 250,
      width: 200,
      height: 150,
    });
    // Clamped to >= 0 inside detail band
    expect(landscape.detailCoords).toEqual({
      x: 0,
      y: 0,
      width: 200,
      height: 150,
    });
  });

  it("generates lint-compliant blank JRXML with unique UUIDv4 attributes and SQL queryString", () => {
    const xml = createBlankJrxmlTemplate("PAISAGEM", "relatorio_produtividade");
    expect(xml).toContain('orientation="Landscape"');
    expect(xml).toContain('pageWidth="842" pageHeight="595"');
    expect(xml).toContain('<queryString language="SQL">');

    const uuidMatches = Array.from(
      xml.matchAll(/\buuid="([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"/gi),
    ).map((m) => m[1]);
    expect(uuidMatches).toHaveLength(3);
    expect(new Set(uuidMatches).size).toBe(3);

    expect(xml).toMatch(/<jasperReport[\s\S]*?\buuid="[0-9a-f-]{36}"/);
    const reportElementTags = xml.match(/<reportElement[^>]*>/g) ?? [];
    expect(reportElementTags).toHaveLength(2);
    for (const tag of reportElementTags) {
      expect(tag).toMatch(/\buuid="[0-9a-f-]{36}"/);
    }
  });
});

describe("JasperStudioView", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(api, "listDbProfiles").mockResolvedValue(MOCK_DB_PROFILES);
    vi.spyOn(api, "listChat").mockResolvedValue([]);
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("displays scaffold CTA when project has no JRXML and generates landscape scaffold", async () => {
    vi.spyOn(api, "getArtifact").mockRejectedValue(
      new ApiError(404, "Artefato jrxml não encontrado"),
    );
    const scaffoldSpy = vi.spyOn(api, "scaffoldJrxml").mockResolvedValue({
      project_id: MOCK_PROJECT.id,
      jrxml: SAMPLE_LANDSCAPE_JRXML,
      lint: { ok: true, valid: true, errors: [], warnings: [] },
      saved_revision: makeArtifactRevision(SAMPLE_LANDSCAPE_JRXML, 1),
    });
    const previewSpy = vi
      .spyOn(api, "generatePreview")
      .mockResolvedValue(makePreviewResponse());

    const onProjectUpdated = vi.fn();
    const user = userEvent.setup();
    renderView(onProjectUpdated);

    const ctaBtn = await screen.findByRole("button", {
      name: /Gerar scaffold base \(\.jrxml\)/i,
    });
    expect(ctaBtn).toBeInTheDocument();

    const orientSelect = screen.getByLabelText(/Orientação do scaffold/i);
    await user.selectOptions(orientSelect, "PAISAGEM");
    await user.click(ctaBtn);

    await waitFor(() => {
      expect(scaffoldSpy).toHaveBeenCalledWith(MOCK_PROJECT.id, {
        save_artifact: true,
        options: { orientacao: "PAISAGEM" },
      });
    });

    await waitFor(() => {
      expect(screen.getByLabelText("Editor XML JRXML")).toHaveValue(
        SAMPLE_LANDSCAPE_JRXML,
      );
    });
    expect(screen.getByText(/Paisagem 842×595/i)).toBeInTheDocument();
    expect(onProjectUpdated).toHaveBeenCalled();
    expect(previewSpy).toHaveBeenCalled();
  });

  it("runs linter and JVM compilation, displaying issues, jump-to-line, and compiler error", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    vi.spyOn(api, "generatePreview").mockResolvedValue(makePreviewResponse());

    const lintReport: JrxmlLintReport = {
      ok: false,
      valid: false,
      errors: [
        {
          rule: "TEXTFIELD_IS_BLANK_WHEN_NULL",
          severity: "error",
          line: 42,
          element: "textField",
          message: 'Todo <textField> deve definir isBlankWhenNull="true".',
        },
      ],
      warnings: [
        {
          rule: "DETAIL_HEIGHT_NEAR_LIMIT",
          severity: "warning",
          line: 18,
          element: "band",
          message: "Altura da banda <detail> próxima do limite de 1 página.",
        },
      ],
    };
    const lintSpy = vi.spyOn(api, "lintJrxml").mockResolvedValue(lintReport);

    const failedCompile: JasperCompileResponse = {
      ok: false,
      compiled: false,
      project_id: MOCK_PROJECT.id,
      slug: MOCK_PROJECT.slug,
      jrxml_path: "/tmp/ficha.jrxml",
      jasper_path: "/tmp/ficha.jasper",
      lint: lintReport,
      daemon: {
        ok: false,
        error: "net.sf.jasperreports.engine.JRException: Invalid tag order at line 42",
      },
    };
    const compileSpy = vi
      .spyOn(api, "compileJasper")
      .mockResolvedValue(failedCompile);

    const user = userEvent.setup();
    renderView();

    await screen.findByLabelText("Editor XML JRXML");

    await user.click(screen.getByRole("button", { name: /^Auditar$/i }));

    await waitFor(() => {
      expect(lintSpy).toHaveBeenCalledWith(
        MOCK_PROJECT.id,
        SAMPLE_PORTRAIT_JRXML,
      );
    });

    expect(screen.getByText("TEXTFIELD_IS_BLANK_WHEN_NULL")).toBeInTheDocument();
    expect(screen.getByText("DETAIL_HEIGHT_NEAR_LIMIT")).toBeInTheDocument();

    // Clicar na linha atualiza a linha ativa (revealLine)
    await user.click(screen.getByRole("button", { name: /Linha 42/i }));
    expect(screen.getByText(/Linha ativa: 42/i)).toBeInTheDocument();

    // Compilar e exibir erro retornado pelo daemon JVM
    await user.click(screen.getByRole("button", { name: /Compilar \(\.jasper\)/i }));

    await waitFor(() => {
      expect(compileSpy).toHaveBeenCalledWith(MOCK_PROJECT.id, {
        inline_jrxml: SAMPLE_PORTRAIT_JRXML,
        run_linter: true,
      });
    });

    const compilerAlert = screen.getByRole("alert");
    expect(
      within(compilerAlert).getByText(
        /Erro do Compilador JasperReports \(JVM\)/i,
      ),
    ).toBeInTheDocument();
    expect(
      within(compilerAlert).getByText(
        /JRException: Invalid tag order at line 42/i,
      ),
    ).toBeInTheDocument();
  });

  it("switches fictitious scenarios (full/stress/blank) and modes (offline/db_hybrid) triggering api.generatePreview", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    const previewSpy = vi
      .spyOn(api, "generatePreview")
      .mockImplementation(async (_projectId, payload) => {
        if (payload?.scenario === "stress") {
          return makePreviewResponse({
            scenario: "stress",
            page_count: 2,
            single_page_ok: false,
            effective_mode: "offline",
          });
        }
        if (payload?.mode === "db_hybrid") {
          return makePreviewResponse({
            scenario: payload.scenario ?? "full",
            requested_mode: "db_hybrid",
            effective_mode: "db_hybrid",
            atendimento_id: payload.atendimento_id ?? 55501,
          });
        }
        return makePreviewResponse({
          scenario: payload?.scenario ?? "full",
          requested_mode: payload?.mode ?? "auto",
          effective_mode: "offline",
          fallback_reason:
            payload?.mode === "auto"
              ? "Banco indisponível; usando mock offline"
              : null,
        });
      });

    const user = userEvent.setup();
    renderView();

    await waitFor(() => {
      expect(screen.getByText(/1 página OK/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Fallback: Banco indisponível/i)).toBeInTheDocument();

    // Troca para cenário Estresse de texto (stress)
    await user.click(
      screen.getByRole("button", { name: /Estresse de texto/i }),
    );
    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        MOCK_PROJECT.id,
        expect.objectContaining({ scenario: "stress" }),
      );
    });
    expect(
      screen.getByText(/Estouro de página \(2 páginas\)/i),
    ).toBeInTheDocument();

    // Troca para cenário Ficha em branco (blank)
    await user.click(screen.getByRole("button", { name: /Ficha em branco/i }));
    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        MOCK_PROJECT.id,
        expect.objectContaining({ scenario: "blank" }),
      );
    });

    // Troca para modo Offline (Mock)
    const modeSelect = screen.getByLabelText(/Modo de preview/i);
    await user.selectOptions(modeSelect, "offline");
    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        MOCK_PROJECT.id,
        expect.objectContaining({
          scenario: "blank",
          mode: "offline",
          db_profile_id: null,
        }),
      );
    });

    // Troca para modo Banco Híbrido (CTE) -> exibe seletor de perfil PG e input atendimento_id
    await user.selectOptions(modeSelect, "db_hybrid");
    const profileSelect = await screen.findByLabelText(/Perfil PostgreSQL/i);
    expect(profileSelect).toHaveValue("prof-homolog");

    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        MOCK_PROJECT.id,
        expect.objectContaining({
          mode: "db_hybrid",
          db_profile_id: "prof-homolog",
        }),
      );
    });

    const atendimentoInput = screen.getByLabelText(/atendimento_id \(opcional\)/i);
    await user.type(atendimentoInput, "77889");
    await user.click(screen.getByRole("button", { name: /Atualizar preview/i }));

    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        MOCK_PROJECT.id,
        expect.objectContaining({
          mode: "db_hybrid",
          db_profile_id: "prof-homolog",
          atendimento_id: 77889,
        }),
      );
    });
    expect(screen.getByText(/Modo: Banco Híbrido \(CTE\)/i)).toBeInTheDocument();

    // Alternar para renderizador PNG
    await user.click(screen.getByRole("button", { name: /^PNG$/i }));
    const pngImg = await screen.findByRole("img", {
      name: /Preview PNG da página 1/i,
    });
    expect(pngImg).toHaveAttribute(
      "src",
      expect.stringContaining(
        `/api/projects/${MOCK_PROJECT.id}/jasper/preview/pages/1?scenario=blank`,
      ),
    );
  });

  it("draws a rectangular region annotation, crops PNG via submitVisualRegionFeedback, and offers 1-click Chat IA jump", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    vi.spyOn(api, "generatePreview").mockResolvedValue(makePreviewResponse());

    const openChatSpy = vi.fn();
    const cropFeedbackSpy = vi
      .spyOn(api, "submitVisualRegionFeedback")
      .mockImplementation(async (_projectId, payload) => ({
        ok: true,
        project_id: MOCK_PROJECT.id,
        crop_png_path: "/tmp/crop_p1.png",
        crop_url: `/api/projects/${MOCK_PROJECT.id}/jasper/preview/feedback/crop_p1.png`,
        message: {
          id: 501,
          project_id: MOCK_PROJECT.id,
          phase: "jrxml",
          role: "user",
          content: payload.content,
          metadata: {
            type: "visual_region_feedback",
            page: payload.page,
            pdf_rect: payload.pdf_rect,
            detail_coords: payload.detail_coords ?? {},
            scenario: payload.scenario ?? "full",
            crop_png_path: "/tmp/crop_p1.png",
            crop_url: `/api/projects/${MOCK_PROJECT.id}/jasper/preview/feedback/crop_p1.png`,
          },
          metadata_json: "{}",
          created_at: "2026-11-25T11:00:00Z",
        },
      }));

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={MOCK_PROJECT}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
          onOpenAgentChat={openChatSpy}
        />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pdf-preview-canvas")).toBeInTheDocument();
    });

    // Ativa modo de seleção visual
    const selectToggle = screen.getByRole("button", {
      name: /Selecionar área para ajuste/i,
    });
    await user.click(selectToggle);
    expect(selectToggle).toHaveAttribute("aria-pressed", "true");

    const surface = screen.getByTestId("region-selection-surface");
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 595,
      bottom: 842,
      width: 595,
      height: 842,
      toJSON: () => ({}),
    });

    // Arrasta retângulo (100, 250) -> (320, 310) em A4 Retrato (595x842)
    fireEvent.mouseDown(surface, { clientX: 100, clientY: 250 });
    fireEvent.mouseMove(surface, { clientX: 320, clientY: 310 });
    fireEvent.mouseUp(surface, { clientX: 320, clientY: 310 });

    const popover = await screen.findByTestId("region-annotation-popover");
    expect(popover).toBeInTheDocument();
    expect(popover).toHaveTextContent("PDF (100, 250) → (320, 310)");
    expect(popover).toHaveTextContent("<detail> x=80, y=68");

    const noteInput = screen.getByLabelText(/Pedido de ajuste visual/i);
    await user.type(
      noteInput,
      "esses 3 checkboxes ficaram colados, espaçar horizontalmente",
    );
    await user.click(
      screen.getByRole("button", { name: /Enviar ajuste ao agente/i }),
    );

    await waitFor(() => {
      expect(cropFeedbackSpy).toHaveBeenCalledWith(MOCK_PROJECT.id, {
        page: 1,
        pdf_rect: {
          x0: 100,
          y0: 250,
          x1: 320,
          y1: 310,
          width: 220,
          height: 60,
        },
        detail_coords: {
          x: 80,
          y: 68,
          width: 220,
          height: 60,
        },
        scenario: "full",
        content: "esses 3 checkboxes ficaram colados, espaçar horizontalmente",
        dpi: 200,
      });
    });

    // Verifica listagem da anotação enviada na sessão e botão 1-clique Abrir Chat IA
    expect(
      screen.getByText(
        /esses 3 checkboxes ficaram colados, espaçar horizontalmente/i,
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Abrir Chat IA/i }));
    expect(openChatSpy).toHaveBeenCalledWith("jrxml");
  });

  it("renders export bundle (.zip) link reflecting active scenario/mode and saves JRXML revisions", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    vi.spyOn(api, "generatePreview").mockResolvedValue(makePreviewResponse());
    const saveSpy = vi.spyOn(api, "saveArtifact").mockResolvedValue({
      artifact: makeArtifactRevision(SAMPLE_PORTRAIT_JRXML + "\n<!-- ok -->", 2),
      generated_sql_insert: null,
      generated_sql_select: null,
    });

    const user = userEvent.setup();
    renderView();

    const editor = await screen.findByLabelText("Editor XML JRXML");

    const exportLink = screen.getByRole("link", {
      name: /Baixar pacote de entrega \(\.zip\)/i,
    });
    expect(exportLink).toHaveAttribute(
      "href",
      api.getExportBundleUrl(MOCK_PROJECT.id, {
        scenario: "full",
        mode: "auto",
        db_profile_id: "prof-homolog",
      }),
    );
    expect(exportLink).toHaveAttribute(
      "download",
      `${MOCK_PROJECT.slug}_entrega_salutem.zip`,
    );

    // Troca cenário e modo e verifica atualização do link de exportação
    await user.click(screen.getByRole("button", { name: /Estresse de texto/i }));
    await user.selectOptions(
      screen.getByLabelText(/Modo de preview/i),
      "offline",
    );
    expect(exportLink).toHaveAttribute(
      "href",
      api.getExportBundleUrl(MOCK_PROJECT.id, {
        scenario: "stress",
        mode: "offline",
        db_profile_id: null,
      }),
    );

    // Edita XML e salva revisão
    fireEvent.change(editor, {
      target: { value: SAMPLE_PORTRAIT_JRXML + "\n<!-- ok -->" },
    });
    expect(screen.getByText(/Alterações não salvas/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Salvar revisão/i }));

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledWith(MOCK_PROJECT.id, "jrxml", {
        content: SAMPLE_PORTRAIT_JRXML + "\n<!-- ok -->",
        summary: "Edição no Jasper Studio Light",
        created_by: "user",
      });
    });

    await waitFor(() => {
      expect(screen.getByText("v2")).toBeInTheDocument();
    });
  });

  it("triggers debounced preview refresh when Live-reload is enabled and XML is edited", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    const previewSpy = vi
      .spyOn(api, "generatePreview")
      .mockResolvedValue(makePreviewResponse());

    const user = userEvent.setup();
    renderView();

    const editor = await screen.findByLabelText("Editor XML JRXML");
    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledTimes(1);
    });

    const liveReloadSwitch = screen.getByRole("switch", {
      name: /Live-reload/i,
    });
    await user.click(liveReloadSwitch);
    expect(liveReloadSwitch).toHaveAttribute("aria-checked", "true");

    const updatedXml = SAMPLE_PORTRAIT_JRXML + "\n<!-- live-edit -->";
    fireEvent.change(editor, { target: { value: updatedXml } });

    await waitFor(
      () => {
        expect(previewSpy).toHaveBeenCalledWith(
          MOCK_PROJECT.id,
          expect.objectContaining({ inline_jrxml: updatedXml }),
        );
      },
      { timeout: 2500 },
    );
  });

  it("defaults free_report to Visual mode, persists 3-mode switcher in localStorage, and exposes AI CTA", async () => {
    const freeProject: ProjectRead = {
      ...MOCK_PROJECT,
      id: "proj-free-visual",
      slug: "guia_encaminhamento",
      name: "Guia de Encaminhamento",
      project_kind: "free_report",
      entry_mode: "jasperserver_import",
      default_db_profile_id: "prof-homolog",
      source_origin: { provider: "jasperserver", profile_id: "js-1" },
    };

    vi.spyOn(api, "getArtifact").mockResolvedValue(
      makeArtifactRevision(SAMPLE_PORTRAIT_JRXML, 1),
    );
    vi.spyOn(api, "generatePreview").mockResolvedValue(
      makePreviewResponse({
        project_id: freeProject.id,
        effective_mode: "db_live",
        page_count: 3,
        single_page_ok: false,
      }),
    );

    const openChatSpy = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={freeProject}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
          onOpenAgentChat={openChatSpy}
        />
      </ToastProvider>,
    );

    // Default layout mode for free_report with no saved preference is "visual"
    expect(
      await screen.findByTestId("jasper-studio-visual-mode"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Editor XML JRXML")).not.toBeInTheDocument();
    expect(screen.getByTestId("visual-mode-tip-bar")).toBeInTheDocument();

    // Prominent AI CTA calls onOpenAgentChat("jrxml")
    await user.click(
      screen.getByRole("button", { name: /Pedir ajuste à IA/i }),
    );
    expect(openChatSpy).toHaveBeenCalledWith("jrxml");

    // Switch to Split mode -> persists in localStorage and shows XML editor
    await user.click(
      screen.getByRole("button", { name: /Dividido \(Código \+ Preview\)/i }),
    );
    expect(screen.getByTestId("jasper-studio-split-mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Editor XML JRXML")).toBeInTheDocument();
    expect(window.localStorage.getItem("salutem:jasper-layout-mode")).toBe(
      "split",
    );

    // Switch to Code-only mode -> persists and hides preview canvas
    await user.click(screen.getByRole("button", { name: /Só Código/i }));
    expect(screen.getByTestId("jasper-studio-code-mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Editor XML JRXML")).toBeInTheDocument();
    expect(
      screen.queryByTestId("preview-control-bar-free-report"),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("salutem:jasper-layout-mode")).toBe(
      "code",
    );
  });

  it("defers initial preview on free_report with unfilled required $P{} params (Option A) and runs db_live after filling", async () => {
    const jrxmlWithRequiredParam = `<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" name="guia_proc" pageWidth="595" pageHeight="842" columnWidth="555" leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20">
  <parameter name="SUBREPORT_DIR" class="java.lang.String"/>
  <parameter name="id_atendimento" class="java.lang.Long"/>
  <parameter name="exibir_obs" class="java.lang.Boolean">
    <defaultValueExpression><![CDATA[Boolean.TRUE]]></defaultValueExpression>
  </parameter>
  <detail><band height="200"/></detail>
</jasperReport>`;

    const freeProject: ProjectRead = {
      ...MOCK_PROJECT,
      id: "proj-free-params",
      slug: "guia_proc",
      name: "Guia Procedimentos",
      project_kind: "free_report",
      entry_mode: "jasperserver_import",
      default_db_profile_id: "prof-homolog",
    };

    vi.spyOn(api, "getArtifact").mockResolvedValue(
      makeArtifactRevision(jrxmlWithRequiredParam, 1),
    );
    const previewSpy = vi
      .spyOn(api, "generatePreview")
      .mockResolvedValue(
        makePreviewResponse({
          project_id: freeProject.id,
          requested_mode: "db_live",
          effective_mode: "db_live",
          page_count: 2,
          single_page_ok: false,
        }),
      );

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={freeProject}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    // Calm empty state shown, NO doomed auto-preview fired on mount!
    const emptyCard = await screen.findByTestId("required-params-empty-state");
    expect(emptyCard).toHaveTextContent(
      /Este relatório precisa de parâmetros para gerar o preview \(id_atendimento\)/i,
    );
    expect(previewSpy).not.toHaveBeenCalled();

    // Mode defaulted automatically to db_live because default_db_profile_id is set
    expect(screen.getByLabelText(/Modo de preview/i)).toHaveValue("db_live");

    // Fill required param and click Gerar Preview
    const paramInput = screen.getByLabelText(/Parâmetro id_atendimento/i);
    await user.type(paramInput, "98765");
    await user.click(
      within(emptyCard).getByRole("button", { name: /Gerar Preview/i }),
    );

    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledWith(
        freeProject.id,
        expect.objectContaining({
          mode: "db_live",
          db_profile_id: "prof-homolog",
          report_params: { id_atendimento: "98765" },
        }),
      );
    });

    // Multi-page free_report shows neutral "2 páginas" badge (NO red "Estouro de página")
    expect(await screen.findByText("2 páginas")).toBeInTheDocument();
    expect(screen.queryByText(/Estouro de página/i)).not.toBeInTheDocument();
  });

  it("renders clean free_report bar: hides scenarios, uses SearchableSelect, Exportar dropdown, and repo: chip with 1-click sync", async () => {
    const freeProject: ProjectRead = {
      ...MOCK_PROJECT,
      id: "proj-free-repo",
      slug: "relatorio_hosp",
      name: "Relatório Hospitalar",
      project_kind: "free_report",
      entry_mode: "jasperserver_import",
      default_db_profile_id: "prof-homolog",
      source_origin: { provider: "jasperserver", profile_id: "js-1" },
    };

    vi.spyOn(api, "getArtifact").mockResolvedValue(
      makeArtifactRevision(SAMPLE_PORTRAIT_JRXML, 1),
    );
    const previewSpy = vi
      .spyOn(api, "generatePreview")
      .mockResolvedValue(
        makePreviewResponse({
          project_id: freeProject.id,
          requested_mode: "db_live",
          effective_mode: "db_live",
          page_count: 4,
          single_page_ok: false,
        }),
      );

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/jasper/repo-resources")) {
          return new Response(
            JSON.stringify({
              project_id: freeProject.id,
              total: 2,
              resolved_count: 1,
              missing_count: 1,
              can_sync_remote: true,
              items: [
                {
                  uri: "repo:/Hospitalar/Cabecalhos/cabecalho",
                  local_path: null,
                  resolved: false,
                  compiled: false,
                  kind: "subreport",
                },
                {
                  uri: "repo:/Hospitalar/Imagens/logo.png",
                  local_path: "repo/Hospitalar/Imagens/logo.png",
                  resolved: true,
                  compiled: false,
                  kind: "image",
                },
              ],
              warnings: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (
          url.includes("/jasper/sync-repo-resources") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              project_id: freeProject.id,
              total: 2,
              resolved_count: 2,
              missing_count: 0,
              can_sync_remote: true,
              items: [],
              warnings: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({ parameters: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      });

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={freeProject}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    // Zero required params -> auto-preview runs on mount!
    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledTimes(1);
    });

    // Clinical scenario pills and atendimento_id input are hidden for free_report
    expect(
      screen.queryByRole("button", { name: /Preenchido completo/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/atendimento_id \(opcional\)/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText("4 páginas")).toBeInTheDocument();
    expect(screen.queryByText(/Estouro de página/i)).not.toBeInTheDocument();

    // repo: pending chip + 1-click sync
    expect(await screen.findByText("repo: 1 pendente(s)")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Sincronizar repo:/i }),
    );
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        `/api/projects/${freeProject.id}/jasper/sync-repo-resources`,
        { method: "POST" },
      );
    });
    expect(await screen.findByText("repo: 2 OK")).toBeInTheDocument();

    // SearchableSelect for PostgreSQL profile
    const dbTrigger = screen.getByRole("button", {
      name: /Perfil PostgreSQL/i,
    });
    await user.click(dbTrigger);
    const searchInput = screen.getByPlaceholderText(
      /Buscar por nome, host, banco ou ambiente/i,
    );
    await user.type(searchInput, "salutem_dev");
    await user.click(screen.getByRole("option", { name: /Local Dev/i }));

    await waitFor(() => {
      expect(previewSpy).toHaveBeenLastCalledWith(
        freeProject.id,
        expect.objectContaining({
          mode: "db_live",
          db_profile_id: "prof-dev",
        }),
      );
    });

    // Exportar dropdown groups Baixar .jrxml, Abrir .pdf, and Pacote .zip
    await user.click(screen.getByRole("button", { name: /Exportar/i }));
    const menu = screen.getByRole("menu", { name: /Opções de exportação/i });
    expect(
      within(menu).getByRole("menuitem", { name: /Baixar \.jrxml/i }),
    ).toBeInTheDocument();
    expect(
      within(menu).getByRole("menuitem", { name: /Abrir \.pdf/i }),
    ).toBeInTheDocument();
    expect(
      within(menu).getByRole("menuitem", { name: /Pacote \.zip/i }),
    ).toHaveAttribute("download", `${freeProject.slug}_entrega_salutem.zip`);
  });

  it("prevents premature 404 PDF/PNG fetch on scenario switch before POST /jasper/preview resolves", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());

    let resolveStress!: (res: JasperPreviewResponse) => void;
    const stressPromise = new Promise<JasperPreviewResponse>((resolve) => {
      resolveStress = resolve;
    });

    vi.spyOn(api, "generatePreview").mockImplementation(async (_id, payload) => {
      if (payload?.scenario === "stress") {
        return stressPromise;
      }
      return makePreviewResponse({ scenario: payload?.scenario ?? "full" });
    });

    const user = userEvent.setup();
    renderView();

    await waitFor(() => {
      expect(screen.getByText(/1 página OK/i)).toBeInTheDocument();
    });

    // Alterna para PNG para inspecionar a URL efetiva requisitada pelo canvas
    await user.click(screen.getByRole("button", { name: /^PNG$/i }));
    const imgBefore = await screen.findByRole("img", {
      name: /Preview PNG da página 1 \(full\)/i,
    });
    expect(imgBefore).toHaveAttribute(
      "src",
      expect.stringContaining("scenario=full"),
    );

    // Clica em "Estresse de texto" -> enquanto o POST não retorna, NÃO deve requisitar scenario=stress!
    await user.click(
      screen.getByRole("button", { name: /Estresse de texto/i }),
    );
    expect(screen.getByText(/Renderizando preview/i)).toBeInTheDocument();
    const imgWhileLoading = screen.getByRole("img");
    expect(imgWhileLoading).toHaveAttribute(
      "src",
      expect.stringContaining("scenario=full"),
    );
    expect(imgWhileLoading.getAttribute("src")).not.toContain("scenario=stress");

    // Quando o POST resolve, o preview atualiza para scenario=stress
    resolveStress(
      makePreviewResponse({
        scenario: "stress",
        page_count: 2,
        single_page_ok: false,
      }),
    );

    await waitFor(() => {
      expect(screen.getByRole("img")).toHaveAttribute(
        "src",
        expect.stringContaining("scenario=stress"),
      );
    });
  });

  it("never dead-ends when free_report has no JRXML: allows creating blank JRXML and uploading .jrxml", async () => {
    const freeBlankProject: ProjectRead = {
      ...MOCK_PROJECT,
      id: "proj-free-empty",
      slug: "relatorio_novo",
      name: "Relatório Novo",
      project_kind: "free_report",
      entry_mode: "blank_report",
      latest_artifacts: {},
    };

    vi.spyOn(api, "getArtifact").mockRejectedValue(
      new ApiError(404, "No jrxml yet"),
    );
    const saveSpy = vi
      .spyOn(api, "saveArtifact")
      .mockImplementation(async (_id, _type, payload) => ({
        artifact: makeArtifactRevision(payload.content, 1),
        generated_sql_insert: null,
        generated_sql_select: null,
      }));
    vi.spyOn(api, "generatePreview").mockResolvedValue(
      makePreviewResponse({ project_id: freeBlankProject.id }),
    );

    const onProjectUpdated = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={freeBlankProject}
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    // Em modo visual sem JRXML, oferece Criar JRXML em branco e Enviar arquivo .jrxml
    const createBlankBtn = await screen.findByRole("button", {
      name: /Criar JRXML em branco/i,
    });
    expect(
      screen.getByRole("button", { name: /Enviar arquivo \.jrxml/i }),
    ).toBeInTheDocument();

    // Troca para Só Código -> também não fica preso, oferece Criar JRXML em branco e upload
    await user.click(screen.getByRole("button", { name: /Só Código/i }));
    const codeCreateBtn = await screen.findByRole("button", {
      name: /Criar JRXML em branco/i,
    });
    await user.click(codeCreateBtn);

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledWith(
        freeBlankProject.id,
        "jrxml",
        expect.objectContaining({
          content: expect.stringContaining("<jasperReport"),
          created_by: "user",
        }),
      );
    });

    const editor = await screen.findByLabelText("Editor XML JRXML");
    expect(editor).toBeInTheDocument();
    expect(onProjectUpdated).toHaveBeenCalled();

    // Botão Salvar revisão fica desabilitado quando !dirty e habilita após editar
    const saveBtn = screen.getByRole("button", { name: /Salvar revisão/i });
    expect(saveBtn).toBeDisabled();

    fireEvent.change(editor, {
      target: { value: SAMPLE_PORTRAIT_JRXML + "\n<!-- edit -->" },
    });
    expect(saveBtn).toBeEnabled();
    expect(createBlankBtn).not.toBeInTheDocument();
  });

  it("persists default_db_profile_id via api.updateProject when changing DB profile", async () => {
    const freeProject: ProjectRead = {
      ...MOCK_PROJECT,
      id: "proj-free-persist-db",
      slug: "rel_db",
      name: "Relatório DB",
      project_kind: "free_report",
      entry_mode: "blank_report",
      default_db_profile_id: "prof-homolog",
    };

    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    vi.spyOn(api, "generatePreview").mockResolvedValue(
      makePreviewResponse({ project_id: freeProject.id }),
    );
    const updatedProj: ProjectRead = {
      ...freeProject,
      default_db_profile_id: "prof-dev",
    };
    const updateSpy = vi
      .spyOn(api, "updateProject")
      .mockResolvedValue(updatedProj);
    const onProjectUpdated = vi.fn();

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <JasperStudioView
          project={freeProject}
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    const dbTrigger = await screen.findByRole("button", {
      name: /Perfil PostgreSQL/i,
    });
    await user.click(dbTrigger);
    await user.click(screen.getByRole("option", { name: /Local Dev/i }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(freeProject.id, {
        default_db_profile_id: "prof-dev",
      });
      expect(onProjectUpdated).toHaveBeenCalledWith(updatedProj);
    });
  });
});
