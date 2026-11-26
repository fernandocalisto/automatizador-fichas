import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import type { ArtifactRevisionRead, ProjectRead } from "@/types/studio";
import { ProjectOverviewView } from "./ProjectOverviewView";

function makeProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  return {
    id: "proj-overview-1",
    slug: "ficha_ubs",
    name: "Ficha Clínica UBS",
    description: "Atendimento ambulatorial",
    current_stage: "form_builder",
    entry_mode: "pdf",
    preferred_harness: "agy",
    template_db_id: 105,
    workspace_dir: "/data/projects/ficha_ubs",
    has_pdf: true,
    gates: [
      {
        project_id: "proj-overview-1",
        gate_name: "gate1_json",
        status: "pending",
        decided_by: null,
        notes: "",
        updated_at: "2026-03-02T10:00:00Z",
      },
      {
        project_id: "proj-overview-1",
        gate_name: "gate2_sql_insert",
        status: "pending",
        decided_by: null,
        notes: "",
        updated_at: "2026-03-02T10:00:00Z",
      },
      {
        project_id: "proj-overview-1",
        gate_name: "gate3_jrxml",
        status: "pending",
        decided_by: null,
        notes: "",
        updated_at: "2026-03-02T10:00:00Z",
      },
    ],
    latest_artifacts: { json: 2, sql_insert: 1 },
    created_at: "2026-03-02T08:00:00Z",
    updated_at: "2026-03-02T10:00:00Z",
    ...overrides,
  };
}

const SAMPLE_REVISIONS: ArtifactRevisionRead[] = [
  {
    id: 10,
    project_id: "proj-overview-1",
    artifact_type: "json",
    version_num: 2,
    content: "{}",
    summary: "Ajuste de respostas",
    created_by: "user",
    created_at: "2026-03-02T09:30:00Z",
  },
  {
    id: 9,
    project_id: "proj-overview-1",
    artifact_type: "json",
    version_num: 1,
    content: "{}",
    summary: "Extração inicial",
    created_by: "agent",
    created_at: "2026-03-02T09:00:00Z",
  },
];

describe("ProjectOverviewView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("updates gates, filters and restores revisions, and inspects PDF geometry", async () => {
    const user = userEvent.setup();
    const project = makeProject();
    const onProjectUpdated = vi.fn();
    const onNavigateSection = vi.fn();

    const listRevsSpy = vi
      .spyOn(api, "listRevisions")
      .mockResolvedValue(SAMPLE_REVISIONS);
    const updateGateSpy = vi.spyOn(api, "updateGate").mockResolvedValue({
      project_id: project.id,
      gate_name: "gate1_json",
      status: "approved",
      decided_by: "user",
      notes: "Campos conferidos",
      updated_at: "2026-03-02T11:00:00Z",
    });
    const restoreSpy = vi.spyOn(api, "restoreArtifact").mockResolvedValue({
      artifact: {
        ...SAMPLE_REVISIONS[1],
        id: 11,
        version_num: 3,
        summary: "Restaurado da v1",
      },
      generated_sql_insert: null,
      generated_sql_select: null,
    });
    const geomSpy = vi.spyOn(api, "getProjectPdfGeometry").mockResolvedValue({
      page_count: 1,
      width: 595,
      height: 842,
      orientation: "RETRATO",
      summary: {
        total_text_spans: 48,
        total_shapes: 24,
        checkbox_candidates: 6,
        radio_candidates: 4,
      },
      pages: [
        {
          page_number: 1,
          text_spans: [
            {
              text: "PRESSÃO ARTERIAL",
              detail_x: 12,
              detail_y: 28,
              size: 8.5,
            },
          ],
        },
      ],
    });

    render(
      <ToastProvider>
        <ProjectOverviewView
          project={project}
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={onNavigateSection}
        />
      </ToastProvider>,
    );

    // PDF iframe points to api.getProjectPdfUrl
    const iframe = screen.getByTitle("PDF original de Ficha Clínica UBS");
    expect(iframe).toHaveAttribute(
      "src",
      "/api/projects/proj-overview-1/pdf",
    );

    // Stepper navigation buttons
    await user.click(screen.getByRole("button", { name: /^Form Builder$/i }));
    expect(onNavigateSection).toHaveBeenCalledWith("form_builder");
    await user.click(screen.getByRole("button", { name: /^SQL & Banco$/i }));
    expect(onNavigateSection).toHaveBeenCalledWith("sql_db");
    await user.click(screen.getByRole("button", { name: /^Jasper Studio$/i }));
    expect(onNavigateSection).toHaveBeenCalledWith("jasper_studio");

    // Gate 1 approval with notes
    await user.type(
      screen.getByLabelText("Observações para G1 JSON"),
      "Campos conferidos",
    );
    const approveButtons = screen.getAllByRole("button", { name: /^Aprovar$/i });
    await user.click(approveButtons[0]);

    await waitFor(() => {
      expect(updateGateSpy).toHaveBeenCalledWith("proj-overview-1", "gate1_json", {
        status: "approved",
        decided_by: "user",
        notes: "Campos conferidos",
      });
      expect(onProjectUpdated).toHaveBeenCalled();
    });

    // Revisions loaded and filterable
    await waitFor(() => {
      expect(screen.getByText("Extração inicial")).toBeInTheDocument();
    });
    await user.selectOptions(
      screen.getByLabelText("Filtrar revisões por artefato"),
      "json",
    );
    await waitFor(() => {
      expect(listRevsSpy).toHaveBeenCalledWith("proj-overview-1", "json");
    });

    // Restore revision v1
    const restoreButtons = screen.getAllByRole("button", {
      name: /Restaurar revisão/i,
    });
    await user.click(restoreButtons[1]);
    await waitFor(() => {
      expect(restoreSpy).toHaveBeenCalledWith("proj-overview-1", "json", {
        version_num: 1,
        created_by: "user",
        auto_regenerate_sql: true,
      });
    });

    // Inspect PDF geometry
    await user.click(
      screen.getByRole("button", { name: /Inspecionar geometria/i }),
    );
    await waitFor(() => {
      expect(geomSpy).toHaveBeenCalledWith("proj-overview-1");
      expect(screen.getByText(/1 · RETRATO/i)).toBeInTheDocument();
      expect(screen.getByText("PRESSÃO ARTERIAL")).toBeInTheDocument();
    });
  });

  it("shows fallback when has_pdf is false and allows uploading source.pdf", async () => {
    const user = userEvent.setup();
    const project = makeProject({ has_pdf: false, current_stage: "landing" });
    const updated = makeProject({ has_pdf: true, current_stage: "extraction" });

    vi.spyOn(api, "listRevisions").mockResolvedValue([]);
    const uploadSpy = vi
      .spyOn(api, "uploadProjectPdf")
      .mockResolvedValue(updated);
    const onProjectUpdated = vi.fn();

    render(
      <ToastProvider>
        <ProjectOverviewView
          project={project}
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    expect(screen.getByText("Nenhum source.pdf anexado")).toBeInTheDocument();

    const pdfFile = new File(["%PDF-1.4"], "ficha.pdf", {
      type: "application/pdf",
    });
    const input = screen.getByLabelText("Enviar ou substituir source.pdf");
    await user.upload(input, pdfFile);

    await waitFor(() => {
      expect(uploadSpy).toHaveBeenCalledWith("proj-overview-1", pdfFile);
      expect(onProjectUpdated).toHaveBeenCalledWith(updated);
    });
  });
});
