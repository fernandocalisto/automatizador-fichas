import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { JasperServerProfilesTab } from "@/features/settings/JasperServerProfilesTab";
import type {
  DbProfileRead,
  JasperServerProfileRead,
  ProjectRead,
} from "@/types/studio";
import { JasperServerDeployModal } from "./JasperServerDeployModal";
import { jasperServerApi } from "./jasperServerApi";

const SAMPLE_DB_PROFILES: DbProfileRead[] = [
  {
    id: "pg-hosp-1",
    name: "PostgreSQL Hospitalar HML",
    host: "db-hml.example.local",
    port: 5432,
    dbname: "hospitalar_hml",
    user: "readonly_user",
    sslmode: "prefer",
    credential_mode: "default",
    environment: "HML",
    read_only: true,
    is_default: true,
    has_password: true,
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
];

const SAMPLE_JS_PROFILES: JasperServerProfileRead[] = [
  {
    id: "js-prd-1",
    name: "Jasper PRD Hospitalar",
    base_url: "https://jasper-prd.example.local/jasperserver",
    organization: "org_hosp",
    username: "jasperadmin",
    credential_mode: "custom",
    default_folder_uri: "/reports/hospitalar",
    environment: "PRD",
    read_only: true,
    linked_db_profile_id: "pg-hosp-1",
    has_password: true,
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
  {
    id: "js-hml-1",
    name: "Jasper HML Hospitalar",
    base_url: "https://jasper-hml.example.local/jasperserver",
    organization: "",
    username: "",
    credential_mode: "default",
    default_folder_uri: "/reports",
    environment: "HML",
    read_only: false,
    linked_db_profile_id: "pg-hosp-1",
    has_password: true,
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
];

const SAMPLE_PROJECT: ProjectRead = {
  id: "proj-hosp-1",
  slug: "resumo_alta",
  name: "Resumo de Alta Hospitalar",
  description: "Relatório importado do JasperServer",
  project_kind: "free_report",
  current_stage: "jrxml_design",
  entry_mode: "jasperserver_import",
  preferred_harness: "agy",
  template_db_id: null,
  default_db_profile_id: "pg-hosp-1",
  source_origin: {
    provider: "jasperserver",
    profile_id: "js-hml-1",
    resource_uri: "/reports/resumo_alta",
    main_jrxml_uri: "/reports/resumo_alta_files/main_jrxml",
    datasource_uri: "/datasources/pg_hospitalar",
  },
  workspace_dir: "/tmp/workspaces/resumo_alta",
  has_pdf: false,
  gates: [],
  latest_artifacts: { jrxml: 2 },
  created_at: "2026-03-01T10:00:00Z",
  updated_at: "2026-03-01T10:00:00Z",
};

describe("JasperServerProfilesTab", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders profiles, tests connection showing version/edition, and creates/deletes a profile", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);

    const testSpy = vi
      .spyOn(jasperServerApi, "testProfile")
      .mockResolvedValue({
        profile_id: "js-prd-1",
        ok: true,
        latency_ms: 42.3,
        version: "8.2.0",
        edition: "Community",
        build: "20230510",
        message: "Conectado",
        error: null,
      });

    const createSpy = vi
      .spyOn(jasperServerApi, "createProfile")
      .mockResolvedValue({
        ...SAMPLE_JS_PROFILES[1],
        id: "js-new-1",
        name: "Jasper DEV Novo",
      });

    const deleteSpy = vi
      .spyOn(jasperServerApi, "deleteProfile")
      .mockResolvedValue({ status: "ok", deleted: "js-prd-1" });

    render(
      <ToastProvider>
        <JasperServerProfilesTab
          profiles={SAMPLE_JS_PROFILES}
          dbProfiles={SAMPLE_DB_PROFILES}
          loading={false}
          onRefresh={onRefresh}
        />
      </ToastProvider>,
    );

    expect(screen.getByText("Jasper PRD Hospitalar")).toBeInTheDocument();
    expect(screen.getByText("Jasper HML Hospitalar")).toBeInTheDocument();
    expect(screen.getByText("Credencial Padrão")).toBeInTheDocument();
    expect(screen.getByText("Personalizada")).toBeInTheDocument();

    // Test connection on first profile
    const testButtons = screen.getAllByRole("button", {
      name: /Testar conexão/i,
    });
    await user.click(testButtons[0]);

    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith("js-prd-1");
      expect(screen.getByText(/Community · 8\.2\.0/i)).toBeInTheDocument();
      expect(screen.getByText("42 ms")).toBeInTheDocument();
    });

    // Create new profile with PRD -> auto enables read_only
    await user.click(
      screen.getByRole("button", { name: /Novo perfil JasperServer/i }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Novo perfil JasperServer",
    });

    await user.type(
      within(dialog).getByLabelText(/Nome do perfil/i),
      "Jasper PRD Novo",
    );
    await user.type(
      within(dialog).getByLabelText(/URL Base/i),
      "https://jasper-novo.example.local/jasperserver",
    );
    await user.selectOptions(
      within(dialog).getByLabelText(/Ambiente/i),
      "PRD",
    );

    const roSwitch = within(dialog).getByRole("switch", {
      name: /Somente leitura/i,
    });
    expect(roSwitch).toHaveAttribute("aria-checked", "true");

    await user.click(
      within(dialog).getByRole("button", { name: /^Criar perfil$/i }),
    );

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Jasper PRD Novo",
          base_url: "https://jasper-novo.example.local/jasperserver",
          credential_mode: "default",
          environment: "PRD",
          read_only: true,
        }),
      );
      expect(onRefresh).toHaveBeenCalled();
    });

    // Delete PRD profile
    await user.click(
      screen.getByRole("button", {
        name: /Excluir perfil Jasper PRD Hospitalar/i,
      }),
    );
    const delDialog = screen.getByRole("dialog", {
      name: "Excluir perfil JasperServer",
    });
    await user.click(
      within(delDialog).getByRole("button", { name: /Confirmar exclusão/i }),
    );
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("js-prd-1");
    });
  });
});

describe("JasperServerDeployModal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("blocks deploy on read_only PRD profile and executes 2-step update deploy on HML profile", async () => {
    const user = userEvent.setup();
    const onDeployed = vi.fn();

    const prepareSpy = vi
      .spyOn(jasperServerApi, "prepareDeploy")
      .mockResolvedValue({
        ok: true,
        project_id: SAMPLE_PROJECT.id,
        profile_id: "js-hml-1",
        mode: "update",
        target_uri: "/reports/resumo_alta",
        main_jrxml_uri: "/reports/resumo_alta_files/main_jrxml",
        remote_exists: true,
        unified_diff: "--- remote\n+++ local\n@@ -1 +1 @@\n-old\n+new\n",
        local_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        remote_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        deploy_token: "jsd_single_use_token_123",
        compiled_ok: true,
        message: "Compilação JVM OK.",
      });

    const executeSpy = vi
      .spyOn(jasperServerApi, "executeDeploy")
      .mockResolvedValue({
        ok: true,
        project_id: SAMPLE_PROJECT.id,
        profile_id: "js-hml-1",
        mode: "update",
        target_uri: "/reports/resumo_alta",
        main_jrxml_uri: "/reports/resumo_alta_files/main_jrxml",
        local_backup_path: "/tmp/backups/jasperserver_20260301_main.jrxml",
        message: "Report Unit atualizada com sucesso.",
      });

    render(
      <ToastProvider>
        <JasperServerDeployModal
          open={true}
          onClose={() => {}}
          project={SAMPLE_PROJECT}
          profiles={SAMPLE_JS_PROFILES}
          onDeployed={onDeployed}
        />
      </ToastProvider>,
    );

    // Pre-filled from project.source_origin
    expect(screen.getByLabelText(/URI da Report Unit/i)).toHaveValue(
      "/reports/resumo_alta",
    );
    const profileTrigger = screen.getByRole("button", {
      name: /Perfil JasperReports Server/i,
    });
    expect(profileTrigger).toHaveTextContent("Jasper HML Hospitalar");

    // Switching to read-only PRD profile via SearchableSelect must block prepare button
    await user.click(profileTrigger);
    await user.type(
      screen.getByPlaceholderText(/Buscar perfil por nome, URL ou ambiente/i),
      "PRD",
    );
    await user.click(
      screen.getByRole("option", { name: /Jasper PRD Hospitalar/i }),
    );
    expect(
      screen.getByText(/Perfil em modo Somente Leitura/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Pré-validar e gerar diff/i }),
    ).toBeDisabled();

    // Switch back to writable HML profile -> Step 1 prepare
    await user.click(profileTrigger);
    await user.click(
      screen.getByRole("option", { name: /Jasper HML Hospitalar/i }),
    );
    const prepareBtn = screen.getByRole("button", {
      name: /Pré-validar e gerar diff/i,
    });
    expect(prepareBtn).toBeEnabled();
    await user.click(prepareBtn);

    await waitFor(() => {
      expect(prepareSpy).toHaveBeenCalledWith(
        SAMPLE_PROJECT.id,
        expect.objectContaining({
          profile_id: "js-hml-1",
          mode: "update",
          target_uri: "/reports/resumo_alta",
        }),
      );
      expect(screen.getByText("Compilação JVM OK")).toBeInTheDocument();
      expect(screen.getByText("+new")).toBeInTheDocument();
    });

    // Step 2 confirm deploy
    await user.click(
      screen.getByRole("button", { name: /Confirmar publicação/i }),
    );
    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(SAMPLE_PROJECT.id, {
        deploy_token: "jsd_single_use_token_123",
      });
      expect(onDeployed).toHaveBeenCalled();
      expect(
        screen.getAllByText(/Report Unit atualizada com sucesso/i).length,
      ).toBeGreaterThanOrEqual(1);
    });
  });

  it("supports creating a new Report Unit with DataSource selector", async () => {
    const user = userEvent.setup();
    const listDsSpy = vi
      .spyOn(jasperServerApi, "listResources")
      .mockResolvedValue([
        {
          uri: "/datasources/pg_hospitalar",
          label: "PG Hospitalar",
          description: "",
          resource_type: "datasource",
          updated_at: null,
        },
      ]);

    const prepareSpy = vi
      .spyOn(jasperServerApi, "prepareDeploy")
      .mockResolvedValue({
        ok: true,
        project_id: SAMPLE_PROJECT.id,
        profile_id: "js-hml-1",
        mode: "create",
        target_uri: "/reports/nova_unit",
        main_jrxml_uri: "/reports/nova_unit_files/main_jrxml",
        remote_exists: false,
        unified_diff: "+<jasperReport/>",
        local_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        remote_sha256: null,
        deploy_token: "jsd_create_token_456",
        compiled_ok: true,
        message: "Pronto para criar.",
      });

    render(
      <ToastProvider>
        <JasperServerDeployModal
          open={true}
          onClose={() => {}}
          project={{ ...SAMPLE_PROJECT, source_origin: {} }}
          profiles={SAMPLE_JS_PROFILES}
        />
      </ToastProvider>,
    );

    await user.click(
      screen.getByRole("button", { name: /Perfil JasperReports Server/i }),
    );
    await user.click(
      screen.getByRole("option", { name: /Jasper HML Hospitalar/i }),
    );

    await waitFor(() => {
      expect(listDsSpy).toHaveBeenCalled();
      expect(screen.getByText(/PG Hospitalar/i)).toBeInTheDocument();
    });

    await user.clear(screen.getByLabelText(/URI da Report Unit/i));
    await user.type(
      screen.getByLabelText(/URI da Report Unit/i),
      "/reports/nova_unit",
    );
    await user.selectOptions(
      screen.getByLabelText(/DataSource do servidor/i),
      "/datasources/pg_hospitalar",
    );

    await user.click(
      screen.getByRole("button", { name: /Pré-validar e gerar diff/i }),
    );

    await waitFor(() => {
      expect(prepareSpy).toHaveBeenCalledWith(
        SAMPLE_PROJECT.id,
        expect.objectContaining({
          profile_id: "js-hml-1",
          mode: "create",
          target_uri: "/reports/nova_unit",
          datasource_uri: "/datasources/pg_hospitalar",
        }),
      );
    });
  });
});
