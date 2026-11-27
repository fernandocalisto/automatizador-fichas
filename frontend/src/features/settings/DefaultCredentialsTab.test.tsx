import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { clientsApi } from "@/features/clients/clientsApi";
import type { CredentialKind, DefaultCredentialRead } from "@/types/studio";
import { DefaultCredentialsTab } from "./DefaultCredentialsTab";

const INITIAL_DEFAULTS: Record<CredentialKind, DefaultCredentialRead> = {
  postgres: {
    kind: "postgres",
    username: "pg_default_demo",
    organization: "",
    auth_type: "password",
    default_dbname: "salutem_default",
    default_dbname_ambulatorial: "salutem_amb",
    default_dbname_hospitalar: "salutem_hosp",
    default_remote_base_dir: "/",
    has_password: true,
    has_private_key: false,
    has_passphrase: false,
    configured: true,
    updated_at: "2026-11-27T10:00:00Z",
  },
  sftp: {
    kind: "sftp",
    username: "",
    organization: "",
    auth_type: "password",
    default_dbname: "",
    default_dbname_ambulatorial: "",
    default_dbname_hospitalar: "",
    default_remote_base_dir: "/opt/reports",
    has_password: false,
    has_private_key: false,
    has_passphrase: false,
    configured: false,
    updated_at: null,
  },
  jasperserver: {
    kind: "jasperserver",
    username: "jasper_demo",
    organization: "org_demo",
    auth_type: "password",
    default_dbname: "",
    default_dbname_ambulatorial: "",
    default_dbname_hospitalar: "",
    default_remote_base_dir: "/",
    has_password: false,
    has_private_key: false,
    has_passphrase: false,
    configured: true,
    updated_at: "2026-11-27T10:00:00Z",
  },
};

describe("DefaultCredentialsTab", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("displays security notice, loads defaults, updates PostgreSQL & SFTP private_key, and clears credentials", async () => {
    const user = userEvent.setup();
    vi.spyOn(clientsApi, "listDefaultCredentials").mockResolvedValue(
      INITIAL_DEFAULTS,
    );
    const updateSpy = vi
      .spyOn(clientsApi, "updateDefaultCredential")
      .mockImplementation(async (kind, payload) => ({
        ...INITIAL_DEFAULTS[kind],
        username: payload.username ?? INITIAL_DEFAULTS[kind].username,
        auth_type: payload.auth_type ?? INITIAL_DEFAULTS[kind].auth_type,
        has_password: Boolean(payload.password) || INITIAL_DEFAULTS[kind].has_password,
        has_private_key:
          Boolean(payload.private_key) || INITIAL_DEFAULTS[kind].has_private_key,
        configured: true,
      }));
    const deleteSpy = vi
      .spyOn(clientsApi, "deleteDefaultCredential")
      .mockImplementation(async (kind) => ({
        ...INITIAL_DEFAULTS[kind],
        username: "",
        organization: "",
        has_password: false,
        has_private_key: false,
        has_passphrase: false,
        configured: false,
      }));

    render(
      <ToastProvider>
        <DefaultCredentialsTab />
      </ToastProvider>,
    );

    // Explicit local-vault security banner
    expect(
      screen.getByText(/Armazenamento exclusivamente no cofre local/i),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByLabelText(/Usuário padrão/i, { selector: "#def-pg-user" })).toHaveValue(
        "pg_default_demo",
      );
      expect(screen.getByLabelText(/Banco padrão Ambulatorial/i)).toHaveValue(
        "salutem_amb",
      );
    });

    // Save PostgreSQL defaults with a new password
    await user.type(
      screen.getByLabelText(/Senha padrão/i, { selector: "#def-pg-pass" }),
      "SyntheticPgSecret#1",
    );
    await user.click(
      screen.getByRole("button", { name: /Salvar PostgreSQL padrão/i }),
    );
    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        "postgres",
        expect.objectContaining({
          username: "pg_default_demo",
          password: "SyntheticPgSecret#1",
          default_dbname_ambulatorial: "salutem_amb",
          default_dbname_hospitalar: "salutem_hosp",
        }),
      );
    });

    // Switch SFTP auth_type to private_key and save
    await user.selectOptions(
      screen.getByLabelText(/Tipo de autenticação/i),
      "private_key",
    );
    await user.type(screen.getByLabelText(/Usuário SSH/i), "deploy_demo");
    await user.type(
      screen.getByLabelText(/Chave privada SSH/i),
      "-----BEGIN SYNTHETIC KEY-----",
    );
    await user.click(
      screen.getByRole("button", { name: /Salvar SFTP padrão/i }),
    );
    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        "sftp",
        expect.objectContaining({
          username: "deploy_demo",
          auth_type: "private_key",
          private_key: "-----BEGIN SYNTHETIC KEY-----",
        }),
      );
    });

    // Clear JasperServer defaults
    await user.click(
      screen.getByRole("button", { name: /Limpar JasperServer/i }),
    );
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("jasperserver");
    });
  });
});
