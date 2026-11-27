import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import type { ClientUnitRead } from "@/types/studio";
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
        metadata: {},
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
        metadata: {},
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

describe("ClientsView & ClientSyncDialog", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists clients, filters by search/type/environment, and triggers 1-click workflow callbacks", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue(SAMPLE_CLIENTS);

    const onCreateFreeReport = vi.fn();
    const onOpenSftpImport = vi.fn();
    const onOpenJasperImport = vi.fn();
    const onOpenSettings = vi.fn();

    render(
      <ToastProvider>
        <ClientsView
          onCreateFreeReport={onCreateFreeReport}
          onOpenSftpImport={onOpenSftpImport}
          onOpenJasperImport={onOpenJasperImport}
          onOpenSettings={onOpenSettings}
        />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Unidade Alpha Exemplo")).toBeInTheDocument();
      expect(screen.getByText("Unidade Beta Exemplo")).toBeInTheDocument();
    });

    // External link rendered with safe target/rel
    const openLinks = screen.getAllByRole("link", { name: /Abrir Sistema/i });
    expect(openLinks[0]).toHaveAttribute(
      "href",
      "https://amb.alpha.example.local",
    );
    expect(openLinks[0]).toHaveAttribute("target", "_blank");

    // 1-click callbacks
    await user.click(
      screen.getAllByRole("button", { name: /Novo Relatório Livre/i })[0],
    );
    expect(onCreateFreeReport).toHaveBeenCalledWith({
      clientSystemId: "sys-amb-prd",
      dbProfileId: "pg-alpha-amb",
      defaultName: "Unidade Alpha Exemplo — Ambulatorial PRD",
    });

    await user.click(screen.getByRole("button", { name: /Importar SFTP/i }));
    expect(onOpenSftpImport).toHaveBeenCalledWith(
      "sftp-alpha-amb",
      "pg-alpha-amb",
    );

    await user.click(
      screen.getByRole("button", { name: /Importar JasperServer/i }),
    );
    expect(onOpenJasperImport).toHaveBeenCalledWith(
      "js-alpha-hosp",
      "pg-alpha-hosp",
    );

    await user.click(
      screen.getByRole("button", { name: /Credenciais Padrão/i }),
    );
    expect(onOpenSettings).toHaveBeenCalledTimes(1);

    // Filter by system_type = hospitalar
    await user.selectOptions(
      screen.getByLabelText(/Filtrar por tipo de sistema/i),
      "hospitalar",
    );
    expect(screen.getByText("Unidade Alpha Exemplo")).toBeInTheDocument();
    expect(screen.queryByText("Unidade Beta Exemplo")).not.toBeInTheDocument();

    // Reset filter and search by tag
    await user.selectOptions(
      screen.getByLabelText(/Filtrar por tipo de sistema/i),
      "all",
    );
    await user.type(
      screen.getByLabelText(/Buscar clientes/i),
      "regional",
    );
    expect(screen.queryByText("Unidade Alpha Exemplo")).not.toBeInTheDocument();
    expect(screen.getByText("Unidade Beta Exemplo")).toBeInTheDocument();
  });

  it("completes the 2-step portal sync dialog (local URL config -> preview diff -> apply)", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listClients").mockResolvedValue([]);
    vi.spyOn(clientsApi, "getSyncSnippet").mockResolvedValue({
      management_portal_url: "",
      console_snippet: "fetch('/api/management/data', { credentials: 'include' })",
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
      screen.getAllByRole("button", { name: /Sincronizar do Portal/i })[0],
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
    await user.paste('{"units":[{"unit_code":"GAMMA-01","name":"Unidade Gamma Exemplo","systems":[]}]}');

    await user.click(
      within(dialog).getByRole("button", { name: /Analisar e Pré-visualizar/i }),
    );

    // Step 2: Diff table rendered
    await waitFor(() => {
      expect(previewSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByText("Unidade Gamma Exemplo")).toBeInTheDocument();
      expect(screen.getByText("Novo cliente com 2 sistema(s)")).toBeInTheDocument();
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
});
