import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import type { DbProfileRead, ProjectRead } from "@/types/studio";
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

  it("filters by project kind pills (Todos / Relatórios / Fichas Clínicas) and hides clinical gate badges on free_report cards", async () => {
    const user = userEvent.setup();
    const clinicalProj = makeProject({
      id: "proj-clin",
      slug: "ficha_obstetrica",
      name: "Ficha Obstétrica",
      project_kind: "clinical_form",
    });
    const jsReport = makeProject({
      id: "proj-js",
      slug: "guia_internacao",
      name: "Guia de Internação",
      project_kind: "free_report",
      entry_mode: "jasperserver_import",
      source_origin: { provider: "jasperserver" },
      current_stage: "jrxml_design",
      template_db_id: null,
      has_pdf: false,
      latest_artifacts: { jrxml: 2 },
    });
    const sftpReport = makeProject({
      id: "proj-sftp",
      slug: "receituario_sftp",
      name: "Receituário SFTP",
      project_kind: "free_report",
      entry_mode: "sftp_import",
      source_origin: { provider: "sftp" },
      current_stage: "jrxml_design",
      template_db_id: null,
      has_pdf: false,
      latest_artifacts: { jrxml: 1 },
    });
    const blankReport = makeProject({
      id: "proj-blank",
      slug: "relatorio_produtividade",
      name: "Relatório Produtividade",
      project_kind: "free_report",
      entry_mode: "blank_report",
      current_stage: "jrxml_design",
      template_db_id: null,
      has_pdf: false,
      latest_artifacts: {},
    });

    render(
      <ToastProvider>
        <ProjectsDashboardView
          projects={[clinicalProj, jsReport, sftpReport, blankReport]}
          loading={false}
          onRefreshProjects={vi.fn().mockResolvedValue(undefined)}
          onSelectProject={vi.fn()}
          onDeleteProject={vi.fn().mockResolvedValue(undefined)}
        />
      </ToastProvider>,
    );

    // Filter to Relatórios -> only free_report projects visible, zero gate badges (G1/G2/G3)
    const filterGroup = screen.getByRole("group", {
      name: /Filtrar por tipo de projeto/i,
    });
    await user.click(
      within(filterGroup).getByRole("button", { name: /Relatórios/i }),
    );

    expect(screen.queryByText("Ficha Obstétrica")).not.toBeInTheDocument();
    expect(screen.getByText("Guia de Internação")).toBeInTheDocument();
    expect(screen.getByText("Receituário SFTP")).toBeInTheDocument();
    expect(screen.getByText("Relatório Produtividade")).toBeInTheDocument();

    // Clean origin badges shown; clinical-only gate jargon hidden
    expect(screen.getByText("JasperServer")).toBeInTheDocument();
    expect(screen.getByText("SFTP")).toBeInTheDocument();
    expect(screen.getByText("Relatório Livre")).toBeInTheDocument();
    expect(screen.queryByText("G1 JSON")).not.toBeInTheDocument();
    expect(screen.queryByText("G2 SQL")).not.toBeInTheDocument();
    expect(screen.queryByText("G3 JRXML")).not.toBeInTheDocument();

    // Filter to Fichas Clínicas -> gate badges preserved
    await user.click(
      within(filterGroup).getByRole("button", { name: /Fichas Clínicas/i }),
    );
    expect(screen.getByText("Ficha Obstétrica")).toBeInTheDocument();
    expect(screen.queryByText("Guia de Internação")).not.toBeInTheDocument();
    expect(screen.getByText("G1 JSON")).toBeInTheDocument();
    expect(screen.getByText("G2 SQL")).toBeInTheDocument();
    expect(screen.getByText("G3 JRXML")).toBeInTheDocument();

    // Back to Todos -> all 4 visible
    await user.click(
      within(filterGroup).getByRole("button", { name: /Todos/i }),
    );
    expect(screen.getByText("Ficha Obstétrica")).toBeInTheDocument();
    expect(screen.getByText("Guia de Internação")).toBeInTheDocument();
  });

  it("uses SearchableSelect for PostgreSQL profile in CreateProjectDialog (free_report)", async () => {
    const user = userEvent.setup();
    const profiles: DbProfileRead[] = [
      {
        id: "db-hml",
        name: "Banco Homologação",
        host: "10.1.2.3",
        port: 5432,
        dbname: "salutem_hml",
        user: "ro",
        sslmode: "prefer",
        environment: "HML",
        read_only: true,
        is_default: false,
        has_password: true,
        created_at: "2026-03-01T00:00:00Z",
        updated_at: "2026-03-01T00:00:00Z",
      },
      {
        id: "db-prd",
        name: "Banco Produção",
        host: "10.9.8.7",
        port: 5432,
        dbname: "salutem_prd",
        user: "ro",
        sslmode: "require",
        environment: "PRD",
        read_only: true,
        is_default: true,
        has_password: true,
        created_at: "2026-03-01T00:00:00Z",
        updated_at: "2026-03-01T00:00:00Z",
      },
    ];

    vi.spyOn(api, "listDbProfiles").mockResolvedValue(profiles);
    const createdFree = makeProject({
      id: "proj-free-1",
      name: "Relatório Faturamento",
      project_kind: "free_report",
      entry_mode: "blank_report",
      default_db_profile_id: "db-hml",
      current_stage: "jrxml_design",
    });
    const createSpy = vi
      .spyOn(api, "createProject")
      .mockResolvedValue(createdFree);
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
    await user.click(
      within(dialog).getByRole("tab", { name: /Relatório Livre/i }),
    );
    await user.type(
      within(dialog).getByLabelText(/Nome do projeto/i),
      "Relatório Faturamento",
    );

    // Open SearchableSelect and filter by environment/host
    const dbTrigger = within(dialog).getByRole("button", {
      name: /Perfil PostgreSQL padrão/i,
    });
    await user.click(dbTrigger);
    const searchInput = within(dialog).getByPlaceholderText(
      /Buscar por nome, host, banco ou ambiente/i,
    );
    await user.type(searchInput, "10.1.2.3");
    await user.click(
      within(dialog).getByRole("option", { name: /Banco Homologação/i }),
    );

    await user.click(
      within(dialog).getByRole("button", { name: /^Criar projeto$/i }),
    );

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Relatório Faturamento",
          entry_mode: "blank_report",
          project_kind: "free_report",
          default_db_profile_id: "db-hml",
        }),
      );
      expect(onSelectProject).toHaveBeenCalledWith(createdFree);
    });
  });
});
