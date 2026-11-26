import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import {
  createSseParser,
  streamAgentTurn,
  type AgentStreamEvent,
} from "./sseClient";

function encodeChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe("createSseParser", () => {
  it("faz parse incremental de chunks partidos no meio de linhas, CRLF e JSON", () => {
    const parser = createSseParser();
    const collected: AgentStreamEvent[] = [];

    const chunks = [
      "event: thought_del",
      'ta\r\ndata: {"type":"thought_delta","con',
      'tent":"Analisando PDF..."}\r',
      "\n\r\nevent: text_delta\ndata: ",
      '{"type":"text_delta","content":"Olá, "}\n\n',
      'event: text_delta\ndata: {"type":"text_delta","content":"clínica!"}\n\n',
    ];

    for (const chunk of chunks) {
      collected.push(...parser.feed(chunk));
    }
    collected.push(...parser.flush());

    expect(collected).toHaveLength(3);
    expect(collected[0]).toMatchObject({
      type: "thought_delta",
      content: "Analisando PDF...",
    });
    expect(collected[1]).toMatchObject({
      type: "text_delta",
      content: "Olá, ",
    });
    expect(collected[2]).toMatchObject({
      type: "text_delta",
      content: "clínica!",
    });
  });

  it("interpreta múltiplos eventos em um mesmo chunk, ignora comentários e suporta flush final", () => {
    const parser = createSseParser();
    const singleChunk = [
      ": heartbeat comment",
      "",
      'event: tool_call\ndata: {"type":"tool_call","tool_name":"inspect_clinical_pdf","tool_call_id":"tc-1","tool_args":{"page":1}}',
      "",
      'event: tool_result\ndata: {"type":"tool_result","tool_name":"inspect_clinical_pdf","tool_call_id":"tc-1","tool_output":{"ok":true,"pages":2}}',
      "",
      // Evento final sem \n\n terminal para testar flush()
      'event: done\ndata: {"type":"done","content":""}',
    ].join("\n");

    const fed = parser.feed(singleChunk);
    expect(fed).toHaveLength(2);
    expect(fed[0]).toMatchObject({
      type: "tool_call",
      tool_name: "inspect_clinical_pdf",
      tool_call_id: "tc-1",
      tool_args: { page: 1 },
    });
    expect(fed[1]).toMatchObject({
      type: "tool_result",
      tool_call_id: "tc-1",
      tool_output: { ok: true, pages: 2 },
    });

    const flushed = parser.flush();
    expect(flushed).toHaveLength(1);
    expect(flushed[0].type).toBe("done");
  });

  it("emite evento de erro quando encontra JSON malformado sem interromper eventos subsequentes", () => {
    const onParseError = vi.fn();
    const parser = createSseParser(onParseError);

    const events = parser.feed(
      'event: text_delta\ndata: {json-quebrado\n\nevent: done\ndata: {"type":"done","content":""}\n\n',
    );

    expect(onParseError).toHaveBeenCalledTimes(1);
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("error");
    expect(events[0].metadata?.parse_error).toBe(true);
    expect(events[1].type).toBe("done");
  });
});

describe("streamAgentTurn", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("consome ReadableStream em chunks e dispara onEvent na ordem correta", async () => {
    const sseStream = encodeChunks([
      'event: thought_delta\ndata: {"type":"thought_delta","content":"Lendo geometria"}\n\n',
      'event: text_delta\ndata: {"type":"text_delta","content":"Resumo pronto"}\n\n',
      'event: done\ndata: {"type":"done","content":""}\n\n',
    ]);

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(sseStream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );

    const received: AgentStreamEvent[] = [];
    await streamAgentTurn(
      "proj-1",
      { phase: "extraction", prompt: "Analisar PDF", harness_id: "agy" },
      { onEvent: (ev) => received.push(ev) },
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/projects/proj-1/agent/stream",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        }),
      }),
    );
    expect(received.map((e) => e.type)).toEqual([
      "thought_delta",
      "text_delta",
      "done",
    ]);
  });

  it("usa fallback quando response.body não expõe getReader (ex.: mock com text())", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      statusText: "OK",
      body: null,
      text: async () =>
        'event: text_delta\ndata: {"type":"text_delta","content":"Via fallback"}\n\nevent: done\ndata: {"type":"done"}\n\n',
    } as unknown as Response;

    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse);

    const received: AgentStreamEvent[] = [];
    await streamAgentTurn(
      "proj-fallback",
      { phase: "jrxml", prompt: "Planejar layout" },
      { onEvent: (ev) => received.push(ev) },
    );

    expect(received).toHaveLength(2);
    expect(received[0].content).toBe("Via fallback");
    expect(received[1].type).toBe("done");
  });

  it("lança ApiError detalhado quando o servidor responde com erro HTTP", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Harness 'desconhecido' inválido" }), {
        status: 400,
        statusText: "Bad Request",
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      streamAgentTurn(
        "proj-1",
        { phase: "extraction", prompt: "Teste", harness_id: "desconhecido" },
        { onEvent: vi.fn() },
      ),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      message: "Harness 'desconhecido' inválido",
    } satisfies Partial<ApiError>);
  });

  it("interrompe a leitura imediatamente quando AbortController é acionado", async () => {
    const encoder = new TextEncoder();
    const controller = new AbortController();

    const stream = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(
          encoder.encode(
            'event: text_delta\ndata: {"type":"text_delta","content":"Parte 1"}\n\n',
          ),
        );
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const received: AgentStreamEvent[] = [];
    await streamAgentTurn(
      "proj-abort",
      { phase: "extraction", prompt: "Executar longo" },
      {
        signal: controller.signal,
        onEvent: (ev) => {
          received.push(ev);
          controller.abort();
        },
      },
    );

    expect(received).toHaveLength(1);
    expect(received[0].content).toBe("Parte 1");
  });
});
