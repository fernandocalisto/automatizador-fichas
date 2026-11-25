# -*- coding: utf-8 -*-
"""
Gerenciamento e aplicação de regras customizadas de higienização OCR / substituição de texto
(`backend/app/core/custom_regex.py`).

Formato suportado (lista JSON ou objeto `{"rules": [...]}`):
    [
        {
            "pattern": "\\bBonba\\b",
            "replacement": "Bomba",
            "is_regex": true,
            "ignore_case": true
        }
    ]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CustomRegexRule:
    """Representa uma regra individual de substituição textual ou expressão regular."""

    pattern: str
    replacement: str = ""
    is_regex: bool = True
    ignore_case: bool = True
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "pattern": self.pattern,
            "replacement": self.replacement,
            "is_regex": self.is_regex,
            "ignore_case": self.ignore_case,
        }
        if not self.enabled:
            data["enabled"] = False
        if self.description:
            data["description"] = self.description
        return data


def validate_custom_regex_rules(raw_rules: Any) -> list[CustomRegexRule]:
    """
    Valida e normaliza uma coleção de regras customizadas de OCR.

    Aceita uma lista de dicts/`CustomRegexRule` ou um objeto `{"rules": [...]}`.
    Levanta `ValueError` caso o formato ou alguma expressão regular seja inválida.
    """
    if raw_rules is None:
        return []

    if isinstance(raw_rules, dict):
        if "rules" not in raw_rules or not isinstance(raw_rules["rules"], list):
            raise ValueError(
                "Estrutura de regras OCR inválida: esperado uma lista JSON ou objeto com chave 'rules'."
            )
        items = raw_rules["rules"]
    elif isinstance(raw_rules, list):
        items = raw_rules
    else:
        raise ValueError(
            "Regras customizadas de OCR devem ser fornecidas como lista ou objeto {'rules': [...]}."
        )

    validated: list[CustomRegexRule] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, CustomRegexRule):
            rule = item
        elif isinstance(item, dict):
            pattern = item.get("pattern")
            if not isinstance(pattern, str) or pattern == "":
                raise ValueError(
                    f"Regra customizada #{idx} inválida: 'pattern' deve ser uma string não vazia."
                )

            raw_replacement = item.get("replacement", "")
            if raw_replacement is None:
                replacement = ""
            elif isinstance(raw_replacement, str):
                replacement = raw_replacement
            else:
                raise ValueError(
                    f"Regra customizada #{idx} inválida: 'replacement' deve ser uma string."
                )

            is_regex = bool(item.get("is_regex", True))
            ignore_case = bool(item.get("ignore_case", True))
            enabled = bool(item.get("enabled", True))
            description = str(item.get("description") or "")

            rule = CustomRegexRule(
                pattern=pattern,
                replacement=replacement,
                is_regex=is_regex,
                ignore_case=ignore_case,
                enabled=enabled,
                description=description,
            )
        else:
            raise ValueError(
                f"Regra customizada #{idx} inválida: esperado um objeto JSON."
            )

        if rule.is_regex:
            flags = re.IGNORECASE if rule.ignore_case else 0
            try:
                re.compile(rule.pattern, flags)
            except re.error as exc:
                raise ValueError(
                    f"Expressão regular inválida na regra #{idx} ('{rule.pattern}'): {exc}"
                ) from exc

        validated.append(rule)

    return validated


def load_custom_regex_rules(
    source: str | Path | list[Any] | dict[str, Any] | None,
) -> list[CustomRegexRule]:
    """
    Carrega e valida regras customizadas de OCR a partir de caminho de arquivo JSON,
    lista de dicionários/regras ou dicionário `{"rules": [...]}`.
    """
    if source is None:
        return []

    if isinstance(source, (list, dict)):
        return validate_custom_regex_rules(source)

    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(
                f"Arquivo de regras customizadas de OCR não encontrado: {path}"
            )
        raw_content = path.read_text(encoding="utf-8-sig").strip()
        if not raw_content:
            return []
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON inválido no arquivo de regras customizadas '{path}': {exc}"
            ) from exc
        return validate_custom_regex_rules(parsed)

    raise ValueError("Fonte de regras customizadas de OCR inválida.")


def save_custom_regex_rules(
    file_path: str | Path,
    rules: list[dict[str, Any] | CustomRegexRule],
) -> list[CustomRegexRule]:
    """Valida e grava regras customizadas de OCR em arquivo JSON UTF-8."""
    validated = validate_custom_regex_rules(rules)
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.to_dict() for r in validated]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return validated


def apply_custom_regex_rules(
    text: str,
    rules: list[dict[str, Any] | CustomRegexRule] | None,
) -> str:
    """Aplica sequencialmente as regras customizadas de substituição sobre `text`."""
    if not text or not rules:
        return text

    validated = (
        rules
        if all(isinstance(r, CustomRegexRule) for r in rules)
        else validate_custom_regex_rules(rules)
    )

    result = text
    for rule in validated:
        if not rule.enabled:
            continue
        flags = re.IGNORECASE if rule.ignore_case else 0
        if rule.is_regex:
            compiled = re.compile(rule.pattern, flags)
            result = compiled.sub(rule.replacement, result)
        else:
            if rule.ignore_case:
                compiled = re.compile(re.escape(rule.pattern), re.IGNORECASE)
                result = compiled.sub(lambda _: rule.replacement, result)
            else:
                result = result.replace(rule.pattern, rule.replacement)

    return result


__all__ = [
    "CustomRegexRule",
    "apply_custom_regex_rules",
    "load_custom_regex_rules",
    "save_custom_regex_rules",
    "validate_custom_regex_rules",
]
