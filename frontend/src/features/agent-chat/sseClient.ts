import { ApiError } from "@/lib/api";
import type {
  AgentSessionRead,
  ChatMessageRead,
  ChatPhase,
  ChatRole,
  GateApprovalRead,
  GateName,
  HarnessStatus,
} from "@/types/studio";

export type AgentEventType =
  | "text_delta"
  | "thought_delta"
  | "tool_call"
  | "tool_result"
  | "gate_request"
  | "error"
  | "done";

export interface AgentStreamEvent {
  type: AgentEventType;
  content?: string;
  tool_name?: string | null;
  tool_call_id?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_output?: unknown;
  harness?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentStatusResponse {
  project_id: string;
  active_run: boolean;
  preferred_harness: string;
  harnesses: HarnessStatus[];
  gates: GateApprovalRead[];
  sessions?: AgentSessionRead[];
  pending_visual_feedback_count: number;
}

export type ToolCallStatus = "running" | "done" | "error";

export interface ToolCallRecord {
  id: string;
  tool_call_id?: string | null;
  tool_name: string;
  status: ToolCallStatus;
  tool_args?: Record<string, unknown> | null;
  tool_output?: unknown;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SyncedArtifactInfo {
  artifact_type: string;
  version_num?: number;
  summary?: string;
}

export interface ChatTimelineItem {
  id: string;
  role: ChatRole;
  phase: ChatPhase;
  content: string;
  createdAt: string;
  harness?: string | null;
  model?: string | null;
  thoughts?: string;
  toolCalls?: ToolCallRecord[];
  syncedArtifacts?: SyncedArtifactInfo[];
  gateRequested?: boolean;
  gateRequestMessage?: string;
  error?: string | null;
  streaming?: boolean;
  metadata?: Record<string, unknown>;
}

export interface AgentStreamRequestPayload {
  phase: ChatPhase;
  prompt: string;
  harness_id?: string;
  model?: string;
  effort?: string;
  gate_authorized?: boolean;
  timeout_seconds?: number;
}

export interface AuthorizeGateRequestPayload {
  phase: ChatPhase;
  notes?: string;
}

export interface AuthorizeGateResponse {
  ok: boolean;
  gate: GateApprovalRead;
  message: ChatMessageRead;
}

export interface CancelAgentResponse {
  ok: boolean;
  cancelled: boolean;
}

export interface StreamAgentOptions {
  signal?: AbortSignal;
  onEvent: (event: AgentStreamEvent) => void;
  onParseError?: (rawData: string, error: unknown) => void;
}

export const CANONICAL_HARNESSES: HarnessStatus[] = [
  {
    id: "agy",
    display_name: "AGY",
    installed: false,
    executable_path: null,
    sdk_available: false,
    version: null,
    auth_hint: "Verifique a instalação do Antigravity CLI (agy).",
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
    auth_hint: "Verifique a instalação do OpenCode CLI.",
    supports_vision: true,
    supports_mcp: true,
  },
  {
    id: "claude",
    display_name: "Claude Code",
    installed: false,
    executable_path: null,
    sdk_available: false,
    version: null,
    auth_hint: "Verifique a instalação do Claude Code CLI.",
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
    auth_hint: "Verifique a instalação do Codex CLI.",
    supports_vision: true,
    supports_mcp: true,
  },
];

export function phaseToGateName(phase: ChatPhase): GateName {
  return phase === "extraction" ? "gate1_json" : "gate3_jrxml";
}

export function getHarnessLabel(harnessId?: string | null): string {
  switch (harnessId) {
    case "agy":
      return "AGY";
    case "opencode":
      return "OpenCode";
    case "claude":
      return "Claude Code";
    case "codex":
      return "Codex";
    default:
      return harnessId ? harnessId.toUpperCase() : "Agente";
  }
}

const VALID_EVENT_TYPES = new Set<AgentEventType>([
  "text_delta",
  "thought_delta",
  "tool_call",
  "tool_result",
  "gate_request",
  "error",
  "done",
]);

function normalizeEventType(
  rawType: unknown,
  sseEventName?: string,
): AgentEventType {
  if (
    typeof rawType === "string" &&
    VALID_EVENT_TYPES.has(rawType as AgentEventType)
  ) {
    return rawType as AgentEventType;
  }
  if (
    sseEventName &&
    VALID_EVENT_TYPES.has(sseEventName as AgentEventType)
  ) {
    return sseEventName as AgentEventType;
  }
  return "text_delta";
}

export interface SseEventParser {
  feed: (chunk: string) => AgentStreamEvent[];
  flush: () => AgentStreamEvent[];
}

/**
 * Parser incremental de Server-Sent Events (`text/event-stream`).
 * Suporta chunks partidos arbitrariamente (inclusive no meio de linhas ou `\r\n`),
 * múltiplos eventos em um mesmo chunk e múltiplas linhas `data:`.
 */
export function createSseParser(
  onParseError?: (rawData: string, error: unknown) => void,
): SseEventParser {
  let buffer = "";

  const parseBlock = (block: string): AgentStreamEvent | null => {
    const lines = block.split("\n");
    let eventName: string | undefined;
    const dataLines: string[] = [];

    for (const rawLine of lines) {
      if (!rawLine || rawLine.startsWith(":")) {
        continue;
      }
      const colonIdx = rawLine.indexOf(":");
      const field = colonIdx === -1 ? rawLine : rawLine.slice(0, colonIdx);
      let value = colonIdx === -1 ? "" : rawLine.slice(colonIdx + 1);
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }

      if (field === "event") {
        eventName = value.trim();
      } else if (field === "data") {
        dataLines.push(value);
      }
    }

    if (dataLines.length === 0) {
      return null;
    }

    const rawData = dataLines.join("\n").trim();
    if (!rawData || rawData === "[DONE]") {
      return rawData === "[DONE]" ? { type: "done", content: "" } : null;
    }

    try {
      const parsed = JSON.parse(rawData) as Record<string, unknown>;
      const type = normalizeEventType(parsed.type, eventName);
      const metadata =
        parsed.metadata && typeof parsed.metadata === "object" && !Array.isArray(parsed.metadata)
          ? (parsed.metadata as Record<string, unknown>)
          : {};

      return {
        type,
        content: typeof parsed.content === "string" ? parsed.content : "",
        tool_name: typeof parsed.tool_name === "string" ? parsed.tool_name : null,
        tool_call_id:
          typeof parsed.tool_call_id === "string" ? parsed.tool_call_id : null,
        tool_args:
          parsed.tool_args && typeof parsed.tool_args === "object" && !Array.isArray(parsed.tool_args)
            ? (parsed.tool_args as Record<string, unknown>)
            : null,
        tool_output: parsed.tool_output,
        harness: typeof parsed.harness === "string" ? parsed.harness : null,
        metadata,
      };
    } catch (err) {
      onParseError?.(rawData, err);
      return {
        type: "error",
        content: `Falha ao interpretar evento SSE: ${err instanceof Error ? err.message : String(err)}`,
        metadata: { raw_data: rawData, parse_error: true },
      };
    }
  };

  const drainCompleteBlocks = (): AgentStreamEvent[] => {
    const events: AgentStreamEvent[] = [];
    // Normaliza CRLF e CR isolados sem quebrar um \r solto no final do chunk
    let normalized = buffer.replace(/\r\n/g, "\n");
    let trailingCr = false;
    if (normalized.endsWith("\r")) {
      trailingCr = true;
      normalized = normalized.slice(0, -1);
    }
    normalized = normalized.replace(/\r/g, "\n");

    let separatorIdx = normalized.indexOf("\n\n");
    while (separatorIdx !== -1) {
      const block = normalized.slice(0, separatorIdx);
      normalized = normalized.slice(separatorIdx + 2);
      const event = parseBlock(block);
      if (event) {
        events.push(event);
      }
      separatorIdx = normalized.indexOf("\n\n");
    }

    buffer = trailingCr ? `${normalized}\r` : normalized;
    return events;
  };

  return {
    feed(chunk: string): AgentStreamEvent[] {
      if (!chunk) return [];
      buffer += chunk;
      return drainCompleteBlocks();
    },
    flush(): AgentStreamEvent[] {
      if (!buffer.trim()) {
        buffer = "";
        return [];
      }
      const remaining = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      buffer = "";
      const events: AgentStreamEvent[] = [];
      for (const block of remaining.split("\n\n")) {
        if (!block.trim()) continue;
        const event = parseBlock(block);
        if (event) {
          events.push(event);
        }
      }
      return events;
    },
  };
}

async function parseErrorResponse(response: Response): Promise<ApiError> {
  let detail: unknown = undefined;
  let message = `HTTP ${response.status} ${response.statusText}`.trim();
  try {
    const payload = await response.json();
    detail = payload?.detail ?? payload;
    if (typeof payload?.detail === "string") {
      message = payload.detail;
    } else if (Array.isArray(payload?.detail)) {
      message = payload.detail
        .map((item: { msg?: string }) => item.msg || JSON.stringify(item))
        .join("; ");
    } else if (typeof payload?.message === "string") {
      message = payload.message;
    }
  } catch {
    const text = await response.text().catch(() => "");
    if (text) {
      message = text;
    }
  }
  return new ApiError(response.status, message, detail);
}

export async function fetchAgentStatus(
  projectId: string,
  signal?: AbortSignal,
): Promise<AgentStatusResponse> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/status`,
    { signal },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as AgentStatusResponse;
}

export async function authorizeAgentGate(
  projectId: string,
  payload: AuthorizeGateRequestPayload,
): Promise<AuthorizeGateResponse> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/authorize-gate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as AuthorizeGateResponse;
}

export async function cancelAgentRun(
  projectId: string,
): Promise<CancelAgentResponse> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as CancelAgentResponse;
}

export async function fetchAgentSessions(
  projectId: string,
  signal?: AbortSignal,
): Promise<AgentSessionRead[]> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/sessions`,
    { signal },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as AgentSessionRead[];
}

export async function resetAgentSession(
  projectId: string,
  opts?: { phase?: ChatPhase; harnessId?: string },
): Promise<{ ok: boolean; deleted: number }> {
  const params = new URLSearchParams();
  if (opts?.phase) params.set("phase", opts.phase);
  if (opts?.harnessId) params.set("harness_id", opts.harnessId);
  const qs = params.toString();
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/session${qs ? `?${qs}` : ""}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as { ok: boolean; deleted: number };
}

export function isAbortError(err: unknown): boolean {
  return (
    err instanceof Error &&
    (err.name === "AbortError" ||
      err.message.toLowerCase().includes("aborted"))
  );
}

/**
 * Executa um turno em streaming via SSE (`POST /api/projects/{project_id}/agent/stream`).
 * Suporta `ReadableStream` nativo e fallback para `string`/`Uint8Array`/`response.text()`
 * em ambientes de teste (Vitest/jsdom).
 */
export async function streamAgentTurn(
  projectId: string,
  payload: AgentStreamRequestPayload,
  options: StreamAgentOptions,
): Promise<void> {
  const { signal, onEvent, onParseError } = options;

  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/agent/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
      signal,
    },
  );

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  const parser = createSseParser(onParseError);
  const emitAll = (events: AgentStreamEvent[]) => {
    for (const ev of events) {
      if (signal?.aborted) return;
      onEvent(ev);
    }
  };

  const body = response.body as unknown;

  if (
    body &&
    typeof body === "object" &&
    "getReader" in body &&
    typeof (body as ReadableStream<Uint8Array | string>).getReader === "function"
  ) {
    const reader = (body as ReadableStream<Uint8Array | string>).getReader();
    const decoder = new TextDecoder("utf-8");

    const onAbort = () => {
      void reader.cancel().catch(() => {});
    };
    signal?.addEventListener("abort", onAbort, { once: true });

    try {
      while (true) {
        if (signal?.aborted) {
          break;
        }
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        if (value === undefined || value === null) {
          continue;
        }
        const text =
          typeof value === "string"
            ? value
            : decoder.decode(value, { stream: true });
        emitAll(parser.feed(text));
      }
      if (!signal?.aborted) {
        const tail = decoder.decode();
        if (tail) {
          emitAll(parser.feed(tail));
        }
        emitAll(parser.flush());
      }
    } finally {
      signal?.removeEventListener("abort", onAbort);
      try {
        reader.releaseLock();
      } catch {
        // Ignora caso o reader já tenha sido liberado
      }
    }
    return;
  }

  if (typeof body === "string") {
    emitAll(parser.feed(body));
    emitAll(parser.flush());
    return;
  }

  if (body instanceof Uint8Array) {
    const text = new TextDecoder("utf-8").decode(body);
    emitAll(parser.feed(text));
    emitAll(parser.flush());
    return;
  }

  const fallbackText = await response.text();
  if (!signal?.aborted) {
    emitAll(parser.feed(fallbackText));
    emitAll(parser.flush());
  }
}

export function isToolOutputError(
  output: unknown,
  metadata?: Record<string, unknown>,
): boolean {
  if (metadata?.is_error === true || metadata?.error) {
    return true;
  }
  if (output && typeof output === "object" && !Array.isArray(output)) {
    const obj = output as Record<string, unknown>;
    if (obj.ok === false) return true;
    if (typeof obj.error === "string" && obj.error.trim().length > 0) {
      return true;
    }
  }
  return false;
}

export function normalizePersistedChatMessage(
  msg: ChatMessageRead,
): ChatTimelineItem {
  const meta = (msg.metadata ?? {}) as Record<string, unknown>;
  const thoughts = typeof meta.thoughts === "string" ? meta.thoughts : "";

  const rawToolCalls = Array.isArray(meta.tool_calls) ? meta.tool_calls : [];
  const toolCalls: ToolCallRecord[] = rawToolCalls.map((raw, idx) => {
    const item =
      raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
    const toolName =
      typeof item.tool_name === "string"
        ? item.tool_name
        : typeof item.name === "string"
          ? item.name
          : "ferramenta";
    const toolOutput = item.tool_output ?? item.output ?? item.result;
    const itemMeta =
      item.metadata && typeof item.metadata === "object"
        ? (item.metadata as Record<string, unknown>)
        : undefined;
    const errored =
      item.status === "error" || isToolOutputError(toolOutput, itemMeta);

    return {
      id:
        typeof item.tool_call_id === "string" && item.tool_call_id
          ? item.tool_call_id
          : `persisted-${msg.id}-tool-${idx}`,
      tool_call_id:
        typeof item.tool_call_id === "string" ? item.tool_call_id : null,
      tool_name: toolName,
      status: errored ? "error" : "done",
      tool_args:
        item.tool_args && typeof item.tool_args === "object"
          ? (item.tool_args as Record<string, unknown>)
          : item.args && typeof item.args === "object"
            ? (item.args as Record<string, unknown>)
            : null,
      tool_output: toolOutput,
      error_message:
        typeof item.error === "string"
          ? item.error
          : typeof item.error_message === "string"
            ? item.error_message
            : null,
      metadata: itemMeta,
    };
  });

  const rawSynced = Array.isArray(meta.synced_artifacts)
    ? meta.synced_artifacts
    : [];
  const syncedArtifacts: SyncedArtifactInfo[] = rawSynced
    .filter((entry): entry is Record<string, unknown> =>
      Boolean(entry && typeof entry === "object"),
    )
    .map((entry) => ({
      artifact_type:
        typeof entry.artifact_type === "string"
          ? entry.artifact_type
          : typeof entry.type === "string"
            ? entry.type
            : msg.phase === "extraction"
              ? "json"
              : "jrxml",
      version_num:
        typeof entry.version_num === "number" ? entry.version_num : undefined,
      summary: typeof entry.summary === "string" ? entry.summary : undefined,
    }));

  if (meta.artifact_synced === true && syncedArtifacts.length === 0) {
    syncedArtifacts.push({
      artifact_type:
        typeof meta.artifact_type === "string"
          ? meta.artifact_type
          : msg.phase === "extraction"
            ? "json"
            : "jrxml",
      version_num:
        typeof meta.version_num === "number" ? meta.version_num : undefined,
    });
  }

  const persistedModel =
    typeof meta.model === "string" && meta.model.trim()
      ? meta.model.trim()
      : typeof meta.resolved_model === "string" && meta.resolved_model.trim()
        ? meta.resolved_model.trim()
        : null;

  return {
    id: `msg-${msg.id}`,
    role: msg.role,
    phase: msg.phase,
    content: msg.content,
    createdAt: msg.created_at,
    harness: typeof meta.harness === "string" ? meta.harness : null,
    model: persistedModel,
    thoughts: thoughts || undefined,
    toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
    syncedArtifacts: syncedArtifacts.length > 0 ? syncedArtifacts : undefined,
    gateRequested: meta.gate_requested === true,
    gateRequestMessage:
      typeof meta.gate_request_message === "string"
        ? meta.gate_request_message
        : undefined,
    metadata: meta,
  };
}
