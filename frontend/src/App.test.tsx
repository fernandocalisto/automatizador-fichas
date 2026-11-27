import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { ProjectRead } from "@/types/studio";

const FREE_REPORT_PROJECT: ProjectRead = {
  id: "proj-free-1",
  slug: "relatorio_livre_1",
  name: "Relatório Financeiro Livre",
  description: "Relatório livre SQL + Jasper",
  project_kind: "free_report",
  current_stage: "sql_db",
  entry_mode: "blank_report",
  preferred_harness: "agy",
  template_db_id: null,
  default_db_profile_id: null,
  client_system_id: null,
  source_origin: {},
  workspace_dir: "/tmp/workspaces/relatorio_livre_1",
  has_pdf: false,
  gates: [],
  latest_artifacts: { jrxml: 1 },
  created_at: "2026-11-27T10:00:00Z",
  updated_at: "2026-11-27T10:00:00Z",
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Studio App shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", window.location.pathname);
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", window.location.pathname);
  });

  it("renders studio header, toggles theme, and opens settings with tab in hash", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/projects")) return jsonResponse([]);
      if (url.includes("/api/clients")) return jsonResponse([]);
      if (url.includes("/api/db/profiles")) return jsonResponse([]);
      if (url.includes("/api/sftp/profiles")) return jsonResponse([]);
      if (url.includes("/api/jasperserver/profiles")) return jsonResponse([]);
      if (url.includes("/api/subreports")) return jsonResponse([]);
      if (url.includes("/api/harnesses")) return jsonResponse([]);
      if (url.includes("/api/skills")) return jsonResponse([]);
      if (url.includes("/api/settings")) return jsonResponse({});
      if (url.includes("/api/health")) {
        return jsonResponse({
          status: "ok",
          app_name: "Salutem Ficha Studio",
          version: "1.1.1",
          database: {},
          paths: {},
          builtin_subreports_count: 4,
          custom_subreports_count: 0,
          effective_subreports_count: 4,
          frontend_built: false,
        });
      }
      return jsonResponse({ status: "UP" });
    });

    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText("Salutem Ficha Studio")).toBeInTheDocument();
    expect(screen.getByText(/O que você quer fazer agora/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("v1.1.1")).toBeInTheDocument();
    });

    const themeBtn = screen.getByRole("button", { name: /Ativar tema escuro/i });
    await user.click(themeBtn);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    await user.click(screen.getByRole("button", { name: /Configurações/i }));
    expect(screen.getByRole("heading", { name: "Configurações" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#section=settings&tab=db_profiles");
  });

  it("opens Default Credentials tab directly from HomeView Quick Start and persists settings tab across hash reload", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/credentials/defaults")) {
        return jsonResponse([
          {
            kind: "postgres",
            username: "postgres",
            organization: "",
            auth_type: "password",
            default_dbname: "salutem",
            default_dbname_ambulatorial: "",
            default_dbname_hospitalar: "",
            default_remote_base_dir: "/",
            has_password: false,
            has_private_key: false,
            has_passphrase: false,
            configured: false,
            updated_at: null,
          },
        ]);
      }
      if (
        url.includes("/api/projects") ||
        url.includes("/api/clients") ||
        url.includes("/api/db/profiles") ||
        url.includes("/api/sftp/profiles") ||
        url.includes("/api/jasperserver/profiles") ||
        url.includes("/api/subreports") ||
        url.includes("/api/harnesses") ||
        url.includes("/api/skills")
      ) {
        return jsonResponse([]);
      }
      if (url.includes("/api/settings")) return jsonResponse({});
      if (url.includes("/api/health")) {
        return jsonResponse({
          status: "ok",
          app_name: "Salutem Ficha Studio",
          version: "1.1.1",
          database: {},
          paths: {},
          builtin_subreports_count: 4,
          custom_subreports_count: 0,
          effective_subreports_count: 4,
          frontend_built: false,
        });
      }
      return jsonResponse({ status: "UP" });
    });

    const user = userEvent.setup();
    const { unmount } = render(<App />);

    const quickStartBtn = await screen.findByRole("button", {
      name: /1\. Credenciais Padrão/i,
    });
    await user.click(quickStartBtn);

    await waitFor(() => {
      const defaultCredTab = screen.getByRole("tab", {
        name: /Credenciais Padrão/i,
      });
      expect(defaultCredTab).toHaveAttribute("aria-selected", "true");
      expect(window.location.hash).toBe(
        "#section=settings&tab=default_credentials",
      );
    });

    // Switch to SFTP tab and verify hash updates
    await user.click(screen.getByRole("tab", { name: /Servidores SFTP/i }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#section=settings&tab=sftp_profiles");
    });

    // Simulate F5 reload on #section=settings&tab=sftp_profiles
    unmount();
    render(<App />);
    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: /Servidores SFTP/i }),
      ).toHaveAttribute("aria-selected", "true");
    });
  });

  it("avoids flashing ProjectsDashboardView while restoring project from hash, strips stale project hash on global navigation, and uses jrxml chat phase for free_report on sql_db", async () => {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}#project=${FREE_REPORT_PROJECT.id}&section=sql_db`,
    );

    let resolveProjects!: (value: Response) => void;
    const projectsPromise = new Promise<Response>((resolve) => {
      resolveProjects = resolve;
    });

    const chatUrls: string[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/projects")) {
        return projectsPromise;
      }
      if (url.includes("/chat")) {
        chatUrls.push(url);
        return jsonResponse([]);
      }
      if (url.includes("/artifacts/")) {
        return jsonResponse({ detail: "Not found" }, 404);
      }
      if (
        url.includes("/api/clients") ||
        url.includes("/api/db/profiles") ||
        url.includes("/api/sftp/profiles") ||
        url.includes("/api/jasperserver/profiles") ||
        url.includes("/api/subreports") ||
        url.includes("/api/harnesses") ||
        url.includes("/api/skills") ||
        url.includes("/revisions") ||
        url.includes("/gates")
      ) {
        return jsonResponse([]);
      }
      if (url.includes("/api/settings")) return jsonResponse({});
      if (url.includes("/api/health")) {
        return jsonResponse({
          status: "ok",
          app_name: "Salutem Ficha Studio",
          version: "1.1.1",
          database: {},
          paths: {},
          builtin_subreports_count: 4,
          custom_subreports_count: 0,
          effective_subreports_count: 4,
          frontend_built: false,
        });
      }
      return jsonResponse({ status: "UP" });
    });

    const user = userEvent.setup();
    render(<App />);

    // While loading projects for a hash-restored project, show restoring indicator (NOT ProjectsDashboardView)
    expect(screen.getByText(/Restaurando projeto/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /Meus Projetos/i }),
    ).not.toBeInTheDocument();

    // Finish loading projects
    resolveProjects(jsonResponse([FREE_REPORT_PROJECT]));

    await waitFor(() => {
      expect(
        screen.getByText("Relatório Financeiro Livre"),
      ).toBeInTheDocument();
    });

    // Open AI Assistant on sql_db for a free_report -> must use phase=jrxml
    await user.click(screen.getByRole("button", { name: /Assistente IA/i }));
    await waitFor(() => {
      expect(chatUrls.some((u) => u.includes("phase=jrxml"))).toBe(true);
    });
    expect(chatUrls.some((u) => u.includes("phase=extraction"))).toBe(false);

    // Navigate to Settings (global section) -> hash MUST NOT keep stale project=<uuid>
    await user.click(screen.getByRole("button", { name: /Configurações/i }));
    await waitFor(() => {
      expect(window.location.hash).toBe("#section=settings&tab=db_profiles");
      expect(window.location.hash).not.toContain("project=");
    });
  });

  it("deep-links CommandPalette DB profile selection into filtered SettingsView", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/db/profiles")) {
        return jsonResponse([
          {
            id: "pg-1",
            name: "Hospital Central PRD",
            host: "10.1.1.10",
            port: 5432,
            dbname: "salutem_central",
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
          {
            id: "pg-2",
            name: "Clínica Sul HML",
            host: "10.1.1.20",
            port: 5432,
            dbname: "salutem_sul",
            user: "postgres",
            sslmode: "prefer",
            environment: "HML",
            credential_mode: "custom",
            read_only: false,
            is_default: false,
            has_password: true,
            created_at: "2026-11-27T10:00:00Z",
            updated_at: "2026-11-27T10:00:00Z",
          },
        ]);
      }
      if (
        url.includes("/api/projects") ||
        url.includes("/api/clients") ||
        url.includes("/api/sftp/profiles") ||
        url.includes("/api/jasperserver/profiles") ||
        url.includes("/api/subreports") ||
        url.includes("/api/harnesses") ||
        url.includes("/api/skills")
      ) {
        return jsonResponse([]);
      }
      if (url.includes("/api/settings")) return jsonResponse({});
      if (url.includes("/api/health")) {
        return jsonResponse({
          status: "ok",
          app_name: "Salutem Ficha Studio",
          version: "1.1.1",
          database: {},
          paths: {},
          builtin_subreports_count: 4,
          custom_subreports_count: 0,
          effective_subreports_count: 4,
          frontend_built: false,
        });
      }
      return jsonResponse({ status: "UP" });
    });

    const user = userEvent.setup();
    render(<App />);

    await user.click(
      screen.getByRole("button", {
        name: /Buscar clientes, bancos, relatórios/i,
      }),
    );
    const searchInput = await screen.findByLabelText(/Buscar clientes, projetos/i);
    await waitFor(() => {
      expect(screen.getByText("Hospital Central PRD")).toBeInTheDocument();
    });
    await user.type(searchInput, "Hospital Central");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Configurações" })).toBeInTheDocument();
      expect(screen.getByLabelText(/Buscar perfis PostgreSQL/i)).toHaveValue(
        "Hospital Central PRD",
      );
      expect(screen.getByText("Hospital Central PRD")).toBeInTheDocument();
      expect(screen.queryByText("Clínica Sul HML")).not.toBeInTheDocument();
    });
  });
});
