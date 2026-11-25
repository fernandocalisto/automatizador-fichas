#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitários de manipulação, validação, auditoria clínica e CRUD determinístico
de JSON do Form Builder (`backend/app/core/json_utils.py`).

Implementa:
- `uppercase_target_fields` (e alias `apply_uppercase_to_text_fields`): conversão recursiva
  de campos textuais alvo (`label`, `labels`, `nome`, `name`, `descricao`, `description`,
  `titulo`, `title`, `valor_texto`) para UPPERCASE, preservando tipos primitivos e campos de código.
- Validação sintática e estrutural de JSON de ficha clínica.
- `audit_clinical_json_warnings`: auditoria não-bloqueante das regras de negócio Salutem.
- Helpers determinísticos de CRUD e reordenação do Form Builder (`add_question`, `update_question`,
  `delete_question`, `reorder_questions`, `add_answer`, `update_answer`, `delete_answer`,
  `reorder_answers`) preservando regras de UPPERCASE e renumerando `ordenacao` `1..N`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# Campos de texto que devem ser convertidos para UPPERCASE conforme a especificação
TEXT_FIELDS_UPPERCASE = {
    "label",
    "labels",
    "nome",
    "name",
    "descricao",
    "description",
    "titulo",
    "title",
    "valor_texto",
}

# Campos de código/configuração estrita que NÃO devem ser alterados pela regra genérica
PRESERVE_CASE_FIELDS = {
    "layout",
    "id",
    "codigo_ficha",
    "cid_codigo",
    "procedimento_codigo",
    "exame_id",
}

VALID_FIELD_TYPES = {
    "BOOLEANO",
    "BOOLEANO_RADIO",
    "CID",
    "COMBOBOX",
    "DATA",
    "EXAME",
    "HORA",
    "NUMERICO",
    "PROCEDIMENTO",
    "PROCEDIMENTO_CID",
    "TEXTO",
}

VALID_ORIENTACOES = {"RETRATO", "PAISAGEM"}
VALID_POSICOES_ASSINATURA = {"RODAPE", "LATERAL"}


def uppercase_target_fields(data: Any) -> Any:
    """
    Percorre recursivamente o objeto JSON (dict/list) e converte apenas os valores
    de texto (strings) associados aos campos alvo (label, labels, nome, name,
    descricao, description, titulo, title, valor_texto) para UPPERCASE,
    preservando booleanos, inteiros, floats, None e campos de código.
    """
    if isinstance(data, dict):
        novo_dict: dict[str, Any] = {}
        for chave, valor in data.items():
            chave_lower = chave.lower() if isinstance(chave, str) else ""

            if chave_lower in PRESERVE_CASE_FIELDS:
                novo_dict[chave] = valor
            elif chave_lower in TEXT_FIELDS_UPPERCASE:
                if isinstance(valor, str):
                    novo_dict[chave] = valor.upper()
                elif isinstance(valor, list):
                    novo_dict[chave] = [
                        item.upper() if isinstance(item, str) else uppercase_target_fields(item)
                        for item in valor
                    ]
                elif isinstance(valor, dict):
                    novo_dict[chave] = {
                        k: (v.upper() if isinstance(v, str) else uppercase_target_fields(v))
                        for k, v in valor.items()
                    }
                else:
                    # Preserva booleanos (ex.: "titulo": false), números e None intactos
                    novo_dict[chave] = valor
            else:
                novo_dict[chave] = uppercase_target_fields(valor)
        return novo_dict

    if isinstance(data, list):
        return [uppercase_target_fields(item) for item in data]

    return data


# Alias para compatibilidade com módulos existentes
apply_uppercase_to_text_fields = uppercase_target_fields


def uppercase_target_fields_in_place(data: Any) -> Any:
    """
    Percorre recursivamente o objeto JSON (dict/list) IN-PLACE, preservando as mesmas
    instâncias de dict e list na memória, e converte apenas os valores de texto (strings)
    associados aos campos alvo para UPPERCASE.
    """
    if isinstance(data, dict):
        for chave, valor in list(data.items()):
            chave_lower = chave.lower() if isinstance(chave, str) else ""

            if chave_lower in PRESERVE_CASE_FIELDS:
                continue
            elif chave_lower in TEXT_FIELDS_UPPERCASE:
                if isinstance(valor, str):
                    data[chave] = valor.upper()
                elif isinstance(valor, list):
                    for idx, item in enumerate(valor):
                        if isinstance(item, str):
                            valor[idx] = item.upper()
                        else:
                            uppercase_target_fields_in_place(item)
                elif isinstance(valor, dict):
                    for k, v in list(valor.items()):
                        if isinstance(v, str):
                            valor[k] = v.upper()
                        else:
                            uppercase_target_fields_in_place(v)
            else:
                uppercase_target_fields_in_place(valor)
        return data

    if isinstance(data, list):
        for item in data:
            uppercase_target_fields_in_place(item)
        return data

    return data


def update_shared_dict_in_place(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """
    Atualiza o dicionário compartilhado `target` in-place com os dados de `source`,
    mantendo a mesma referência de objeto Python (e sub-dicionários quando `target is source`)
    entre as abas.
    """
    if target is source:
        return uppercase_target_fields_in_place(target)

    converted = uppercase_target_fields(source)
    target.clear()
    target.update(converted)
    return target


def validate_json_text(raw_text: str) -> Any:
    """
    Valida se a string fornecida é um JSON bem-formado.
    Retorna o objeto Python decodificado ou levanta ValueError / json.JSONDecodeError.
    """
    texto_limpo = raw_text.strip()
    if not texto_limpo:
        raise ValueError("O conteúdo JSON está vazio.")
    return json.loads(texto_limpo)


def validate_clinical_json_structure(data: Any) -> tuple[bool, str]:
    """
    Verifica a estrutura mínima de um JSON de ficha clínica:
    deve ser um dicionário contendo 'template' (dict) e 'perguntas' (list).
    Retorna (True, "") se válido ou (False, mensagem_de_erro) caso contrário.
    """
    if not isinstance(data, dict):
        return (
            False,
            "JSON de ficha clínica inválido: o elemento raiz deve ser um objeto JSON ({...}).",
        )

    if "template" not in data or not isinstance(data.get("template"), dict):
        return (
            False,
            "Não é um JSON de ficha clínica válido: a chave 'template' (objeto) é obrigatória.",
        )

    if "perguntas" not in data or not isinstance(data.get("perguntas"), list):
        return (
            False,
            "Não é um JSON de ficha clínica válido: a chave 'perguntas' (lista) é obrigatória.",
        )

    return True, ""


def parse_and_validate_clinical_json(
    raw_text: str,
    *,
    require_clinical_structure: bool = True,
    apply_uppercase: bool = True,
) -> dict[str, Any]:
    """
    Faz o parse do texto JSON, valida a estrutura mínima ('template' e 'perguntas')
    e aplica a conversão para UPPERCASE nos campos de texto alvo.
    """
    parsed = validate_json_text(raw_text)

    if require_clinical_structure:
        is_valid, error_msg = validate_clinical_json_structure(parsed)
        if not is_valid:
            raise ValueError(error_msg)

    if apply_uppercase:
        parsed = uppercase_target_fields(parsed)

    return parsed


def format_json(data: Any) -> str:
    """Formata um objeto Python em string JSON indentada (UTF-8 legível)."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def load_json_file(file_path: str | Path) -> Any:
    """Lê e faz o parse de um arquivo JSON em padrão UTF-8 (aceitando BOM se presente)."""
    path = Path(file_path)
    conteudo = path.read_text(encoding="utf-8-sig")
    return json.loads(conteudo)


def save_json_file(file_path: str | Path, data: Any, apply_uppercase: bool = True) -> str:
    """
    Formata e grava o objeto JSON em arquivo UTF-8.
    Retorna a string JSON formatada que foi gravada.
    """
    path = Path(file_path)
    dados_finais = uppercase_target_fields(data) if apply_uppercase else data
    texto_formatado = format_json(dados_finais)
    path.write_text(texto_formatado + "\n", encoding="utf-8")
    return texto_formatado


# =============================================================================
# Auditoria de Regras de Negócio Salutem (`extrator_ficha/SKILL.md`)
# =============================================================================


def audit_clinical_json_warnings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Audita um JSON de ficha clínica contra as regras de negócio do Salutem
    (`extrator_ficha/SKILL.md`), retornando avisos estruturados:
    `[{"code": str, "severity": str, "path": str, "message": str}]`.

    Regras verificadas:
    - Chave legada `template_ficha_clinica` em vez de `template`
    - `template.layout != 'ficha-clinica'`
    - `template.quantidade_pagina != 1`
    - `template.orientacao` fora de `('RETRATO', 'PAISAGEM')`
    - `template.posicao_assinatura` fora de `('RODAPE', 'LATERAL')`
    - Pergunta divisora de seção (`titulo=True`) com `respostas` não vazias
    - Pergunta comum (`titulo=False`) com 0 `respostas`
    - Mais de 2 itens `BOOLEANO_RADIO` na mesma pergunta (risco de grupos independentes colapsados)
    - `tipo_campo` desconhecido fora dos 11 tipos oficiais do Salutem
    """
    warnings: list[dict[str, Any]] = []

    if not isinstance(data, dict):
        warnings.append(
            {
                "code": "INVALID_ROOT",
                "severity": "warning",
                "path": "$",
                "message": "O elemento raiz do JSON deve ser um objeto contendo 'template' e 'perguntas'.",
            }
        )
        return warnings

    if "template_ficha_clinica" in data:
        warnings.append(
            {
                "code": "LEGACY_TEMPLATE_KEY",
                "severity": "warning",
                "path": "template_ficha_clinica",
                "message": "Use obrigatoriamente a chave raiz 'template' e nunca 'template_ficha_clinica'.",
            }
        )

    is_valid, struct_msg = validate_clinical_json_structure(data)
    if not is_valid:
        warnings.append(
            {
                "code": "INVALID_CLINICAL_STRUCTURE",
                "severity": "warning",
                "path": "$",
                "message": struct_msg,
            }
        )
        return warnings

    template = data.get("template", {})
    if "layout" in template and template.get("layout") != "ficha-clinica":
        warnings.append(
            {
                "code": "TEMPLATE_LAYOUT_INVALID",
                "severity": "warning",
                "path": "template.layout",
                "message": (
                    f"Valor inválido em template.layout='{template.get('layout')}'. "
                    "No Salutem o valor obrigatório é 'ficha-clinica' (minúsculo)."
                ),
            }
        )

    if "quantidade_pagina" in template and template.get("quantidade_pagina") != 1:
        warnings.append(
            {
                "code": "TEMPLATE_PAGE_COUNT_INVALID",
                "severity": "warning",
                "path": "template.quantidade_pagina",
                "message": (
                    f"Valor inválido em template.quantidade_pagina={template.get('quantidade_pagina')!r}. "
                    "No Salutem 'quantidade_pagina' deve ser sempre 1."
                ),
            }
        )

    if "orientacao" in template and template.get("orientacao") is not None:
        orient = str(template.get("orientacao")).strip().upper()
        if orient not in VALID_ORIENTACOES:
            warnings.append(
                {
                    "code": "TEMPLATE_ORIENTACAO_INVALID",
                    "severity": "warning",
                    "path": "template.orientacao",
                    "message": (
                        f"Orientação inválida '{template.get('orientacao')}'. "
                        "Valores esperados: 'RETRATO' ou 'PAISAGEM'."
                    ),
                }
            )

    if "posicao_assinatura" in template and template.get("posicao_assinatura") is not None:
        pos_ass = str(template.get("posicao_assinatura")).strip().upper()
        if pos_ass not in VALID_POSICOES_ASSINATURA:
            warnings.append(
                {
                    "code": "TEMPLATE_POSICAO_ASSINATURA_INVALID",
                    "severity": "warning",
                    "path": "template.posicao_assinatura",
                    "message": (
                        f"Posição de assinatura inválida '{template.get('posicao_assinatura')}'. "
                        "Valores esperados: 'RODAPE' ou 'LATERAL'."
                    ),
                }
            )

    perguntas = data.get("perguntas", [])
    for idx_p, p in enumerate(perguntas):
        p_path = f"perguntas[{idx_p}]"
        if not isinstance(p, dict):
            warnings.append(
                {
                    "code": "INVALID_QUESTION_ITEM",
                    "severity": "warning",
                    "path": p_path,
                    "message": f"Pergunta #{idx_p + 1} inválida: esperado um objeto JSON.",
                }
            )
            continue

        p_nome = str(p.get("nome") or f"PERGUNTA #{idx_p + 1}")
        is_titulo = bool(p.get("titulo", False))
        respostas_raw = p.get("respostas")
        respostas = respostas_raw if isinstance(respostas_raw, list) else []

        if is_titulo and len(respostas) > 0:
            warnings.append(
                {
                    "code": "TITLE_WITH_ANSWERS",
                    "severity": "warning",
                    "path": f"{p_path}.respostas",
                    "message": (
                        f"A pergunta '{p_nome}' possui titulo=True (divisor de seção), "
                        f"mas contém {len(respostas)} resposta(s). Divisores de seção devem ter respostas=[]."
                    ),
                }
            )
        elif not is_titulo and len(respostas) == 0:
            warnings.append(
                {
                    "code": "QUESTION_WITHOUT_ANSWERS",
                    "severity": "warning",
                    "path": f"{p_path}.respostas",
                    "message": (
                        f"A pergunta '{p_nome}' possui titulo=False, mas não possui respostas vinculadas."
                    ),
                }
            )

        radio_count = 0
        for idx_r, r in enumerate(respostas):
            r_path = f"{p_path}.respostas[{idx_r}]"
            if not isinstance(r, dict):
                warnings.append(
                    {
                        "code": "INVALID_ANSWER_ITEM",
                        "severity": "warning",
                        "path": r_path,
                        "message": f"Resposta #{idx_r + 1} da pergunta '{p_nome}' deve ser um objeto JSON.",
                    }
                )
                continue

            raw_tc = r.get("tipo_campo")
            tc = "" if raw_tc is None else str(raw_tc).strip().upper()
            if tc not in VALID_FIELD_TYPES:
                warnings.append(
                    {
                        "code": "UNKNOWN_FIELD_TYPE",
                        "severity": "warning",
                        "path": f"{r_path}.tipo_campo",
                        "message": (
                            f"Tipo de campo desconhecido '{raw_tc}' na pergunta '{p_nome}'. "
                            f"Valores válidos: {sorted(VALID_FIELD_TYPES)}."
                        ),
                    }
                )
            elif tc == "BOOLEANO_RADIO":
                radio_count += 1

        if radio_count > 2:
            warnings.append(
                {
                    "code": "MULTIPLE_RADIO_GROUPS_RISK",
                    "severity": "warning",
                    "path": f"{p_path}.respostas",
                    "message": (
                        f"A pergunta '{p_nome}' contém {radio_count} opções BOOLEANO_RADIO. "
                        "No Salutem todas as opções BOOLEANO_RADIO da mesma pergunta formam um único "
                        "grupo mutuamente exclusivo; se houver pares independentes (ex.: Sim/Não distintos), "
                        "divida-os em perguntas separadas."
                    ),
                }
            )

    return warnings


# =============================================================================
# Helpers Determinísticos de CRUD e Reordenação (Form Builder)
# =============================================================================


def _ensure_clinical_root(data: dict[str, Any], *, in_place: bool = False) -> dict[str, Any]:
    is_valid, err_msg = validate_clinical_json_structure(data)
    if not is_valid:
        raise ValueError(err_msg)
    return data if in_place else copy.deepcopy(data)


def _renumber_and_normalize_in_place(doc: dict[str, Any]) -> dict[str, Any]:
    """Aplica regras de UPPERCASE e renumera `ordenacao` sequencialmente `1..N`."""
    uppercase_target_fields_in_place(doc)
    perguntas = doc.get("perguntas", [])
    for idx_p, p in enumerate(perguntas, start=1):
        if not isinstance(p, dict):
            continue
        p["titulo"] = bool(p.get("titulo", False))
        p["ordenacao"] = idx_p
        respostas = p.get("respostas")
        if not isinstance(respostas, list):
            respostas = []
            p["respostas"] = respostas
        for idx_r, r in enumerate(respostas, start=1):
            if not isinstance(r, dict):
                continue
            if "tipo_campo" in r and r["tipo_campo"] is not None:
                r["tipo_campo"] = str(r["tipo_campo"]).strip().upper()
            r["ordenacao"] = idx_r
    return doc


def _validate_index(index: int, length: int, entity_label: str) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= length:
        raise IndexError(
            f"Índice de {entity_label} fora do intervalo válido: {index} (tamanho={length})."
        )
    return index


def _apply_permutation(
    items: list[Any],
    new_order: list[int] | int,
    to_index: int | None = None,
    entity_label: str = "item",
) -> list[Any]:
    """
    Reordena `items` aceitando:
    - permutação 0-based `[2, 0, 1]`
    - permutação 1-based `[3, 1, 2]` (valores de `ordenacao`)
    - movimentação unitária `(from_index, to_index)` quando `new_order` é `int`
    """
    n = len(items)
    if isinstance(new_order, int) and not isinstance(new_order, bool):
        if to_index is None:
            raise ValueError(
                f"Para mover um único {entity_label}, informe 'to_index' ou passe a lista 'new_order'."
            )
        src = _validate_index(new_order, n, entity_label)
        dst = _validate_index(to_index, n, entity_label)
        moved_list = list(items)
        elem = moved_list.pop(src)
        moved_list.insert(dst, elem)
        return moved_list

    if not isinstance(new_order, list):
        raise ValueError(f"'new_order' deve ser uma lista de índices para reordenar {entity_label}.")

    if len(new_order) != n:
        raise ValueError(
            f"Tamanho de 'new_order' ({len(new_order)}) difere da quantidade de {entity_label} ({n})."
        )

    if n == 0:
        return []

    if any(not isinstance(i, int) or isinstance(i, bool) for i in new_order):
        raise ValueError(f"'new_order' deve conter apenas inteiros válidos ({entity_label}).")

    expected_zero = set(range(n))
    expected_one = set(range(1, n + 1))
    given = set(new_order)

    if given == expected_zero:
        return [items[i] for i in new_order]
    if given == expected_one:
        return [items[i - 1] for i in new_order]

    raise ValueError(
        f"'new_order' inválido para {entity_label}: esperado permutação exata de 0..{n - 1} ou 1..{n}."
    )


def _prepare_answer_dict(raw_answer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_answer, dict):
        raise ValueError("A resposta fornecida deve ser um dicionário.")
    ans = copy.deepcopy(raw_answer)
    ans.setdefault("label", "")
    raw_tc = ans.get("tipo_campo", "TEXTO")
    tc = str(raw_tc if raw_tc is not None else "TEXTO").strip().upper()
    if tc not in VALID_FIELD_TYPES:
        raise ValueError(
            f"tipo_campo inválido '{tc}'. Valores aceitos: {sorted(VALID_FIELD_TYPES)}."
        )
    ans["tipo_campo"] = tc
    ans.setdefault("campo_obrigatorio", bool(ans.get("obrigatorio", False)))
    ans.setdefault("importa_historico", False)
    ans.setdefault("observacao", False)
    ans.setdefault("minimo", 0)
    return ans


def _prepare_question_dict(raw_question: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_question, dict):
        raise ValueError("A pergunta fornecida deve ser um dicionário.")
    q = copy.deepcopy(raw_question)
    q.setdefault("nome", "")
    q["titulo"] = bool(q.get("titulo", False))
    raw_respostas = q.get("respostas")
    if raw_respostas is None:
        q["respostas"] = []
    elif isinstance(raw_respostas, list):
        q["respostas"] = [_prepare_answer_dict(r) for r in raw_respostas]
    else:
        raise ValueError("O campo 'respostas' da pergunta deve ser uma lista.")
    return q


def add_question(
    data: dict[str, Any],
    question: dict[str, Any],
    index: int | None = None,
    *,
    position: int | None = None,
    in_place: bool = False,
) -> dict[str, Any]:
    """Adiciona uma pergunta na ficha clínica, normaliza UPPERCASE e renumera `ordenacao` `1..N`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    prepared = _prepare_question_dict(question)
    perguntas: list[dict[str, Any]] = doc["perguntas"]

    target_pos = position if position is not None else index
    if target_pos is None:
        perguntas.append(prepared)
    else:
        clamped = max(0, min(int(target_pos), len(perguntas)))
        perguntas.insert(clamped, prepared)

    return _renumber_and_normalize_in_place(doc)


def update_question(
    data: dict[str, Any],
    question_index: int,
    updates: dict[str, Any],
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Atualiza campos de uma pergunta existente (`question_index` 0-based) e renumera `ordenacao`."""
    if not isinstance(updates, dict):
        raise ValueError("'updates' deve ser um dicionário.")
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    idx = _validate_index(question_index, len(perguntas), "pergunta")

    current = copy.deepcopy(perguntas[idx])
    upd = copy.deepcopy(updates)
    if "respostas" in upd and upd["respostas"] is not None:
        if not isinstance(upd["respostas"], list):
            raise ValueError("O campo 'respostas' deve ser uma lista.")
        upd["respostas"] = [_prepare_answer_dict(r) for r in upd["respostas"]]
    current.update(upd)
    perguntas[idx] = current

    return _renumber_and_normalize_in_place(doc)


def delete_question(
    data: dict[str, Any],
    question_index: int,
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Remove a pergunta em `question_index` (0-based) e renumera `ordenacao` `1..N`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    idx = _validate_index(question_index, len(perguntas), "pergunta")
    perguntas.pop(idx)
    return _renumber_and_normalize_in_place(doc)


def reorder_questions(
    data: dict[str, Any],
    new_order: list[int] | int,
    to_index: int | None = None,
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Reordena `perguntas` determinísticamente e renumera `ordenacao` `1..N`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    doc["perguntas"] = _apply_permutation(
        doc["perguntas"], new_order, to_index=to_index, entity_label="pergunta"
    )
    return _renumber_and_normalize_in_place(doc)


def add_answer(
    data: dict[str, Any],
    question_index: int,
    answer: dict[str, Any],
    index: int | None = None,
    *,
    position: int | None = None,
    in_place: bool = False,
) -> dict[str, Any]:
    """Adiciona uma resposta na pergunta `question_index`, preserva UPPERCASE e renumera `1..M`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    q_idx = _validate_index(question_index, len(perguntas), "pergunta")

    prepared_ans = _prepare_answer_dict(answer)
    respostas = perguntas[q_idx].setdefault("respostas", [])
    if not isinstance(respostas, list):
        respostas = []
        perguntas[q_idx]["respostas"] = respostas

    target_pos = position if position is not None else index
    if target_pos is None:
        respostas.append(prepared_ans)
    else:
        clamped = max(0, min(int(target_pos), len(respostas)))
        respostas.insert(clamped, prepared_ans)

    return _renumber_and_normalize_in_place(doc)


def update_answer(
    data: dict[str, Any],
    question_index: int,
    answer_index: int,
    updates: dict[str, Any],
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Atualiza a resposta `answer_index` da pergunta `question_index` e renumera `ordenacao` `1..M`."""
    if not isinstance(updates, dict):
        raise ValueError("'updates' deve ser um dicionário.")
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    q_idx = _validate_index(question_index, len(perguntas), "pergunta")
    respostas: list[dict[str, Any]] = perguntas[q_idx].get("respostas") or []
    a_idx = _validate_index(answer_index, len(respostas), "resposta")

    merged = copy.deepcopy(respostas[a_idx])
    merged.update(copy.deepcopy(updates))
    respostas[a_idx] = _prepare_answer_dict(merged)
    perguntas[q_idx]["respostas"] = respostas

    return _renumber_and_normalize_in_place(doc)


def delete_answer(
    data: dict[str, Any],
    question_index: int,
    answer_index: int,
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Remove a resposta `answer_index` da pergunta `question_index` e renumera `ordenacao` `1..M`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    q_idx = _validate_index(question_index, len(perguntas), "pergunta")
    respostas: list[dict[str, Any]] = perguntas[q_idx].get("respostas") or []
    a_idx = _validate_index(answer_index, len(respostas), "resposta")

    respostas.pop(a_idx)
    return _renumber_and_normalize_in_place(doc)


def reorder_answers(
    data: dict[str, Any],
    question_index: int,
    new_order: list[int] | int,
    to_index: int | None = None,
    *,
    in_place: bool = False,
) -> dict[str, Any]:
    """Reordena as respostas da pergunta `question_index` e renumera `ordenacao` `1..M`."""
    doc = _ensure_clinical_root(data, in_place=in_place)
    perguntas: list[dict[str, Any]] = doc["perguntas"]
    q_idx = _validate_index(question_index, len(perguntas), "pergunta")
    respostas: list[dict[str, Any]] = perguntas[q_idx].get("respostas") or []

    perguntas[q_idx]["respostas"] = _apply_permutation(
        respostas, new_order, to_index=to_index, entity_label="resposta"
    )
    return _renumber_and_normalize_in_place(doc)


__all__ = [
    "PRESERVE_CASE_FIELDS",
    "TEXT_FIELDS_UPPERCASE",
    "VALID_FIELD_TYPES",
    "add_answer",
    "add_question",
    "apply_uppercase_to_text_fields",
    "audit_clinical_json_warnings",
    "delete_answer",
    "delete_question",
    "format_json",
    "load_json_file",
    "parse_and_validate_clinical_json",
    "reorder_answers",
    "reorder_questions",
    "save_json_file",
    "update_answer",
    "update_question",
    "update_shared_dict_in_place",
    "uppercase_target_fields",
    "uppercase_target_fields_in_place",
    "validate_clinical_json_structure",
    "validate_json_text",
]
