import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { StudioShell } from "@/components/layout/StudioShell";
import { FAVORITE_CLIENTS_STORAGE_KEY, HomeView } from "@/features/home";
import { jasperServerApi } from "@/features/jasperserver/jasperServerApi";
import { sftpApi } from "@/features/sftp/sftpApi";
import { api } from "@/lib/api";
import type { ClientUnitRead, ProjectRead } from "@/types/studio";
import { clientsApi } from "./clientsApi";
import { ClientsView } from "./ClientsView";

const SAMPLE_CLIENTS: ClientUnitRead[] = [
  {
    id: "unit-1",
    external_id: "101",
    unit_code: "ALPHA-01",
    name: "Unidade Alpha Exemplo",
    hosting: "Cloud",
    license_status: "Licença Ativa",
    notes: "Unidade piloto sintética",
    tags: ["prioridade"],
    integrations: ["RNDS", "e-SUS"],
    last_synced_at: "2026-11-27T10:00:00Z",
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
    systems: [
      {
        id: "sys-amb-prd",
        client_unit_id: "unit-1",
        system_key: "ambulatorial_prd",
        label: "Ambulatorial PRD",
        system_type: "ambulatorial",
        environment: "PRD",
        system_url: "https://amb.alpha.example.local",
        version_label: "4.14.0",
        db_profile_id: "pg-alpha-amb",
        sftp_profile_id: "sftp-alpha-amb",
        jasperserver_profile_id: null,
        metadata: {
          pg_host: "db-amb.alpha.example.local",
          sftp_host: "sftp.alpha.example.local",
        },
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
      {
        id: "sys-hosp-hml",
        client_unit_id: "unit-1",
        system_key: "hospitalar_hml",
        label: "Hospitalar Homologação",
        system_type: "hospitalar",
        environment: "HML",
        system_url: "https://hosp-hml.alpha.example.local",
        version_label: "3.9.2",
        db_profile_id: "pg-alpha-hosp",
        sftp_profile_id: null,
        jasperserver_profile_id: "js-alpha-hosp",
        metadata: {
          jasper_url: "https://jasper.alpha.example.local/jasperserver",
        },
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ],
  },
  {
    id: "unit-2",
    external_id: "202",
    unit_code: "BETA-02",
    name: "Unidade Beta Exemplo",
    hosting: "On-Premise",
    license_status: "Ativa",
    notes: "",
    tags: ["regional"],
    integrations: [],
    last_synced_at: null,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
    systems: [
      {
        id: "sys-beta-amb",
        client_unit_id: "unit-2",
        system_key: "ambulatorial_prd",
        label: "Ambulatorial PRD",
        system_type: "ambulatorial",
        environment: "PRD",
        system_url: "https://amb.beta.example.local",
        version_label: "4.12.1",
        db_profile_id: "pg-beta-amb",
        sftp_profile_id: null,
        jasperserver_profile_id: null,
        metadata: {},
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ],
  },
];

const SAMPLE_IMPORTED_PROJECT: ProjectRead = {
  id: "proj-imp-1",
  slug: "resumo_alta",
  name: "Resumo de Alta",
  description: "Importado do JasperServer",
  project_kind: "free_report",
  current_stage: "jrxml_design",
  entry_mode: "jasperserver_import",
  preferred_harness: "agy",
  template_db_id: null,
  default_db_profile_id: "pg-alpha-hosp",
  client_system_id: null,
  source_origin: { provider: "jasperserver" },
  workspace_dir: "/tmp/workspaces/resumo_alta",
  has_pdf: false,
  gates: [],
  latest_artifacts: { jrxml: 1 },
  created_at: "2026-11-27T10:00:00Z",
  updated_at: "2026-11-27T10:00:00Z",
};

describe("ClientsView Master-Detail & ClientSyncDialog", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders Master-Detail layout, defaults to inline JasperServer explorer, and opens report in 1 click", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue(SAMPLE_CLIENTS);
    vi.spyOn(jasperServerApi, "listResources").mockResolvedValue([
      {
        uri: "/reports/resumo_alta",
        label: "Resumo de Alta",
        description: "Relatório hospitalar",
        resource_type: "reportUnit",
        updated_at: "2026-11-27T09:00:00Z",
      },
    ]);
    const importJasperSpy = vi
      .spyOn(jasperServerApi, "importReport")
      .mockResolvedValue(SAMPLE_IMPORTED_PROJECT);
    vi.spyOn(sftpApi, "browse").mockResolvedValue({
      profile_id: "sftp-alpha-amb",
      current_path: "/opt/salutem/relatorios",
      parent_path: "/opt/salutem",
      entries: [
        {
          name: "ficha_evolucao.jrxml",
          path: "/opt/salutem/relatorios/ficha_evolucao.jrxml",
          is_dir: false,
          size_bytes: 4096,
          modified_at: "2026-11-27T09:00:00Z",
          kind: "jrxml",
          has_paired_file: true,
        },
      ],
    });
    const importSftpSpy = vi.spyOn(sftpApi, "importReport").mockResolvedValue({
      ...SAMPLE_IMPORTED_PROJECT,
      id: "proj-sftp-2",
      name: "ficha evolucao",
      entry_mode: "sftp_import",
    });

    const onProjectImported = vi.fn();
    const onCreateFreeReport = vi.fn();
    const onOpenSettings = vi.fn();

    render(
      <ToastProvider>
        <ClientsView
          onProjectImported={onProjectImported}
          onCreateFreeReport={onCreateFreeReport}
          onOpenSettings={onOpenSettings}
        />
      </ToastProvider>,
    );

    // Master list renders both clients and auto-selects first client
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Unidade Alpha Exemplo" }),
      ).toBeInTheDocument();
      expect(screen.getByText("Unidade Beta Exemplo")).toBeInTheDocument();
    });

    // Header direct clickable web links
    const ambLink = screen.getByRole("link", { name: /Abrir Ambulatorial/i });
    expect(ambLink).toHaveAttribute("href", "https://amb.alpha.example.local");
    expect(ambLink).toHaveAttribute("target", "_blank");

    // Defaults to JasperServer tab and loads report units inline
    await waitFor(() => {
      expect(screen.getByText("Resumo de Alta")).toBeInTheDocument();
    });

    // 1-click "Abrir no Studio" imports report and notifies parent
    await user.click(
      screen.getByRole("button", { name: /Abrir no Studio/i }),
    );
    await waitFor(() => {
      expect(importJasperSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          profile_id: "js-alpha-hosp",
          resource_uri: "/reports/resumo_alta",
          db_profile_id: "pg-alpha-hosp",
          sync_subreports: true,
        }),
      );
      expect(onProjectImported).toHaveBeenCalledWith(SAMPLE_IMPORTED_PROJECT);
    });

    // Switch to SFTP tab and open file in 1 click
    await user.click(screen.getByRole("tab", { name: /Fichas \(SFTP\)/i }));
    await waitFor(() => {
      expect(screen.getByText("ficha_evolucao.jrxml")).toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: /Abrir no Studio/i }),
    );
    await waitFor(() => {
      expect(importSftpSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          profile_id: "sftp-alpha-amb",
          remote_path: "/opt/salutem/relatorios/ficha_evolucao.jrxml",
          db_profile_id: "pg-alpha-amb",
          sync_subreports: true,
        }),
      );
    });

    // Switch to Conexões & Sistemas tab -> test Novo Relatório Livre & Credenciais Padrão
    await user.click(
      screen.getByRole("tab", { name: /Conexões & Sistemas/i }),
    );
    await user.click(
      screen.getAllByRole("button", {
        name: /Novo Relatório Livre neste Banco/i,
      })[0],
    );
    expect(onCreateFreeReport).toHaveBeenCalledWith({
      clientSystemId: "sys-amb-prd",
      dbProfileId: "pg-alpha-amb",
      defaultName: "Unidade Alpha Exemplo — Ambulatorial PRD",
    });

    await user.click(
      screen.getByRole("button", { name: /Credenciais Padrão/i }),
    );
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("supports favorites persistence, filter pills, instant search, and initialSelectedClientId", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue(SAMPLE_CLIENTS);
    vi.spyOn(jasperServerApi, "listResources").mockResolvedValue([]);

    render(
      <ToastProvider>
        <ClientsView initialSelectedClientId="unit-2" />
      </ToastProvider>,
    );

    // initialSelectedClientId selects Unidade Beta Exemplo right away
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Unidade Beta Exemplo" }),
      ).toBeInTheDocument();
    });

    // Star Unidade Beta Exemplo -> persisted in localStorage
    await user.click(
      screen.getByRole("button", {
        name: /Marcar Unidade Beta Exemplo como favorito/i,
      }),
    );
    expect(
      JSON.parse(
        window.localStorage.getItem(FAVORITE_CLIENTS_STORAGE_KEY) || "[]",
      ),
    ).toEqual(["unit-2"]);

    // Filter by ★ Favoritos pill
    await user.click(screen.getByRole("button", { name: /^Favoritos/i }));
    expect(
      screen.queryByText("Unidade Alpha Exemplo"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText("Unidade Beta Exemplo").length,
    ).toBeGreaterThanOrEqual(1);

    // Reset with "Todos" pill, then filter by "Hospitalar"
    await user.click(screen.getByRole("button", { name: /^Todos$/i }));
    await user.click(screen.getByRole("button", { name: /^Hospitalar$/i }));
    expect(
      screen.getAllByText("Unidade Alpha Exemplo").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.queryByRole("button", {
        name: /Remover Unidade Beta Exemplo dos favoritos/i,
      }),
    ).not.toBeInTheDocument();

    // Reset and search by tag
    await user.click(screen.getByRole("button", { name: /^Todos$/i }));
    await user.type(screen.getByLabelText(/Buscar clientes/i), "regional");
    expect(
      screen.queryByText("Unidade Alpha Exemplo"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText("Unidade Beta Exemplo").length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("completes the 2-step portal sync dialog (local URL config -> preview diff -> apply)", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue([]);
    vi.spyOn(clientsApi, "getSyncSnippet").mockResolvedValue({
      management_portal_url: "",
      console_snippet:
        "fetch('/api/management/data', { credentials: 'include' })",
      bookmarklet: "javascript:void(0)",
      instructions: ["Passo 1: abrir portal", "Passo 2: colar JSON"],
    });
    const saveCfgSpy = vi
      .spyOn(clientsApi, "saveSyncConfig")
      .mockResolvedValue({
        management_portal_url: "https://portal.exemplo.local",
      });
    const previewSpy = vi
      .spyOn(clientsApi, "previewClientSync")
      .mockResolvedValue({
        ok: true,
        total_parsed: 1,
        to_create: 1,
        to_update: 0,
        unchanged: 0,
        warnings: [],
        items: [
          {
            unit_code: "GAMMA-01",
            name: "Unidade Gamma Exemplo",
            action: "create",
            systems_count: 2,
            changes: ["Novo cliente com 2 sistema(s)"],
          },
        ],
        normalized_units: [],
      });
    const applySpy = vi
      .spyOn(clientsApi, "applyClientSync")
      .mockResolvedValue({
        ok: true,
        created_units: 1,
        updated_units: 0,
        created_systems: 2,
        updated_systems: 0,
        created_profiles: { postgres: 2, sftp: 1, jasperserver: 1 },
        warnings: [],
      });

    render(
      <ToastProvider>
        <ClientsView />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Nenhum cliente cadastrado")).toBeInTheDocument();
    });

    // Open Sync Dialog
    await user.click(
      screen.getByRole("button", { name: /Sincronizar do Portal/i }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: /Sincronizar Clientes do Portal/i,
    });

    // Portal URL starts empty, user saves local URL
    const urlInput = within(dialog).getByLabelText(/URL do portal de gestão/i);
    expect(urlInput).toHaveValue("");
    await user.type(urlInput, "https://portal.exemplo.local");
    await user.click(
      within(dialog).getByRole("button", { name: /Salvar URL local/i }),
    );
    await waitFor(() => {
      expect(saveCfgSpy).toHaveBeenCalledWith("https://portal.exemplo.local");
    });

    // SSH password import toggle is OFF by default
    const sshSwitch = within(dialog).getByRole("switch", {
      name: /Importar senhas SSH no cofre local/i,
    });
    expect(sshSwitch).toHaveAttribute("aria-checked", "false");

    // Paste synthetic JSON and click Preview
    const textarea = within(dialog).getByLabelText(/Colar JSON \/ HTML/i);
    await user.click(textarea);
    await user.paste(
      '{"units":[{"unit_code":"GAMMA-01","name":"Unidade Gamma Exemplo","systems":[]}]}',
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: /Analisar e Pré-visualizar/i,
      }),
    );

    // Step 2: Diff table rendered
    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText("Unidade Gamma Exemplo")).toBeInTheDocument();
      expect(
        screen.getByText("Novo cliente com 2 sistema(s)"),
      ).toBeInTheDocument();
    });

    // Confirm Apply
    await user.click(
      screen.getByRole("button", { name: /Confirmar Sincronização/i }),
    );

    await waitFor(() => {
      expect(applySpy).toHaveBeenCalledWith(
        expect.objectContaining({
          import_ssh_passwords: false,
        }),
      );
    });
  });

  it("shows 'Novo Relatório Livre' when a system has no PG profile and uses SearchableSelect dropdowns in ClientSystemFormDialog", async () => {
    const user = userEvent.setup();
    const clientWithoutPg: ClientUnitRead = {
      ...SAMPLE_CLIENTS[1],
      systems: [
        {
          ...SAMPLE_CLIENTS[1].systems[0],
          id: "sys-no-pg",
          label: "Painel Sem Banco",
          db_profile_id: null,
          sftp_profile_id: null,
          jasperserver_profile_id: null,
        },
      ],
    };

    vi.spyOn(clientsApi, "listClients").mockResolvedValue([clientWithoutPg]);
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([
      {
        id: "pg-99",
        name: "Banco Beta PRD",
        host: "10.9.9.1",
        port: 5432,
        dbname: "salutem_beta",
        user: "postgres",
        sslmode: "prefer",
        environment: "PRD",
        credential_mode: "default",
        read_only: true,
        is_default: false,
        has_password: true,
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ]);
    vi.spyOn(sftpApi, "listProfiles").mockResolvedValue([
      {
        id: "sftp-99",
        name: "SFTP Beta PRD",
        host: "10.9.9.2",
        port: 22,
        username: "salutem",
        auth_type: "private_key",
        credential_mode: "default",
        remote_base_dir: "/opt/salutem",
        environment: "PRD",
        read_only: true,
        linked_db_profile_id: null,
        has_secret: true,
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ]);
    vi.spyOn(jasperServerApi, "listProfiles").mockResolvedValue([
      {
        id: "js-99",
        name: "Jasper Beta PRD",
        base_url: "https://jasper.beta.local/jasperserver",
        organization: "",
        username: "jasperadmin",
        credential_mode: "default",
        default_folder_uri: "/",
        environment: "PRD",
        read_only: true,
        linked_db_profile_id: null,
        has_password: true,
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ]);
    const createSystemSpy = vi
      .spyOn(clientsApi, "createClientSystem")
      .mockResolvedValue(clientWithoutPg.systems[0]);

    render(
      <ToastProvider>
        <ClientsView onCreateFreeReport={vi.fn()} />
      </ToastProvider>,
    );

    // Since client has no Jasper/SFTP, it defaults to Conexões & Sistemas tab
    await waitFor(() => {
      expect(screen.getByText("Painel Sem Banco")).toBeInTheDocument();
      expect(screen.getByText("Sem PG")).toBeInTheDocument();
    });

    // Button must say "Novo Relatório Livre" and NOT "... neste Banco"
    expect(
      screen.getByRole("button", { name: /^Novo Relatório Livre$/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /Novo Relatório Livre neste Banco/i,
      }),
    ).not.toBeInTheDocument();

    // Open "Adicionar sistema" modal and pick profiles via SearchableSelect dropdowns
    await user.click(
      screen.getByRole("button", { name: /Adicionar sistema/i }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: /Adicionar sistema — Unidade Beta Exemplo/i,
    });

    await user.type(
      within(dialog).getByLabelText(/Rótulo do sistema/i),
      "Hospitalar Beta",
    );

    await user.click(within(dialog).getByRole("button", { name: "Perfil PostgreSQL" }));
    await user.click(await within(dialog).findByRole("option", { name: /Banco Beta PRD/i }));

    await user.click(within(dialog).getByRole("button", { name: "Perfil SFTP" }));
    await user.click(await within(dialog).findByRole("option", { name: /SFTP Beta PRD/i }));

    await user.click(within(dialog).getByRole("button", { name: "Perfil JasperServer" }));
    await user.click(await within(dialog).findByRole("option", { name: /Jasper Beta PRD/i }));

    await user.click(
      within(dialog).getByRole("button", { name: /^Adicionar sistema$/i }),
    );

    await waitFor(() => {
      expect(createSystemSpy).toHaveBeenCalledWith(
        "unit-2",
        expect.objectContaining({
          label: "Hospitalar Beta",
          db_profile_id: "pg-99",
          sftp_profile_id: "sftp-99",
          jasperserver_profile_id: "js-99",
        }),
      );
    });
  });
});

describe("HomeView, CommandPalette & StudioShell Dual-Mode", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders HomeView action cards, favorite clients, recent work, and quick guide", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      FAVORITE_CLIENTS_STORAGE_KEY,
      JSON.stringify(["unit-1"]),
    );
    vi.spyOn(clientsApi, "listClients").mockResolvedValue(SAMPLE_CLIENTS);

    const onSelectProject = vi.fn();
    const onNavigateSection = vi.fn();
    const onOpenCreateDialog = vi.fn();
    const onOpenClientById = vi.fn();
    const onOpenCommandPalette = vi.fn();

    render(
      <HomeView
        projects={[SAMPLE_IMPORTED_PROJECT]}
        onSelectProject={onSelectProject}
        onNavigateSection={onNavigateSection}
        onOpenCreateDialog={onOpenCreateDialog}
        onOpenClientById={onOpenClientById}
        onOpenCommandPalette={onOpenCommandPalette}
      />,
    );

    expect(
      screen.getByText("O que você quer fazer agora?"),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Unidade Alpha Exemplo")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Unidade Alpha Exemplo"));
    expect(onOpenClientById).toHaveBeenCalledWith("unit-1");

    await user.click(screen.getByText("Nova Ficha Clínica (de PDF)"));
    expect(onOpenCreateDialog).toHaveBeenCalledWith("pdf");

    await user.click(screen.getByText("Novo Relatório Livre (SQL + Jasper)"));
    expect(onOpenCreateDialog).toHaveBeenCalledWith("blank_report");

    await user.click(screen.getByRole("button", { name: /Continuar/i }));
    expect(onSelectProject).toHaveBeenCalledWith(SAMPLE_IMPORTED_PROJECT);
  });

  it("navigates directly to default_credentials when clicking Quick Start '1. Credenciais Padrão'", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue([]);
    const onNavigateSection = vi.fn();

    render(
      <HomeView
        projects={[]}
        onSelectProject={vi.fn()}
        onNavigateSection={onNavigateSection}
        onOpenCreateDialog={vi.fn()}
        onOpenClientById={vi.fn()}
        onOpenCommandPalette={vi.fn()}
      />,
    );

    const btn = await screen.findByRole("button", {
      name: /1\. Credenciais Padrão/i,
    });
    await user.click(btn);
    expect(onNavigateSection).toHaveBeenCalledWith(
      "settings",
      "default_credentials",
    );
  });

  it("navigates CommandPalette across clients, projects, and settings profiles with keyboard and deep-link search", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue(SAMPLE_CLIENTS);
    vi.spyOn(api, "listDbProfiles").mockResolvedValue([
      {
        id: "pg-alpha-1",
        name: "Postgres Alpha PRD",
        host: "10.0.1.5",
        port: 5432,
        dbname: "salutem_alpha",
        user: "postgres",
        sslmode: "prefer",
        environment: "PRD",
        credential_mode: "default",
        read_only: true,
        is_default: false,
        has_password: true,
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:00:00Z",
      },
    ]);
    vi.spyOn(sftpApi, "listProfiles").mockResolvedValue([]);
    vi.spyOn(jasperServerApi, "listProfiles").mockResolvedValue([]);

    const onClose = vi.fn();
    const onSelectProject = vi.fn();
    const onSelectClient = vi.fn();
    const onOpenSettingsTab = vi.fn();

    render(
      <CommandPalette
        open={true}
        onClose={onClose}
        projects={[SAMPLE_IMPORTED_PROJECT]}
        onSelectProject={onSelectProject}
        onSelectClient={onSelectClient}
        onOpenSettingsTab={onOpenSettingsTab}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Unidade Alpha Exemplo")).toBeInTheDocument();
      expect(screen.getByText("Resumo de Alta")).toBeInTheDocument();
      expect(screen.getByText("Postgres Alpha PRD")).toBeInTheDocument();
    });

    const input = screen.getByLabelText(/Buscar clientes, projetos/i);
    await user.type(input, "Postgres Alpha");
    await user.keyboard("{Enter}");

    expect(onOpenSettingsTab).toHaveBeenCalledWith(
      "db_profiles",
      "Postgres Alpha PRD",
    );
    expect(onClose).toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, "Beta");
    await user.keyboard("{Enter}");

    expect(onSelectClient).toHaveBeenCalledWith("unit-2");
    expect(onClose).toHaveBeenCalled();
  });

  it("renders StudioShell Global Mode without disabled tabs and Active Project Mode with contextual tabs", () => {
    const onNavigate = vi.fn();
    const onToggleTheme = vi.fn();

    const { rerender } = render(
      <StudioShell
        activeSection="home"
        onNavigate={onNavigate}
        projects={[SAMPLE_IMPORTED_PROJECT]}
        activeProject={null}
        onSelectProjectId={vi.fn()}
        theme="light"
        onToggleTheme={onToggleTheme}
        health={null}
        jasperUp={true}
        onOpenCommandPalette={vi.fn()}
      >
        <div>Body</div>
      </StudioShell>,
    );

    expect(screen.getByRole("button", { name: "Início" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Clientes" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Meus Projetos" })).toBeEnabled();
    expect(screen.queryByText(/Form Builder/i)).not.toBeInTheDocument();

    // Free Report Project Mode
    rerender(
      <StudioShell
        activeSection="jasper_studio"
        onNavigate={onNavigate}
        projects={[SAMPLE_IMPORTED_PROJECT]}
        activeProject={SAMPLE_IMPORTED_PROJECT}
        onSelectProjectId={vi.fn()}
        theme="light"
        onToggleTheme={onToggleTheme}
        health={null}
        jasperUp={true}
        onToggleChat={vi.fn()}
      >
        <div>Body</div>
      </StudioShell>,
    );

    expect(
      screen.getByRole("button", { name: /Relatório & Preview/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Banco & SQL/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Assistente IA/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/2\. Perguntas/i)).not.toBeInTheDocument();

    // Clinical Form Project Mode
    const clinicalProject: ProjectRead = {
      ...SAMPLE_IMPORTED_PROJECT,
      id: "proj-clin-1",
      name: "Ficha Anamnese",
      project_kind: "clinical_form",
    };
    rerender(
      <StudioShell
        activeSection="workspace"
        onNavigate={onNavigate}
        projects={[clinicalProject]}
        activeProject={clinicalProject}
        onSelectProjectId={vi.fn()}
        theme="light"
        onToggleTheme={onToggleTheme}
        health={null}
        jasperUp={true}
        onToggleChat={vi.fn()}
      >
        <div>Body</div>
      </StudioShell>,
    );

    expect(screen.getByText("1. Resumo & PDF")).toBeInTheDocument();
    expect(screen.getByText("2. Perguntas")).toBeInTheDocument();
    expect(screen.getByText("3. SQL & Banco")).toBeInTheDocument();
    expect(screen.getByText("4. Layout & PDF")).toBeInTheDocument();
  });
});
