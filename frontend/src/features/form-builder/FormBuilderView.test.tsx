import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type {
  ArtifactRevisionRead,
  ArtifactSaveResponse,
  ClinicalFormJson,
  ProjectRead,
} from "@/types/studio";
import { FormBuilderView } from "./index";

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "proj-1",
    slug: "ficha-triagem",
    name: "Ficha Triagem",
    description: "Ficha de teste",
    current_stage: "form_builder",
    entry_mode: "pdf",
    preferred_harness: "agy",
    template_db_id: null,
    workspace_dir: "/tmp/proj-1",
    has_pdf: true,
    gates: [],
    latest_artifacts: { json: 1 },
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

function makeSampleForm(): ClinicalFormJson {
  return {
    template: {
      nome: "FICHA TRIAGEM",
      descricao: "AVALIAÇÃO INICIAL",
      ativo: true,
      layout: "ficha-clinica",
      orientacao: "RETRATO",
      posicao_assinatura: "RODAPE",
      quantidade_pagina: 1,
      importa_historico_ficha_clinica: false,
    },
    perguntas: [
      {
        nome: "SINAIS VITAIS",
        titulo: false,
        ordenacao: 1,
        obrigatorio: false,
        observacao: false,
        respostas: [
          {
            label: "PRESSÃO ARTERIAL",
            tipo_campo: "TEXTO",
            ordenacao: 1,
            obrigatorio: true,
            observacao: false,
            quantidade_linhas: 1,
          },
          {
            label: "TEMPERATURA",
            tipo_campo: "NUMERICO",
            ordenacao: 2,
            obrigatorio: false,
            observacao: false,
            quantidade_linhas: 1,
          },
        ],
      },
      {
        nome: "QUEIXA PRINCIPAL",
        titulo: false,
        ordenacao: 2,
        obrigatorio: false,
        observacao: false,
        respostas: [
          {
            label: "RELATO",
            tipo_campo: "TEXTO",
            ordenacao: 1,
            obrigatorio: false,
            observacao: false,
            quantidade_linhas: 3,
          },
        ],
      },
    ],
  };
}

function makeArtifactRevision(
  form: ClinicalFormJson,
  versionNum = 1,
): ArtifactRevisionRead {
  return {
    id: 10 + versionNum,
    project_id: "proj-1",
    artifact_type: "json",
    version_num: versionNum,
    content: JSON.stringify(form, null, 2),
    summary: "Inicial",
    created_by: "user",
    created_at: "2026-01-01T12:00:00Z",
  };
}

function renderFormBuilder(
  project = makeProject(),
  onProjectUpdated = vi.fn(),
  onNavigateSection = vi.fn(),
) {
  return {
    onProjectUpdated,
    onNavigateSection,
    ...render(
      <ToastProvider>
        <FormBuilderView
          project={project}
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={onNavigateSection}
        />
      </ToastProvider>,
    ),
  };
}

describe("FormBuilderView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows empty state when project has no JSON and allows creating a blank form", async () => {
    vi.spyOn(api, "getArtifact").mockRejectedValue(
      new ApiError(404, "Artifact not found"),
    );
    vi.spyOn(api, "getJsonWarnings").mockResolvedValue({
      project_id: "proj-1",
      version_num: 0,
      warnings_count: 0,
      warnings: [],
    });

    const user = userEvent.setup();
    renderFormBuilder(makeProject({ latest_artifacts: {} }));

    await waitFor(() => {
      expect(
        screen.getByText(/Nenhuma estrutura JSON criada/i),
      ).toBeInTheDocument();
    });

    await user.click(
      screen.getByRole("button", { name: /Criar ficha em branco/i }),
    );

    expect(screen.getByDisplayValue("FICHA TRIAGEM")).toBeInTheDocument();
    expect(screen.getByText(/Alterações não salvas/i)).toBeInTheDocument();

    const jsonEditor = screen.getByLabelText("Editor JSON da ficha clínica");
    const parsed = JSON.parse((jsonEditor as HTMLTextAreaElement).value);
    expect(parsed.template.layout).toBe("ficha-clinica");
    expect(parsed.perguntas.length).toBeGreaterThanOrEqual(2);
  });

  it("supports adding, editing, duplicating, reordering and deleting questions and answers with COMBOBOX options", async () => {
    const sample = makeSampleForm();
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision(sample));
    vi.spyOn(api, "getJsonWarnings").mockResolvedValue({
      project_id: "proj-1",
      version_num: 1,
      warnings_count: 0,
      warnings: [],
    });

    const user = userEvent.setup();
    renderFormBuilder();

    await waitFor(() => {
      expect(screen.getByDisplayValue("SINAIS VITAIS")).toBeInTheDocument();
    });

    // Add a new question
    await user.click(screen.getByRole("button", { name: /Nova pergunta/i }));
    expect(screen.getByDisplayValue("NOVA PERGUNTA")).toBeInTheDocument();

    // Reorder question 1 down -> swaps SINAIS VITAIS and QUEIXA PRINCIPAL
    await user.click(screen.getByRole("button", { name: "Descer pergunta 1" }));
    const editor = screen.getByLabelText(
      "Editor JSON da ficha clínica",
    ) as HTMLTextAreaElement;
    let parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[0].nome).toBe("QUEIXA PRINCIPAL");
    expect(parsed.perguntas[0].ordenacao).toBe(1);
    expect(parsed.perguntas[1].nome).toBe("SINAIS VITAIS");
    expect(parsed.perguntas[1].ordenacao).toBe(2);

    // Duplicate question 1
    await user.click(
      screen.getByRole("button", { name: "Duplicar pergunta 1" }),
    );
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[1].nome).toBe("QUEIXA PRINCIPAL (CÓPIA)");
    expect(parsed.perguntas.map((q) => q.ordenacao)).toEqual([1, 2, 3, 4]);

    // Delete duplicated question (index 1 -> question 2)
    await user.click(
      screen.getByRole("button", { name: "Excluir pergunta 2" }),
    );
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas).toHaveLength(3);
    expect(parsed.perguntas.map((q) => q.ordenacao)).toEqual([1, 2, 3]);

    // Reorder answer 1 down inside question 2 (SINAIS VITAIS: PRESSÃO ARTERIAL <-> TEMPERATURA)
    await user.click(
      screen.getByRole("button", { name: "Descer resposta 1 da pergunta 2" }),
    );
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[1].respostas[0].label).toBe("TEMPERATURA");
    expect(parsed.perguntas[1].respostas[0].ordenacao).toBe(1);
    expect(parsed.perguntas[1].respostas[1].label).toBe("PRESSÃO ARTERIAL");
    expect(parsed.perguntas[1].respostas[1].ordenacao).toBe(2);

    // Duplicate answer 1 of question 2 and delete it
    await user.click(
      screen.getByRole("button", {
        name: "Duplicar resposta 1 da pergunta 2",
      }),
    );
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[1].respostas).toHaveLength(3);
    expect(parsed.perguntas[1].respostas[1].label).toBe("TEMPERATURA (CÓPIA)");

    await user.click(
      screen.getByRole("button", { name: "Excluir resposta 2 da pergunta 2" }),
    );
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[1].respostas).toHaveLength(2);

    // Change answer 1 of question 1 to COMBOBOX and add option
    const typeSelect = screen.getByLabelText(
      "Tipo de campo da resposta 1 da pergunta 1",
    );
    await user.selectOptions(typeSelect, "COMBOBOX");

    const optInput = screen.getByLabelText(
      "Nova opção do combobox da resposta 1 da pergunta 1",
    );
    await user.type(optInput, "URGENTE{Enter}");
    parsed = JSON.parse(editor.value) as ClinicalFormJson;
    expect(parsed.perguntas[0].respostas[0].tipo_campo).toBe("COMBOBOX");
    expect(parsed.perguntas[0].respostas[0].opcoes).toEqual(["URGENTE"]);

    // Search filter works
    const searchInput = screen.getByLabelText("Buscar perguntas ou respostas");
    await user.type(searchInput, "PRESSÃO");
    expect(screen.getByDisplayValue("SINAIS VITAIS")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("QUEIXA PRINCIPAL")).not.toBeInTheDocument();
  });

  it("synchronizes bidirectionally with JSON editor and handles invalid JSON without crashing", async () => {
    const sample = makeSampleForm();
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision(sample));
    vi.spyOn(api, "getJsonWarnings").mockResolvedValue({
      project_id: "proj-1",
      version_num: 1,
      warnings_count: 0,
      warnings: [],
    });

    const user = userEvent.setup();
    renderFormBuilder();

    await waitFor(() => {
      expect(screen.getByDisplayValue("SINAIS VITAIS")).toBeInTheDocument();
    });

    const editor = screen.getByLabelText(
      "Editor JSON da ficha clínica",
    ) as HTMLTextAreaElement;

    // 1. Type invalid JSON -> shows inline error, disables Save, preserves Form Builder view
    fireEvent.change(editor, { target: { value: "{ invalid json" } });

    expect(
      screen.getByText(/JSON temporariamente inválido/i),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("SINAIS VITAIS")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Salvar revisão/i }),
    ).toBeDisabled();

    // 2. Enter valid updated JSON -> updates Form Builder immediately
    const updatedForm: ClinicalFormJson = {
      ...sample,
      template: { ...sample.template, nome: "ficha atualizada" },
      perguntas: [
        {
          nome: "exame fisico",
          titulo: false,
          ordenacao: 1,
          respostas: [
            {
              label: "ausculta",
              tipo_campo: "TEXTO",
              ordenacao: 1,
              quantidade_linhas: 2,
            },
          ],
        },
      ],
    };

    fireEvent.change(editor, {
      target: { value: JSON.stringify(updatedForm, null, 2) },
    });

    expect(
      screen.queryByText(/JSON temporariamente inválido/i),
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("ficha atualizada")).toBeInTheDocument();
    expect(screen.getByDisplayValue("exame fisico")).toBeInTheDocument();
    expect(screen.getByDisplayValue("ausculta")).toBeInTheDocument();

    // 3. Apply local UPPERCASE button
    await user.click(
      screen.getByRole("button", { name: /Converter UPPERCASE/i }),
    );
    expect(screen.getByDisplayValue("FICHA ATUALIZADA")).toBeInTheDocument();
    expect(screen.getByDisplayValue("EXAME FISICO")).toBeInTheDocument();
    expect(screen.getByDisplayValue("AUSCULTA")).toBeInTheDocument();

    // 4. Switch to PDF Original tab
    await user.click(screen.getByRole("tab", { name: /PDF Original/i }));
    const iframe = screen.getByTitle("PDF original da ficha clínica");
    expect(iframe).toHaveAttribute("src", "/api/projects/proj-1/pdf");
  });

  it("displays clinical warnings, saves revision via api.saveArtifact, updates project and navigates to sql_db", async () => {
    const sample = makeSampleForm();
    vi.spyOn(api, "getArtifact").mockResolvedValue(makeArtifactRevision(sample));
    const warningsSpy = vi.spyOn(api, "getJsonWarnings").mockResolvedValue({
      project_id: "proj-1",
      version_num: 1,
      warnings_count: 1,
      warnings: [
        {
          code: "MULTIPLE_RADIO_GROUPS_RISK",
          severity: "warning",
          path: "perguntas[0].respostas",
          message: "Verifique grupos BOOLEANO_RADIO independentes.",
        },
      ],
    });

    const saveResponse: ArtifactSaveResponse = {
      artifact: makeArtifactRevision(sample, 2),
      generated_sql_insert: {
        id: 21,
        project_id: "proj-1",
        artifact_type: "sql_insert",
        version_num: 2,
        content: "DO $$ BEGIN END $$;",
        summary: "Auto",
        created_by: "system",
        created_at: "2026-01-01T13:00:00Z",
      },
      generated_sql_select: {
        id: 22,
        project_id: "proj-1",
        artifact_type: "sql_select",
        version_num: 2,
        content: "SELECT 1;",
        summary: "Auto",
        created_by: "system",
        created_at: "2026-01-01T13:00:00Z",
      },
    };
    const saveSpy = vi
      .spyOn(api, "saveArtifact")
      .mockResolvedValue(saveResponse);

    const user = userEvent.setup();
    const { onProjectUpdated, onNavigateSection } = renderFormBuilder();

    await waitFor(() => {
      expect(screen.getByText(/Avisos clínicos \(1\)/i)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Verifique grupos BOOLEANO_RADIO independentes/i),
    ).toBeInTheDocument();

    // Collapse warnings banner
    await user.click(screen.getByRole("button", { name: /Avisos clínicos/i }));
    expect(
      screen.queryByText(/Verifique grupos BOOLEANO_RADIO independentes/i),
    ).not.toBeInTheDocument();

    // Edit template name & save
    const nomeInput = screen.getByLabelText("Nome do template");
    await user.clear(nomeInput);
    await user.type(nomeInput, "ficha revisada");

    await user.click(screen.getByRole("button", { name: /Salvar revisão/i }));

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });

    const [projId, artType, payload] = saveSpy.mock.calls[0];
    expect(projId).toBe("proj-1");
    expect(artType).toBe("json");
    expect(payload.auto_regenerate_sql).toBe(true);
    expect(payload.apply_uppercase).toBe(true);
    expect(JSON.parse(payload.content).template.nome).toBe("FICHA REVISADA");

    expect(onProjectUpdated).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "proj-1",
        latest_artifacts: expect.objectContaining({
          json: 2,
          sql_insert: 2,
          sql_select: 2,
        }),
      }),
    );

    // Warnings reloaded after save
    await waitFor(() => {
      expect(warningsSpy).toHaveBeenCalledTimes(2);
    });

    // Navigate to SQL & Banco
    await user.click(
      screen.getByRole("button", { name: /Avançar para SQL & Banco/i }),
    );
    expect(onNavigateSection).toHaveBeenCalledWith("sql_db");
  });
});
