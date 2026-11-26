import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProjectRead } from "@/types/studio";
import { ProjectsDashboardView } from "./ProjectsDashboardView";

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "proj-1",
    slug: "ficha_triagem",
    name: "Ficha de Triagem Obstétrica",
    description: "Triagem inicial da maternidade",
    current_stage: "form_builder",
    entry_mode: "pdf",
    preferred_harness: "agy",
    template_db_id: 42,
    workspace_dir: "/tmp/ficha_triagem",
    has_pdf: true,
    gates: [
      {
        project_id: "proj-1",
        gate_name: "gate1_json",
        status: "approved",
        decided_by: "user",
        notes: "Revisado",
        updated_at: "2026-03-01T10:00:00Z",
      },
      {
        project_id: "proj-1",
        gate_name: "gate2_sql_insert",
        status: "pending",
        decided_by: null,
        notes: "",
        updated_at: "2026-03-01T10:00:00Z",
      },
      {
        project_id: "proj-1",
        gate_name: "gate3_jrxml",
        status: "rejected",
        decided_by: "user",
        notes: "Ajustar margens",
        updated_at: "2026-03-01T10:00:00Z",
      },
    ],
    latest_artifacts: {
      json: 3,
      sql_insert: 2,
      sql_select: 2,
    },
    created_at: "2026-03-01T09:00:00Z",
    updated_at: "2026-03-01T12:00:00Z",
    ...overrides,
  };
}

describe("ProjectsDashboardView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders project metadata, filters by search and stage, and triggers navigation shortcuts", async () => {
    const user = userEvent.setup();
    const p1 = makeProject();
    const p2 = makeProject({
      id: "proj-2",
      slug: "evolucao_enfermagem",
      name: "Evolução de Enfermagem",
      current_stage: "jrxml_design",
      entry_mode: "jrxml",
      template_db_id: null,
      has_pdf: false,
      latest_artifacts: { jrxml: 1 },
    });

    const onSelectProject = vi.fn();
    const onRefreshProjects = vi.fn().mockResolvedValue(undefined);
    const onDeleteProject = vi.fn().mockResolvedValue(undefined);

    render(
      <ToastProvider>
        <ProjectsDashboardView
          projects={[p1, p2]}
          loading={false}
          onRefreshProjects={onRefreshProjects}
          onSelectProject={onSelectProject}
          onDeleteProject={onDeleteProject}
        />
      </ToastProvider>,
    );

    expect(screen.getByText("Ficha de Triagem Obstétrica")).toBeInTheDocument();
    expect(screen.getByText("ficha_triagem")).toBeInTheDocument();
    expect(screen.getByText("ID #42")).toBeInTheDocument();
    expect(screen.getByText("JSON Clínico v3")).toBeInTheDocument();
    expect(screen.getByText("Evolução de Enfermagem")).toBeInTheDocument();

    // Filter by search query (slug)
    const searchInput = screen.getByLabelText(/Buscar projetos por nome ou slug/i);
    await user.type(searchInput, "evolucao");
    expect(screen.queryByText("Ficha de Triagem Obstétrica")).not.toBeInTheDocument();
    expect(screen.getByText("Evolução de Enfermagem")).toBeInTheDocument();

    // Clear search and filter by stage
    await user.click(screen.getByLabelText("Limpar busca"));
    await user.selectOptions(screen.getByLabelText("Filtrar por etapa"), "form_builder");
    expect(screen.getByText("Ficha de Triagem Obstétrica")).toBeInTheDocument();
    expect(screen.queryByText("Evolução de Enfermagem")).not.toBeInTheDocument();

    // Direct shortcuts
    await user.click(screen.getByRole("button", { name: /^Form Builder$/i }));
    expect(onSelectProject).toHaveBeenCalledWith(p1, "form_builder");

    await user.click(screen.getByRole("button", { name: /^SQL$/i }));
    expect(onSelectProject).toHaveBeenCalledWith(p1, "sql_db");

    await user.click(screen.getByRole("button", { name: /^Jasper$/i }));
    expect(onSelectProject).toHaveBeenCalledWith(p1, "jasper_studio");

    // Refresh button
    await user.click(screen.getByRole("button", { name: /Atualizar/i }));
    expect(onRefreshProjects).toHaveBeenCalledTimes(1);
  });

  it("confirms and deletes a project via dialog", async () => {
    const user = userEvent.setup();
    const project = makeProject();
    const onDeleteProject = vi.fn().mockResolvedValue(undefined);

    render(
      <ToastProvider>
        <ProjectsDashboardView
          projects={[project]}
          loading={false}
          onRefreshProjects={vi.fn().mockResolvedValue(undefined)}
          onSelectProject={vi.fn()}
          onDeleteProject={onDeleteProject}
        />
      </ToastProvider>,
    );

    await user.click(
      screen.getByRole("button", {
        name: /Excluir projeto Ficha de Triagem Obstétrica/i,
      }),
    );

    const dialog = screen.getByRole("dialog", { name: "Excluir projeto" });
    await user.click(
      within(dialog).getByRole("button", { name: /Confirmar exclusão/i }),
    );

    await waitFor(() => {
      expect(onDeleteProject).toHaveBeenCalledWith("proj-1");
    });
  });

  it("creates a project in PDF mode and uploads source.pdf", async () => {
    const user = userEvent.setup();
    const createdBase = makeProject({
      id: "proj-new",
      name: "Anamnese Pediátrica",
      has_pdf: false,
      current_stage: "landing",
    });
    const createdWithPdf = makeProject({
      id: "proj-new",
      name: "Anamnese Pediátrica",
      has_pdf: true,
      current_stage: "extraction",
    });

    const createSpy = vi
      .spyOn(api, "createProject")
      .mockResolvedValue(createdBase);
    const uploadSpy = vi
      .spyOn(api, "uploadProjectPdf")
      .mockResolvedValue(createdWithPdf);
    const onSelectProject = vi.fn();

    render(
      <ToastProvider>
        <ProjectsDashboardView
          projects={[]}
          loading={false}
          onRefreshProjects={vi.fn().mockResolvedValue(undefined)}
          onSelectProject={onSelectProject}
          onDeleteProject={vi.fn().mockResolvedValue(undefined)}
        />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: /Novo projeto/i }));
    const dialog = screen.getByRole("dialog", { name: "Novo projeto" });

    await user.type(
      within(dialog).getByLabelText(/Nome do projeto/i),
      "Anamnese Pediátrica",
    );
    await user.selectOptions(
      within(dialog).getByLabelText(/Harness de IA preferido/i),
      "claude",
    );

    const pdfFile = new File(["%PDF-1.4 mock"], "anamnese.pdf", {
      type: "application/pdf",
    });
    const fileInput = within(dialog).getByLabelText("Selecionar arquivo PDF");
    await user.upload(fileInput, pdfFile);

    await user.click(
      within(dialog).getByRole("button", { name: /^Criar projeto$/i }),
    );

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Anamnese Pediátrica",
          entry_mode: "pdf",
          preferred_harness: "claude",
        }),
      );
      expect(uploadSpy).toHaveBeenCalledWith("proj-new", pdfFile);
      expect(onSelectProject).toHaveBeenCalledWith(createdWithPdf);
    });
  });

  it("creates projects in JSON and JRXML modes with validation", async () => {
    const user = userEvent.setup();
    const jsonProject = makeProject({
      id: "proj-json",
      name: "Ficha JSON",
      entry_mode: "json",
      current_stage: "form_builder",
    });
    const jrxmlProject = makeProject({
      id: "proj-jrxml",
      name: "Ficha JRXML",
      entry_mode: "jrxml",
      current_stage: "jrxml_design",
    });

    const createSpy = vi
      .spyOn(api, "createProject")
      .mockResolvedValueOnce(jsonProject)
      .mockResolvedValueOnce(jrxmlProject);
    const onSelectProject = vi.fn();

    render(
      <ToastProvider>
        <ProjectsDashboardView
          projects={[]}
          loading={false}
          onRefreshProjects={vi.fn().mockResolvedValue(undefined)}
          onSelectProject={onSelectProject}
          onDeleteProject={vi.fn().mockResolvedValue(undefined)}
        />
      </ToastProvider>,
    );

    // JSON mode with invalid JSON first, then valid JSON
    await user.click(screen.getByRole("button", { name: /Novo projeto/i }));
    let dialog = screen.getByRole("dialog", { name: "Novo projeto" });
    await user.click(within(dialog).getByRole("tab", { name: /Importar JSON/i }));
    await user.type(within(dialog).getByLabelText(/Nome do projeto/i), "Ficha JSON");

    const jsonArea = within(dialog).getByLabelText(/JSON clínico inicial/i);
    await user.click(jsonArea);
    await user.paste("{invalid json");
    await user.click(within(dialog).getByRole("button", { name: /^Criar projeto$/i }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/JSON informado é inválido/i);

    await user.clear(jsonArea);
    await user.paste('{"template":{"nome":"TESTE"},"perguntas":[]}');
    await user.click(within(dialog).getByRole("button", { name: /^Criar projeto$/i }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Ficha JSON",
          entry_mode: "json",
          initial_json: '{"template":{"nome":"TESTE"},"perguntas":[]}',
        }),
      );
      expect(onSelectProject).toHaveBeenCalledWith(jsonProject);
    });

    // JRXML mode
    await user.click(screen.getByRole("button", { name: /Novo projeto/i }));
    dialog = screen.getByRole("dialog", { name: "Novo projeto" });
    await user.click(within(dialog).getByRole("tab", { name: /Importar JRXML/i }));
    await user.type(within(dialog).getByLabelText(/Nome do projeto/i), "Ficha JRXML");
    const jrxmlArea = within(dialog).getByLabelText(/Conteúdo JRXML inicial/i);
    await user.click(jrxmlArea);
    await user.paste("<jasperReport name='ficha'/>");
    await user.click(within(dialog).getByRole("button", { name: /^Criar projeto$/i }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Ficha JRXML",
          entry_mode: "jrxml",
          initial_jrxml: "<jasperReport name='ficha'/>",
        }),
      );
      expect(onSelectProject).toHaveBeenCalledWith(jrxmlProject);
    });
  });
});
