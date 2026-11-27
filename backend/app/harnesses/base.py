# -*- coding: utf-8 -*-
"""Protocolo AgentHarness, construtor de prompt 2-Gate e executor assíncrono de subprocessos."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from backend.app.config import PROJECT_ROOT, SKILLS_DIR, get_data_dir, get_db_path
from backend.app.harnesses.types import (
    EventType,
    HarnessEvent,
    HarnessKind,
    HarnessRunRequest,
    HarnessStatus,
    PhaseKind,
)

STUDIO_MCP_SERVER_NAME = "salutem_studio"

STUDIO_MCP_TOOL_NAMES: tuple[str, ...] = (
    "inspect_clinical_pdf",
    "render_pdf_preview_pages",
    "crop_pdf_feedback_region",
    "get_salutem_skill",
    "extract_pdf_geometry",
    "save_validated_json",
    "validate_and_compile_jrxml",
    "render_preview_images",
)


def build_studio_mcp_server_spec() -> dict[str, Any]:
    """
    Retorna a especificação canônica stdio do servidor MCP nativo do Salutem Ficha Studio
    (`python -m backend.app.mcp_tools.mcp_server`) com `PYTHONPATH`, UTF-8 e caminhos do banco.
    """
    return {
        "command": sys.executable,
        "args": ["-m", "backend.app.mcp_tools.mcp_server"],
        "env": {
            "PYTHONPATH": str(PROJECT_ROOT.resolve()),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "FICHA_STUDIO_DATA_DIR": str(get_data_dir().resolve()),
            "FICHA_STUDIO_DB_PATH": str(get_db_path().resolve()),
        },
    }

SKILL_FOLDER_BY_PHASE: dict[str, str] = {
    "extraction": "extrator_ficha",
    "jrxml": "gerador_jrxml",
}


def load_phase_skill_markdown(phase: PhaseKind) -> str:
    """Carrega o conteúdo integral do SKILL.md embutido correspondente à fase."""
    folder = SKILL_FOLDER_BY_PHASE.get(phase)
    if not folder:
        raise ValueError(f"Fase inválida '{phase}'. Esperado: 'extraction' ou 'jrxml'.")
    skill_path = SKILLS_DIR / folder / "SKILL.md"
    if not skill_path.is_file():
        raise FileNotFoundError(f"Arquivo SKILL.md não encontrado em: {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def compose_phase_system_prompt(
    phase: PhaseKind,
    skill_markdown: str | None = None,
    gate_authorized: bool = False,
    workspace_dir: str | Path | None = None,
) -> str:
    """
    Compõe o System Prompt da fase combinando o SKILL.md oficial do Salutem com as travas
    estritas do fluxo de 2 Gates (Gate 1 = análise/perguntas sem gerar arquivos finais;
    Gate 2 = gravação direta dos artefatos finais no workspace sem despejar código gigante no chat).
    """
    if phase not in SKILL_FOLDER_BY_PHASE:
        raise ValueError(f"Fase inválida '{phase}'. Esperado: 'extraction' ou 'jrxml'.")

    resolved_skill = (
        skill_markdown if skill_markdown is not None else load_phase_skill_markdown(phase)
    )
    ws_text = str(Path(workspace_dir).resolve()) if workspace_dir is not None else "(workspace atual)"

    if not gate_authorized:
        if phase == "extraction":
            gate_instructions = f"""## CONTROLE ESTRITO DE FLUXO — GATE 1 (ANÁLISE E PERGUNTAS — NÃO AUTORIZADO A GERAR ARQUIVOS)

STATUS DA AUTORIZAÇÃO (`gate_authorized`): `False` (AGUARDANDO APROVAÇÃO DO USUÁRIO)
DIRETÓRIO DO WORKSPACE: `{ws_text}`

REGRAS OBRIGATÓRIAS DESTE TURNO:
1. **PROIBIDO GERAR ARQUIVOS FINAIS OU DESPEJAR JSON/SQL:** NÃO crie nem sobrescreva arquivos `.json` ou `.sql` finais no workspace, NÃO chame a ferramenta `save_validated_json` e **NUNCA** exiba o bloco JSON estruturado completo no chat neste turno.
2. **ANÁLISE TÉCNICA SILENCIOSA:** Inspecione silenciosamente o PDF/imagens/textos da ficha clínica no workspace (preferindo a ferramenta MCP `extract_pdf_geometry` ou `inspect_clinical_pdf` quando disponível).
3. **APRESENTAÇÃO CLARA E ESTRUTURADA:** Apresente ao usuário:
   - Resumo clínico e metadados identificados da ficha (`orientacao`, assinatura, finalidade).
   - Mapeamento detalhado das seções (`titulo: true`) e perguntas (`pergunta_template_ficha_clinica`), destacando agrupamentos independentes de `BOOLEANO_RADIO` e itens com `observacao: true`.
   - Tipos de campo (`tipo_campo`) sugeridos conforme o dicionário estrito de 11 tipos do Salutem.
4. **DÚVIDAS E SOLICITAÇÃO DE GATE:** Liste quaisquer ambiguidades encontradas no documento e finalize solicitando explicitamente a confirmação/autorização do usuário para avançar ao Gate 2 (geração do arquivo `.json`)."""
        else:
            gate_instructions = f"""## CONTROLE ESTRITO DE FLUXO — GATE 1 (DECISÕES DE DESIGN E PERGUNTAS — NÃO AUTORIZADO A GERAR JRXML)

STATUS DA AUTORIZAÇÃO (`gate_authorized`): `False` (PAUSA OBRIGATÓRIA ANTES DO CÓDIGO)
DIRETÓRIO DO WORKSPACE: `{ws_text}`

REGRAS OBRIGATÓRIAS DESTE TURNO:
1. **PROIBIDO GERAR ARQUIVOS `.jrxml`/`.xml` OU DESPEJAR XML:** NÃO crie arquivos `.jrxml` ou `.xml` finais no workspace, NÃO chame `validate_and_compile_jrxml` com `save_artifact=true` e **NUNCA** gere código XML JasperReports no chat neste turno.
2. **FASE 1 SILENCIOSA:** Inspecione silenciosamente as coordenadas exatas do PDF (preferindo a ferramenta MCP `extract_pdf_geometry` ou `inspect_clinical_pdf` quando disponível — textos, fontes, retângulos ~10x10 de checkbox vs círculos ~10x10 de rádio e área útil de `623 px` na banda `<detail>` Retrato com offset vertical `pdf_y - 182`) e os `<field>` da ficha.
3. **FASE 2 — RESUMO E PERGUNTAS:** Apresente ao usuário:
   - Validação cruzada entre PDF, título interno e campos da ficha/query.
   - Campos omitidos do `<detail>` por já existirem em `cabecalho_retrato.jasper` e `dados_paciente.jasper`.
   - Mapeamento exato de círculos (`<ellipse>`) vs quadrados (`<rectangle>`), textos estáticos (`<staticText>`), frases com `markup="styled"` e divisão planejada de bandas `<band>` (respeitando `height <= 623 px`).
   - Todas as perguntas necessárias sobre eventuais ambiguidades visuais ou de campos.
4. **PEDIDO DE AUTORIZAÇÃO EXPRESSA:** Finalize aguardando a resposta às dúvidas e a autorização expressa do usuário para avançar ao Gate 2."""
    else:
        if phase == "extraction":
            gate_instructions = f"""## CONTROLE ESTRITO DE FLUXO — GATE 2 (GERAÇÃO AUTORIZADA DIRETA NO WORKSPACE)

STATUS DA AUTORIZAÇÃO (`gate_authorized`): `True` (AUTORIZADO PELO USUÁRIO)
DIRETÓRIO DO WORKSPACE: `{ws_text}`

REGRAS OBRIGATÓRIAS DESTE TURNO:
1. **GRAVAÇÃO DIRETA EM ARQUIVO NO WORKSPACE OU VIA MCP:** O usuário JÁ AUTORIZOU a geração final. Salve o JSON estruturado usando a ferramenta MCP `save_validated_json` (passando `project_id` do contexto e `json_content`) **OU** grave diretamente em arquivo `.json` dentro de `{ws_text}` (ex.: `ficha_clinica.json`, salvo se outro nome foi especificado no workspace/prompt), obedecendo obrigatoriamente à raiz `{{"template": {{...}}, "perguntas": [...]}}`.
2. **PROIBIDO POLUIR O CHAT COM JSON GIGANTE:** NÃO despeje o JSON completo na mensagem do chat. Salve via `save_validated_json` ou escreva o arquivo diretamente no disco do workspace.
3. **RESPOSTA CONCISA DE ENTREGA:** No chat, informe a revisão/arquivo `.json` gravado, a contagem de seções, perguntas e respostas geradas, e confirme a conformidade com os 11 tipos estritos do Salutem."""
        else:
            gate_instructions = f"""## CONTROLE ESTRITO DE FLUXO — GATE 2 (GERAÇÃO JRXML AUTORIZADA DIRETA NO WORKSPACE)

STATUS DA AUTORIZAÇÃO (`gate_authorized`): `True` (AUTORIZADO PELO USUÁRIO)
DIRETÓRIO DO WORKSPACE: `{ws_text}`

REGRAS OBRIGATÓRIAS DESTE TURNO:
1. **GRAVAÇÃO DIRETA EM ARQUIVOS NO WORKSPACE OU VIA MCP:** O usuário JÁ AUTORIZOU a geração final do layout JasperReports. Escreva diretamente no diretório `{ws_text}` o arquivo `.jrxml` completo da ficha (e, quando aplicável, o bloco `detail_<nome>.xml`) e/ou utilize as ferramentas MCP `validate_and_compile_jrxml` e `render_preview_images` (passando `project_id` do contexto), validando 100% da árvore XML antes de concluir (`isBlankWhenNull="true"` em todos os `<textField>`, UUIDs v4 reais e únicos, `Boolean.TRUE.equals($F{{...}})` em CDATA, ordem estrita XSD e `band_height <= 623`).
2. **PROIBIDO POLUIR O CHAT COM XML LONGO:** **NUNCA** cole o código `.jrxml` / XML completo no chat. Salve diretamente nos arquivos do workspace ou via `validate_and_compile_jrxml`.
3. **RESPOSTA CONCISA DE ENTREGA:** No chat, confirme os arquivos gravados no workspace, o resultado do checklist de validação automática (XML, UUIDs, fields, limites de banda) e eventuais observações para o preview."""

    return (
        f"# Salutem Ficha Studio — Instruções do Agente ({phase.upper()})\n\n"
        f"{gate_instructions}\n\n"
        f"---\n\n"
        f"{resolved_skill.strip()}\n"
    )


def compose_user_prompt_with_context(request: HarnessRunRequest) -> str:
    """Enriquece o prompt do usuário com metadados de imagens e contexto extra do workspace."""
    sections: list[str] = [f"Workspace: {request.workspace_dir.resolve()}"]

    if request.image_paths:
        img_lines = "\n".join(f"- {Path(p).resolve()}" for p in request.image_paths)
        sections.append(f"Imagens de referência para inspeção visual:\n{img_lines}")

    if request.extra_context:
        ctx_json = json.dumps(request.extra_context, ensure_ascii=False, indent=2, default=str)
        sections.append(f"Contexto adicional do Studio:\n```json\n{ctx_json}\n```")

    sections.append(request.prompt.strip())
    return "\n\n".join(sections)


@runtime_checkable
class AgentHarness(Protocol):
    """Protocolo unificado implementado pelos 4 adaptadores de agentes do Studio."""

    kind: HarnessKind
    display_name: str

    def check_status(self) -> HarnessStatus:
        """Inspeciona sincronamente disponibilidade de binário/SDK, versão e dicas de auth."""
        ...

    def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        """Executa um turno do agente emitindo eventos normalizados em tempo real."""
        ...


@dataclass(slots=True)
class SubprocessChunk:
    """Unidade produzida pelo executor de subprocesso assíncrono (linha ou código de saída)."""

    stream: Literal["stdout", "stderr", "exit"]
    line: str = ""
    returncode: int | None = None


SubprocessRunner = Callable[
    [
        Sequence[str],
        Path,
        dict[str, str] | None,
        bytes | None,
        float | None,
    ],
    AsyncIterator[SubprocessChunk],
]


async def default_subprocess_runner(
    cmd: Sequence[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin_data: bytes | None = None,
    timeout_seconds: float | None = 300.0,
) -> AsyncIterator[SubprocessChunk]:
    """
    Executa um subprocesso assíncrono com `asyncio.create_subprocess_exec`, leitura concorrente
    linha a linha de stdout e stderr sem risco de deadlock, timeout configurável e limpeza
    garantida do processo em caso de cancelamento ou timeout.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    cwd_path = Path(cwd).resolve()
    cwd_path.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd_path),
        env=merged_env,
        limit=4 * 1024 * 1024,  # 4 MiB por linha para suportar JSONL grandes de tool_result
    )

    queue: asyncio.Queue[SubprocessChunk | BaseException | None] = asyncio.Queue()

    async def _feed_stdin() -> None:
        if stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

    async def _pump_stream(
        reader: asyncio.StreamReader | None,
        stream_name: Literal["stdout", "stderr"],
    ) -> None:
        if reader is None:
            return
        try:
            while True:
                raw_line = await reader.readline()
                if not raw_line:
                    break
                decoded = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                await queue.put(SubprocessChunk(stream=stream_name, line=decoded))
        except BaseException as exc:
            await queue.put(exc)

    stdin_task = asyncio.create_task(_feed_stdin())
    stdout_task = asyncio.create_task(_pump_stream(proc.stdout, "stdout"))
    stderr_task = asyncio.create_task(_pump_stream(proc.stderr, "stderr"))

    async def _await_readers_and_close() -> None:
        await asyncio.gather(stdin_task, stdout_task, stderr_task, return_exceptions=True)
        await queue.put(None)

    watcher_task = asyncio.create_task(_await_readers_and_close())

    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item

            rc = await proc.wait()
            yield SubprocessChunk(stream="exit", returncode=rc)
    finally:
        for task in (stdin_task, stdout_task, stderr_task, watcher_task):
            if not task.done():
                task.cancel()
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:
                pass


class BaseSubprocessHarness:
    """
    Classe base para harnesses baseados em CLI assíncrono, oferecendo descoberta de binários,
    sondagem segura de versão, composição de prompt 2-Gate e injeção de runner para testes.
    """

    kind: HarnessKind
    display_name: str

    def __init__(
        self,
        *,
        runner: SubprocessRunner | None = None,
        which_resolver: Callable[[str], str | None] | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        self._runner: SubprocessRunner = runner or default_subprocess_runner
        self._which: Callable[[str], str | None] = which_resolver or shutil.which
        self._default_timeout = default_timeout

    def _resolve_executable(
        self,
        binary_name: str,
        fallback_paths: Sequence[Path] = (),
    ) -> str | None:
        """Localiza executável no PATH (via `which_resolver`) ou em caminhos de fallback."""
        found = self._which(binary_name)
        if found:
            return found
        for candidate in fallback_paths:
            if candidate.is_file():
                return str(candidate)
        return None

    def _probe_version(
        self,
        executable: str | None,
        args: Sequence[str] = ("--version",),
    ) -> str | None:
        """Executa `<bin> --version` com timeout curto, retornando a primeira linha limpa."""
        if not executable:
            return None
        try:
            completed = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                check=False,
            )
            output = (completed.stdout or completed.stderr or "").strip()
            if output:
                return output.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return None

    def _build_prompts(self, request: HarnessRunRequest) -> tuple[str, str]:
        """Retorna `(system_prompt, enriched_user_prompt)` para a requisição atual."""
        system_prompt = request.system_prompt_override or compose_phase_system_prompt(
            phase=request.phase,
            skill_markdown=None,
            gate_authorized=request.gate_authorized,
            workspace_dir=request.workspace_dir,
        )
        user_prompt = compose_user_prompt_with_context(request)
        return system_prompt, user_prompt

    async def _exec_lines(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[SubprocessChunk]:
        """Delega a execução ao runner assíncrono injetável."""
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._default_timeout
        )
        async for chunk in self._runner(cmd, cwd, env, stdin_data, effective_timeout):
            yield chunk

    def _make_gate_event_if_needed(self, request: HarnessRunRequest) -> HarnessEvent | None:
        """Emite `GATE_REQUEST` ao término de um turno Gate 1 (`gate_authorized=False`)."""
        if not request.gate_authorized:
            return HarnessEvent(
                type=EventType.GATE_REQUEST,
                content="Análise concluída. Aguardando autorização expressa do usuário para gerar os artefatos finais.",
                harness=self.kind,
                metadata={"phase": request.phase, "gate_authorized": False},
            )
        return None

    def stream(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        """Método abstrato implementado por cada adaptador concreto."""
        raise NotImplementedError

    def run(self, request: HarnessRunRequest) -> AsyncIterator[HarnessEvent]:
        """Alias ergonômico para `stream(request)`."""
        return self.stream(request)

    async def run_to_completion(self, request: HarnessRunRequest) -> list[HarnessEvent]:
        """Consome todo o stream de um turno e retorna a lista ordenada de eventos."""
        events: list[HarnessEvent] = []
        async for ev in self.stream(request):
            events.append(ev)
        return events
