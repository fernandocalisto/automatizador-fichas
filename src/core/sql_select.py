#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de Consulta SQL SELECT para Jasper Reports (Padrão Ouro) (src/core/sql_select.py).

Implementa `generate_select_jasper()` conforme `spec_sql_select.md` e `gerar_select_jasper.py`:
- Lê o modelo base (`select_padrao_ouro_jasper.sql`), extrai CABEÇALHO e RODAPÉ via regex
  (`----- PERGUNTAS -----` e `----- PACIENTE`), mantendo-os intactos
- Gera as projeções agregadas (`max(case when ...)`, `coalesce(bool_or(...), false)`) a partir do JSON
- Normaliza labels para identificadores SQL válidos (`normalizar_slug`, snake_case ASCII)
- Resolve colisões de aliases com sufixo de tipo (`sufixo_tipo`) ou contador incremental
- Expande respostas com `label` vazio e `quantidade_linhas > 1` (`p{idx_p}_r{idx_r}`)
- Adiciona projeção `{alias}_obs` quando `observacao: true` (na pergunta ou resposta) e `tipo_campo != 'TEXTO'`
- Reutiliza `validate_postgres_syntax()` e `apply_syntax_highlighting()`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from src.core.sql_insert import (
    POSTGRES_FUNCTIONS,
    POSTGRES_KEYWORDS,
    TIPOS_VALIDOS,
    apply_syntax_highlighting,
    validate_postgres_syntax,
)
from src.utils.resource_path import resource_path

MODEL_RESOURCE_NAME = "select_padrao_ouro_jasper.sql"

_MODEL_SECTION_REGEX = re.compile(
    r"^(.*?[ \t]*-----\s*PERGUNTAS\s*-----).*?(^[ \t]*-----\s*PACIENTE.*)$",
    re.DOTALL | re.MULTILINE,
)


def normalizar_slug(texto: str | None) -> str:
    """
    Converte um texto para um identificador SQL válido (snake_case ASCII).
    Ex: 'CIRURGIÃO / AUXILIAR:' -> 'cirurgiao_auxiliar'
        'ÁLCOOL 70%' -> 'alcool_70'
        '123 TESTE' -> 'f_123_teste'
    """
    if not texto:
        return "campo"

    # Remove acentos (NFKD)
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Converte para minúsculas
    slug = sem_acento.lower()

    # Substitui caracteres não-alfanuméricos por underscore
    slug = re.sub(r"[^a-z0-9]+", "_", slug)

    # Remove underscores repetidos e das extremidades
    slug = re.sub(r"_+", "_", slug).strip("_")

    if not slug:
        slug = "campo"
    elif slug[0].isdigit():
        slug = "f_" + slug

    return slug


def gerar_projecao_resposta(
    idx_p: int,
    idx_r: int,
    tipo_campo: str,
    alias: str,
    boolean_style: str = "coalesce_bool_or",
) -> str:
    """Gera a cláusula SQL agregada para a resposta conforme `tipo_campo` e `boolean_style`."""
    tipo = str(tipo_campo or "").strip().upper()
    b_style = str(boolean_style or "coalesce_bool_or").strip().lower()

    if tipo == "HORA":
        return (
            f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"and c.tipo_campo = 'HORA' then TO_CHAR(c.valor_hora, 'HH24:MI') end) as {alias},"
        )
    elif tipo in ("BOOLEANO", "BOOLEANO_RADIO"):
        if b_style == "x_empty":
            return (
                f"        coalesce(max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
                f"and c.valor_booleano is true then 'X' end), '') as {alias},"
            )
        if b_style == "sim_nao":
            return (
                f"        case when coalesce(bool_or(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
                f"then c.valor_booleano::bool end), false) then 'SIM' else 'NÃO' end as {alias},"
            )
        if b_style == "1_0":
            return (
                f"        case when coalesce(bool_or(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
                f"then c.valor_booleano::bool end), false) then 1 else 0 end as {alias},"
            )
        return (
            f"        coalesce(bool_or(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"then c.valor_booleano::bool end), false) as {alias},"
        )
    elif tipo in ("TEXTO", "EXAME", "PROCEDIMENTO", "PROCEDIMENTO_CID", "CID", "COMBOBOX"):
        return (
            f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"and c.tipo_campo = '{tipo}' then c.valor_texto end) as {alias},"
        )
    elif tipo == "NUMERICO":
        return (
            f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"and c.tipo_campo = 'NUMERICO' then c.valor_numerico end) as {alias},"
        )
    elif tipo == "DATA":
        return (
            f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"and c.tipo_campo = 'DATA' then TO_CHAR(c.valor_data, 'DD/MM/YYYY') end) as {alias},"
        )
    else:
        # Fallback genérico para texto
        return (
            f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
            f"then c.valor_texto end) as {alias},"
        )


def sufixo_tipo(tipo_campo: str) -> str:
    """Retorna abreviação do tipo para resolver colisões de aliases idênticos."""
    tipo = str(tipo_campo or "").strip().upper()
    if tipo in ("BOOLEANO", "BOOLEANO_RADIO"):
        return "bool"
    elif tipo == "HORA":
        return "hora"
    elif tipo == "DATA":
        return "data"
    elif tipo == "NUMERICO":
        return "num"
    elif tipo == "TEXTO":
        return "txt"
    return tipo.lower()[:4] if tipo else "txt"


def gerar_secao_perguntas(
    dados_json: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str:
    """Gera o bloco SQL com as colunas agregadas de perguntas e respostas."""
    opts = options or {}
    include_obs: bool = bool(
        opts.get("include_obs", opts.get("include_observations", True))
    )
    include_metadata: bool = bool(opts.get("include_metadata", False))
    only_non_title: bool = bool(opts.get("only_non_title", False))
    boolean_style: str = str(opts.get("boolean_style", "coalesce_bool_or") or "coalesce_bool_or")
    column_naming: str = str(opts.get("column_naming", "label_only") or "label_only")

    linhas: list[str] = [
        "        ----- PERGUNTAS -----",
        "",
    ]

    aliases_usados: set[str] = set()

    perguntas = dados_json.get("perguntas", [])
    for idx_p, p in enumerate(perguntas, start=1):
        if not isinstance(p, dict):
            raise ValueError(f"Pergunta na posição {idx_p} inválida: esperado um objeto JSON.")

        if only_non_title and bool(p.get("titulo", False)):
            continue

        p_nome = p.get("nome", f"PERGUNTA_{idx_p}")
        linhas.append(f"        -- Pergunta {idx_p}: {p_nome}")

        respostas = p.get("respostas", [])
        if respostas is None:
            respostas = []
        if not isinstance(respostas, list):
            raise ValueError(
                f"Erro na pergunta '{p_nome}': 'respostas' deve ser uma lista."
            )

        if include_metadata:
            linhas.append(
                f"        -- [Metadados] titulo={bool(p.get('titulo', False))} "
                f"| obrigatoria={bool(p.get('obrigatoria', False))} "
                f"| observacao={bool(p.get('observacao', False))} "
                f"| respostas={len(respostas)}"
            )

        # Expandir caso haja repetição de quantidade_linhas com label vazio (generate_series)
        respostas_expandidas: list[dict[str, Any]] = []
        for r in respostas:
            if not isinstance(r, dict):
                raise ValueError(f"Resposta inválida na pergunta '{p_nome}'.")
            qtd_raw = r.get("quantidade_linhas", 1)
            qtd = int(qtd_raw if qtd_raw is not None else 1)
            lbl_raw = str(r.get("label") or "").strip()
            if not lbl_raw and qtd > 1:
                for sub_i in range(1, qtd + 1):
                    novo_r = dict(r)
                    novo_r["_sub_idx"] = sub_i
                    respostas_expandidas.append(novo_r)
            else:
                respostas_expandidas.append(r)

        p_slug = normalizar_slug(str(p_nome))

        for idx_r, r in enumerate(respostas_expandidas, start=1):
            lbl = str(r.get("label") or "").strip()
            raw_tipo = r.get("tipo_campo")
            tipo = str(raw_tipo if raw_tipo is not None else "TEXTO").strip().upper()
            if not tipo:
                tipo = "TEXTO"

            if column_naming == "pergunta_label":
                if not lbl:
                    base_alias = f"{p_slug}_r{idx_r}"
                else:
                    lbl_slug = normalizar_slug(lbl)
                    base_alias = (
                        lbl_slug
                        if lbl_slug == p_slug or lbl_slug.startswith(f"{p_slug}_")
                        else f"{p_slug}_{lbl_slug}"
                    )
            elif column_naming == "label_sufixo":
                raw_base = f"p{idx_p}_r{idx_r}" if not lbl else normalizar_slug(lbl)
                suf = sufixo_tipo(tipo)
                base_alias = (
                    raw_base if raw_base.endswith(f"_{suf}") else f"{raw_base}_{suf}"
                )
            else:
                # "label_only" (padrão clássico)
                if not lbl:
                    base_alias = f"p{idx_p}_r{idx_r}"
                else:
                    base_alias = normalizar_slug(lbl)

            # Verifica colisão de alias
            alias = base_alias
            if alias in aliases_usados:
                suf = sufixo_tipo(tipo)
                cand = f"{base_alias}_{suf}" if not base_alias.endswith(f"_{suf}") else f"{base_alias}_2"
                if cand not in aliases_usados:
                    alias = cand
                else:
                    c = 2
                    while f"{cand}_{c}" in aliases_usados:
                        c += 1
                    alias = f"{cand}_{c}"

            aliases_usados.add(alias)
            projecao = gerar_projecao_resposta(
                idx_p, idx_r, tipo, alias, boolean_style=boolean_style
            )
            linhas.append(projecao)

            # Se tiver observação ativa (observacao: true) e NÃO for do tipo TEXTO, puxa também o valor_texto com alias _obs
            tem_observacao = (
                (p.get("observacao") is True or r.get("observacao") is True)
                and tipo != "TEXTO"
            )
            if include_obs and tem_observacao:
                alias_obs_base = f"{base_alias}_obs"
                alias_obs = alias_obs_base
                c = 2
                while alias_obs in aliases_usados:
                    alias_obs = f"{alias_obs_base}_{c}"
                    c += 1
                aliases_usados.add(alias_obs)
                proj_obs = (
                    f"        max(case when pfc.ordenacao = {idx_p} and c.ordenacao = {idx_r} "
                    f"then c.valor_texto end) as {alias_obs},"
                )
                linhas.append(proj_obs)

        linhas.append("")

    return "\n".join(linhas)


def load_default_model_sql() -> str:
    """Carrega o conteúdo do arquivo modelo `select_padrao_ouro_jasper.sql` via `resource_path`."""
    model_path = resource_path(MODEL_RESOURCE_NAME)
    if not model_path.exists():
        raise FileNotFoundError(
            f"Arquivo modelo não encontrado em: {model_path}"
        )
    return model_path.read_text(encoding="utf-8-sig")


def _strip_last_projection_comma(block_text: str) -> str:
    """Remove a vírgula final da última linha de projeção válida antes do FROM."""
    lines = block_text.split("\n")
    for idx in range(len(lines) - 1, -1, -1):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines[idx] = re.sub(r",\s*$", "", lines[idx])
        break
    return "\n".join(lines)


def _assemble_select_blocks(
    cabecalho: str,
    secao_perguntas: str,
    rodape: str,
    options: dict[str, Any] | None = None,
) -> str:
    """Monta o SQL final filtrando os blocos adicionais caso desmarcados."""
    opts = options or {}
    master_all = bool(opts.get("include_all_blocks", True))
    inc_cabecalho = master_all and bool(opts.get("include_cabecalho", True))
    inc_paciente = master_all and bool(opts.get("include_paciente", True))
    inc_profissional = master_all and bool(opts.get("include_profissional", True))
    inc_atendimento = master_all and bool(opts.get("include_atendimento", True))

    if inc_cabecalho and inc_paciente and inc_profissional and inc_atendimento:
        return f"{cabecalho}\n\n{secao_perguntas}\n{rodape}"

    header_sql = cabecalho if inc_cabecalho else "select"

    # Separa cláusula FROM do rodapé
    from_match = re.search(r"\n\s*from\s+ficha_clinica\b", rodape, re.IGNORECASE)
    if from_match:
        projections_tail = rodape[: from_match.start()]
        from_clause = rodape[from_match.start() :]
    else:
        projections_tail = rodape
        from_clause = ""

    # Separa PACIENTE, PROFISSIONAL e ATENDIMENTO dentro de projections_tail
    prof_match = re.search(r"^[ \t]*-----\s*PROFISSIONAL\s*-----", projections_tail, re.MULTILINE)
    if prof_match:
        bloco_paciente = projections_tail[: prof_match.start()].rstrip()
        prof_and_atend = projections_tail[prof_match.start() :]
    else:
        bloco_paciente = projections_tail.rstrip()
        prof_and_atend = ""

    atend_match = re.search(
        r"^[ \t]*max\s*\(\s*cast\s*\(\s*age\.horario\s+as\s+date\s*\)",
        prof_and_atend,
        re.IGNORECASE | re.MULTILINE,
    )
    if atend_match:
        bloco_profissional = prof_and_atend[: atend_match.start()].rstrip()
        bloco_atendimento = (
            "        ----- ATENDIMENTO -----\n" + prof_and_atend[atend_match.start() :].rstrip()
        )
    else:
        bloco_profissional = prof_and_atend.rstrip()
        bloco_atendimento = ""

    parts: list[str] = [secao_perguntas.rstrip()]
    if inc_paciente and bloco_paciente:
        parts.append(bloco_paciente)
    if inc_profissional and bloco_profissional:
        parts.append(bloco_profissional)
    if inc_atendimento and bloco_atendimento:
        parts.append(bloco_atendimento)

    body = "\n".join(parts)
    body = _strip_last_projection_comma(body)

    return f"{header_sql}\n\n{body}\n{from_clause}"


def generate_select_jasper(
    json_data: dict[str, Any],
    model_sql: str | Path | None = None,
    options: dict[str, Any] | None = None,
) -> str:
    """
    Recebe o dicionário JSON de ficha clínica e o conteúdo (ou caminho) do modelo SQL
    `select_padrao_ouro_jasper.sql`, substituindo a seção `----- PERGUNTAS -----`
    e respeitando as opções de blocos e formatação em `options`.

    Não modifica `json_data`.
    """
    if not isinstance(json_data, dict) or not json_data:
        raise ValueError(
            "JSON inválido ou vazio: esperado um objeto contendo 'template' e 'perguntas'."
        )

    if "template" not in json_data or not isinstance(json_data.get("template"), dict):
        raise ValueError(
            "Estrutura JSON inválida: a chave 'template' (objeto) é obrigatória."
        )

    if "perguntas" not in json_data or not isinstance(json_data.get("perguntas"), list):
        raise ValueError(
            "Estrutura JSON inválida: a chave 'perguntas' (lista) é obrigatória."
        )

    if model_sql is None:
        conteudo_modelo = load_default_model_sql()
    elif isinstance(model_sql, Path):
        if not model_sql.exists():
            raise FileNotFoundError(f"Arquivo modelo não encontrado em: {model_sql}")
        conteudo_modelo = model_sql.read_text(encoding="utf-8-sig")
    elif isinstance(model_sql, str):
        if (
            "\n" not in model_sql
            and model_sql.strip().lower().endswith(".sql")
            and Path(model_sql).exists()
        ):
            conteudo_modelo = Path(model_sql).read_text(encoding="utf-8-sig")
        else:
            conteudo_modelo = model_sql
    else:
        raise ValueError("Parâmetro 'model_sql' inválido.")

    conteudo_modelo = conteudo_modelo.lstrip("\ufeff").replace("\r\n", "\n")

    match = _MODEL_SECTION_REGEX.search(conteudo_modelo)
    if not match:
        raise ValueError(
            "Não foi possível identificar as seções '----- PERGUNTAS -----' e '----- PACIENTE' no arquivo modelo."
        )

    cabecalho = match.group(1).rstrip()
    cabecalho = re.sub(r"\n?[ \t]*-----\s*PERGUNTAS\s*-----\s*$", "", cabecalho)
    rodape = match.group(2)

    secao_perguntas = gerar_secao_perguntas(json_data, options=options)

    return _assemble_select_blocks(cabecalho, secao_perguntas, rodape, options=options)


def find_unknown_field_types(json_data: dict[str, Any]) -> list[str]:
    """
    Retorna lista ordenada de `tipo_campo` presentes no JSON que não pertencem
    aos 11 tipos oficiais (`TIPOS_VALIDOS`), para exibição de aviso na barra de status.
    """
    unknown: set[str] = set()
    perguntas = json_data.get("perguntas", []) if isinstance(json_data, dict) else []
    if not isinstance(perguntas, list):
        return []
    for p in perguntas:
        if not isinstance(p, dict):
            continue
        respostas = p.get("respostas", [])
        if not isinstance(respostas, list):
            continue
        for r in respostas:
            if not isinstance(r, dict):
                continue
            raw_tc = r.get("tipo_campo")
            tc = "" if raw_tc is None else str(raw_tc).strip().upper()
            if tc not in TIPOS_VALIDOS:
                unknown.add(tc or "<VAZIO>")
    return sorted(unknown)


def gerar_select_jasper(caminho_modelo: str | Path, caminho_json: str | Path) -> str:
    """Função de compatibilidade com o script CLI `gerar_select_jasper.py`."""
    modelo_path = Path(caminho_modelo)
    json_path = Path(caminho_json)
    conteudo_modelo = modelo_path.read_text(encoding="utf-8-sig")
    dados_json = json.loads(json_path.read_text(encoding="utf-8-sig"))
    return generate_select_jasper(dados_json, conteudo_modelo)


__all__ = [
    "MODEL_RESOURCE_NAME",
    "POSTGRES_FUNCTIONS",
    "POSTGRES_KEYWORDS",
    "TIPOS_VALIDOS",
    "apply_syntax_highlighting",
    "find_unknown_field_types",
    "generate_select_jasper",
    "gerar_projecao_resposta",
    "gerar_secao_perguntas",
    "gerar_select_jasper",
    "load_default_model_sql",
    "normalizar_slug",
    "sufixo_tipo",
    "validate_postgres_syntax",
]
