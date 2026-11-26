import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";

describe("Studio App shell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders studio header, toggles theme, and opens settings", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/projects")) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/health")) {
        return new Response(
          JSON.stringify({
            status: "ok",
            app_name: "Salutem Ficha Studio",
            version: "1.0.0",
            database: {},
            paths: {},
            builtin_subreports_count: 4,
            custom_subreports_count: 0,
            effective_subreports_count: 4,
            frontend_built: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ status: "UP" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText("Salutem Ficha Studio")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("v1.0.0")).toBeInTheDocument();
    });

    const themeBtn = screen.getByRole("button", { name: /Ativar tema escuro/i });
    await user.click(themeBtn);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    await user.click(screen.getByRole("button", { name: /Configurações/i }));
    expect(screen.getByRole("heading", { name: "Configurações" })).toBeInTheDocument();
    expect(window.location.hash).toContain("section=settings");
  });
});
