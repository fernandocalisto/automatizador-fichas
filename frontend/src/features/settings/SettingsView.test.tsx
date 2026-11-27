import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import type {
  DbProfileRead,
  HarnessStatus,
  SkillInfo,
  SubreportInfo,
} from "@/types/studio";
import { SettingsView } from "./SettingsView";

const SAMPLE_PROFILES: DbProfileRead[] = [
  {
    id: "pg-1",
    name: "Produção Salutem",
    host: "db.salutem.local",
    port: 5432,
    dbname: "salutem_prod",
    user: "readonly_user",
    sslmode: "require",
    read_only: true,
    is_default: true,
    has_password: true,
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
];

const SAMPLE_SUBREPORTS: SubreportInfo[] = [
  {
    filename: "cabecalho_retrato.jasper",
    name: "cabecalho_retrato",
    source: "builtin",
    is_builtin_standard: true,
    is_overridden: false,
    size_bytes: 18432,
    sha256: "abcdef1234567890abcdef",
    path: "/builtin/cabecalho_retrato.jasper",
    updated_at: "2026-03-01T10:00:00Z",
  },
  {
    filename: "rodape_retrato.jasper",
    name: "rodape_retrato",
    source: "custom_override",
    is_builtin_standard: true,
    is_overridden: true,
    size_bytes: 12288,
    sha256: "11223344556677889900aa",
    path: "/custom/rodape_retrato.jasper",
    updated_at: "2026-03-02T10:00:00Z",
  },
];

const SAMPLE_HARNESSES: HarnessStatus[] = [
  {
    id: "agy",
    display_name: "Antigravity (AGY)",
    installed: true,
    executable_path: "C:\\Tools\\agy.exe",
    sdk_available: true,
    version: "2.1.0",
    auth_hint: "Autenticado via Google CLI",
    supports_vision: true,
    supports_mcp: true,
  },
  {
    id: "codex",
    display_name: "Codex CLI",
    installed: false,
    executable_path: null,
    sdk_available: false,
    version: null,
    auth_hint: "Defina OPENAI_API_KEY",
    supports_vision: true,
    supports_mcp: false,
  },
];

const SAMPLE_SKILLS: SkillInfo[] = [
  {
    id: "extrator_ficha",
    name: "Extrator de Ficha Clínica",
    description: "Extrai estrutura JSON Salutem a partir de PDF.",
    path: "backend/app/skills/extrator_ficha/SKILL.md",
  },
];

function mockBaseSettingsApis() {
  vi.spyOn(api, "listDbProfiles").mockResolvedValue(SAMPLE_PROFILES);
  vi.spyOn(api, "listSubreports").mockResolvedValue(SAMPLE_SUBREPORTS);
  vi.spyOn(api, "listHarnesses").mockResolvedValue(SAMPLE_HARNESSES);
  vi.spyOn(api, "listSkills").mockResolvedValue(SAMPLE_SKILLS);
  vi.spyOn(api, "getSettings").mockResolvedValue({
    default_harness: "agy",
    default_preview_mode: "auto",
    default_preview_dpi: 150,
    default_unit_name: "UPA Central",
    auto_regenerate_sql: true,
    apply_uppercase_default: true,
  });
}

describe("SettingsView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("manages PostgreSQL profiles CRUD and tests connection with latency and version", async () => {
    const user = userEvent.setup();
    mockBaseSettingsApis();

    const createSpy = vi.spyOn(api, "createDbProfile").mockResolvedValue({
      ...SAMPLE_PROFILES[0],
      id: "pg-2",
      name: "Homologação Local",
      host: "127.0.0.1",
      read_only: false,
      is_default: false,
    });
    const testSpy = vi.spyOn(api, "testDbProfile").mockResolvedValue({
      profile_id: "pg-1",
      ok: true,
      latency_ms: 23.4,
      server_version: "PostgreSQL 16.4",
      current_database: "salutem_prod",
      current_user: "readonly_user",
      read_only: true,
      message: "OK",
      error: null,
    });
    const deleteSpy = vi
      .spyOn(api, "deleteDbProfile")
      .mockResolvedValue({ status: "ok", deleted: "pg-1" });

    render(
      <ToastProvider>
        <SettingsView />
      </ToastProvider>,
    );

    expect(
      screen.getByRole("heading", { name: "Configurações" }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Produção Salutem")).toBeInTheDocument();
      expect(screen.getByText("Senha protegida")).toBeInTheDocument();
      expect(screen.getByText("Somente leitura")).toBeInTheDocument();
    });

    // Test connection
    await user.click(screen.getByRole("button", { name: /Testar conexão/i }));
    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith("pg-1");
      expect(screen.getAllByText("PostgreSQL 16.4").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("23 ms")).toBeInTheDocument();
    });

    // Edit profile without exposing password
    const updateSpy = vi.spyOn(api, "updateDbProfile").mockResolvedValue({
      ...SAMPLE_PROFILES[0],
      name: "Produção Salutem (RO)",
    });
    await user.click(screen.getByRole("button", { name: /^Editar$/i }));
    const editDialog = screen.getByRole("dialog", {
      name: /Editar perfil — Produção Salutem/i,
    });
    expect(within(editDialog).getByText("Senha protegida")).toBeInTheDocument();
    expect(within(editDialog).getByLabelText(/^Senha$/i)).toHaveValue("");
    await user.clear(within(editDialog).getByLabelText(/Nome do perfil/i));
    await user.type(
      within(editDialog).getByLabelText(/Nome do perfil/i),
      "Produção Salutem (RO)",
    );
    await user.click(
      within(editDialog).getByRole("button", { name: /Salvar alterações/i }),
    );
    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        "pg-1",
        expect.objectContaining({
          name: "Produção Salutem (RO)",
          read_only: true,
        }),
      );
      expect(updateSpy.mock.calls[0]?.[1]).not.toHaveProperty("password");
    });

    // Create new profile
    await user.click(
      screen.getByRole("button", { name: /Novo perfil PostgreSQL/i }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Novo perfil PostgreSQL",
    });

    await user.type(
      within(dialog).getByLabelText(/Nome do perfil/i),
      "Homologação Local",
    );
    await user.clear(within(dialog).getByLabelText(/Host/i));
    await user.type(within(dialog).getByLabelText(/Host/i), "127.0.0.1");
    await user.type(within(dialog).getByLabelText(/^Senha$/i), "segredo123");

    // Toggle Somente leitura off
    const roSwitch = within(dialog).getByRole("switch", {
      name: /Somente leitura/i,
    });
    expect(roSwitch).toHaveAttribute("aria-checked", "true");
    await user.click(roSwitch);
    expect(roSwitch).toHaveAttribute("aria-checked", "false");

    await user.click(
      within(dialog).getByRole("button", { name: /^Criar perfil$/i }),
    );

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Homologação Local",
          host: "127.0.0.1",
          port: 5432,
          password: "segredo123",
          read_only: false,
        }),
      );
    });

    // Delete existing profile with confirmation
    await user.click(
      screen.getByRole("button", { name: /Excluir perfil Produção Salutem/i }),
    );
    const delDialog = screen.getByRole("dialog", {
      name: "Excluir perfil PostgreSQL",
    });
    await user.click(
      within(delDialog).getByRole("button", { name: /Confirmar exclusão/i }),
    );
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("pg-1");
    });
  });

  it("lists, uploads, and resets Jasper subreports", async () => {
    const user = userEvent.setup();
    mockBaseSettingsApis();

    const uploadSpy = vi.spyOn(api, "uploadSubreport").mockResolvedValue({
      filename: "cabecalho_retrato.jasper",
      name: "cabecalho_retrato",
      source: "custom_override",
      is_builtin_standard: true,
      is_overridden: true,
      size_bytes: 20480,
      sha256: "999999888888",
      path: "/custom/cabecalho_retrato.jasper",
      updated_at: "2026-03-03T10:00:00Z",
    });
    const deleteSpy = vi
      .spyOn(api, "deleteSubreport")
      .mockResolvedValue({ status: "ok" });

    render(
      <ToastProvider>
        <SettingsView />
      </ToastProvider>,
    );

    await user.click(
      screen.getByRole("tab", { name: /Subreports Jasper/i }),
    );

    await waitFor(() => {
      expect(screen.getByText("cabecalho_retrato.jasper")).toBeInTheDocument();
      expect(screen.getByText("rodape_retrato.jasper")).toBeInTheDocument();
      expect(screen.getByText("Override customizado")).toBeInTheDocument();
    });

    // Restore overridden subreport to builtin
    await user.click(
      screen.getByRole("button", { name: /Restaurar padrão/i }),
    );
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("rodape_retrato.jasper");
    });

    // Upload custom .jasper overriding cabecalho_retrato.jasper
    const jasperFile = new File(["binary-jasper"], "custom_hdr.jasper", {
      type: "application/octet-stream",
    });
    await user.upload(
      screen.getByLabelText("Selecionar arquivo .jasper"),
      jasperFile,
    );
    await user.selectOptions(
      screen.getByLabelText(/Destino \/ Override/i),
      "cabecalho_retrato.jasper",
    );
    await user.click(screen.getByRole("button", { name: /Enviar \.jasper/i }));

    await waitFor(() => {
      expect(uploadSpy).toHaveBeenCalledWith(
        jasperFile,
        "cabecalho_retrato.jasper",
      );
    });
  });

  it("renders harnesses, embedded skills, and saves studio preferences", async () => {
    const user = userEvent.setup();
    mockBaseSettingsApis();

    const updateSettingsSpy = vi
      .spyOn(api, "updateSettings")
      .mockImplementation(async (payload) => payload);

    render(
      <ToastProvider>
        <SettingsView />
      </ToastProvider>,
    );

    // Harnesses & Skills tab
    await user.click(
      screen.getByRole("tab", { name: /Assistentes IA \(Harnesses\)/i }),
    );
    await waitFor(() => {
      expect(screen.getByText("Antigravity (AGY)")).toBeInTheDocument();
      expect(screen.getByText("2.1.0")).toBeInTheDocument();
      expect(screen.getByText("Codex CLI")).toBeInTheDocument();
      expect(screen.getByText(/Defina OPENAI_API_KEY/i)).toBeInTheDocument();
      expect(
        screen.getByText("Extrator de Ficha Clínica"),
      ).toBeInTheDocument();
    });

    // Studio Preferences tab
    await user.click(
      screen.getByRole("tab", { name: /^Preferências$/i }),
    );
    const unitInput = await screen.findByLabelText(
      /Nome padrão da unidade de saúde/i,
    );
    expect(unitInput).toHaveValue("UPA Central");

    await user.clear(unitInput);
    await user.type(unitInput, "Hospital Municipal");
    await user.selectOptions(
      screen.getByLabelText(/Harness de IA padrão/i),
      "opencode",
    );

    await user.click(
      screen.getByRole("button", { name: /Salvar preferências/i }),
    );

    await waitFor(() => {
      expect(updateSettingsSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          default_harness: "opencode",
          default_unit_name: "Hospital Municipal",
          default_preview_dpi: 150,
        }),
      );
    });
  });

  it("renders categorized sidebar groups and filters/paginates PostgreSQL profiles", async () => {
    const user = userEvent.setup();
    const manyProfiles: DbProfileRead[] = Array.from({ length: 28 }, (_, idx) => ({
      id: `pg-${idx + 1}`,
      name: idx === 0 ? "Hospital PRD Central" : `Unidade HML ${idx + 1}`,
      host: `10.0.0.${idx + 1}`,
      port: 5432,
      dbname: idx === 0 ? "salutem_prd" : `salutem_hml_${idx + 1}`,
      user: "postgres",
      sslmode: "prefer",
      environment: idx === 0 ? "PRD" : "HML",
      read_only: idx === 0,
      is_default: idx === 0,
      has_password: true,
      created_at: "2026-03-01T10:00:00Z",
      updated_at: "2026-03-01T10:00:00Z",
    }));

    vi.spyOn(api, "listDbProfiles").mockResolvedValue(manyProfiles);
    vi.spyOn(api, "listSubreports").mockResolvedValue(SAMPLE_SUBREPORTS);
    vi.spyOn(api, "listHarnesses").mockResolvedValue(SAMPLE_HARNESSES);
    vi.spyOn(api, "listSkills").mockResolvedValue(SAMPLE_SKILLS);
    vi.spyOn(api, "getSettings").mockResolvedValue({});

    render(
      <ToastProvider>
        <SettingsView />
      </ToastProvider>,
    );

    // Categorized sidebar groups visible
    expect(screen.getByText("Acesso & Cofre")).toBeInTheDocument();
    expect(screen.getByText("Conexões")).toBeInTheDocument();
    expect(screen.getByText("Studio & IA")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Hospital PRD Central")).toBeInTheDocument();
      expect(screen.getByText(/Mostrando 1–25 de 28 perfis/i)).toBeInTheDocument();
    });

    // Go to page 2
    await user.click(screen.getByRole("button", { name: /Próxima/i }));
    await waitFor(() => {
      expect(screen.getByText("Unidade HML 28")).toBeInTheDocument();
    });

    // Filter by PRD pill
    const envGroup = screen.getByRole("group", {
      name: /Filtrar PostgreSQL por ambiente/i,
    });
    await user.click(within(envGroup).getByRole("button", { name: /PRD/i }));
    await waitFor(() => {
      expect(screen.getByText("Hospital PRD Central")).toBeInTheDocument();
      expect(screen.queryByText("Unidade HML 28")).not.toBeInTheDocument();
    });

    // Search by dbname
    await user.click(within(envGroup).getByRole("button", { name: /Todos/i }));
    await user.type(
      screen.getByLabelText(/Buscar perfis PostgreSQL/i),
      "salutem_hml_28",
    );
    await waitFor(() => {
      expect(screen.getByText("Unidade HML 28")).toBeInTheDocument();
      expect(screen.queryByText("Hospital PRD Central")).not.toBeInTheDocument();
    });
  });
});
