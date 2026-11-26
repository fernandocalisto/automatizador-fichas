import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";

describe("API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("builds preview and export bundle URLs with query parameters", () => {
    expect(api.getPreviewPdfUrl("proj-1", "stress", 123)).toBe(
      "/api/projects/proj-1/jasper/preview/pdf?scenario=stress&t=123",
    );
    expect(api.getPreviewPageUrl("proj-1", 2, "full")).toBe(
      "/api/projects/proj-1/jasper/preview/pages/2?scenario=full",
    );
    expect(
      api.getExportBundleUrl("proj-1", {
        scenario: "blank",
        mode: "db_hybrid",
        db_profile_id: "prof-9",
      }),
    ).toBe(
      "/api/projects/proj-1/jasper/export-bundle?scenario=blank&mode=db_hybrid&db_profile_id=prof-9",
    );
  });

  it("throws structured ApiError when backend returns error JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Perfil somente leitura" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      api.commitInsert("proj-1", {
        profile_id: "p1",
        dry_run_token: "tok",
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: "Perfil somente leitura",
    } satisfies Partial<ApiError>);
  });
});
