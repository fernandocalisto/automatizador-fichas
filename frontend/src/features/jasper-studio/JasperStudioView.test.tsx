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
});

describe("JasperStudioView", () => {
  beforeEach(() => {
    vi.spyOn(api, "listDbProfiles").mockResolvedValue(MOCK_DB_PROFILES);
    vi.spyOn(api, "listChat").mockResolvedValue([]);
  });

  afterEach(() => {
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

  it("draws a rectangular region annotation and submits visual_region_feedback to api.appendChat", async () => {
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision());
    vi.spyOn(api, "generatePreview").mockResolvedValue(makePreviewResponse());

    const appendChatSpy = vi
      .spyOn(api, "appendChat")
      .mockImplementation(async (_projectId, payload) => ({
        id: 501,
        project_id: MOCK_PROJECT.id,
        phase: payload.phase ?? "jrxml",
        role: payload.role ?? "user",
        content: payload.content,
        metadata: payload.metadata ?? {},
        metadata_json: JSON.stringify(payload.metadata ?? {}),
        created_at: "2026-11-25T11:00:00Z",
      }));

    const user = userEvent.setup();
    renderView();

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
      expect(appendChatSpy).toHaveBeenCalledWith(MOCK_PROJECT.id, {
        phase: "jrxml",
        role: "user",
        content: "esses 3 checkboxes ficaram colados, espaçar horizontalmente",
        metadata: {
          type: "visual_region_feedback",
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
        },
      });
    });

    // Verifica listagem da anotação enviada na sessão
    expect(
      screen.getByText(
        /esses 3 checkboxes ficaram colados, espaçar horizontalmente/i,
      ),
    ).toBeInTheDocument();
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
});
