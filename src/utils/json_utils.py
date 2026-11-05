#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitários de manipulação, validação e formatação de JSON (src/utils/json_utils.py).

Implementa:
- uppercase_target_fields (e alias apply_uppercase_to_text_fields): conversão recursiva
  de campos textuais alvo (label, labels, nome, name, descricao, description, titulo,
  title, valor_texto) para UPPERCASE, preservando tipos primitivos (booleanos, números)
  e campos de código estritos (layout, id, cid_codigo, etc.).
- Validação sintática de JSON (com linha e coluna) e validação de estrutura mínima
  de ficha clínica (chaves 'template' como dict e 'perguntas' como list).
"""

from __future__ import annotations

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


def update_shared_dict_in_place(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """
    Atualiza o dicionário compartilhado `target` in-place com os dados de `source`,
    mantendo a mesma referência de objeto Python entre as abas.
    """
    if target is source:
        converted = uppercase_target_fields(target)
        target.clear()
        target.update(converted)
        return target

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
