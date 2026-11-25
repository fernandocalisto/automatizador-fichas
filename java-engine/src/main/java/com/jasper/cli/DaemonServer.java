package com.jasper.cli;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import net.sf.jasperreports.engine.DefaultJasperReportsContext;

import java.io.IOException;
import java.io.OutputStream;
import java.io.PrintStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Servidor HTTP local ({@code 127.0.0.1}) que mantém a JVM e o JasperReports aquecidos
 * para compilações, descompilações, inspeções e exportações de PDF em baixa latência.
 */
public final class DaemonServer {

    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);

    private final int requestedPort;
    private final PrintStream jsonOut;
    private final long startedAtNanos = System.nanoTime();
    private final CountDownLatch shutdownLatch = new CountDownLatch(1);
    private final AtomicBoolean shuttingDown = new AtomicBoolean(false);

    private volatile int boundPort = -1;

    public DaemonServer(int requestedPort, PrintStream jsonOut) {
        this.requestedPort = requestedPort;
        this.jsonOut = jsonOut;
    }

    public void runBlocking() throws CliException {
        if (requestedPort < 0 || requestedPort > 65535) {
            throw new CliException(ErrorType.INVALID_ARGUMENT,
                    "Porta inválida em --port: " + requestedPort + " (esperado 0..65535).");
        }

        HttpServer server;
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", requestedPort), 64);
        } catch (IOException e) {
            throw new CliException(ErrorType.IO_ERROR,
                    "Não foi possível iniciar o servidor HTTP local em 127.0.0.1:" + requestedPort
                            + ": " + CliException.messageOf(e), e);
        }

        AtomicInteger workerSeq = new AtomicInteger(1);
        ThreadFactory tf = runnable -> {
            Thread t = new Thread(runnable, "jasper-daemon-http-" + workerSeq.getAndIncrement());
            t.setDaemon(true);
            return t;
        };
        ExecutorService executor = Executors.newCachedThreadPool(tf);
        server.setExecutor(executor);

        server.createContext("/health", this::handleHealth);
        server.createContext("/rpc", this::handleRpc);
        server.createContext("/shutdown", this::handleShutdown);

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            if (shuttingDown.compareAndSet(false, true)) {
                shutdownLatch.countDown();
            }
        }, "jasper-daemon-shutdown-hook"));

        server.start();
        this.boundPort = server.getAddress().getPort();

        // Emite o anúncio de porta na stdout real antes de bloquear.
        jsonOut.println("{\"status\":\"LISTENING\",\"port\":" + boundPort + "}");
        jsonOut.flush();

        // Pré-aquece o contexto do JasperReports em background.
        executor.submit(() -> {
            try {
                DefaultJasperReportsContext.getInstance();
            } catch (Throwable ignored) {
                // aquecimento best-effort
            }
        });

        try {
            shutdownLatch.await();
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        } finally {
            server.stop(0);
            executor.shutdownNow();
        }
    }

    private void handleHealth(HttpExchange exchange) throws IOException {
        try {
            String method = exchange.getRequestMethod();
            if (!"GET".equalsIgnoreCase(method) && !"HEAD".equalsIgnoreCase(method)) {
                sendJson(exchange, 405, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "Método HTTP não suportado em /health: " + method + " (use GET).",
                        null).toJson());
                return;
            }
            drainRequestBody(exchange);
            long uptimeMs = (System.nanoTime() - startedAtNanos) / 1_000_000L;
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "UP");
            body.put("ok", true);
            body.put("port", boundPort);
            body.put("pid", ProcessHandle.current().pid());
            body.put("uptimeMs", uptimeMs);
            body.put("javaVersion", System.getProperty("java.version"));
            sendJson(exchange, 200, JSON.writeValueAsString(body));
        } catch (Throwable t) {
            sendJson(exchange, 500, OutputPayload.fromThrowable(t).toJson());
        }
    }

    private void handleRpc(HttpExchange exchange) throws IOException {
        try {
            String method = exchange.getRequestMethod();
            if (!"POST".equalsIgnoreCase(method)) {
                sendJson(exchange, 405, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "Método HTTP não suportado em /rpc: " + method + " (use POST).",
                        null).toJson());
                return;
            }

            byte[] rawBytes = exchange.getRequestBody().readAllBytes();
            String rawJson = new String(rawBytes, StandardCharsets.UTF_8).trim();
            if (rawJson.startsWith("\uFEFF")) {
                rawJson = rawJson.substring(1);
            }
            if (rawJson.isEmpty()) {
                sendJson(exchange, 422, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "Corpo JSON vazio na requisição POST /rpc.",
                        null).toJson());
                return;
            }

            JsonNode root;
            try {
                root = JSON.readTree(rawJson);
            } catch (JsonProcessingException e) {
                sendJson(exchange, 422, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "JSON malformado em POST /rpc: " + e.getOriginalMessage(),
                        e).toJson());
                return;
            }

            if (root == null || !root.isObject()) {
                sendJson(exchange, 422, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "O corpo de POST /rpc deve ser um objeto JSON.",
                        null).toJson());
                return;
            }

            Main opts = buildOptionsFromJson(root);
            OutputPayload payload = new CommandHandler(opts).handle();
            sendJson(exchange, 200, payload.toJson());
        } catch (Throwable t) {
            OutputPayload errPayload = OutputPayload.fromThrowable(t);
            sendJson(exchange, 422, errPayload.toJson());
        }
    }

    private void handleShutdown(HttpExchange exchange) throws IOException {
        try {
            String method = exchange.getRequestMethod();
            if (!"POST".equalsIgnoreCase(method)) {
                sendJson(exchange, 405, OutputPayload.error(
                        ErrorType.INVALID_ARGUMENT,
                        "Método HTTP não suportado em /shutdown: " + method + " (use POST).",
                        null).toJson());
                return;
            }
            drainRequestBody(exchange);
            OutputPayload ack = OutputPayload.success("shutdown").meta("stopping", true);
            sendJson(exchange, 200, ack.toJson());
        } finally {
            if (shuttingDown.compareAndSet(false, true)) {
                Thread stopper = new Thread(() -> {
                    try {
                        Thread.sleep(25L);
                    } catch (InterruptedException ignored) {
                        Thread.currentThread().interrupt();
                    }
                    shutdownLatch.countDown();
                }, "jasper-daemon-stopper");
                stopper.setDaemon(true);
                stopper.start();
            }
        }
    }

    private static Main buildOptionsFromJson(JsonNode root) throws CliException {
        Main opts = new Main();
        opts.setAction(textField(root, "action"));
        String format = textField(root, "format");
        opts.setFormat(format != null ? format : "pdf");
        opts.setInput(textField(root, "input"));
        opts.setOutput(textField(root, "output"));
        opts.setSubreportDir(firstTextField(root, "subreportDir", "subreport_dir"));
        opts.setDbUrl(firstTextField(root, "dbUrl", "db_url"));
        opts.setDbUser(firstTextField(root, "dbUser", "db_user"));
        opts.setDbPass(firstTextField(root, "dbPass", "db_pass"));
        opts.setCustomDriverJar(firstTextField(root, "customDriverJar", "custom_driver_jar"));
        opts.setCustomDriverClass(firstTextField(root, "customDriverClass", "custom_driver_class"));

        JsonNode paramsNode = root.get("params");
        if (paramsNode != null && !paramsNode.isNull()) {
            if (paramsNode.isObject()) {
                @SuppressWarnings("unchecked")
                Map<String, Object> map = JSON.convertValue(paramsNode, LinkedHashMap.class);
                opts.setParamsMap(map);
            } else if (paramsNode.isTextual()) {
                opts.setParams(paramsNode.asText());
            } else {
                throw new CliException(ErrorType.INVALID_ARGUMENT,
                        "Campo 'params' deve ser um objeto JSON ou string JSON/@arquivo.");
            }
        }

        JsonNode mockNode = root.has("mockRows") ? root.get("mockRows") : root.get("mock_rows");
        if (mockNode != null && !mockNode.isNull()) {
            if (mockNode.isArray()) {
                List<Map<String, Object>> rows = new ArrayList<>(mockNode.size());
                for (int i = 0; i < mockNode.size(); i++) {
                    JsonNode item = mockNode.get(i);
                    if (item == null || !item.isObject()) {
                        throw new CliException(ErrorType.INVALID_ARGUMENT,
                                "Cada elemento de 'mockRows' deve ser um objeto JSON (índice " + i + ").");
                    }
                    @SuppressWarnings("unchecked")
                    Map<String, Object> row = JSON.convertValue(item, LinkedHashMap.class);
                    rows.add(row);
                }
                opts.setMockRows(rows);
            } else if (mockNode.isTextual()) {
                opts.setMockData(mockNode.asText());
            } else {
                throw new CliException(ErrorType.INVALID_ARGUMENT,
                        "Campo 'mockRows' deve ser um array JSON de objetos.");
            }
        }

        return opts;
    }

    private static String firstTextField(JsonNode node, String primaryKey, String fallbackKey) {
        String val = textField(node, primaryKey);
        return val != null ? val : textField(node, fallbackKey);
    }

    private static String textField(JsonNode node, String key) {
        JsonNode child = node.get(key);
        if (child == null || child.isNull()) {
            return null;
        }
        if (child.isTextual()) {
            return child.asText();
        }
        if (child.isValueNode()) {
            return child.asText();
        }
        return null;
    }

    private static void drainRequestBody(HttpExchange exchange) {
        try {
            exchange.getRequestBody().readAllBytes();
        } catch (IOException ignored) {
            // sem efeito
        }
    }

    private static void sendJson(HttpExchange exchange, int statusCode, String jsonBody) throws IOException {
        byte[] bytes = jsonBody.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        if ("HEAD".equalsIgnoreCase(exchange.getRequestMethod())) {
            exchange.sendResponseHeaders(statusCode, -1);
            exchange.close();
            return;
        }
        exchange.sendResponseHeaders(statusCode, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
            os.flush();
        } finally {
            exchange.close();
        }
    }
}
