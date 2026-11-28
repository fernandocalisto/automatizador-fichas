# -*- coding: utf-8 -*-
"""Adaptador Google Antigravity (AGY) com suporte primário ao Python SDK e fallback CLI."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.app.harnesses.base import (
    STUDIO_MCP_TOOL_NAMES,
    BaseSubprocessHarness,
    SubprocessChunk,
    SubprocessRunner,
    build_studio_mcp_server_spec,
    compose_delta_system_prompt,
    default_subprocess_runner,
)
from backend.app.harnesses.types import (
    VALID_EFFORT_LEVELS,
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
)

AGY_MODELS_CACHE_TTL_SECONDS: float = 300.0
AGY_PERSISTENT_IDLE_TTL_SECONDS: float = 600.0
AGY_EFFORT_LEVELS: tuple[str, ...] = VALID_EFFORT_LEVELS

PoolKey = tuple[str, bool, str, str]


def _extract_model_from_payload(
    obj: dict[str, Any],
    nested: dict[str, Any] | None = None,
) -> str | None:
    """Extrai o identificador de modelo de eventos JSON `init`, `step_update` ou `result`."""
    candidates: list[Any] = []
    if isinstance(nested, dict):
        candidates.extend(
            [
                nested.get("resolved_model"),
                nested.get("model"),
                nested.get("model_id"),
                nested.get("modelName"),
            ]
        )
        usage = nested.get("usage")
        if isinstance(usage, dict):
            candidates.extend([usage.get("model"), usage.get("model_id")])
        meta = nested.get("metadata")
        if isinstance(meta, dict):
            candidates.extend([meta.get("model"), meta.get("model_id")])
    candidates.extend(
        [
            obj.get("resolved_model"),
            obj.get("model"),
            obj.get("model_id"),
            obj.get("modelName"),
        ]
    )
    for val in candidates:
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


@dataclass
class AgyWarmSession:
    """Subprocesso `agy` persistente mantido aquecido entre turnos via NDJSON stdio."""

    key: PoolKey
    proc: Any
    lock: asyncio.Lock
    loop: asyncio.AbstractEventLoop
    last_used_monotonic: float
    turn_count: int = 0
    conversation_id: str | None = None
    stderr_lines: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    stderr_task: asyncio.Task[None] | None = None

    def is_alive(self) -> bool:
        return getattr(self.proc, "returncode", None) is None


class AgyPersistentSessionPool:
    """
    Pool thread/asyncio-safe de subprocessos `agy --input-format stream-json --output-format stream-json`
    mantidos aquecidos por `(workspace_dir, gate_authorized, model, effort)`, eliminando a latência
    de cold-start (~10s) entre turnos consecutivos.
    """

    def __init__(
        self,
        *,
        idle_ttl_seconds: float = AGY_PERSISTENT_IDLE_TTL_SECONDS,
        process_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._idle_ttl_seconds = float(idle_ttl_seconds)
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._clock = clock or time.monotonic
        self._guard = threading.Lock()
        self._sessions: dict[PoolKey, AgyWarmSession] = {}

    @staticmethod
    def make_key(
        workspace_dir: Path | str,
        *,
        gate_authorized: bool,
        model: str | None = None,
        effort: str | None = None,
    ) -> PoolKey:
        return (
            str(Path(workspace_dir).resolve()),
            bool(gate_authorized),
            (model or "").strip(),
            (effort or "").strip().lower(),
        )

    def _is_expired(self, session: AgyWarmSession, now: float) -> bool:
        return (now - session.last_used_monotonic) > self._idle_ttl_seconds

    @staticmethod
    def _is_compatible_for_request(
        session: AgyWarmSession,
        *,
        loop: asyncio.AbstractEventLoop,
        resume_session_id: str | None,
    ) -> bool:
        if not session.is_alive() or session.loop is not loop or session.loop.is_closed():
            return False
        if resume_session_id:
            return session.conversation_id == resume_session_id
        # Sem resume_session_id: só reutiliza se ainda estiver pré-aquecido (turn_count == 0)
        return session.turn_count == 0 and session.conversation_id is None

    def has_warm_turn_session(
        self,
        key: PoolKey,
        *,
        resume_session_id: str | None = None,
    ) -> bool:
        """Retorna True se existe processo aquecido pronto para turno #2+ compatível."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        now = self._clock()
        with self._guard:
            session = self._sessions.get(key)
        if session is None or not session.is_alive() or self._is_expired(session, now):
            return False
        if loop is not None and session.loop is not loop:
            return False
        if session.turn_count < 1:
            return False
        if resume_session_id and session.conversation_id and session.conversation_id != resume_session_id:
            return False
        return True

    def active_count(self) -> int:
        with self._guard:
            return sum(1 for s in self._sessions.values() if s.is_alive())

    async def _terminate_session(self, session: AgyWarmSession) -> None:
        if session.stderr_task is not None and not session.stderr_task.done():
            session.stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await session.stderr_task

        stdin = getattr(session.proc, "stdin", None)
        if stdin is not None:
            with contextlib.suppress(Exception):
                stdin.close()

        if session.is_alive():
            with contextlib.suppress(ProcessLookupError, OSError, Exception):
                session.proc.kill()
            wait_fn = getattr(session.proc, "wait", None)
            if callable(wait_fn):
                with contextlib.suppress(TimeoutError, Exception):
                    async with asyncio.timeout(2.0):
                        await wait_fn()

    async def _spawn_session(
        self,
        key: PoolKey,
        cmd: Sequence[str],
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
        resume_session_id: str | None = None,
    ) -> AgyWarmSession:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        cwd_path = Path(cwd).resolve()
        cwd_path.mkdir(parents=True, exist_ok=True)

        proc = await self._process_factory(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd_path),
            env=merged_env,
            limit=4 * 1024 * 1024,
        )
        loop = asyncio.get_running_loop()
        session = AgyWarmSession(
            key=key,
            proc=proc,
            lock=asyncio.Lock(),
            loop=loop,
            last_used_monotonic=self._clock(),
            turn_count=0,
            conversation_id=resume_session_id,
        )

        async def _pump_stderr() -> None:
            reader = getattr(proc, "stderr", None)
            if reader is None:
                return
            try:
                while True:
                    raw = await reader.readline()
                    if not raw:
                        break
                    decoded = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if decoded.strip():
                        session.stderr_lines.append(decoded.strip())
            except asyncio.CancelledError:
                raise
            except Exception:
                return

        session.stderr_task = asyncio.create_task(_pump_stderr())
        return session

    async def evict_expired(self) -> int:
        """Remove e encerra sessões ociosas além do TTL ou já finalizadas."""
        now = self._clock()
        stale: list[AgyWarmSession] = []
        with self._guard:
            for k in list(self._sessions.keys()):
                sess = self._sessions[k]
                if not sess.is_alive() or sess.loop.is_closed() or self._is_expired(sess, now):
                    stale.append(self._sessions.pop(k))
        for sess in stale:
            await self._terminate_session(sess)
        return len(stale)

    async def _remove_if_same(self, key: PoolKey, session: AgyWarmSession) -> None:
        with self._guard:
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)
        await self._terminate_session(session)

    async def warmup(
        self,
        key: PoolKey,
        cmd: Sequence[str],
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
        resume_session_id: str | None = None,
    ) -> tuple[AgyWarmSession, bool]:
        """
        Garante um processo `agy` aquecido para `key`.
        Retorna `(session, already_warm)`.
        """
        await self.evict_expired()
        loop = asyncio.get_running_loop()
        old_to_close: AgyWarmSession | None = None

        with self._guard:
            existing = self._sessions.get(key)
            if existing is not None:
                if self._is_compatible_for_request(
                    existing, loop=loop, resume_session_id=resume_session_id
                ):
                    existing.last_used_monotonic = self._clock()
                    return existing, True
                old_to_close = self._sessions.pop(key)

        if old_to_close is not None:
            await self._terminate_session(old_to_close)

        session = await self._spawn_session(
            key,
            cmd,
            cwd,
            env=env,
            resume_session_id=resume_session_id,
        )
        with self._guard:
            replaced = self._sessions.get(key)
            self._sessions[key] = session
        if replaced is not None and replaced is not session:
            await self._terminate_session(replaced)
        return session, False

    async def run_turn(
        self,
        key: PoolKey,
        cmd: Sequence[str],
        cwd: Path,
        stdin_line: bytes,
        *,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = 300.0,
        resume_session_id: str | None = None,
    ) -> AsyncIterator[SubprocessChunk]:
        """
        Envia 1 linha NDJSON ao processo `agy` aquecido (sem fechar `stdin`) e faz streaming
        de stdout até o evento `result` (ou EOF/erro). Recria automaticamente o processo caso
        esteja morto, expirado, incompatível ou falhe durante o turno.
        """
        session, _ = await self.warmup(
            key,
            cmd,
            cwd,
            env=env,
            resume_session_id=resume_session_id,
        )

        unhealthy = False
        async with session.lock:
            if not session.is_alive():
                await self._remove_if_same(key, session)
                session = await self._spawn_session(
                    key,
                    cmd,
                    cwd,
                    env=env,
                    resume_session_id=resume_session_id,
                )
                with self._guard:
                    self._sessions[key] = session

            session.stderr_lines.clear()
            payload = stdin_line if stdin_line.endswith(b"\n") else stdin_line + b"\n"
            try:
                if session.proc.stdin is None or session.proc.stdout is None:
                    raise RuntimeError("Processo AGY persistente sem pipes stdin/stdout ativos.")

                session.proc.stdin.write(payload)
                await session.proc.stdin.drain()

                async with asyncio.timeout(timeout_seconds):
                    while True:
                        raw_line = await session.proc.stdout.readline()
                        if not raw_line:
                            # EOF antes do evento result -> processo encerrou
                            unhealthy = True
                            for err_line in list(session.stderr_lines):
                                yield SubprocessChunk(stream="stderr", line=err_line)
                            rc = await session.proc.wait()
                            yield SubprocessChunk(stream="exit", returncode=rc)
                            break

                        decoded = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        yield SubprocessChunk(stream="stdout", line=decoded)

                        stripped = decoded.strip()
                        if stripped.startswith("{") and stripped.endswith("}"):
                            try:
                                obj = json.loads(stripped)
                            except json.JSONDecodeError:
                                obj = None
                            if isinstance(obj, dict):
                                ev_name = obj.get("event")
                                if ev_name == "init" and obj.get("conversation_id"):
                                    session.conversation_id = str(obj["conversation_id"])
                                elif ev_name == "result":
                                    res = obj.get("result")
                                    if isinstance(res, dict):
                                        if res.get("conversation_id"):
                                            session.conversation_id = str(res["conversation_id"])
                                        status_val = str(res.get("status") or "SUCCESS").upper()
                                        if status_val != "SUCCESS":
                                            unhealthy = True
                                    break
                                elif ev_name in ("error", "permission_request", "approval_request"):
                                    unhealthy = True
                                    break

                if not unhealthy and session.is_alive():
                    session.turn_count += 1
                    session.last_used_monotonic = self._clock()
                else:
                    unhealthy = True
            except BaseException:
                unhealthy = True
                await self._remove_if_same(key, session)
                raise

        if unhealthy:
            await self._remove_if_same(key, session)

    async def close_workspace(self, workspace_dir: Path | str) -> int:
        """Encerra todos os processos aquecidos vinculados a um diretório de workspace."""
        target_ws = str(Path(workspace_dir).resolve())
        to_close: list[AgyWarmSession] = []
        with self._guard:
            for k in list(self._sessions.keys()):
                if k[0] == target_ws:
                    to_close.append(self._sessions.pop(k))
        for sess in to_close:
            await self._terminate_session(sess)
        return len(to_close)

    async def shutdown_all(self) -> int:
        """Encerra de forma limpa todos os processos `agy` persistentes do pool."""
        with self._guard:
            to_close = list(self._sessions.values())
            self._sessions.clear()
        for sess in to_close:
            await self._terminate_session(sess)
        return len(to_close)


_DEFAULT_AGY_SESSION_POOL: AgyPersistentSessionPool | None = None


def get_agy_session_pool() -> AgyPersistentSessionPool:
    """Retorna o pool singleton global de sessões persistentes do AGY CLI."""
    global _DEFAULT_AGY_SESSION_POOL
    if _DEFAULT_AGY_SESSION_POOL is None:
        _DEFAULT_AGY_SESSION_POOL = AgyPersistentSessionPool()
    return _DEFAULT_AGY_SESSION_POOL


class AgyHarness(BaseSubprocessHarness):
    """
    Adaptador oficial do Google Antigravity (`agy`).

    Modo primário: `google-antigravity` Python SDK (`google.antigravity`), fazendo streaming
    concorrente de `response` (texto), `response.thoughts` (raciocínio) e `response.tool_calls`.
    Modo fallback: executável CLI `agy` (no PATH ou `%LOCALAPPDATA%/agy/bin/agy.exe` no Windows).
    """

    kind = HarnessKind.AGY
    display_name = "Google Antigravity (AGY)"

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        sdk_spec_finder: Callable[[str], Any] | None = None,
        sdk_importer: Callable[[str], ModuleType | Any] | None = None,
        local_appdata_dir: str | Path | None = None,
        default_timeout: float = 300.0,
        dangerously_skip_permissions: bool | None = None,
        session_pool: AgyPersistentSessionPool | None = None,
        models_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
        models_cache_ttl: float = AGY_MODELS_CACHE_TTL_SECONDS,
    ) -> None:
        super().__init__(
            runner=runner,
            which_resolver=which_resolver,
            default_timeout=default_timeout,
        )
        self._sdk_spec_finder = sdk_spec_finder or importlib.util.find_spec
        self._sdk_importer = sdk_importer or importlib.import_module
        self._local_appdata_dir = local_appdata_dir
        self._session_pool = session_pool
        self._models_runner = models_runner
        self._models_cache_ttl = float(models_cache_ttl)
        self._models_cache_lock = threading.Lock()
        self._models_cache: list[dict[str, str]] | None = None
        self._models_cache_ts: float = 0.0
        if dangerously_skip_permissions is None:
            env_val = os.environ.get("AGY_SKIP_PERMISSIONS", "1").strip().lower()
            self._dangerously_skip_permissions = env_val not in ("0", "false", "no", "off")
        else:
            self._dangerously_skip_permissions = bool(dangerously_skip_permissions)

    def _get_session_pool(self) -> AgyPersistentSessionPool:
        return self._session_pool if self._session_pool is not None else get_agy_session_pool()

    def _should_use_persistent_pool(self) -> bool:
        if self._runner is not default_subprocess_runner:
            return False
        env_val = os.environ.get("AGY_PERSISTENT_SESSION", "1").strip().lower()
        return env_val not in ("0", "false", "no", "off")

    @staticmethod
    def _parse_models_output(raw_stdout: str) -> list[dict[str, str]]:
        """Converte a saída stdout de `agy models` (`<id>\\t<label>`) em lista estruturada."""
        models: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_line in (raw_stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "\t" in line:
                left, right = line.split("\t", 1)
                model_id = left.strip()
                label = right.strip() or model_id
            else:
                # Ignora mensagens de log/status com espaços sem tabulação
                if " " in line or line.endswith("..."):
                    continue
                model_id = line
                label = line
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append({"id": model_id, "label": label})
        return models

    def list_models(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        """
        Lista os modelos disponíveis no `agy` CLI (`agy models`) com cache em memória de 5 minutos
        e fallback seguro para lista vazia em caso de indisponibilidade ou erro.
        """
        now = time.monotonic()
        if not force_refresh:
            with self._models_cache_lock:
                if (
                    self._models_cache is not None
                    and (now - self._models_cache_ts) < self._models_cache_ttl
                ):
                    return [dict(item) for item in self._models_cache]

        exe = self._find_cli_executable()
        if not exe:
            return []

        try:
            if self._models_runner is not None:
                completed = self._models_runner([exe, "models"])
            else:
                completed = subprocess.run(
                    [exe, "models"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15.0,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError):
            return []

        if completed.returncode != 0 and not (completed.stdout or "").strip():
            return []

        parsed = self._parse_models_output(completed.stdout or "")
        if completed.returncode == 0 or parsed:
            with self._models_cache_lock:
                self._models_cache = list(parsed)
                self._models_cache_ts = time.monotonic()
        return [dict(item) for item in parsed]

    def has_warm_session(
        self,
        workspace_dir: Path | str,
        *,
        gate_authorized: bool,
        model: str | None = None,
        effort: str | None = None,
        resume_session_id: str | None = None,
    ) -> bool:
        """Indica se há um processo persistente aquecido no turno #2+ para esta configuração."""
        if not self._should_use_persistent_pool():
            return False
        key = AgyPersistentSessionPool.make_key(
            workspace_dir,
            gate_authorized=gate_authorized,
            model=model,
            effort=effort,
        )
        return self._get_session_pool().has_warm_turn_session(
            key, resume_session_id=resume_session_id
        )

    async def warmup(
        self,
        workspace_dir: Path,
        *,
        phase: str = "jrxml",
        gate_authorized: bool = False,
        model: str | None = None,
        effort: str | None = None,
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Pré-aquece um subprocesso `agy` persistente para o workspace/configuração informados."""
        if not self._should_use_persistent_pool():
            return {"warmed": False, "already_warm": False, "reason": "persistent_session_disabled"}
        if self.is_sdk_available():
            return {"warmed": False, "already_warm": False, "reason": "sdk_mode_active"}
        exe = self._find_cli_executable()
        if not exe:
            return {"warmed": False, "already_warm": False, "reason": "agy_cli_not_found"}

        ws_path = Path(workspace_dir).resolve()
        self.ensure_workspace_mcp_config(ws_path)
        dummy_req = HarnessRunRequest(
            workspace_dir=ws_path,
            phase="extraction" if phase == "extraction" else "jrxml",
            prompt="warmup",
            gate_authorized=gate_authorized,
            model=model,
            effort=effort,
            resume_session_id=resume_session_id,
        )
        cmd = self.build_cli_command(exe, dummy_req, persistent=True)
        key = AgyPersistentSessionPool.make_key(
            ws_path,
            gate_authorized=gate_authorized,
            model=dummy_req.model,
            effort=dummy_req.effort,
        )
        _, already_warm = await self._get_session_pool().warmup(
            key,
            cmd,
            ws_path,
            resume_session_id=resume_session_id,
        )
        return {"warmed": True, "already_warm": already_warm}

    async def close_workspace_sessions(self, workspace_dir: Path | str) -> int:
        """Encerra processos persistentes aquecidos pertencentes a um workspace."""
        return await self._get_session_pool().close_workspace(workspace_dir)

    def is_sdk_available(self) -> bool:
        """Verifica dinamicamente se o pacote `google.antigravity` está instalado."""
        try:
            return self._sdk_spec_finder("google.antigravity") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _candidate_windows_paths(self) -> list[Path]:
        raw_appdata = (
            str(self._local_appdata_dir)
            if self._local_appdata_dir is not None
            else os.environ.get("LOCALAPPDATA", "")
        )
        if not raw_appdata:
            return []
        base = Path(raw_appdata)
        return [
            base / "agy" / "bin" / "agy.exe",
            base / "Programs" / "Antigravity" / "bin" / "agy.exe",
        ]

    def _find_cli_executable(self) -> str | None:
        return self._resolve_executable("agy", fallback_paths=self._candidate_windows_paths())

    def check_status(self) -> HarnessStatus:
        sdk_ok = self.is_sdk_available()
        exe = self._find_cli_executable()
        version = self._probe_version(exe) if exe else None

        if version is None and sdk_ok:
            try:
                mod = self._sdk_importer("google.antigravity")
                version = getattr(mod, "__version__", None) or "sdk"
            except Exception:
                version = "sdk"

        return HarnessStatus(
            id=self.kind,
            display_name=self.display_name,
            installed=bool(sdk_ok or exe),
            executable_path=exe,
            sdk_available=sdk_ok,
            version=version,
            auth_hint="Execute 'agy' no terminal para autenticar ou instale 'pip install google-antigravity'.",
            supports_vision=True,
            supports_mcp=True,
        )

    async def _stream_via_sdk(
        self,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Executa o turno usando `Agent`, `LocalAgentConfig` e `CapabilitiesConfig` do SDK."""
        mod = self._sdk_importer("google.antigravity")
        agent_cls = getattr(mod, "Agent")
        config_cls = getattr(mod, "LocalAgentConfig")
        caps_cls = getattr(mod, "CapabilitiesConfig")

        cfg_kwargs: dict[str, Any] = {
            "system_instructions": system_prompt,
            "capabilities": caps_cls(),
        }
        try:
            sig = inspect.signature(config_cls)
            params = sig.parameters
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if request.model and ("model" in params or accepts_var_kw):
                cfg_kwargs["model"] = request.model
            if request.effort and ("effort" in params or accepts_var_kw):
                cfg_kwargs["effort"] = request.effort
            if "cwd" in params:
                cfg_kwargs["cwd"] = str(request.workspace_dir.resolve())
            elif "workspace_dir" in params:
                cfg_kwargs["workspace_dir"] = str(request.workspace_dir.resolve())
        except (TypeError, ValueError):
            pass

        config = config_cls(**cfg_kwargs)

        sdk_session_id: str | None = None
        sdk_resolved_model: str | None = None
        async with asyncio.timeout(request.timeout_seconds):
            async with agent_cls(config) as agent:
                response = await agent.chat(user_prompt)
                raw_sid = (
                    getattr(response, "conversation_id", None)
                    or getattr(response, "session_id", None)
                    or getattr(agent, "conversation_id", None)
                    or getattr(agent, "session_id", None)
                )
                if raw_sid:
                    sdk_session_id = str(raw_sid)
                raw_sdk_model = (
                    getattr(response, "model", None)
                    or getattr(agent, "model", None)
                    or request.model
                )
                if raw_sdk_model:
                    sdk_resolved_model = str(raw_sdk_model)

                queue: asyncio.Queue[HarnessEvent | BaseException | None] = asyncio.Queue()

                async def _consume_tokens() -> None:
                    try:
                        async for token in response:
                            if token:
                                await queue.put(
                                    HarnessEvent(
                                        type=EventType.TEXT_DELTA,
                                        content=str(token),
                                        harness=self.kind,
                                    )
                                )
                    except BaseException as exc:
                        await queue.put(exc)

                async def _consume_thoughts() -> None:
                    thoughts_iter = getattr(response, "thoughts", None)
                    if thoughts_iter is None:
                        return
                    try:
                        async for thought in thoughts_iter:
                            if thought:
                                await queue.put(
                                    HarnessEvent(
                                        type=EventType.THOUGHT_DELTA,
                                        content=str(thought),
                                        harness=self.kind,
                                    )
                                )
                    except BaseException as exc:
                        await queue.put(exc)

                async def _consume_tool_calls() -> None:
                    calls_iter = getattr(response, "tool_calls", None)
                    if calls_iter is None:
                        return
                    try:
                        async for call in calls_iter:
                            raw_args = getattr(call, "args", None)
                            tool_args = (
                                dict(raw_args)
                                if isinstance(raw_args, dict)
                                else ({"value": raw_args} if raw_args is not None else {})
                            )
                            await queue.put(
                                HarnessEvent(
                                    type=EventType.TOOL_CALL,
                                    tool_name=str(getattr(call, "name", "tool")),
                                    tool_call_id=getattr(call, "id", None),
                                    tool_args=tool_args,
                                    harness=self.kind,
                                )
                            )
                    except BaseException as exc:
                        await queue.put(exc)

                tasks = [
                    asyncio.create_task(_consume_thoughts()),
                    asyncio.create_task(_consume_tool_calls()),
                    asyncio.create_task(_consume_tokens()),
                ]

                async def _join_streams() -> None:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await queue.put(None)

                join_task = asyncio.create_task(_join_streams())
                try:
                    while True:
                        item = await queue.get()
                        if item is None:
                            break
                        if isinstance(item, BaseException):
                            raise item
                        yield item
                finally:
                    for t in (*tasks, join_task):
                        if not t.done():
                            t.cancel()

        gate_ev = self._make_gate_event_if_needed(request)
        if gate_ev is not None:
            yield gate_ev
        sdk_meta: dict[str, Any] = {"mode": "sdk"}
        if sdk_session_id:
            sdk_meta["session_id"] = sdk_session_id
            sdk_meta["conversation_id"] = sdk_session_id
        if sdk_resolved_model:
            sdk_meta["resolved_model"] = sdk_resolved_model
            sdk_meta["model"] = sdk_resolved_model
        yield HarnessEvent(
            type=EventType.DONE,
            harness=self.kind,
            metadata=sdk_meta,
        )

    @staticmethod
    def ensure_workspace_mcp_config(workspace_dir: Path) -> Path | None:
        """
        Materializa o plugin de workspace `.agents/plugins/salutem/` com `plugin.json` e
        `mcp_config.json` (chave `studio` -> namespace limpo `salutem_studio`) apontando
        para o servidor MCP stdio nativo do Studio (`python -m backend.app.mcp_tools.mcp_server`),
        com todas as 8 ferramentas explicitamente habilitadas (`disabled: false`, `disabledTools: []`).
        """
        try:
            ws_root = Path(workspace_dir).resolve()
            plugins_root = ws_root / ".agents" / "plugins"
            # Remove pasta legada com nome duplicado (salutem-ficha-studio_salutem-ficha-studio)
            legacy_plugin_dir = plugins_root / "salutem-ficha-studio"
            if legacy_plugin_dir.is_dir():
                shutil.rmtree(legacy_plugin_dir, ignore_errors=True)

            plugin_dir = plugins_root / "salutem"
            plugin_dir.mkdir(parents=True, exist_ok=True)

            plugin_manifest_path = plugin_dir / "plugin.json"
            plugin_manifest_text = json.dumps(
                {"name": "salutem"},
                ensure_ascii=False,
                indent=2,
            ) + "\n"
            if (
                not plugin_manifest_path.is_file()
                or plugin_manifest_path.read_text(encoding="utf-8") != plugin_manifest_text
            ):
                plugin_manifest_path.write_text(plugin_manifest_text, encoding="utf-8")

            spec = build_studio_mcp_server_spec()
            mcp_config_path = plugin_dir / "mcp_config.json"
            mcp_payload = {
                "mcpServers": {
                    "studio": {
                        "command": spec["command"],
                        "args": spec["args"],
                        "env": spec["env"],
                        "disabled": False,
                        "disabledTools": [],
                        "alwaysAllow": list(STUDIO_MCP_TOOL_NAMES),
                    }
                }
            }
            mcp_text = json.dumps(mcp_payload, ensure_ascii=False, indent=2) + "\n"
            if (
                not mcp_config_path.is_file()
                or mcp_config_path.read_text(encoding="utf-8") != mcp_text
            ):
                mcp_config_path.write_text(mcp_text, encoding="utf-8")

            return mcp_config_path
        except OSError:
            return None

    def build_cli_command(
        self,
        executable: str,
        request: HarnessRunRequest,
        *,
        persistent: bool = False,
    ) -> list[str]:
        """Constrói o comando oficial headless/streaming do `agy` CLI (`--input-format stream-json`)."""
        cmd: list[str] = [
            executable,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--add-dir",
            str(request.workspace_dir.resolve()),
            "--mode",
            "accept-edits" if request.gate_authorized else "plan",
        ]
        if self._dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if request.resume_session_id:
            cmd.extend(["--conversation", request.resume_session_id])
        if request.model:
            cmd.extend(["--model", request.model])
        if request.effort:
            cmd.extend(["--effort", request.effort])
        if not persistent and request.timeout_seconds and request.timeout_seconds > 0:
            cmd.extend(["--print-timeout", f"{max(1, int(request.timeout_seconds))}s"])
        return cmd

    def _parse_cli_line(
        self,
        line: str,
        state: dict[str, Any] | None = None,
    ) -> list[HarnessEvent]:
        """
        Converte uma linha stdout do `agy` CLI em `HarnessEvent`s normalizados.

        Suporta:
        1. Protocolo oficial `agy --output-format stream-json` (`init`, `step_update`, `result`);
        2. Envelopes JSON simples (`{"type": "text"|"thought"|"tool_call"|"tool_result"|"error"}`);
        3. Fallback de texto plano.
        """
        stripped = line.strip()
        if not stripped:
            return []

        if state is None:
            state = {}
        emitted_tool_steps: set[str] = state.setdefault("emitted_tool_steps", set())
        emitted_tool_results: set[str] = state.setdefault("emitted_tool_results", set())
        emitted_step_text: set[str] = state.setdefault("emitted_step_text", set())
        tool_names_by_id: dict[str, str] = state.setdefault("tool_names_by_id", {})

        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                obj = None

            if isinstance(obj, dict):
                # 1) Formato oficial agy --output-format stream-json
                event_name = obj.get("event")
                if isinstance(event_name, str):
                    if event_name == "init":
                        conv_id = obj.get("conversation_id")
                        if conv_id:
                            state["conversation_id"] = str(conv_id)
                        init_model = _extract_model_from_payload(
                            obj, obj.get("init") if isinstance(obj.get("init"), dict) else None
                        )
                        if init_model:
                            state["model"] = init_model
                        return []

                    if event_name == "step_update":
                        su = obj.get("step_update")
                        if not isinstance(su, dict):
                            return []
                        if su.get("conversation_id"):
                            state["conversation_id"] = str(su["conversation_id"])
                        su_model = _extract_model_from_payload(obj, su)
                        if su_model:
                            state["model"] = su_model

                        step_type = str(su.get("step_type") or "")
                        step_state = str(su.get("state") or "")
                        step_state_upper = step_state.strip().upper()
                        step_index = su.get("step_index")
                        call_id = (
                            f"agy-step-{step_index}"
                            if step_index is not None
                            else str(su.get("id") or "agy-step")
                        )
                        events: list[HarnessEvent] = []

                        # Pensamento / raciocínio incremental
                        thought_val = su.get("thought_delta") or su.get("thinking_delta")
                        if thought_val:
                            events.append(
                                HarnessEvent(
                                    type=EventType.THOUGHT_DELTA,
                                    content=str(thought_val),
                                    harness=self.kind,
                                )
                            )
                        elif step_type in ("thinking", "thought") and su.get("text_delta"):
                            events.append(
                                HarnessEvent(
                                    type=EventType.THOUGHT_DELTA,
                                    content=str(su["text_delta"]),
                                    harness=self.kind,
                                )
                            )

                        # Texto de resposta do agente
                        if step_type == "agent_response":
                            if su.get("text_delta"):
                                state["emitted_text"] = True
                                emitted_step_text.add(call_id)
                                events.append(
                                    HarnessEvent(
                                        type=EventType.TEXT_DELTA,
                                        content=str(su["text_delta"]),
                                        harness=self.kind,
                                    )
                                )
                            elif (
                                step_state_upper in ("DONE", "COMPLETED", "SUCCESS")
                                and call_id not in emitted_step_text
                            ):
                                full_text = su.get("text") or su.get("response")
                                if full_text:
                                    state["emitted_text"] = True
                                    emitted_step_text.add(call_id)
                                    events.append(
                                        HarnessEvent(
                                            type=EventType.TEXT_DELTA,
                                            content=str(full_text),
                                            harness=self.kind,
                                        )
                                    )

                        # Chamadas e resultados de ferramenta
                        if step_type in ("tool", "tool_call", "tool_use", "mcp_tool", "mcp_tool_call"):
                            tool_info = su.get("tool_info")
                            info = tool_info if isinstance(tool_info, dict) else {}
                            tool_name = str(
                                info.get("name")
                                or su.get("tool_name")
                                or tool_names_by_id.get(call_id)
                                or "tool"
                            )
                            tool_names_by_id[call_id] = tool_name
                            params = info.get("parameters")
                            if params is None:
                                params = info.get("arguments")
                            tool_args = (
                                dict(params)
                                if isinstance(params, dict)
                                else ({"value": params} if params is not None else {})
                            )

                            if call_id not in emitted_tool_steps:
                                emitted_tool_steps.add(call_id)
                                events.append(
                                    HarnessEvent(
                                        type=EventType.TOOL_CALL,
                                        tool_name=tool_name,
                                        tool_call_id=call_id,
                                        tool_args=tool_args,
                                        harness=self.kind,
                                    )
                                )

                            success_states = {"DONE", "COMPLETED", "SUCCESS"}
                            error_states = {
                                "ERROR",
                                "FAILED",
                                "CANCELLED",
                                "CANCELED",
                                "REJECTED",
                                "DENIED",
                                "BLOCKED",
                                "TIMEOUT",
                                "ABORTED",
                            }
                            has_payload = any(
                                k in info for k in ("output", "result", "error")
                            ) or any(k in su for k in ("output", "result", "error"))

                            if (
                                call_id not in emitted_tool_results
                                and (
                                    step_state_upper in success_states
                                    or step_state_upper in error_states
                                )
                            ):
                                tool_err = (
                                    info.get("error")
                                    if "error" in info
                                    else su.get("error")
                                )
                                if step_state_upper in error_states and tool_err is None:
                                    tool_err = (
                                        f"Ferramenta '{tool_name}' encerrada com estado "
                                        f"{step_state_upper}."
                                    )
                                if "output" in info:
                                    tool_out = info.get("output")
                                elif "result" in info:
                                    tool_out = info.get("result")
                                elif "output" in su:
                                    tool_out = su.get("output")
                                elif "result" in su:
                                    tool_out = su.get("result")
                                else:
                                    tool_out = tool_err if tool_err is not None else ""

                                res_meta: dict[str, Any] = {}
                                if step_state_upper:
                                    res_meta["state"] = step_state_upper
                                if tool_err is not None:
                                    res_meta["error"] = (
                                        tool_err.get("message")
                                        if isinstance(tool_err, dict)
                                        else str(tool_err)
                                    )

                                if has_payload or step_state_upper in (success_states | error_states):
                                    emitted_tool_results.add(call_id)
                                    events.append(
                                        HarnessEvent(
                                            type=EventType.TOOL_RESULT,
                                            tool_name=tool_name,
                                            tool_call_id=call_id,
                                            tool_output=tool_out,
                                            harness=self.kind,
                                            metadata=res_meta,
                                        )
                                    )

                        return events

                    if event_name == "result":
                        state["saw_result"] = True
                        res = obj.get("result")
                        if not isinstance(res, dict):
                            res_model_top = _extract_model_from_payload(obj, None)
                            if res_model_top:
                                state["model"] = res_model_top
                            return []
                        if res.get("conversation_id"):
                            state["conversation_id"] = str(res["conversation_id"])
                        if isinstance(res.get("usage"), dict):
                            state["usage"] = dict(res["usage"])
                        res_model = _extract_model_from_payload(obj, res)
                        if res_model:
                            state["model"] = res_model

                        status_val = str(res.get("status") or "SUCCESS").upper()
                        if status_val != "SUCCESS":
                            err_msg = str(
                                res.get("error")
                                or f"AGY CLI encerrou com status {status_val}."
                            )
                            return [
                                HarnessEvent(
                                    type=EventType.ERROR,
                                    content=err_msg,
                                    harness=self.kind,
                                    metadata={"status": status_val},
                                )
                            ]

                        response_text = res.get("response")
                        if response_text and not state.get("emitted_text"):
                            state["emitted_text"] = True
                            return [
                                HarnessEvent(
                                    type=EventType.TEXT_DELTA,
                                    content=str(response_text),
                                    harness=self.kind,
                                )
                            ]
                        return []

                    if event_name in ("error", "permission_request", "approval_request"):
                        detail = (
                            obj.get("message")
                            or obj.get("error")
                            or f"AGY CLI emitiu evento '{event_name}' sem suporte interativo."
                        )
                        if isinstance(detail, dict):
                            detail = detail.get("message") or json.dumps(detail, ensure_ascii=False)
                        return [
                            HarnessEvent(
                                type=EventType.ERROR,
                                content=str(detail),
                                harness=self.kind,
                                metadata={"event": event_name},
                            )
                        ]

                # 2) Formato JSON flat (retrocompatibilidade / adapters auxiliares)
                if "type" in obj:
                    ev_type = str(obj["type"])
                    if ev_type in ("text", "text_delta", "message"):
                        state["emitted_text"] = True
                        return [
                            HarnessEvent(
                                type=EventType.TEXT_DELTA,
                                content=str(obj.get("content") or obj.get("text") or ""),
                                harness=self.kind,
                            )
                        ]
                    if ev_type in ("thought", "thought_delta", "thinking", "reasoning"):
                        return [
                            HarnessEvent(
                                type=EventType.THOUGHT_DELTA,
                                content=str(obj.get("content") or obj.get("text") or ""),
                                harness=self.kind,
                            )
                        ]
                    if ev_type in ("tool_call", "tool_use"):
                        return [
                            HarnessEvent(
                                type=EventType.TOOL_CALL,
                                tool_name=str(obj.get("name") or obj.get("tool_name") or "tool"),
                                tool_call_id=obj.get("id"),
                                tool_args=obj.get("args") or obj.get("input") or {},
                                harness=self.kind,
                            )
                        ]
                    if ev_type == "tool_result":
                        return [
                            HarnessEvent(
                                type=EventType.TOOL_RESULT,
                                tool_name=obj.get("name") or obj.get("tool_name"),
                                tool_call_id=obj.get("id"),
                                tool_output=obj.get("output") or obj.get("content"),
                                harness=self.kind,
                            )
                        ]
                    if ev_type == "error":
                        return [
                            HarnessEvent(
                                type=EventType.ERROR,
                                content=str(obj.get("message") or obj.get("content") or "Erro AGY CLI"),
                                harness=self.kind,
                            )
                        ]

        return [
            HarnessEvent(
                type=EventType.TEXT_DELTA,
                content=line + "\n",
                harness=self.kind,
            )
        ]

    async def _stream_via_cli(
        self,
        executable: str,
        request: HarnessRunRequest,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Executa o turno via binário CLI `agy` em modo headless `--input-format stream-json --output-format stream-json`."""
        self.ensure_workspace_mcp_config(request.workspace_dir)
        use_persistent = self._should_use_persistent_pool()

        effective_system_prompt = system_prompt
        pool_key: PoolKey | None = None
        if use_persistent:
            pool_key = AgyPersistentSessionPool.make_key(
                request.workspace_dir,
                gate_authorized=request.gate_authorized,
                model=request.model,
                effort=request.effort,
            )
            if (
                request.system_prompt_override is None
                and self._get_session_pool().has_warm_turn_session(
                    pool_key, resume_session_id=request.resume_session_id
                )
            ):
                effective_system_prompt = compose_delta_system_prompt(
                    request.phase,
                    gate_authorized=request.gate_authorized,
                    workspace_dir=request.workspace_dir,
                )

        cmd = self.build_cli_command(executable, request, persistent=use_persistent)

        combined_prompt = (
            f"{effective_system_prompt}\n\n---\n\n{user_prompt}"
            if effective_system_prompt.strip()
            else user_prompt
        )
        stdin_envelope = (
            json.dumps(
                {"event": "user", "message": {"content": combined_prompt}},
                ensure_ascii=False,
            )
            + "\n"
        )
        stderr_lines: list[str] = []
        had_error = False
        parse_state: dict[str, Any] = {}

        if use_persistent and pool_key is not None:
            chunk_stream = self._get_session_pool().run_turn(
                pool_key,
                cmd,
                request.workspace_dir,
                stdin_envelope.encode("utf-8"),
                timeout_seconds=request.timeout_seconds,
                resume_session_id=request.resume_session_id,
            )
        else:
            chunk_stream = self._exec_lines(
                cmd,
                cwd=request.workspace_dir,
                stdin_data=stdin_envelope.encode("utf-8"),
                timeout_seconds=request.timeout_seconds,
            )

        async for chunk in chunk_stream:
            if chunk.stream == "stdout":
                for ev in self._parse_cli_line(chunk.line, state=parse_state):
                    if ev.type == EventType.ERROR:
                        had_error = True
                    yield ev
            elif chunk.stream == "stderr":
                if chunk.line.strip():
                    stderr_lines.append(chunk.line.strip())
            elif chunk.stream == "exit":
                if chunk.returncode not in (0, None) and not had_error:
                    had_error = True
                    detail = "\n".join(stderr_lines[-10:]) or f"Código de saída {chunk.returncode}"
                    yield HarnessEvent(
                        type=EventType.ERROR,
                        content=f"Falha na execução do AGY CLI: {detail}",
                        harness=self.kind,
                        metadata={"returncode": chunk.returncode},
                    )

        unfinished_ids = (
            parse_state.get("emitted_tool_steps", set())
            - parse_state.get("emitted_tool_results", set())
        )
        tool_names = parse_state.get("tool_names_by_id", {})
        if not had_error and unfinished_ids and not parse_state.get("emitted_text"):
            had_error = True
            for cid in sorted(unfinished_ids):
                t_name = tool_names.get(cid, "tool")
                err_text = "Ferramenta interrompida antes de retornar resultado no AGY CLI."
                yield HarnessEvent(
                    type=EventType.TOOL_RESULT,
                    tool_name=t_name,
                    tool_call_id=cid,
                    tool_output=err_text,
                    harness=self.kind,
                    metadata={"error": err_text, "interrupted": True},
                )
            stderr_tail = "\n".join(stderr_lines[-5:]).strip()
            detail_msg = (
                "O AGY CLI encerrou antes de concluir as ferramentas em andamento "
                f"({', '.join(tool_names.get(c, c) for c in sorted(unfinished_ids))})."
            )
            if stderr_tail:
                detail_msg = f"{detail_msg}\nDetalhes: {stderr_tail}"
            yield HarnessEvent(
                type=EventType.ERROR,
                content=detail_msg,
                harness=self.kind,
                metadata={"unfinished_tools": sorted(unfinished_ids)},
            )

        if not had_error:
            gate_ev = self._make_gate_event_if_needed(request)
            if gate_ev is not None:
                yield gate_ev
            done_meta: dict[str, Any] = {"mode": "cli_persistent" if use_persistent else "cli"}
            if parse_state.get("conversation_id"):
                done_meta["conversation_id"] = parse_state["conversation_id"]
                done_meta["session_id"] = parse_state["conversation_id"]
            if parse_state.get("usage"):
                done_meta["usage"] = parse_state["usage"]
            resolved_model = parse_state.get("model") or request.model
            if resolved_model:
                done_meta["resolved_model"] = resolved_model
                done_meta["model"] = resolved_model
            yield HarnessEvent(
                type=EventType.DONE,
                harness=self.kind,
                metadata=done_meta,
            )

    async def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        system_prompt, user_prompt = self._build_prompts(request)

        try:
            if self.is_sdk_available():
                async for ev in self._stream_via_sdk(request, system_prompt, user_prompt):
                    yield ev
                return

            exe = self._find_cli_executable()
            if exe:
                async for ev in self._stream_via_cli(exe, request, system_prompt, user_prompt):
                    yield ev
                return

            yield HarnessEvent(
                type=EventType.ERROR,
                content=(
                    "Google Antigravity (AGY) indisponível: instale o SDK "
                    "'pip install google-antigravity' ou adicione o CLI 'agy' ao PATH."
                ),
                harness=self.kind,
            )
        except TimeoutError:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Tempo limite excedido ({request.timeout_seconds}s) no Google Antigravity.",
                harness=self.kind,
            )
        except Exception as exc:
            yield HarnessEvent(
                type=EventType.ERROR,
                content=f"Erro inesperado no AGY Harness: {exc}",
                harness=self.kind,
            )
