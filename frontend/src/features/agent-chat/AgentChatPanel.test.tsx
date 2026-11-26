import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui";
import { api } from "@/lib/api";
import type { ChatMessageRead, ProjectRead } from "@/types/studio";
import {
  AgentChatDrawer,
  AgentChatPanel,
  type AgentStatusResponse,
} from "./index";

const BASE_PROJECT: ProjectRead = {
  id: "proj-chat-1",
  slug: "ficha_cardiologia",
  name: "Ficha Cardiologia",
  description: "Avaliação cardiológica ambulatorial",
  current_stage: "extraction",
  entry_mode: "pdf",
  preferred_harness: "agy",
  template_db_id: null,
  workspace_dir: "/tmp/proj-chat-1",
  has_pdf: true,
  gates: [
    {
      project_id: "proj-chat-1",
      gate_name: "gate1_json",
      status: "pending",
      decided_by: null,
      notes: "",
      updated_at: "2026-11-25T12:00:00Z",
    },
    {
      project_id: "proj-chat-1",
      gate_name: "gate3_jrxml",
      status: "pending",
      decided_by: null,
      notes: "",
      updated_at: "2026-11-25T12:00:00Z",
    },
  ],
  latest_artifacts: {},
  created_at: "2026-11-25T10:00:00Z",
  updated_at: "2026-11-25T10:00:00Z",
};

const DEFAULT_AGENT_STATUS: AgentStatusResponse = {
  project_id: BASE_PROJECT.id,
  active_run: false,
  preferred_harness: "agy",
  harnesses: [
    {
      id: "agy",
      display_name: "AGY",
      installed: true,
      executable_path: "/usr/local/bin/agy",
      sdk_available: true,
      version: "2.1.0",
      auth_hint: "",
      supports_vision: true,
      supports_mcp: true,
    },
    {
      id: "opencode",
      display_name: "OpenCode",
      installed: false,
      executable_path: null,
      sdk_available: false,
      version: null,
      auth_hint: "Instale opencode",
      supports_vision: true,
      supports_mcp: true,
    },
    {
      id: "claude",
      display_name: "Claude Code",
      installed: true,
      executable_path: "/usr/local/bin/claude",
      sdk_available: false,
      version: "1.4.2",
      auth_hint: "",
      supports_vision: true,
      supports_mcp: true,
    },
    {
      id: "codex",
      display_name: "Codex",
      installed: false,
      executable_path: null,
      sdk_available: false,
      version: null,
      auth_hint: "Instale codex",
      supports_vision: true,
      supports_mcp: true,
    },
  ],
  gates: BASE_PROJECT.gates,
  pending_visual_feedback_count: 1,
};

function makeSseStream(events: Array<{ event?: string; data: Record<string, unknown> }>) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const item of events) {
        const eventType = item.event ?? String(item.data.type ?? "text_delta");
        const payload = `event: ${eventType}\ndata: ${JSON.stringify(item.data)}\n\n`;
        controller.enqueue(encoder.encode(payload));
      }
      controller.close();
    },
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("AgentChatPanel & AgentChatDrawer", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("carrega histórico persistido incluindo card de anotação visual visual_region_feedback e status dos harnesses", async () => {
    const history: ChatMessageRead[] = [
      {
        id: 1,
        project_id: BASE_PROJECT.id,
        phase: "jrxml",
        role: "user",
        content: "Esses 3 checkboxes ficaram colados, espaçar horizontalmente",
        metadata: {
          type: "visual_region_feedback",
          page: 1,
          scenario: "full",
          pdf_rect: {
            x0: 42,
            y0: 210,
            x1: 310,
            y1: 245,
            width: 268,
            height: 35,
          },
          detail_coords: {
            x: 22,
            y: 28,
            width: 268,
            height: 35,
          },
        },
        metadata_json: "{}",
        created_at: "2026-11-25T13:15:00Z",
      },
      {
        id: 2,
        project_id: BASE_PROJECT.id,
        phase: "jrxml",
        role: "assistant",
        content: "Anotei o ajuste no bloco de checkboxes da página 1.",
        metadata: { harness: "agy" },
        metadata_json: "{}",
        created_at: "2026-11-25T13:16:00Z",
      },
    ];

    vi.spyOn(api, "listChat").mockResolvedValue(history);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/agent/status")) {
        return jsonResponse(DEFAULT_AGENT_STATUS);
      }
      return jsonResponse({}, 404);
    });

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <AgentChatPanel
          project={BASE_PROJECT}
          initialPhase="jrxml"
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    const feedbackCard = await screen.findByTestId(
      "visual-region-feedback-card",
    );
    expect(feedbackCard).toHaveTextContent("Anotação Visual · Jasper Studio");
    expect(feedbackCard).toHaveTextContent("Página 1");
    expect(feedbackCard).toHaveTextContent("PDF (42, 210) → (310, 245)");
    expect(feedbackCard).toHaveTextContent("<detail> x=22, y=28 (268×35)");
    expect(feedbackCard).toHaveTextContent(
      "Esses 3 checkboxes ficaram colados, espaçar horizontalmente",
    );

    // Status do Gate 1 e indicador verde do AGY instalado
    expect(screen.getByTestId("gate-status-pill")).toHaveTextContent(
      "Gate 1 — Aguardando",
    );
    expect(screen.getByTestId("harness-install-indicator")).toHaveAttribute(
      "aria-label",
      "Harness instalado",
    );

    // Trocar para OpenCode (não instalado) muda o indicador para não instalado
    const select = screen.getByLabelText("Harness ativo");
    await user.selectOptions(select, "opencode");
    expect(screen.getByTestId("harness-install-indicator")).toHaveAttribute(
      "aria-label",
      "Harness não instalado",
    );
  });

  it("renderiza streaming completo (thought_delta, tool_call + tool_result colapsáveis, text_delta, gate_request e done)", async () => {
    vi.spyOn(api, "listChat").mockResolvedValue([]);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/agent/status")) {
        return jsonResponse(DEFAULT_AGENT_STATUS);
      }
      if (url.endsWith("/agent/stream")) {
        const sse = makeSseStream([
          {
            data: {
              type: "thought_delta",
              content: "Inspecionando estrutura de perguntas no PDF...",
              harness: "agy",
            },
          },
          {
            data: {
              type: "tool_call",
              tool_name: "extract_pdf_geometry",
              tool_call_id: "call-geo-1",
              tool_args: { project_id: BASE_PROJECT.id },
              harness: "agy",
            },
          },
          {
            data: {
              type: "tool_result",
              tool_name: "extract_pdf_geometry",
              tool_call_id: "call-geo-1",
              tool_output: { ok: true, pages: 1, checkboxes: 6 },
              harness: "agy",
            },
          },
          {
            data: {
              type: "text_delta",
              content: "Mapeamento concluído:\n- **6 campos** identificados\n",
              harness: "agy",
            },
          },
          {
            data: {
              type: "text_delta",
              content: "Use `BOOLEANO_RADIO` para o bloco de risco.",
              harness: "agy",
            },
          },
          {
            data: {
              type: "gate_request",
              content:
                "Confirme o mapeamento para autorizar a geração do JSON.",
              harness: "agy",
              metadata: { phase: "extraction", gate_authorized: false },
            },
          },
          {
            data: {
              type: "done",
              content: "",
              harness: "agy",
            },
          },
        ]);
        return new Response(sse, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return jsonResponse({}, 404);
    });

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <AgentChatPanel
          project={BASE_PROJECT}
          initialPhase="extraction"
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    await waitFor(() => expect(api.listChat).toHaveBeenCalled());

    // Usa chip de prompt rápido e envia
    await user.click(
      screen.getByRole("button", {
        name: "Analisar PDF da ficha e mapear perguntas",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    // Texto streamado aparece formatado
    expect(
      await screen.findByText(/Mapeamento concluído:/),
    ).toBeInTheDocument();
    expect(screen.getByText("BOOLEANO_RADIO")).toBeInTheDocument();

    // Raciocínio colapsável com contagem de caracteres
    const thoughtToggle = screen.getByRole("button", { name: /Raciocínio/i });
    expect(thoughtToggle).toHaveAttribute("aria-expanded", "false");
    expect(thoughtToggle).toHaveTextContent("46 caracteres");
    await user.click(thoughtToggle);
    expect(thoughtToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("thought-content")).toHaveTextContent(
      "Inspecionando estrutura de perguntas no PDF...",
    );

    // Tool call colapsável pareado com tool_result
    const toolCard = screen.getByTestId("tool-call-card-extract_pdf_geometry");
    expect(toolCard).toHaveTextContent("Concluído");
    const toolToggle = within(toolCard).getByRole("button");
    expect(toolToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toolToggle);
    expect(toolToggle).toHaveAttribute("aria-expanded", "true");
    expect(toolCard).toHaveTextContent("Argumentos");
    expect(toolCard).toHaveTextContent(BASE_PROJECT.id);
    expect(toolCard).toHaveTextContent("Saída");
    expect(toolCard).toHaveTextContent('"checkboxes": 6');

    // Banner de aprovação do Gate aparece após gate_request
    const banner = screen.getByTestId("gate-approval-banner");
    expect(banner).toHaveTextContent(
      "Confirme o mapeamento para autorizar a geração do JSON.",
    );

    // Botão "Pedir ajustes" foca o composer
    await user.click(
      within(banner).getByRole("button", { name: "Pedir ajustes" }),
    );
    expect(screen.getByLabelText("Mensagem para o agente")).toHaveFocus();
  });

  it("autoriza Gate 1 -> Gate 2, dispara turno autorizado e sincroniza artefato com atalho para Form Builder", async () => {
    const historyWithPendingGate: ChatMessageRead[] = [
      {
        id: 10,
        project_id: BASE_PROJECT.id,
        phase: "extraction",
        role: "assistant",
        content: "Análise concluída. Podemos gerar o JSON?",
        metadata: {
          harness: "agy",
          gate_requested: true,
          gate_request_message: "Aguardando sua autorização para gerar JSON.",
        },
        metadata_json: "{}",
        created_at: "2026-11-25T14:00:00Z",
      },
    ];

    const updatedProject: ProjectRead = {
      ...BASE_PROJECT,
      current_stage: "form_builder",
      latest_artifacts: { json: 1, sql_insert: 1, sql_select: 1 },
      gates: [
        {
          project_id: BASE_PROJECT.id,
          gate_name: "gate1_json",
          status: "approved",
          decided_by: "user",
          notes: "Autorizado via painel",
          updated_at: "2026-11-25T14:05:00Z",
        },
      ],
    };

    vi.spyOn(api, "listChat").mockResolvedValue(historyWithPendingGate);
    const getProjectSpy = vi
      .spyOn(api, "getProject")
      .mockResolvedValue(updatedProject);

    const streamPayloads: Array<Record<string, unknown>> = [];
    const authorizePayloads: Array<Record<string, unknown>> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/agent/status")) {
        return jsonResponse(DEFAULT_AGENT_STATUS);
      }
      if (url.endsWith("/agent/authorize-gate")) {
        authorizePayloads.push(JSON.parse(String(init?.body ?? "{}")));
        return jsonResponse({
          ok: true,
          gate: updatedProject.gates[0],
          message: {
            id: 11,
            project_id: BASE_PROJECT.id,
            phase: "extraction",
            role: "system",
            content: "Gate 1 autorizado.",
            metadata: {},
            metadata_json: "{}",
            created_at: "2026-11-25T14:05:00Z",
          },
        });
      }
      if (url.endsWith("/agent/stream")) {
        streamPayloads.push(JSON.parse(String(init?.body ?? "{}")));
        const sse = makeSseStream([
          {
            data: {
              type: "tool_result",
              tool_name: "workspace_sync",
              tool_output: { ok: true, version_num: 1 },
              harness: "agy",
              metadata: {
                artifact_synced: true,
                artifact_type: "json",
                version_num: 1,
                summary: "JSON clínico importado automaticamente",
              },
            },
          },
          {
            data: {
              type: "text_delta",
              content: "Arquivo `ficha_clinica.json` gravado no workspace!",
              harness: "agy",
            },
          },
          {
            data: { type: "done", content: "", harness: "agy" },
          },
        ]);
        return new Response(sse, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return jsonResponse({}, 404);
    });

    const onProjectUpdated = vi.fn();
    const onNavigateSection = vi.fn();
    const onArtifactSynced = vi.fn();
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <AgentChatPanel
          project={BASE_PROJECT}
          initialPhase="extraction"
          onProjectUpdated={onProjectUpdated}
          onNavigateSection={onNavigateSection}
          onArtifactSynced={onArtifactSynced}
        />
      </ToastProvider>,
    );

    const authorizeBtn = await screen.findByRole("button", {
      name: /Autorizar e gerar artefato \(Autorizado\)/i,
    });
    await user.click(authorizeBtn);

    // Verifica chamada ao authorize-gate
    await waitFor(() => {
      expect(authorizePayloads).toHaveLength(1);
    });
    expect(authorizePayloads[0]).toEqual({ phase: "extraction" });

    // Verifica disparo imediato do Gate 2 com gate_authorized: true
    await waitFor(() => {
      expect(streamPayloads).toHaveLength(1);
    });
    expect(streamPayloads[0]).toMatchObject({
      phase: "extraction",
      prompt: "Autorizado",
      gate_authorized: true,
      harness_id: "agy",
    });

    // Verifica atualização do pill de Gate e sincronização do projeto/artefato
    expect(screen.getByTestId("gate-status-pill")).toHaveTextContent(
      "Gate 2 — Autorizado",
    );
    await waitFor(() => {
      expect(getProjectSpy).toHaveBeenCalledWith(BASE_PROJECT.id);
      expect(onProjectUpdated).toHaveBeenCalledWith(updatedProject);
      expect(onArtifactSynced).toHaveBeenCalledWith("json", 1);
    });

    // Card de artefato sincronizado com atalho direto para Form Builder
    const syncedCard = await screen.findByTestId("synced-artifact-card");
    expect(syncedCard).toHaveTextContent("Artefato sincronizado");
    expect(syncedCard).toHaveTextContent("JSON Clínico v1");

    await user.click(
      within(syncedCard).getByRole("button", { name: "Abrir Form Builder" }),
    );
    expect(onNavigateSection).toHaveBeenCalledWith("form_builder");
  });

  it("interrompe streaming ativo acionando AbortController e chamando POST /agent/cancel", async () => {
    vi.spyOn(api, "listChat").mockResolvedValue([]);

    let cancelCalled = false;
    let streamAborted = false;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/agent/status")) {
        return jsonResponse(DEFAULT_AGENT_STATUS);
      }
      if (url.endsWith("/agent/cancel")) {
        cancelCalled = true;
        return jsonResponse({ ok: true, cancelled: true });
      }
      if (url.endsWith("/agent/stream")) {
        init?.signal?.addEventListener("abort", () => {
          streamAborted = true;
        });

        const encoder = new TextEncoder();
        const openStream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                'event: text_delta\ndata: {"type":"text_delta","content":"Processando..."}\n\n',
              ),
            );
            // Mantém aberto até o cancelamento
          },
        });

        return new Response(openStream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return jsonResponse({}, 404);
    });

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <AgentChatPanel
          project={BASE_PROJECT}
          initialPhase="extraction"
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    await waitFor(() => expect(api.listChat).toHaveBeenCalled());

    const input = screen.getByLabelText("Mensagem para o agente");
    await user.type(input, "Executar tarefa longa{Enter}");

    const stopBtn = await screen.findByRole("button", { name: "Interromper" });
    await user.click(stopBtn);

    await waitFor(() => {
      expect(cancelCalled).toBe(true);
      expect(streamAborted).toBe(true);
    });

    // Botão Enviar volta a ficar visível após interromper
    expect(
      await screen.findByRole("button", { name: "Enviar" }),
    ).toBeInTheDocument();
  });

  it("renderiza AgentChatDrawer acoplado à direita sem cobrir o header e fecha via botão ou Escape", async () => {
    vi.spyOn(api, "listChat").mockResolvedValue([]);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(DEFAULT_AGENT_STATUS),
    );

    const onClose = vi.fn();
    const user = userEvent.setup();

    const { rerender } = render(
      <ToastProvider>
        <AgentChatDrawer
          open={false}
          onClose={onClose}
          project={BASE_PROJECT}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    expect(screen.queryByTestId("agent-chat-drawer")).not.toBeInTheDocument();

    rerender(
      <ToastProvider>
        <AgentChatDrawer
          open
          onClose={onClose}
          project={BASE_PROJECT}
          onProjectUpdated={vi.fn()}
          onNavigateSection={vi.fn()}
        />
      </ToastProvider>,
    );

    const drawer = screen.getByTestId("agent-chat-drawer");
    expect(drawer.className).toContain("w-[440px]");
    expect(drawer.className).toContain("max-w-[95vw]");
    expect(drawer.className).toContain("top-12");

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByLabelText("Fechar painel do agente"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("alterna abas Extração <-> Layout JRXML recarregando histórico, chips rápidos e atalho do Jasper Studio", async () => {
    const listChatSpy = vi
      .spyOn(api, "listChat")
      .mockImplementation(async (_projectId, phase) => {
        if (phase === "jrxml") {
          return [
            {
              id: 21,
              project_id: BASE_PROJECT.id,
              phase: "jrxml",
              role: "assistant",
              content: "Layout JRXML v2 sincronizado no workspace.",
              metadata: {
                harness: "claude",
                synced_artifacts: [
                  {
                    artifact_type: "jrxml",
                    version_num: 2,
                    summary: "Layout fiel ao PDF",
                  },
                ],
              },
              metadata_json: "{}",
              created_at: "2026-11-25T15:00:00Z",
            },
          ];
        }
        return [];
      });

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        ...DEFAULT_AGENT_STATUS,
        gates: [
          ...BASE_PROJECT.gates.slice(0, 1),
          {
            project_id: BASE_PROJECT.id,
            gate_name: "gate3_jrxml",
            status: "approved",
            decided_by: "user",
            notes: "",
            updated_at: "2026-11-25T15:00:00Z",
          },
        ],
      }),
    );

    const onNavigateSection = vi.fn();
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <AgentChatPanel
          project={BASE_PROJECT}
          initialPhase="extraction"
          onProjectUpdated={vi.fn()}
          onNavigateSection={onNavigateSection}
        />
      </ToastProvider>,
    );

    await waitFor(() =>
      expect(listChatSpy).toHaveBeenCalledWith(BASE_PROJECT.id, "extraction"),
    );
    expect(
      screen.getByRole("button", { name: "Revisar campos obrigatórios" }),
    ).toBeInTheDocument();

    // Alterna para Layout JRXML
    await user.click(screen.getByRole("tab", { name: /Layout JRXML/i }));

    await waitFor(() =>
      expect(listChatSpy).toHaveBeenCalledWith(BASE_PROJECT.id, "jrxml"),
    );
    expect(
      screen.getByRole("button", { name: "Aplicar ajustes visuais marcados" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("gate-status-pill")).toHaveTextContent(
      "Gate 2 — Autorizado",
    );

    const syncedCard = await screen.findByTestId("synced-artifact-card");
    expect(syncedCard).toHaveTextContent("Layout JRXML v2");
    await user.click(
      within(syncedCard).getByRole("button", { name: "Abrir Jasper Studio" }),
    );
    expect(onNavigateSection).toHaveBeenCalledWith("jasper_studio");
  });
});
