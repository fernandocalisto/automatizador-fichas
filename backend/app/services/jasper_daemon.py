# -*- coding: utf-8 -*-
"""
Serviço de gerenciamento do ciclo de vida e RPC aquecido do motor Java JasperReports
(`backend/app/services/jasper_daemon.py`).

Mantém um subprocesso `jasper-daemon.jar --action serve --port 0` ativo em `127.0.0.1`,
com descoberta automática do JDK, drenagem assíncrona de stdout/stderr (anti-deadlock no Windows),
healthcheck `/health`, auto-restart transparente em caso de queda da JVM e erros estruturados.
"""

from __future__ import annotations

import atexit
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any
import weakref

import httpx

try:
    from backend.app.config import JASPER_DAEMON_JAR
except ModuleNotFoundError:  # pragma: no cover
    from app.config import JASPER_DAEMON_JAR  # type: ignore[no-redef]


class JasperDaemonError(RuntimeError):
    """Exceção estruturada lançada quando o motor JasperReports retorna erro ou falha de ciclo de vida."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "UNKNOWN_ERROR",
        stack_trace_snippet: str | None = None,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.error_type = error_type or "UNKNOWN_ERROR"
        self.stack_trace_snippet = stack_trace_snippet
        self.status_code = status_code
        self.payload = dict(payload or {})
        formatted = f"[{self.error_type}] {message}" if self.error_type else message
        super().__init__(formatted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "ERROR",
            "error_type": self.error_type,
            "errorType": self.error_type,
            "message": self.message,
            "stack_trace_snippet": self.stack_trace_snippet,
            "stackTraceSnippet": self.stack_trace_snippet,
            "status_code": self.status_code,
        }


def _resolve_java_executable(explicit_java: str | Path | None = None) -> Path:
    """Localiza `java` / `java.exe` via argumento explícito, env, PATH ou diretórios padrão do JDK."""
    exe_name = "java.exe" if os.name == "nt" else "java"

    candidates: list[Path] = []
    env_bin = os.environ.get("FICHA_STUDIO_JAVA_BIN")
    if explicit_java:
        candidates.append(Path(explicit_java))
    if env_bin:
        candidates.append(Path(env_bin))

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / exe_name)

    if os.name == "nt":
        # Prioriza instalações reais de JDK antes de shims como Common Files\Oracle\Java\javapath\java.exe,
        # pois shims criam subprocesso filho separado (PID distinto e pipes órfãos em proc.kill()).
        program_files = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(r"C:\Program Files"),
        ]
        vendor_subdirs = ("Java", "Eclipse Adoptium", "Microsoft", "BellSoft", "Amazon Corretto")
        seen_roots: set[str] = set()
        for pf in program_files:
            pf_key = str(pf).lower()
            if pf_key in seen_roots or not pf.is_dir():
                continue
            seen_roots.add(pf_key)
            for vendor in vendor_subdirs:
                vendor_dir = pf / vendor
                if not vendor_dir.is_dir():
                    continue
                jdk_dirs = sorted(
                    (d for d in vendor_dir.iterdir() if d.is_dir() and "jdk" in d.name.lower()),
                    key=lambda p: p.name,
                    reverse=True,
                )
                for jdk_dir in jdk_dirs:
                    candidates.append(jdk_dir / "bin" / exe_name)

    which_java = shutil.which("java")
    if which_java:
        candidates.append(Path(which_java))

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        except OSError:
            continue

    raise JasperDaemonError(
        "Executável 'java' (JDK 11+) não encontrado no sistema. Configure JAVA_HOME ou FICHA_STUDIO_JAVA_BIN.",
        error_type="JAVA_NOT_FOUND",
    )


def _register_atexit_stop(service: JasperDaemonService) -> None:
    ref = weakref.ref(service)

    def _cleanup() -> None:
        inst = ref()
        if inst is not None:
            try:
                inst.stop()
            except Exception:
                pass

    atexit.register(_cleanup)


class JasperDaemonService:
    """Cliente e gerenciador do subprocesso HTTP aquecido `jasper-daemon.jar`."""

    def __init__(
        self,
        *,
        jar_path: str | Path | None = None,
        java_executable: str | Path | None = None,
        port: int = 0,
        startup_timeout: float = 25.0,
        request_timeout: float = 60.0,
    ) -> None:
        self.jar_path = Path(jar_path).resolve() if jar_path else JASPER_DAEMON_JAR.resolve()
        self._explicit_java = java_executable
        self.requested_port = int(port)
        self.startup_timeout = float(startup_timeout)
        self.request_timeout = float(request_timeout)

        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._port: int | None = None
        self._jvm_pid: int | None = None
        self._stderr_tail: deque[str] = deque(maxlen=120)
        self._http = httpx.Client(
            timeout=httpx.Timeout(self.request_timeout, connect=5.0),
            trust_env=False,
        )
        _register_atexit_stop(self)

    # ------------------------------------------------------------------ propriedades

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def pid(self) -> int | None:
        proc = self._process
        if proc is not None and proc.poll() is None:
            return self._jvm_pid or proc.pid
        return None

    @property
    def is_running(self) -> bool:
        proc = self._process
        return proc is not None and proc.poll() is None and self._port is not None

    def __enter__(self) -> JasperDaemonService:
        self.ensure_started()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    # ------------------------------------------------------------------ ciclo de vida

    def ensure_started(self) -> int:
        """Garante que o daemon JVM esteja rodando e saudável, iniciando ou reiniciando se necessário."""
        with self._lock:
            if self.is_running and self._probe_health_quiet():
                assert self._port is not None
                return self._port
            self._terminate_process_locked()
            return self._start_process_locked()

    def _start_process_locked(self) -> int:
        if not self.jar_path.is_file():
            raise JasperDaemonError(
                f"Arquivo JAR do motor Jasper não encontrado: {self.jar_path}",
                error_type="JAR_NOT_FOUND",
            )

        java_bin = _resolve_java_executable(self._explicit_java)
        env = os.environ.copy()
        jdk_home = java_bin.parent.parent
        if (jdk_home / "bin").is_dir():
            env.setdefault("JAVA_HOME", str(jdk_home))
            env["PATH"] = f"{java_bin.parent}{os.pathsep}{env.get('PATH', '')}"

        cmd = [
            str(java_bin),
            "-Djava.awt.headless=true",
            "-Dfile.encoding=UTF-8",
            "-jar",
            str(self.jar_path),
            "--action",
            "serve",
            "--port",
            str(self.requested_port),
        ]

        self._stderr_tail.clear()
        port_queue: queue.Queue[int | Exception] = queue.Queue(maxsize=1)

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise JasperDaemonError(
                f"Falha ao iniciar subprocesso Java ({java_bin}): {exc}",
                error_type="DAEMON_START_ERROR",
            ) from exc

        self._process = proc

        def _stdout_reader() -> None:
            assert proc.stdout is not None
            announced = False
            try:
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if not announced:
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(data, dict) and data.get("status") == "LISTENING" and "port" in data:
                            announced = True
                            port_queue.put(int(data["port"]))
                        elif isinstance(data, dict) and data.get("status") == "ERROR":
                            announced = True
                            port_queue.put(
                                JasperDaemonError(
                                    str(data.get("message") or "Falha ao iniciar jasper-daemon."),
                                    error_type=str(data.get("errorType") or "DAEMON_START_ERROR"),
                                    stack_trace_snippet=data.get("stackTraceSnippet"),
                                    payload=data,
                                )
                            )
            except Exception as exc:  # pragma: no cover
                if not announced:
                    port_queue.put(exc)

        def _stderr_reader() -> None:
            assert proc.stderr is not None
            try:
                for raw_line in proc.stderr:
                    stripped = raw_line.rstrip("\r\n")
                    if stripped:
                        self._stderr_tail.append(stripped)
            except Exception:  # pragma: no cover
                pass

        threading.Thread(target=_stdout_reader, name="jasper-daemon-stdout", daemon=True).start()
        threading.Thread(target=_stderr_reader, name="jasper-daemon-stderr", daemon=True).start()

        deadline = time.monotonic() + self.startup_timeout
        bound_port: int | None = None
        while time.monotonic() < deadline:
            try:
                item = port_queue.get(timeout=0.1)
                if isinstance(item, JasperDaemonError):
                    self._terminate_process_locked()
                    raise item
                if isinstance(item, Exception):
                    self._terminate_process_locked()
                    raise JasperDaemonError(
                        f"Erro ao ler porta de escuta do jasper-daemon: {item}",
                        error_type="DAEMON_START_ERROR",
                    ) from item
                bound_port = item
                break
            except queue.Empty:
                if proc.poll() is not None:
                    stderr_dump = "\n".join(self._stderr_tail)
                    rc = proc.returncode
                    self._terminate_process_locked()
                    raise JasperDaemonError(
                        f"jasper-daemon encerrou prematuramente (exit code {rc}). {stderr_dump}".strip(),
                        error_type="DAEMON_START_ERROR",
                    )

        if bound_port is None:
            stderr_dump = "\n".join(self._stderr_tail)
            self._terminate_process_locked()
            raise JasperDaemonError(
                f"Timeout ({self.startup_timeout}s) aguardando jasper-daemon anunciar porta. {stderr_dump}".strip(),
                error_type="DAEMON_TIMEOUT",
            )

        self._port = bound_port
        if not self._wait_until_healthy(timeout=5.0):
            stderr_dump = "\n".join(self._stderr_tail)
            self._terminate_process_locked()
            raise JasperDaemonError(
                f"jasper-daemon iniciou na porta {bound_port}, mas falhou no healthcheck /health. {stderr_dump}".strip(),
                error_type="DAEMON_UNHEALTHY",
            )

        return bound_port

    def _wait_until_healthy(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._probe_health_quiet():
                return True
            if self._process is not None and self._process.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def _probe_health_quiet(self) -> bool:
        if self._port is None or self._process is None or self._process.poll() is not None:
            return False
        try:
            resp = self._http.get(f"http://127.0.0.1:{self._port}/health", timeout=2.0)
            if resp.status_code != 200:
                return False
            data = resp.json()
            if isinstance(data, dict) and data.get("status") == "UP":
                if isinstance(data.get("pid"), int):
                    self._jvm_pid = int(data["pid"])
                return True
            return False
        except Exception:
            return False

    def _terminate_process_locked(self) -> None:
        proc = self._process
        port = self._port
        self._process = None
        self._port = None
        self._jvm_pid = None

        if proc is None:
            return

        if proc.poll() is None and port is not None:
            try:
                self._http.post(f"http://127.0.0.1:{port}/shutdown", timeout=1.5)
            except Exception:
                pass

        if proc.poll() is None:
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass

        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def stop(self) -> None:
        """Encerra o subprocesso JVM do daemon de forma limpa."""
        with self._lock:
            self._terminate_process_locked()

    # ------------------------------------------------------------------ HTTP / RPC

    def health(self, *, auto_start: bool = True) -> dict[str, Any]:
        """Consulta `GET /health` no daemon (iniciando/reiniciando automaticamente se `auto_start=True`)."""
        if not auto_start:
            with self._lock:
                if not self.is_running:
                    return {"status": "DOWN", "ok": False}
                port = self._port
        else:
            port = self.ensure_started()

        try:
            resp = self._http.get(f"http://127.0.0.1:{port}/health", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data
            raise JasperDaemonError("Resposta inesperada em /health.", error_type="PROTOCOL_ERROR")
        except JasperDaemonError:
            raise
        except Exception as exc:
            if not auto_start:
                return {"status": "DOWN", "ok": False, "error": str(exc)}
            with self._lock:
                self._terminate_process_locked()
                port = self._start_process_locked()
            resp = self._http.get(f"http://127.0.0.1:{port}/health", timeout=5.0)
            resp.raise_for_status()
            return dict(resp.json())

    def _rpc(self, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        effective_timeout = timeout if timeout is not None else self.request_timeout
        port = self.ensure_started()

        try:
            resp = self._http.post(
                f"http://127.0.0.1:{port}/rpc",
                json=payload,
                timeout=effective_timeout,
            )
        except httpx.TransportError as exc:
            # Se a JVM caiu no meio ou a conexão local quebrou, reinicia 1x e repete a chamada.
            with self._lock:
                if not self._probe_health_quiet():
                    self._terminate_process_locked()
                    port = self._start_process_locked()
                else:
                    raise JasperDaemonError(
                        f"Falha de transporte ao chamar jasper-daemon: {exc}",
                        error_type="TRANSPORT_ERROR",
                    ) from exc
            try:
                resp = self._http.post(
                    f"http://127.0.0.1:{port}/rpc",
                    json=payload,
                    timeout=effective_timeout,
                )
            except httpx.HTTPError as retry_exc:
                raise JasperDaemonError(
                    f"Falha ao comunicar com jasper-daemon após reinício: {retry_exc}",
                    error_type="DAEMON_UNAVAILABLE",
                ) from retry_exc

        try:
            body = resp.json()
        except ValueError as exc:
            raise JasperDaemonError(
                f"Resposta não-JSON do jasper-daemon (HTTP {resp.status_code}): {resp.text[:400]}",
                error_type="PROTOCOL_ERROR",
                status_code=resp.status_code,
            ) from exc

        if not isinstance(body, dict):
            raise JasperDaemonError(
                f"Formato JSON inválido retornado pelo jasper-daemon (HTTP {resp.status_code}).",
                error_type="PROTOCOL_ERROR",
                status_code=resp.status_code,
            )

        if resp.status_code == 200 and body.get("status") == "SUCCESS":
            return body

        raise JasperDaemonError(
            str(body.get("message") or f"Erro retornado pelo jasper-daemon (HTTP {resp.status_code})."),
            error_type=str(body.get("errorType") or "UNKNOWN_ERROR"),
            stack_trace_snippet=body.get("stackTraceSnippet"),
            status_code=resp.status_code,
            payload=body,
        )

    # ------------------------------------------------------------------ ações de negócio

    def compile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Compila um arquivo `.jrxml` em `.jasper` usando a JVM aquecida."""
        req: dict[str, Any] = {
            "action": "compile",
            "input": str(Path(input_path).resolve()),
        }
        if output_path is not None:
            req["output"] = str(Path(output_path).resolve())
        if subreport_dir is not None:
            req["subreportDir"] = str(Path(subreport_dir).resolve())
        return self._rpc(req)

    def decompile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Descompila um arquivo `.jasper` reconstruindo o `.jrxml` em UTF-8."""
        req: dict[str, Any] = {
            "action": "decompile",
            "input": str(Path(input_path).resolve()),
        }
        if output_path is not None:
            req["output"] = str(Path(output_path).resolve())
        if subreport_dir is not None:
            req["subreportDir"] = str(Path(subreport_dir).resolve())
        return self._rpc(req)

    def export_pdf(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        params: dict[str, Any] | None = None,
        mock_rows: list[dict[str, Any]] | None = None,
        subreport_dir: str | Path | None = None,
        db_url: str | None = None,
        db_user: str | None = None,
        db_pass: str | None = None,
        custom_driver_jar: str | Path | None = None,
        custom_driver_class: str | None = None,
    ) -> dict[str, Any]:
        """Compila (se `.jrxml`), preenche (via JDBC, `mock_rows` ou vazio) e exporta para PDF."""
        req: dict[str, Any] = {
            "action": "export",
            "format": "pdf",
            "input": str(Path(input_path).resolve()),
        }
        if output_path is not None:
            req["output"] = str(Path(output_path).resolve())
        if params is not None:
            req["params"] = params
        if mock_rows is not None:
            req["mockRows"] = mock_rows
        if subreport_dir is not None:
            req["subreportDir"] = str(Path(subreport_dir).resolve())
        if db_url:
            req["dbUrl"] = db_url
        if db_user is not None:
            req["dbUser"] = db_user
        if db_pass is not None:
            req["dbPass"] = db_pass
        if custom_driver_jar is not None:
            req["customDriverJar"] = str(Path(custom_driver_jar).resolve())
        if custom_driver_class is not None:
            req["customDriverClass"] = custom_driver_class
        return self._rpc(req)

    def inspect_params(
        self,
        input_path: str | Path,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Inspeciona parâmetros, campos e SQL declarados em um `.jrxml` ou `.jasper`."""
        req: dict[str, Any] = {
            "action": "inspect-params",
            "input": str(Path(input_path).resolve()),
        }
        if subreport_dir is not None:
            req["subreportDir"] = str(Path(subreport_dir).resolve())
        return self._rpc(req)

    def inspect_query(
        self,
        input_path: str | Path,
        *,
        db_url: str,
        db_user: str | None = None,
        db_pass: str | None = None,
        params: dict[str, Any] | None = None,
        custom_driver_jar: str | Path | None = None,
        custom_driver_class: str | None = None,
    ) -> dict[str, Any]:
        """Executa a query do relatório sem varrer linhas para extrair metadados JDBC das colunas."""
        req: dict[str, Any] = {
            "action": "inspect-query",
            "input": str(Path(input_path).resolve()),
            "dbUrl": db_url,
        }
        if db_user is not None:
            req["dbUser"] = db_user
        if db_pass is not None:
            req["dbPass"] = db_pass
        if params is not None:
            req["params"] = params
        if custom_driver_jar is not None:
            req["customDriverJar"] = str(Path(custom_driver_jar).resolve())
        if custom_driver_class is not None:
            req["customDriverClass"] = custom_driver_class
        return self._rpc(req)

    def test_connection(
        self,
        db_url: str,
        db_user: str | None = None,
        db_pass: str | None = None,
        *,
        custom_driver_jar: str | Path | None = None,
        custom_driver_class: str | None = None,
    ) -> dict[str, Any]:
        """Testa conectividade JDBC e retorna latência e metadados do banco."""
        req: dict[str, Any] = {
            "action": "test-conn",
            "dbUrl": db_url,
        }
        if db_user is not None:
            req["dbUser"] = db_user
        if db_pass is not None:
            req["dbPass"] = db_pass
        if custom_driver_jar is not None:
            req["customDriverJar"] = str(Path(custom_driver_jar).resolve())
        if custom_driver_class is not None:
            req["customDriverClass"] = custom_driver_class
        return self._rpc(req)


_singleton_lock = threading.Lock()
_default_daemon: JasperDaemonService | None = None


def get_jasper_daemon() -> JasperDaemonService:
    """Retorna a instância singleton compartilhada do `JasperDaemonService`."""
    global _default_daemon
    if _default_daemon is None:
        with _singleton_lock:
            if _default_daemon is None:
                _default_daemon = JasperDaemonService()
    return _default_daemon


__all__ = [
    "JasperDaemonError",
    "JasperDaemonService",
    "get_jasper_daemon",
]
