import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type {
  ArtifactRevisionRead,
  CommitInsertResult,
  DbConnectionTestResult,
  DbProfileRead,
  DryRunInsertResult,
  InspectSelectResult,
  ProjectRead,
  SqlValidateResponse,
} from "@/types/studio";
import { SqlDbView } from "./index";
import { computeLineDiff } from "./sqlDiff";

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "proj-1",
    slug: "avaliacao_pre_anestesica",
    name: "Avaliação Pré-Anestésica",
    description: "Ficha clínica",
    current_stage: "sql_db",
    entry_mode: "pdf",
    preferred_harness: "agy",
    template_db_id: null,
    workspace_dir: "/tmp/proj-1",
    has_pdf: true,
    gates: [],
    latest_artifacts: { json: 1, sql_insert: 1, sql_select: 2 },
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

const SAMPLE_INSERT_ARTIFACT: ArtifactRevisionRead = {
  id: 101,
  project_id: "proj-1",
  artifact_type: "sql_insert",
  version_num: 1,
  content: "DO $$\nDECLARE\n  v_template_id BIGINT;\nBEGIN\n  RAISE NOTICE 'Template ID = 4042';\nEND $$;",
  summary: "Auto-generated INSERT",
  created_by: "system",
  created_at: "2026-01-01T10:01:00Z",
};

const SAMPLE_SELECT_ARTIFACT: ArtifactRevisionRead = {
  id: 102,
  project_id: "proj-1",
  artifact_type: "sql_select",
  version_num: 2,
  content: "SELECT\n  coalesce(bool_or(c.valor_booleano::bool), false) AS alergia,\n  max(c.valor_texto) AS alergia_obs\nFROM ficha_clinica fc\nWHERE fc.id = $P{id};",
  summary: "Auto-generated SELECT",
  created_by: "system",
  created_at: "2026-01-01T10:02:00Z",
};

const PROFILE_RW: DbProfileRead = {
  id: "prof-hml",
  name: "Homologação Salutem",
  host: "db-hml.salutem.local",
  port: 5432,
  dbname: "salutem_hml",
  user: "ficha_rw",
  sslmode: "prefer",
  read_only: false,
  is_default: true,
  has_password: true,
  created_at: "2026-01-01T09:00:00Z",
  updated_at: "2026-01-01T09:00:00Z",
};

const PROFILE_RO: DbProfileRead = {
  id: "prof-prod-ro",
  name: "Produção (Somente Leitura)",
  host: "db-prod.salutem.local",
  port: 5432,
  dbname: "salutem_prod",
  user: "ficha_ro",
  sslmode: "require",
  read_only: true,
  is_default: false,
  has_password: true,
  created_at: "2026-01-01T09:00:00Z",
  updated_at: "2026-01-01T09:00:00Z",
};

function renderSqlDbView(props?: {
  project?: ProjectRead;
  onProjectUpdated?: (p: ProjectRead) => void;
  onNavigateSection?: (s: string) => void;
}) {
  const project = props?.project ?? makeProject();
  const onProjectUpdated = props?.onProjectUpdated ?? vi.fn();
  const onNavigateSection = props?.onNavigateSection ?? vi.fn();

  const view = render(
    <ToastProvider>
      <SqlDbView
        project={project}
        onProjectUpdated={onProjectUpdated}
        onNavigateSection={onNavigateSection}
      />
    </ToastProvider>,
  );

  return { ...view, project, onProjectUpdated, onNavigateSection };
}

describe("computeLineDiff", () => {
  it("detects equal, added and removed lines cleanly", () => {
    const diff = computeLineDiff(
      "line 1\nline 2\nline 3",
      "line 1\nline 2 edited\nline 3\nline 4",
    );
    expect(diff.hasChanges).toBe(true);
    expect(diff.removedCount).toBe(1);
    expect(diff.addedCount).toBe(2);
    expect(diff.equalCount).toBe(2);
  });

  it("reports no changes for identical scripts with CRLF vs LF", () => {
    const diff = computeLineDiff("DO $$\r\nEND $$;", "DO $$\nEND $$;");
    expect(diff.hasChanges).toBe(false);
    expect(diff.addedCount).toBe(0);
    expect(diff.removedCount).toBe(0);
  });
});

describe("SqlDbView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads INSERT/SELECT artifacts, validates syntax with unknown_field_types, shows diff and regenerates with options", async () => {
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) => {
      if (type === "sql_insert") return SAMPLE_INSERT_ARTIFACT;
      return SAMPLE_SELECT_ARTIFACT;
    });
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW, PROFILE_RO]);

    const validateMock = vi
      .spyOn(api, "validateSql")
      .mockResolvedValue({
        valid: true,
        message: "Sintaxe SQL válida (PL/pgSQL balanceado).",
        artifact_type: "sql_insert",
        unknown_field_types: ["TIPO_LEGADO"],
      } satisfies SqlValidateResponse);

    const regenerateMock = vi.spyOn(api, "regenerateSql").mockResolvedValue({
      sql_insert: {
        ...SAMPLE_INSERT_ARTIFACT,
        version_num: 2,
        content: "DO $$\nBEGIN\n  RAISE NOTICE 'Regenerado v2';\nEND $$;",
      },
      sql_select: {
        ...SAMPLE_SELECT_ARTIFACT,
        version_num: 3,
        content:
          "SELECT max(c.valor_texto) AS pergunta_alergia FROM ficha_clinica fc WHERE fc.id = ${id};",
      },
    });

    const user = userEvent.setup();
    renderSqlDbView();

    // Wait for INSERT editor to load
    const editor = await screen.findByLabelText(/Editor SQL INSERT/i);
    expect(editor).toHaveValue(SAMPLE_INSERT_ARTIFACT.content);
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();

    // Validate syntax and verify unknown_field_types badge
    await user.click(screen.getByRole("button", { name: /Validar sintaxe/i }));
    await waitFor(() => {
      expect(validateMock).toHaveBeenCalledWith("proj-1", {
        sql: SAMPLE_INSERT_ARTIFACT.content,
        artifact_type: "sql_insert",
      });
    });
    expect(screen.getByText(/Sintaxe PostgreSQL válida/i)).toBeInTheDocument();
    expect(screen.getByText("TIPO_LEGADO")).toBeInTheDocument();

    // Edit INSERT SQL -> "Modificado" indicator + line-by-line diff viewer
    await user.type(editor, "\n-- ajuste manual");
    expect(screen.getByText("Modificado")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Ver diff com revisão salva/i }),
    );
    expect(screen.getByLabelText(/Diff de SQL INSERT/i)).toBeInTheDocument();
    expect(screen.getByText("-- ajuste manual")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Voltar ao editor/i }));

    // Open regenerate panel and customize SELECT options
    await user.click(screen.getByRole("button", { name: /Regenerar do JSON/i }));
    await user.selectOptions(
      screen.getByLabelText(/Estilo booleano/i),
      "sim_nao",
    );
    await user.selectOptions(
      screen.getByLabelText(/Nomeação das colunas/i),
      "pergunta_label",
    );
    await user.selectOptions(
      screen.getByLabelText(/Sintaxe do parâmetro/i),
      "salutem",
    );
    await user.click(screen.getByRole("switch", { name: /Incluir colunas _obs/i }));

    await user.click(
      screen.getByRole("button", { name: /Regenerar SQL \(INSERT \+ SELECT\)/i }),
    );

    await waitFor(() => {
      expect(regenerateMock).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({
          select_options: {
            boolean_style: "sim_nao",
            column_naming: "pergunta_label",
            param_syntax: "salutem",
            include_obs: false,
          },
        }),
      );
    });

    // Switch to SELECT tab and verify regenerated content
    await user.click(screen.getByRole("tab", { name: /SQL SELECT Jasper/i }));
    const selectEditor = await screen.findByLabelText(/Editor SQL SELECT/i);
    expect(selectEditor).toHaveValue(
      "SELECT max(c.valor_texto) AS pergunta_alergia FROM ficha_clinica fc WHERE fc.id = ${id};",
    );
  });

  it("shows empty state when SQL artifacts do not exist yet and generates from JSON", async () => {
    vi.spyOn(api, "getArtifact").mockRejectedValue(
      new ApiError(404, "Artifact not found"),
    );
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([]);

    const regenerateMock = vi.spyOn(api, "regenerateSql").mockResolvedValue({
      sql_insert: SAMPLE_INSERT_ARTIFACT,
      sql_select: SAMPLE_SELECT_ARTIFACT,
    });

    const onNavigateSection = vi.fn();
    const user = userEvent.setup();
    renderSqlDbView({ onNavigateSection });

    expect(
      await screen.findByText(/Nenhum script SQL gerado ainda/i),
    ).toBeInTheDocument();

    // Missing profile callout navigates to settings
    await user.click(
      screen.getByRole("button", { name: /Configurar perfil PostgreSQL/i }),
    );
    expect(onNavigateSection).toHaveBeenCalledWith("settings");

    // Generate SQL from JSON
    const generateButtons = screen.getAllByRole("button", {
      name: /Gerar SQL a partir do JSON/i,
    });
    await user.click(generateButtons[0]);

    await waitFor(() => {
      expect(regenerateMock).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByLabelText(/Editor SQL INSERT/i),
    ).toHaveValue(SAMPLE_INSERT_ARTIFACT.content);
  });

  it("blocks COMMIT before Dry-Run and strictly blocks COMMIT on read-only profiles", async () => {
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) =>
      type === "sql_insert" ? SAMPLE_INSERT_ARTIFACT : SAMPLE_SELECT_ARTIFACT,
    );
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW, PROFILE_RO]);

    vi.spyOn(api, "testDbProfile").mockResolvedValue({
      profile_id: PROFILE_RO.id,
      ok: true,
      latency_ms: 14,
      server_version: "PostgreSQL 16.2",
      current_database: "salutem_prod",
      current_user: "ficha_ro",
      read_only: true,
      message: "Conexão OK",
      error: null,
    } satisfies DbConnectionTestResult);

    vi.spyOn(api, "dryRunInsert").mockResolvedValue({
      ok: true,
      project_id: "proj-1",
      profile_id: PROFILE_RO.id,
      rolled_back: true,
      template_id: null,
      simulated_template_id: 9001,
      notices: ["NOTICE: Template ID simulado = 9001"],
      sql_sha256: "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
      dry_run_token: "token-ro-1",
      latency_ms: 21,
      message: "Dry-Run OK",
    } satisfies DryRunInsertResult);

    const user = userEvent.setup();
    renderSqlDbView();

    await screen.findByLabelText(/Editor SQL INSERT/i);

    const commitBtn = screen.getByRole("button", {
      name: /Confirmar e executar INSERT \(COMMIT\)/i,
    });
    // Strictly disabled before Dry-Run
    expect(commitBtn).toBeDisabled();

    // Switch to read-only profile via SearchableSelect
    await user.click(screen.getByRole("button", { name: /Conexão alvo/i }));
    await user.click(
      screen.getByRole("option", { name: /Produção \(Somente Leitura\)/i }),
    );
    expect(screen.getAllByText(/Somente Leitura/i).length).toBeGreaterThanOrEqual(
      1,
    );
    expect(screen.getByText(/Trava Somente Leitura ativa/i)).toBeInTheDocument();

    // Test connection works
    await user.click(screen.getByRole("button", { name: /Testar conexão/i }));
    expect(await screen.findByText("PostgreSQL 16.2")).toBeInTheDocument();

    // Even after Dry-Run passes on read-only profile, COMMIT must remain disabled
    await user.click(
      screen.getByRole("button", { name: /Executar Dry-Run \(BEGIN\/ROLLBACK\)/i }),
    );
    expect(await screen.findByText("Dry-Run aprovado")).toBeInTheDocument();
    expect(commitBtn).toBeDisabled();
  });

  it("enforces full 2-step Dry-Run -> token invalidation on edit -> new Dry-Run -> Dialog -> COMMIT", async () => {
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) =>
      type === "sql_insert" ? SAMPLE_INSERT_ARTIFACT : SAMPLE_SELECT_ARTIFACT,
    );
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW, PROFILE_RO]);

    const dryRunMock = vi
      .spyOn(api, "dryRunInsert")
      .mockResolvedValueOnce({
        ok: true,
        project_id: "proj-1",
        profile_id: PROFILE_RW.id,
        rolled_back: true,
        template_id: null,
        simulated_template_id: 4042,
        notices: ["NOTICE: Template criado (simulação) id=4042"],
        sql_sha256:
          "111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0000",
        dry_run_token: "token-first-1",
        latency_ms: 35,
        message: "Dry-Run concluído com ROLLBACK.",
      } satisfies DryRunInsertResult)
      .mockResolvedValueOnce({
        ok: true,
        project_id: "proj-1",
        profile_id: PROFILE_RW.id,
        rolled_back: true,
        template_id: null,
        simulated_template_id: 4043,
        notices: ["NOTICE: Template criado (simulação) id=4043"],
        sql_sha256:
          "999988887777666655554444333322221111ffff0000eeeebbbbccccddddaaaa",
        dry_run_token: "token-second-2",
        latency_ms: 28,
        message: "Dry-Run concluído com ROLLBACK.",
      } satisfies DryRunInsertResult);

    const commitMock = vi.spyOn(api, "commitInsert").mockResolvedValue({
      ok: true,
      committed: true,
      project_id: "proj-1",
      profile_id: PROFILE_RW.id,
      template_id: 4043,
      notices: ["NOTICE: Template gravado id=4043"],
      sql_sha256:
        "999988887777666655554444333322221111ffff0000eeeebbbbccccddddaaaa",
      artifact_version: 2,
      gate2_status: "approved",
      latency_ms: 42,
      message: "INSERT executado com COMMIT e Gate 2 aprovado.",
    } satisfies CommitInsertResult);

    const updatedProject = makeProject({
      template_db_id: 4043,
      current_stage: "jrxml_design",
    });
    const getProjectMock = vi
      .spyOn(api, "getProject")
      .mockResolvedValue(updatedProject);

    const onProjectUpdated = vi.fn();
    const onNavigateSection = vi.fn();
    const user = userEvent.setup();
    renderSqlDbView({ onProjectUpdated, onNavigateSection });

    const editor = await screen.findByLabelText(/Editor SQL INSERT/i);
    const dryRunBtn = screen.getByRole("button", {
      name: /Executar Dry-Run \(BEGIN\/ROLLBACK\)/i,
    });
    const commitBtn = screen.getByRole("button", {
      name: /Confirmar e executar INSERT \(COMMIT\)/i,
    });

    expect(commitBtn).toBeDisabled();

    // 1) First Dry-Run passes
    await user.click(dryRunBtn);
    const approvedCard = await screen.findByTestId("dry-run-approved-card");
    expect(within(approvedCard).getByText("Dry-Run aprovado")).toBeInTheDocument();
    expect(within(approvedCard).getByText("ROLLBACK confirmado")).toBeInTheDocument();
    expect(within(approvedCard).getByText("#4042")).toBeInTheDocument();
    expect(within(approvedCard).getByText("35 ms")).toBeInTheDocument();
    expect(
      within(approvedCard).getByText(/Template criado \(simulação\) id=4042/i),
    ).toBeInTheDocument();
    expect(commitBtn).toBeEnabled();

    // 2) Edit SQL INSERT -> immediately invalidates dry_run_token and re-locks COMMIT
    await user.type(editor, "\n-- alteracao pos dry-run");
    expect(screen.queryByTestId("dry-run-approved-card")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Token de Dry-Run invalidado/i),
    ).toBeInTheDocument();
    expect(commitBtn).toBeDisabled();

    // 3) Run second Dry-Run for edited SQL
    await user.click(dryRunBtn);
    const secondCard = await screen.findByTestId("dry-run-approved-card");
    expect(within(secondCard).getByText("#4043")).toBeInTheDocument();
    expect(dryRunMock).toHaveBeenCalledTimes(2);
    expect(commitBtn).toBeEnabled();

    // 4) Click COMMIT -> confirmation Dialog opens
    await user.click(commitBtn);
    const dialog = await screen.findByRole("dialog", {
      name: /Confirmar e executar INSERT \(COMMIT\)/i,
    });
    expect(within(dialog).getByText("Homologação Salutem")).toBeInTheDocument();
    expect(
      within(dialog).getByText("db-hml.salutem.local:5432/salutem_hml"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("#4043")).toBeInTheDocument();

    // Confirm inside Dialog -> calls commitInsert with second token
    await user.click(
      within(dialog).getByRole("button", {
        name: /Confirmar COMMIT no PostgreSQL/i,
      }),
    );

    await waitFor(() => {
      expect(commitMock).toHaveBeenCalledWith("proj-1", {
        profile_id: PROFILE_RW.id,
        dry_run_token: "token-second-2",
        sql_text: `${SAMPLE_INSERT_ARTIFACT.content}\n-- alteracao pos dry-run`,
      });
    });

    // Success banner, project refresh, and Jasper Studio CTA
    const banner = await screen.findByTestId("commit-success-banner");
    expect(within(banner).getByText(/template_id: #4043/i)).toBeInTheDocument();
    expect(getProjectMock).toHaveBeenCalledWith("proj-1");
    expect(onProjectUpdated).toHaveBeenCalledWith(updatedProject);

    await user.click(
      within(banner).getByRole("button", {
        name: /Avançar para Jasper Studio/i,
      }),
    );
    expect(onNavigateSection).toHaveBeenCalledWith("jasper_studio");
  });

  it("inspects SELECT with LIMIT 0 and displays columns table with PG types, OIDs and Java classes", async () => {
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) =>
      type === "sql_insert" ? SAMPLE_INSERT_ARTIFACT : SAMPLE_SELECT_ARTIFACT,
    );
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW]);

    const inspectMock = vi.spyOn(api, "inspectSelect").mockResolvedValue({
      ok: true,
      profile_id: PROFILE_RW.id,
      columns: [
        {
          name: "alergia",
          type_oid: 16,
          pg_type: "bool",
          java_class: "java.lang.Boolean",
          nullable: false,
        },
        {
          name: "alergia_obs",
          type_oid: 25,
          pg_type: "text",
          java_class: "java.lang.String",
          nullable: true,
        },
        {
          name: "peso_kg",
          type_oid: 1700,
          pg_type: "numeric",
          java_class: "java.lang.Double",
          nullable: true,
        },
      ],
      sample_id_used: 88210,
      sample_atendimento_id: 88210,
      parameter_placeholders_replaced: 1,
      latency_ms: 19,
      message: "3 colunas descobertas.",
    } satisfies InspectSelectResult);

    const user = userEvent.setup();
    renderSqlDbView();

    await screen.findByLabelText(/Editor SQL INSERT/i);

    // Toggle "Buscar atendimento real recente"
    await user.click(
      screen.getByRole("switch", { name: /Buscar atendimento real recente/i }),
    );
    expect(screen.getByLabelText(/ID de atendimento \(opcional\)/i)).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: /Inspecionar colunas do SELECT \(LIMIT 0\)/i }),
    );

    await waitFor(() => {
      expect(inspectMock).toHaveBeenCalledWith("proj-1", {
        profile_id: PROFILE_RW.id,
        sql_select: SAMPLE_SELECT_ARTIFACT.content,
        lookup_sample_id: true,
      });
    });

    // Verify table rows and metadata
    expect(await screen.findByText("alergia")).toBeInTheDocument();
    expect(screen.getByText("java.lang.Boolean")).toBeInTheDocument();
    expect(screen.getByText("alergia_obs")).toBeInTheDocument();
    expect(screen.getByText("java.lang.String")).toBeInTheDocument();
    expect(screen.getByText("peso_kg")).toBeInTheDocument();
    expect(screen.getByText("java.lang.Double")).toBeInTheDocument();
    expect(screen.getByText("1700")).toBeInTheDocument();
    expect(screen.getByText("88210")).toBeInTheDocument();
    expect(screen.getByText(/Total: 3 colunas/i)).toBeInTheDocument();
  });

  it("saves manual SQL revision and invalidates Dry-Run token when switching PostgreSQL profiles", async () => {
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) =>
      type === "sql_insert" ? SAMPLE_INSERT_ARTIFACT : SAMPLE_SELECT_ARTIFACT,
    );
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW, PROFILE_RO]);

    const saveMock = vi.spyOn(api, "saveArtifact").mockResolvedValue({
      artifact: {
        ...SAMPLE_INSERT_ARTIFACT,
        version_num: 2,
        content: `${SAMPLE_INSERT_ARTIFACT.content}\n-- revisao manual`,
      },
      generated_sql_insert: null,
      generated_sql_select: null,
    });

    vi.spyOn(api, "dryRunInsert").mockResolvedValue({
      ok: true,
      project_id: "proj-1",
      profile_id: PROFILE_RW.id,
      rolled_back: true,
      template_id: null,
      simulated_template_id: 5001,
      notices: [],
      sql_sha256: "deadbeef1234567890deadbeef1234567890deadbeef1234567890deadbeef12",
      dry_run_token: "token-prof-switch",
      latency_ms: 17,
      message: "Dry-Run OK",
    } satisfies DryRunInsertResult);

    const inspectMock = vi.spyOn(api, "inspectSelect").mockResolvedValue({
      ok: true,
      profile_id: PROFILE_RO.id,
      columns: [
        {
          name: "paciente_nome",
          type_oid: 1043,
          pg_type: "varchar",
          java_class: "java.lang.String",
          nullable: true,
        },
      ],
      sample_id_used: 12345,
      sample_atendimento_id: null,
      parameter_placeholders_replaced: 1,
      latency_ms: 11,
      message: "1 coluna",
    } satisfies InspectSelectResult);

    const user = userEvent.setup();
    renderSqlDbView();

    const editor = await screen.findByLabelText(/Editor SQL INSERT/i);
    await user.type(editor, "\n-- revisao manual");
    expect(screen.getByText("Modificado")).toBeInTheDocument();

    // Save revision
    await user.click(screen.getByRole("button", { name: /Salvar revisão/i }));
    await waitFor(() => {
      expect(saveMock).toHaveBeenCalledWith(
        "proj-1",
        "sql_insert",
        expect.objectContaining({
          content: `${SAMPLE_INSERT_ARTIFACT.content}\n-- revisao manual`,
          created_by: "user",
        }),
      );
    });
    expect(await screen.findByText("Revisão v2 sincronizada")).toBeInTheDocument();

    // Run Dry-Run on RW profile -> approved
    await user.click(
      screen.getByRole("button", { name: /Executar Dry-Run \(BEGIN\/ROLLBACK\)/i }),
    );
    expect(await screen.findByTestId("dry-run-approved-card")).toBeInTheDocument();

    // Switch profile via SearchableSelect -> immediately invalidates token
    await user.click(screen.getByRole("button", { name: /Conexão alvo/i }));
    await user.click(
      screen.getByRole("option", { name: /Produção \(Somente Leitura\)/i }),
    );
    expect(screen.queryByTestId("dry-run-approved-card")).not.toBeInTheDocument();
    expect(
      screen.getByText(/O perfil PostgreSQL foi alterado após o último Dry-Run/i),
    ).toBeInTheDocument();

    // Inspect SELECT with explicit sample_id
    await user.type(screen.getByLabelText(/ID de atendimento \(opcional\)/i), "12345");
    await user.click(
      screen.getByRole("button", { name: /Inspecionar colunas do SELECT \(LIMIT 0\)/i }),
    );
    await waitFor(() => {
      expect(inspectMock).toHaveBeenCalledWith("proj-1", {
        profile_id: PROFILE_RO.id,
        sql_select: SAMPLE_SELECT_ARTIFACT.content,
        sample_id: 12345,
        lookup_sample_id: false,
      });
    });
    expect(await screen.findByText("paciente_nome")).toBeInTheDocument();
  });

  it("uses SearchableSelect in free_report SQL Workbench and persists default_db_profile_id on change", async () => {
    const freeProject = makeProject({
      id: "proj-free-sql",
      project_kind: "free_report",
      entry_mode: "blank_report",
      default_db_profile_id: PROFILE_RW.id,
    });
    vi.spyOn(api, "getArtifact").mockImplementation(async (_id, type) => {
      if (type === "sql_select") return SAMPLE_SELECT_ARTIFACT;
      throw new ApiError(404, "Not found");
    });
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([PROFILE_RW, PROFILE_RO]);

    const updatedProj: ProjectRead = {
      ...freeProject,
      default_db_profile_id: PROFILE_RO.id,
    };
    const updateSpy = vi
      .spyOn(api, "updateProject")
      .mockResolvedValue(updatedProj);
    const onProjectUpdated = vi.fn();

    const user = userEvent.setup();
    renderSqlDbView({ project: freeProject, onProjectUpdated });

    expect(
      await screen.findByTestId("free-report-sql-workbench"),
    ).toBeInTheDocument();

    // SearchableSelect for DB profile in free_report workbench
    const trigger = screen.getByRole("button", {
      name: /Perfil PostgreSQL do Workbench/i,
    });
    await user.click(trigger);
    await user.type(
      screen.getByPlaceholderText(/Buscar por nome, host, banco ou ambiente/i),
      "salutem_prod",
    );
    await user.click(
      screen.getByRole("option", { name: /Produção \(Somente Leitura\)/i }),
    );

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(freeProject.id, {
        default_db_profile_id: PROFILE_RO.id,
      });
      expect(onProjectUpdated).toHaveBeenCalledWith(updatedProj);
    });
  });
});
