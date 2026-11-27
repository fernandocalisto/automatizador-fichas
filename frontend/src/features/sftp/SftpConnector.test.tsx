import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { SftpProfilesTab } from "@/features/settings/SftpProfilesTab";
import { SftpDeployModal } from "./SftpDeployModal";
import { SftpImportTab } from "./SftpImportTab";
import { sftpApi } from "./sftpApi";
import type {
  DbProfileRead,
  ProjectRead,
  SftpProfileRead,
} from "@/types/studio";

const SAMPLE_DB_PROFILES: DbProfileRead[] = [
  {
    id: "pg-hml-1",
    name: "PostgreSQL HML",
    host: "10.0.0.10",
    port: 5432,
    dbname: "salutem_hml",
    user: "postgres",
    sslmode: "prefer",
    credential_mode: "default",
    environment: "HML",
    read_only: false,
    is_default: true,
    has_password: true,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
  },
];

const SAMPLE_SFTP_PROFILES: SftpProfileRead[] = [
  {
    id: "sftp-prd-1",
    name: "Unidade PRD",
    host: "10.0.0.100",
    port: 22,
    username: "ops_ro",
    auth_type: "password",
    credential_mode: "default",
    remote_base_dir: "/opt/salutem/relatorios",
    environment: "PRD",
    read_only: true,
    linked_db_profile_id: "pg-hml-1",
    has_secret: true,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
  },
  {
    id: "sftp-hml-1",
    name: "Unidade HML",
    host: "10.0.0.200",
    port: 2222,
    username: "deploy_hml",
    auth_type: "password",
    credential_mode: "custom",
    remote_base_dir: "/opt/salutem/relatorios",
    environment: "HML",
    read_only: false,
    linked_db_profile_id: "pg-hml-1",
    has_secret: true,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
  },
];

const SAMPLE_PROJECT: ProjectRead = {
  id: "proj-sftp-1",
  slug: "ficha_evolucao",
  name: "Ficha Evolução",
  description: "Importada via SFTP",
  project_kind: "free_report",
  current_stage: "jrxml_design",
  entry_mode: "sftp_import",
  preferred_harness: "agy",
  template_db_id: null,
  default_db_profile_id: "pg-hml-1",
  client_system_id: null,
  source_origin: {
    provider: "sftp",
    profile_id: "sftp-prd-1",
    remote_path: "/opt/salutem/relatorios/ficha_evolucao.jrxml",
    remote_dir: "/opt/salutem/relatorios",
    base_filename: "ficha_evolucao",
  },
  workspace_dir: "/tmp/workspaces/ficha_evolucao",
  has_pdf: false,
  gates: [],
  latest_artifacts: { jrxml: 2 },
  created_at: "2026-11-27T10:00:00Z",
  updated_at: "2026-11-27T10:00:00Z",
};

describe("SftpProfilesTab", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders profiles, tests connection, auto-enables read_only on PRD, and creates a custom profile", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);

    const testSpy = vi.spyOn(sftpApi, "testProfile").mockResolvedValue({
      profile_id: "sftp-prd-1",
      ok: true,
      latency_ms: 18.7,
      remote_base_dir: "/opt/salutem/relatorios",
      item_count: 14,
      message: "Conexão SFTP OK (14 itens em /opt/salutem/relatorios).",
      error: null,
    });
    const createSpy = vi.spyOn(sftpApi, "createProfile").mockResolvedValue({
      ...SAMPLE_SFTP_PROFILES[0],
      id: "sftp-new-1",
      name: "Novo PRD",
      host: "10.0.5.5",
      environment: "PRD",
      read_only: true,
    });

    render(
      <ToastProvider>
        <SftpProfilesTab
          profiles={SAMPLE_SFTP_PROFILES}
          dbProfiles={SAMPLE_DB_PROFILES}
          loading={false}
          onRefresh={onRefresh}
        />
      </ToastProvider>,
    );

    expect(screen.getByText("Unidade PRD")).toBeInTheDocument();
    expect(screen.getByText("Credencial Padrão")).toBeInTheDocument();
    expect(screen.getByText("Somente leitura")).toBeInTheDocument();

    // Test connection on first profile
    const testButtons = screen.getAllByRole("button", {
      name: /Testar conexão/i,
    });
    await user.click(testButtons[0]);

    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith("sftp-prd-1");
      expect(screen.getByText("19 ms")).toBeInTheDocument();
    });

    // Open create modal
    await user.click(
      screen.getByRole("button", { name: /Novo servidor SFTP/i }),
    );
    const dialog = screen.getByRole("dialog", { name: /Novo servidor SFTP/i });

    // Switching environment to PRD auto-enables read_only switch
    const readOnlySwitch = within(dialog).getByRole("switch");
    expect(readOnlySwitch).toHaveAttribute("aria-checked", "false");

    await user.selectOptions(
      within(dialog).getByLabelText("Ambiente"),
      "PRD",
    );
    expect(readOnlySwitch).toHaveAttribute("aria-checked", "true");

    // Switch to Personalizada -> private key
    await user.click(
      within(dialog).getByRole("radio", { name: "Personalizada" }),
    );
    await user.type(within(dialog).getByLabelText("Nome do servidor"), "Novo PRD");
    await user.type(within(dialog).getByLabelText("Host / IP"), "10.0.5.5");
    await user.type(within(dialog).getByLabelText("Usuário SSH"), "salutem_ro");
    await user.selectOptions(
      within(dialog).getByLabelText("Tipo de autenticação"),
      "private_key",
    );
    await user.type(
      within(dialog).getByLabelText(/Chave privada PEM/i),
      "-----BEGIN KEY-----\nTEST\n-----END KEY-----",
    );

    await user.click(
      within(dialog).getByRole("button", { name: /Criar perfil SFTP/i }),
    );

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Novo PRD",
          host: "10.0.5.5",
          username: "salutem_ro",
          credential_mode: "custom",
          auth_type: "private_key",
          environment: "PRD",
          read_only: true,
        }),
      );
      expect(onRefresh).toHaveBeenCalled();
    });
  });
});

describe("SftpDeployModal", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("pre-fills from source_origin, blocks read-only profiles, and executes 2-step jrxml_only deploy", async () => {
    const user = userEvent.setup();
    const onDeployed = vi.fn();

    const prepareSpy = vi.spyOn(sftpApi, "prepareDeploy").mockResolvedValue({
      ok: true,
      project_id: "proj-sftp-1",
      profile_id: "sftp-hml-1",
      remote_dir: "/opt/salutem/relatorios",
      base_filename: "ficha_evolucao",
      publish_mode: "jrxml_only",
      target_files: ["/opt/salutem/relatorios/ficha_evolucao.jrxml"],
      remote_exists: true,
      unified_diff:
        '--- remote:/opt/salutem/relatorios/ficha_evolucao.jrxml\n+++ local:ficha_evolucao.jrxml\n@@ -1,1 +1,1 @@\n-<band height="40">\n+<band height="60">',
      local_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      remote_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      deploy_token: "nonce123.sig456",
      compiled_ok: true,
      message: "Compilação JVM aprovada.",
    });

    const executeSpy = vi.spyOn(sftpApi, "executeDeploy").mockResolvedValue({
      ok: true,
      project_id: "proj-sftp-1",
      profile_id: "sftp-hml-1",
      published_files: ["/opt/salutem/relatorios/ficha_evolucao.jrxml"],
      backup_files: [
        "/opt/salutem/relatorios/ficha_evolucao.jrxml.bak.20261127_140000",
      ],
      local_backup_path: "/tmp/workspaces/ficha_evolucao/backups/sftp_bak.jrxml",
      message: "Publicado(s) 1 arquivo(s) no servidor SFTP (1 backup(s) .bak criado(s)).",
    });

    render(
      <ToastProvider>
        <SftpDeployModal
          open={true}
          onClose={vi.fn()}
          project={SAMPLE_PROJECT}
          profiles={SAMPLE_SFTP_PROFILES}
          onDeployed={onDeployed}
        />
      </ToastProvider>,
    );

    // Pre-filled with sftp-prd-1 (read_only=true): red alert shown and submit button disabled
    expect(screen.getByText(/Publicação bloqueada neste servidor/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue("/opt/salutem/relatorios")).toBeInTheDocument();
    expect(screen.getByDisplayValue("ficha_evolucao")).toBeInTheDocument();

    const modeSelect = screen.getByLabelText("Modo de publicação") as HTMLSelectElement;
    expect(modeSelect.value).toBe("jrxml_only");

    const validateBtn = screen.getByRole("button", {
      name: /Validar JVM e Gerar Diff/i,
    });
    expect(validateBtn).toBeDisabled();

    // Switch to writable HML profile -> button enables
    await user.selectOptions(
      screen.getByLabelText("Servidor SFTP de destino"),
      "sftp-hml-1",
    );
    expect(validateBtn).not.toBeDisabled();

    // Step 1 -> Prepare
    await user.click(validateBtn);
    await waitFor(() => {
      expect(prepareSpy).toHaveBeenCalledWith("proj-sftp-1", {
        profile_id: "sftp-hml-1",
        remote_dir: "/opt/salutem/relatorios",
        base_filename: "ficha_evolucao",
        publish_mode: "jrxml_only",
      });
      expect(screen.getByText(/Compilação JVM OK/i)).toBeInTheDocument();
      expect(screen.getByText(/\.bak\./i)).toBeInTheDocument();
      expect(screen.getByText(/\+<band height="60">/)).toBeInTheDocument();
    });

    // Step 2 -> Execute
    await user.click(
      screen.getByRole("button", { name: /Confirmar e Publicar no SFTP/i }),
    );
    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith("proj-sftp-1", {
        deploy_token: "nonce123.sig456",
      });
      expect(
        screen.getByText(/ficha_evolucao\.jrxml\.bak\.20261127_140000/i),
      ).toBeInTheDocument();
      expect(onDeployed).toHaveBeenCalled();
    });
  });
});

describe("SftpImportTab", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("browses SFTP directory, highlights .jasper auto-decompile, and imports report", async () => {
    const user = userEvent.setup();
    const onProjectImported = vi.fn();

    vi.spyOn(sftpApi, "listProfiles").mockResolvedValue(SAMPLE_SFTP_PROFILES);
    vi.spyOn(sftpApi, "browse").mockResolvedValue({
      profile_id: "sftp-hml-1",
      current_path: "/opt/salutem/relatorios",
      parent_path: null,
      entries: [
        {
          name: "ficha_legada.jasper",
          path: "/opt/salutem/relatorios/ficha_legada.jasper",
          is_dir: false,
          size_bytes: 12040,
          modified_at: "2026-11-27T09:00:00Z",
          kind: "jasper",
          has_paired_file: false,
        },
      ],
    });
    const importSpy = vi.spyOn(sftpApi, "importReport").mockResolvedValue({
      ...SAMPLE_PROJECT,
      name: "ficha legada",
    });

    render(
      <ToastProvider>
        <SftpImportTab
          initialProfileId="sftp-hml-1"
          dbProfiles={SAMPLE_DB_PROFILES}
          onProjectImported={onProjectImported}
        />
      </ToastProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ficha_legada.jasper")).toBeInTheDocument();
      expect(screen.getByText(/Decompila automático/i)).toBeInTheDocument();
    });

    await user.click(screen.getByText("ficha_legada.jasper"));
    expect(
      screen.getByText(/decompilá-lo automaticamente para/i),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Importar via SFTP/i }),
    );
    await waitFor(() => {
      expect(importSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          profile_id: "sftp-hml-1",
          remote_path: "/opt/salutem/relatorios/ficha_legada.jasper",
          sync_subreports: true,
        }),
      );
      expect(onProjectImported).toHaveBeenCalled();
    });
  });
});
