import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  Bot,
  FileCode2,
  FileText,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  Tabs,
  useToast,
  type TabOption,
} from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type {
  ChatPhase,
  GateApprovalRead,
  HarnessStatus,
  ProjectRead,
  StudioSection,
} from "@/types/studio";
import { GateApprovalBanner } from "./GateApprovalBanner";
import { MessageBubble } from "./MessageBubble";
import {
  authorizeAgentGate,
  cancelAgentRun,
  CANONICAL_HARNESSES,
  fetchAgentStatus,
  isAbortError,
  isToolOutputError,
  normalizePersistedChatMessage,
  phaseToGateName,
  streamAgentTurn,
  type AgentStreamEvent,
  type ChatTimelineItem,
  type SyncedArtifactInfo,
  type ToolCallRecord,
} from "./sseClient";

export interface AgentChatPanelProps {
  project: ProjectRead;
  initialPhase?: ChatPhase;
  onProjectUpdated: (project: ProjectRead) => void;
  onNavigateSection: (section: StudioSection) => void;
  onArtifactSynced?: (artifactType: string, versionNum?: number) => void;
  className?: string;
  onClose?: () => void;
}

const PHASE_TABS: TabOption<ChatPhase>[] = [
  {
    id: "extraction",
    label: "Extração (PDF → JSON)",
    icon: <FileText className="h-3.5 w-3.5" />,
  },
  {
    id: "jrxml",
    label: "Layout JRXML",
    icon: <FileCode2 className="h-3.5 w-3.5" />,
  },
];

const QUICK_PROMPTS_BY_PHASE: Record<ChatPhase, string[]> = {
  extraction: [
    "Analisar PDF da ficha e mapear perguntas",
    "Revisar campos obrigatórios",
    "Conferir agrupamentos BOOLEANO_RADIO e observações",
  ],
  jrxml: [
    "Planejar layout JRXML fiel ao PDF",
    "Aplicar ajustes visuais marcados",
    "Revisar limites de banda e campos nulos",
  ],
};

function defaultPhaseForProject(project: ProjectRead): ChatPhase {
  if (
    project.current_stage === "jrxml_design" ||
    project.current_stage === "completed"
  ) {
    return "jrxml";
  }
  return "extraction";
}

function mergeHarnesses(incoming?: HarnessStatus[]): HarnessStatus[] {
  if (!incoming || incoming.length === 0) {
    return CANONICAL_HARNESSES;
  }
  const byId = new Map<string, HarnessStatus>();
  for (const base of CANONICAL_HARNESSES) {
    byId.set(base.id, base);
  }
  for (const item of incoming) {
    byId.set(item.id, item);
  }
  return Array.from(byId.values());
}

function upsertSyncedArtifact(
  existing: SyncedArtifactInfo[] | undefined,
  next: SyncedArtifactInfo,
): SyncedArtifactInfo[] {
  const list = existing ? [...existing] : [];
  const matchIdx = list.findIndex(
    (item) =>
      item.artifact_type === next.artifact_type &&
      item.version_num === next.version_num,
  );
  if (matchIdx === -1) {
    list.push(next);
  } else {
    list[matchIdx] = { ...list[matchIdx], ...next };
  }
  return list;
}

function applyToolCallEvent(
  existing: ToolCallRecord[] | undefined,
  event: AgentStreamEvent,
): ToolCallRecord[] {
  const list = existing ? [...existing] : [];
  const callId = event.tool_call_id ?? null;
  const toolName = event.tool_name || "ferramenta";
  const recordId = callId || `call-${Date.now()}-${list.length}`;

  if (callId) {
    const idx = list.findIndex((item) => item.tool_call_id === callId);
    if (idx !== -1) {
      list[idx] = {
        ...list[idx],
        tool_name: toolName,
        tool_args: event.tool_args ?? list[idx].tool_args,
        status: "running",
      };
      return list;
    }
  }

  list.push({
    id: recordId,
    tool_call_id: callId,
    tool_name: toolName,
    status: "running",
    tool_args: event.tool_args ?? null,
    metadata: event.metadata,
  });
  return list;
}

function applyToolResultEvent(
  existing: ToolCallRecord[] | undefined,
  event: AgentStreamEvent,
): ToolCallRecord[] {
  const list = existing ? [...existing] : [];
  const callId = event.tool_call_id ?? null;
  const toolName = event.tool_name || "ferramenta";
  const errored = isToolOutputError(event.tool_output, event.metadata);
  const errorMessage =
    errored && typeof event.content === "string" && event.content.trim()
      ? event.content
      : errored &&
          event.tool_output &&
          typeof event.tool_output === "object" &&
          "error" in (event.tool_output as Record<string, unknown>)
        ? String((event.tool_output as Record<string, unknown>).error)
        : null;

  let targetIdx = -1;
  if (callId) {
    targetIdx = list.findIndex((item) => item.tool_call_id === callId);
  }
  if (targetIdx === -1 && event.tool_name) {
    targetIdx = list.findIndex(
      (item) => item.status === "running" && item.tool_name === event.tool_name,
    );
  }
  if (targetIdx === -1) {
    targetIdx = list.findIndex((item) => item.status === "running");
  }

  if (targetIdx !== -1) {
    list[targetIdx] = {
      ...list[targetIdx],
      tool_name: event.tool_name || list[targetIdx].tool_name,
      status: errored ? "error" : "done",
      tool_output:
        event.tool_output !== undefined ? event.tool_output : event.content,
      error_message: errorMessage,
      metadata: { ...list[targetIdx].metadata, ...event.metadata },
    };
    return list;
  }

  list.push({
    id: callId || `result-${Date.now()}-${list.length}`,
    tool_call_id: callId,
    tool_name: toolName,
    status: errored ? "error" : "done",
    tool_output:
      event.tool_output !== undefined ? event.tool_output : event.content,
    error_message: errorMessage,
    metadata: event.metadata,
  });
  return list;
}

export function AgentChatPanel({
  project,
  initialPhase,
  onProjectUpdated,
  onNavigateSection,
  onArtifactSynced,
  className,
  onClose,
}: AgentChatPanelProps) {
  const { pushToast } = useToast();

  const [phase, setPhase] = useState<ChatPhase>(
    () => initialPhase ?? defaultPhaseForProject(project),
  );
  const [messages, setMessages] = useState<ChatTimelineItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [harnesses, setHarnesses] = useState<HarnessStatus[]>(
    CANONICAL_HARNESSES,
  );
  const [selectedHarness, setSelectedHarness] = useState<string>(
    project.preferred_harness || "agy",
  );
  const [gates, setGates] = useState<GateApprovalRead[]>(project.gates ?? []);
  const [pendingVisualFeedbackCount, setPendingVisualFeedbackCount] =
    useState(0);

  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [authorizingGate, setAuthorizingGate] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [pendingGateRequest, setPendingGateRequest] = useState<{
    phase: ChatPhase;
    message?: string;
  } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const timelineEndRef = useRef<HTMLDivElement | null>(null);
  const userSelectedHarnessRef = useRef(false);

  // Sincroniza fase quando `initialPhase` muda explicitamente
  useEffect(() => {
    if (initialPhase) {
      setPhase(initialPhase);
    }
  }, [initialPhase]);

  // Sincroniza estado básico quando muda de projeto
  useEffect(() => {
    setGates(project.gates ?? []);
    if (!userSelectedHarnessRef.current) {
      setSelectedHarness(project.preferred_harness || "agy");
    }
  }, [project.id, project.gates, project.preferred_harness]);

  // Carrega status do agente e histórico da fase ativa
  const loadChatAndStatus = useCallback(
    async (targetProjectId: string, targetPhase: ChatPhase) => {
      setLoadingHistory(true);
      setHistoryError(null);
      setPendingGateRequest(null);

      try {
        const [chatResult, statusResult] = await Promise.allSettled([
          api.listChat(targetProjectId, targetPhase),
          fetchAgentStatus(targetProjectId),
        ]);

        if (chatResult.status === "fulfilled") {
          const normalized = chatResult.value.map(
            normalizePersistedChatMessage,
          );
          setMessages(normalized);
        } else {
          setMessages([]);
          setHistoryError(
            chatResult.reason instanceof Error
              ? chatResult.reason.message
              : "Não foi possível carregar o histórico do chat.",
          );
        }

        if (statusResult.status === "fulfilled") {
          const st = statusResult.value;
          setHarnesses(mergeHarnesses(st.harnesses));
          if (Array.isArray(st.gates)) {
            setGates(st.gates);
          }
          setPendingVisualFeedbackCount(st.pending_visual_feedback_count ?? 0);
          if (st.preferred_harness && !userSelectedHarnessRef.current) {
            setSelectedHarness(st.preferred_harness);
          }
        }
      } finally {
        setLoadingHistory(false);
      }
    },
    [],
  );

  useEffect(() => {
    // Cancela eventual stream ativo ao trocar de projeto ou fase
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setStreaming(false);

    void loadChatAndStatus(project.id, phase);

    return () => {
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
    };
  }, [project.id, phase, loadChatAndStatus]);

  // Auto-scroll suave ao receber novas mensagens ou deltas
  useEffect(() => {
    timelineEndRef.current?.scrollIntoView?.({
      behavior: "smooth",
      block: "end",
    });
  }, [messages]);

  const activeGateName = phaseToGateName(phase);
  const activeGate = useMemo(
    () => gates.find((g) => g.gate_name === activeGateName) ?? null,
    [gates, activeGateName],
  );
  const isGateApproved = activeGate?.status === "approved";

  const activeHarnessInfo = useMemo(
    () => harnesses.find((h) => h.id === selectedHarness) ?? harnesses[0],
    [harnesses, selectedHarness],
  );
  const isHarnessReady = Boolean(
    activeHarnessInfo?.installed || activeHarnessInfo?.sdk_available,
  );

  // Detecta se há análise pendente de aprovação na fase atual
  const latestAssistantGateMsg = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (m.role === "assistant") {
        if (m.gateRequested) {
          return m;
        }
        return null;
      }
    }
    return null;
  }, [messages]);

  const showGateBanner =
    pendingGateRequest?.phase === phase ||
    (!isGateApproved && Boolean(latestAssistantGateMsg));

  const gateBannerMessage =
    pendingGateRequest?.phase === phase
      ? pendingGateRequest.message
      : latestAssistantGateMsg?.gateRequestMessage;

  const triggerProjectSync = useCallback(
    (artifactType: string, versionNum?: number) => {
      onArtifactSynced?.(artifactType, versionNum);
      void api
        .getProject(project.id)
        .then((updated) => {
          onProjectUpdated(updated);
          if (Array.isArray(updated.gates)) {
            setGates(updated.gates);
          }
        })
        .catch(() => {
          // Mantém UI estável mesmo se refresh falhar
        });
    },
    [onArtifactSynced, onProjectUpdated, project.id],
  );

  const sendPrompt = useCallback(
    async (
      rawPrompt: string,
      options?: { gateAuthorized?: boolean },
    ): Promise<void> => {
      const trimmed = rawPrompt.trim();
      if (!trimmed || streaming) return;

      const effectiveGateAuthorized =
        options?.gateAuthorized !== undefined
          ? options.gateAuthorized
          : isGateApproved;

      const nowIso = new Date().toISOString();
      const userMsgId = `local-user-${Date.now()}`;
      const assistantMsgId = `local-assistant-${Date.now() + 1}`;

      const userBubble: ChatTimelineItem = {
        id: userMsgId,
        role: "user",
        phase,
        content: trimmed,
        createdAt: nowIso,
      };

      const assistantPlaceholder: ChatTimelineItem = {
        id: assistantMsgId,
        role: "assistant",
        phase,
        content: "",
        createdAt: nowIso,
        harness: selectedHarness,
        thoughts: "",
        toolCalls: [],
        syncedArtifacts: [],
        streaming: true,
      };

      setMessages((prev) => [...prev, userBubble, assistantPlaceholder]);
      setPendingGateRequest(null);
      setStreaming(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const updateAssistant = (
        updater: (prev: ChatTimelineItem) => ChatTimelineItem,
      ) => {
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantMsgId ? updater(item) : item,
          ),
        );
      };

      try {
        await streamAgentTurn(
          project.id,
          {
            phase,
            prompt: trimmed,
            harness_id: selectedHarness,
            gate_authorized: effectiveGateAuthorized,
          },
          {
            signal: controller.signal,
            onEvent: (event) => {
              const meta = event.metadata ?? {};
              const isArtifactSynced =
                meta.artifact_synced === true ||
                (event.type as string) === "artifact_synced";

              if (isArtifactSynced) {
                const artifactType =
                  typeof meta.artifact_type === "string"
                    ? meta.artifact_type
                    : phase === "extraction"
                      ? "json"
                      : "jrxml";
                const versionNum =
                  typeof meta.version_num === "number"
                    ? meta.version_num
                    : undefined;
                const summary =
                  typeof meta.summary === "string" ? meta.summary : undefined;

                updateAssistant((prev) => ({
                  ...prev,
                  harness: event.harness || prev.harness,
                  syncedArtifacts: upsertSyncedArtifact(prev.syncedArtifacts, {
                    artifact_type: artifactType,
                    version_num: versionNum,
                    summary,
                  }),
                }));
                triggerProjectSync(artifactType, versionNum);
                pushToast({
                  tone: "success",
                  title: "Artefato sincronizado",
                  description: `${artifactType.toUpperCase()}${versionNum !== undefined ? ` v${versionNum}` : ""} atualizado no Studio.`,
                });
              }

              switch (event.type) {
                case "thought_delta":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    thoughts: (prev.thoughts ?? "") + (event.content ?? ""),
                  }));
                  break;

                case "text_delta":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    content: prev.content + (event.content ?? ""),
                  }));
                  break;

                case "tool_call":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    toolCalls: applyToolCallEvent(prev.toolCalls, event),
                  }));
                  break;

                case "tool_result":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    toolCalls: applyToolResultEvent(prev.toolCalls, event),
                  }));
                  break;

                case "gate_request":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    gateRequested: true,
                    gateRequestMessage: event.content || undefined,
                  }));
                  setPendingGateRequest({
                    phase,
                    message: event.content || undefined,
                  });
                  break;

                case "error":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    error: event.content || "Erro durante execução do agente.",
                  }));
                  break;

                case "done":
                  updateAssistant((prev) => ({
                    ...prev,
                    harness: event.harness || prev.harness,
                    streaming: false,
                  }));
                  break;
              }
            },
          },
        );
      } catch (err) {
        if (isAbortError(err)) {
          updateAssistant((prev) => ({
            ...prev,
            streaming: false,
            toolCalls: prev.toolCalls?.map((tc) =>
              tc.status === "running"
                ? {
                    ...tc,
                    status: "error",
                    error_message: "Execução interrompida pelo usuário.",
                  }
                : tc,
            ),
          }));
        } else {
          const message =
            err instanceof Error
              ? err.message
              : "Erro de comunicação com o agente.";
          updateAssistant((prev) => ({
            ...prev,
            streaming: false,
            error: message,
          }));
          pushToast({
            tone: "error",
            title: "Falha no streaming do agente",
            description: message,
          });
        }
      } finally {
        updateAssistant((prev) => ({ ...prev, streaming: false }));
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
        setStreaming(false);
      }
    },
    [
      isGateApproved,
      phase,
      project.id,
      pushToast,
      selectedHarness,
      streaming,
      triggerProjectSync,
    ],
  );

  const handleSubmit = useCallback(() => {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    void sendPrompt(text);
  }, [draft, sendPrompt, streaming]);

  const handleComposerKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleCancelStream = useCallback(async () => {
    setCancelling(true);
    try {
      abortControllerRef.current?.abort();
      await cancelAgentRun(project.id);
    } catch {
      // Mesmo se o servidor já tiver encerrado, o AbortController já interrompeu o cliente
    } finally {
      setCancelling(false);
      setStreaming(false);
    }
  }, [project.id]);

  const handleAuthorizeAndGenerate = useCallback(async () => {
    if (authorizingGate || streaming) return;
    setAuthorizingGate(true);
    try {
      const result = await authorizeAgentGate(project.id, { phase });
      if (result.gate) {
        setGates((prev) => {
          const exists = prev.some(
            (g) => g.gate_name === result.gate.gate_name,
          );
          return exists
            ? prev.map((g) =>
                g.gate_name === result.gate.gate_name ? result.gate : g,
              )
            : [...prev, result.gate];
        });
      }
      setPendingGateRequest(null);
      setAuthorizingGate(false);

      // Dispara imediatamente o turno de Gate 2
      await sendPrompt("Autorizado", { gateAuthorized: true });
    } catch (err) {
      setAuthorizingGate(false);
      pushToast({
        tone: "error",
        title: "Falha ao autorizar Gate",
        description: err instanceof Error ? err.message : String(err),
      });
    }
  }, [authorizingGate, phase, project.id, pushToast, sendPrompt, streaming]);

  const handleRequestAdjustments = useCallback(() => {
    composerRef.current?.focus();
  }, []);

  const handleQuickPromptClick = (promptText: string) => {
    setDraft(promptText);
    composerRef.current?.focus();
  };

  const quickPrompts = QUICK_PROMPTS_BY_PHASE[phase];

  return (
    <section
      aria-label="Painel de Chat do Agente"
      className={cn(
        "flex h-full min-h-0 flex-col bg-surface text-ink",
        className,
      )}
    >
      {/* Cabeçalho e seletor de contexto */}
      <header className="shrink-0 space-y-2.5 border-b border-border bg-surface px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0 leading-tight">
              <h2 className="truncate text-xs font-semibold tracking-tight text-ink">
                Agente Clínico IA
              </h2>
              <p className="truncate text-[11px] text-ink-muted">
                {project.name}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {pendingVisualFeedbackCount > 0 && (
              <Badge
                tone="blueprint"
                className="py-0 text-[10px] tabular-nums"
                title="Anotações visuais pendentes enviadas do Jasper Studio"
              >
                {pendingVisualFeedbackCount} ajuste
                {pendingVisualFeedbackCount > 1 ? "s" : ""}
              </Badge>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void loadChatAndStatus(project.id, phase)}
              disabled={loadingHistory || streaming}
              aria-label="Atualizar histórico do chat"
              title="Atualizar histórico e status do agente"
              className="h-7 w-7"
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", loadingHistory && "animate-spin")}
              />
            </Button>
            {onClose && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                aria-label="Fechar painel do agente"
                title="Fechar painel do agente"
                className="h-7 w-7"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* Abas de fase */}
        <Tabs
          options={PHASE_TABS}
          value={phase}
          onChange={(nextPhase) => setPhase(nextPhase)}
          className="w-full grid grid-cols-2"
        />

        {/* Seletor de Harness + Pill de Status do Gate */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span
              data-testid="harness-install-indicator"
              aria-label={
                isHarnessReady ? "Harness instalado" : "Harness não instalado"
              }
              title={
                isHarnessReady
                  ? `${activeHarnessInfo?.display_name} instalado${activeHarnessInfo?.version ? ` (${activeHarnessInfo.version})` : ""}`
                  : activeHarnessInfo?.auth_hint || "Harness não instalado"
              }
              className={cn(
                "h-2 w-2 shrink-0 rounded-full",
                isHarnessReady ? "bg-success" : "bg-danger",
              )}
            />
            <label htmlFor="agent-harness-select" className="sr-only">
              Harness de IA ativo
            </label>
            <select
              id="agent-harness-select"
              aria-label="Harness ativo"
              value={selectedHarness}
              disabled={streaming}
              onChange={(e) => {
                userSelectedHarnessRef.current = true;
                setSelectedHarness(e.target.value);
              }}
              className="h-7 rounded border border-border bg-surface-subtle px-2 text-xs font-medium text-ink focus:border-accent focus:outline-none cursor-pointer disabled:opacity-50"
            >
              {harnesses.map((h) => {
                const ready = Boolean(h.installed || h.sdk_available);
                return (
                  <option key={h.id} value={h.id}>
                    {ready ? h.display_name : `${h.display_name} (não instalado)`}
                  </option>
                );
              })}
            </select>
          </div>

          <Badge
            data-testid="gate-status-pill"
            tone={isGateApproved ? "success" : "warning"}
            dot
            className="text-[11px]"
          >
            {isGateApproved ? "Gate 2 — Autorizado" : "Gate 1 — Aguardando"}
          </Badge>
        </div>
      </header>

      {/* Timeline de mensagens */}
      <div
        role="log"
        aria-live="polite"
        aria-label="Histórico de mensagens do agente"
        className="min-h-0 flex-1 overflow-y-auto bg-canvas/50 px-3 py-3 space-y-3"
      >
        {loadingHistory && messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-ink-muted">
            Carregando histórico da fase...
          </div>
        ) : historyError && messages.length === 0 ? (
          <div className="rounded-md border border-danger/35 bg-danger-soft/60 p-3 text-xs text-danger">
            {historyError}
          </div>
        ) : messages.length === 0 ? (
          <EmptyState
            icon={<Bot className="h-5 w-5 text-accent" />}
            title={
              phase === "extraction"
                ? "Pronto para extrair a ficha clínica"
                : "Pronto para projetar o layout JRXML"
            }
            description={
              phase === "extraction"
                ? "Inicie uma análise do PDF em Gate 1 para mapear seções, perguntas e tipos do Salutem antes de gerar o JSON."
                : "Planeje o layout JasperReports em Gate 1 ou aplique anotações visuais marcadas no Jasper Studio."
            }
            className="my-4"
          />
        ) : (
          messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onNavigateSection={onNavigateSection}
            />
          ))
        )}
        <div ref={timelineEndRef} />
      </div>

      {/* Banner de aprovação rápida nos Gates */}
      {showGateBanner && (
        <GateApprovalBanner
          phase={phase}
          message={gateBannerMessage}
          authorizing={authorizingGate}
          disabled={streaming}
          onAuthorize={() => void handleAuthorizeAndGenerate()}
          onRequestAdjustments={handleRequestAdjustments}
        />
      )}

      {/* Composer inteligente */}
      <footer className="shrink-0 space-y-2 border-t border-border bg-surface p-3">
        {/* Chips de prompts rápidos por fase */}
        <div
          aria-label="Prompts rápidos"
          className="flex flex-wrap gap-1.5"
        >
          {quickPrompts.map((chip) => (
            <button
              key={chip}
              type="button"
              disabled={streaming}
              onClick={() => handleQuickPromptClick(chip)}
              className="rounded-full border border-border bg-surface-subtle px-2.5 py-0.5 text-[11px] text-ink-secondary hover:border-accent/40 hover:bg-accent-soft/60 hover:text-accent transition-colors cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed"
            >
              {chip}
            </button>
          ))}
        </div>

        <div className="space-y-1.5">
          <textarea
            ref={composerRef}
            aria-label="Mensagem para o agente"
            value={draft}
            disabled={streaming}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder={
              phase === "extraction"
                ? "Descreva ajustes ou peça a análise do PDF... (Enter envia, Shift+Enter quebra linha)"
                : "Descreva ajustes de layout JRXML ou coordenadas... (Enter envia, Shift+Enter quebra linha)"
            }
            className={cn(
              "w-full rounded-md border border-border bg-surface px-2.5 py-2 text-xs leading-relaxed text-ink placeholder:text-ink-muted/70",
              "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20",
              "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
              "min-h-[68px] max-h-40 resize-none",
            )}
          />

          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-ink-muted">
              Enter envia · Shift+Enter nova linha
            </span>

            <div className="flex items-center gap-1.5">
              {streaming ? (
                <Button
                  variant="danger"
                  size="sm"
                  loading={cancelling}
                  icon={<Square className="h-3 w-3 fill-current" />}
                  onClick={() => void handleCancelStream()}
                >
                  Interromper
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!draft.trim() || authorizingGate}
                  icon={<Send className="h-3.5 w-3.5" />}
                  onClick={handleSubmit}
                >
                  Enviar
                </Button>
              )}
            </div>
          </div>
        </div>
      </footer>
    </section>
  );
}
