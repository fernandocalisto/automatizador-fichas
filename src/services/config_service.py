# -*- coding: utf-8 -*-
"""
Serviço de configuração centralizado (src/services/config_service.py).

Fornece fonte única de verdade para configurações da aplicação utilizando
`QSettings` (organization="FernandoCalisto", application="AutomatizadorFichas")
com fallback e sincronismo em JSON (`%LOCALAPPDATA%/AutomatizadorFichas/config.json`)
e padrão Observer (`subscribe` / `unsubscribe`).
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSettings

logger = logging.getLogger("services.config_service")


def _default_app_data_dir() -> Path:
    """Retorna o diretório em AppData/Local para armazenamento da aplicação."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "AutomatizadorFichas"


@dataclass
class AppConfig:
    """Schema de configuração global do Automatizador de Fichas v0.2.0."""

    # General
    language: str = "pt_BR"
    auto_check_updates: bool = True
    last_update_check: str = ""
    ignored_update_version: str = ""
    show_tour_on_startup: bool = True

    # Theme
    app_theme: str = "system"        # "light" | "dark" | "system"
    editor_theme: str = "vscode"     # "monokai" | "dracula" | "github" | "solarized" | "vscode"
    font_family: str = "JetBrains Mono"
    font_size: int = 11

    # Editor
    tab_size: int = 4
    show_line_numbers: bool = True
    show_whitespace: bool = False
    enable_folding: bool = True
    autocomplete_delay_ms: int = 150

    # Select Options (spec_05)
    boolean_style: str = "coalesce_bool_or"  # "coalesce_bool_or" | "x_empty" | "sim_nao" | "1_0"
    column_naming: str = "label_only"        # "pergunta_label" | "label_only" | "label_sufixo"
    include_observations: bool = True
    include_metadata: bool = False
    include_all_blocks: bool = True
    include_cabecalho: bool = True
    include_paciente: bool = True
    include_profissional: bool = True
    include_atendimento: bool = True
    select_jasper_options: dict[str, Any] = field(default_factory=dict)

    # Regex (spec_06)
    use_custom_regex: bool = False
    custom_regex_path: str = ""

    # Logging (spec_09)
    log_level: str = "INFO"          # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    log_module_levels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converte a configuração para dicionário serializável em JSON."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        """Cria uma instância validada de `AppConfig` a partir de um dicionário."""
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in raw or raw[f.name] is None:
                continue
            val = raw[f.name]
            default_val = getattr(defaults, f.name)
            try:
                if isinstance(default_val, bool):
                    if isinstance(val, str):
                        kwargs[f.name] = val.strip().lower() in ("true", "1", "yes", "on")
                    else:
                        kwargs[f.name] = bool(val)
                elif isinstance(default_val, int):
                    kwargs[f.name] = int(val)
                elif isinstance(default_val, str):
                    kwargs[f.name] = str(val)
                elif isinstance(default_val, dict):
                    if isinstance(val, str):
                        parsed = json.loads(val)
                        kwargs[f.name] = dict(parsed) if isinstance(parsed, dict) else {}
                    elif isinstance(val, dict):
                        if f.name == "log_module_levels":
                            kwargs[f.name] = {str(k): str(v) for k, v in val.items()}
                        else:
                            kwargs[f.name] = {str(k): v for k, v in val.items()}
                else:
                    kwargs[f.name] = val
            except (ValueError, TypeError, json.JSONDecodeError):
                logger.warning(
                    "Valor inválido para config '%s': %r. Usando padrão %r.",
                    f.name,
                    val,
                    default_val,
                )
        return cls(**kwargs)


ConfigSchema = AppConfig


class ConfigService:
    """
    Serviço gerenciador de configurações com `QSettings`, fallback JSON e padrão Observer.

    Args:
        organization: Nome da organização no QSettings (padrão: "FernandoCalisto").
        application: Nome da aplicação no QSettings (padrão: "AutomatizadorFichas").
        json_path: Caminho opcional para o arquivo `config.json` de fallback.
    """

    ORGANIZATION = "FernandoCalisto"
    APPLICATION = "AutomatizadorFichas"

    def __init__(
        self,
        organization: str = ORGANIZATION,
        application: str = APPLICATION,
        json_path: Path | None = None,
    ) -> None:
        self.organization = organization
        self.application = application
        self.json_path = json_path or (_default_app_data_dir() / "config.json")
        self._qsettings = QSettings(self.organization, self.application)
        self._config: AppConfig = AppConfig()
        self._subscribers: dict[int, tuple[str, Callable[..., None]]] = {}
        self._next_token: int = 1
        self.load()

    @property
    def config(self) -> AppConfig:
        """Retorna a instância atual de `AppConfig`."""
        return self._config

    @property
    def settings(self) -> QSettings:
        """Retorna a instância subjacente de `QSettings`."""
        return self._qsettings

    def load(self) -> AppConfig:
        """
        Carrega as configurações do `QSettings` ou do arquivo JSON de fallback.

        Returns:
            Instância de `AppConfig` carregada.
        """
        raw_data: dict[str, Any] = {}

        # 1. Tenta carregar do JSON de fallback primeiro como base
        if self.json_path.exists():
            try:
                content = self.json_path.read_text(encoding="utf-8")
                loaded_json = json.loads(content)
                if isinstance(loaded_json, dict):
                    raw_data.update(loaded_json)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Falha ao ler config JSON em %s: %s", self.json_path, exc)

        # 2. Sobrepõe com chaves salvas no QSettings (se presentes)
        try:
            qkeys = set(self._qsettings.allKeys())
            for f in fields(AppConfig):
                qkey = f"config/{f.name}"
                if qkey in qkeys:
                    val = self._qsettings.value(qkey)
                    if val is not None:
                        raw_data[f.name] = val
                elif f.name in qkeys:
                    val = self._qsettings.value(f.name)
                    if val is not None:
                        raw_data[f.name] = val
        except Exception as exc:
            logger.warning("Falha ao ler QSettings, usando fallback JSON: %s", exc)

        self._config = AppConfig.from_dict(raw_data)
        return self._config

    def save(self, config: AppConfig | None = None) -> None:
        """
        Persiste o `AppConfig` tanto no `QSettings` quanto no arquivo JSON de fallback.

        Args:
            config: Nova instância de `AppConfig` (se omitida, salva a instância atual).
        """
        previous_dict = self._config.to_dict()
        if config is not None:
            self._config = copy.deepcopy(config)

        data = self._config.to_dict()

        # 1. Salva no QSettings
        try:
            for key, value in data.items():
                if isinstance(value, dict):
                    self._qsettings.setValue(f"config/{key}", json.dumps(value, ensure_ascii=False))
                else:
                    self._qsettings.setValue(f"config/{key}", value)
            self._qsettings.sync()
        except Exception as exc:
            logger.warning("Não foi possível salvar no QSettings: %s", exc)

        # 2. Salva no arquivo JSON de fallback
        try:
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            self.json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Não foi possível salvar config JSON em %s: %s", self.json_path, exc)

        # 3. Notifica inscritos das chaves que mudaram
        for key, new_val in data.items():
            if previous_dict.get(key) != new_val:
                self._notify(key, new_val)

    def reset_to_defaults(self) -> AppConfig:
        """
        Restaura todas as configurações para os valores padrão de fábrica e salva.

        Returns:
            Nova instância de `AppConfig` com valores padrão.
        """
        defaults = AppConfig()
        try:
            self._qsettings.remove("config")
            self._qsettings.sync()
        except Exception as exc:
            logger.warning("Erro ao limpar grupo config no QSettings: %s", exc)
        self.save(defaults)
        return self._config

    def get(self, key: str, default: Any = None) -> Any:
        """
        Obtém o valor de uma chave de configuração.

        Args:
            key: Nome do campo em `AppConfig` ou chave customizada no `QSettings`.
            default: Valor padrão caso a chave não exista.

        Returns:
            Valor armazenado para a chave.
        """
        if hasattr(self._config, key):
            return getattr(self._config, key)
        return self._qsettings.value(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        """
        Define o valor de uma chave de configuração e notifica observadores.

        Args:
            key: Nome do campo em `AppConfig` ou chave customizada.
            value: Novo valor a definir.
            auto_save: Se `True`, persiste imediatamente em disco/registro.
        """
        if hasattr(self._config, key):
            old_val = getattr(self._config, key)
            setattr(self._config, key, value)
            if auto_save:
                self.save(self._config)
            if old_val != value:
                self._notify(key, value)
        else:
            self._qsettings.setValue(key, value)
            if auto_save:
                self._qsettings.sync()
            self._notify(key, value)

    def subscribe(self, key: str, callback: Callable[..., None]) -> int:
        """
        Inscreve um callback para ser notificado quando `key` (ou `"*"` para qualquer chave) mudar.

        Args:
            key: Nome da chave de configuração ou `"*"` para todas.
            callback: Função chamada na alteração (`callback(value)` ou `callback(key, value)`).

        Returns:
            Token inteiro de inscrição para uso em `unsubscribe(token)`.
        """
        token = self._next_token
        self._next_token += 1
        self._subscribers[token] = (key, callback)
        return token

    def unsubscribe(self, token: int) -> None:
        """
        Remove uma inscrição ativa pelo token retornado em `subscribe`.

        Args:
            token: Identificador numérico da inscrição.
        """
        self._subscribers.pop(token, None)

    def get_select_jasper_options(self) -> dict[str, Any]:
        """Retorna o dicionário consolidado de opções SELECT Jasper persistidas."""
        cfg = self._config
        stored = cfg.select_jasper_options if isinstance(cfg.select_jasper_options, dict) else {}
        return {
            "boolean_style": str(stored.get("boolean_style", cfg.boolean_style) or "coalesce_bool_or"),
            "column_naming": str(stored.get("column_naming", cfg.column_naming) or "label_only"),
            "include_obs": bool(stored.get("include_obs", cfg.include_observations)),
            "include_metadata": bool(stored.get("include_metadata", cfg.include_metadata)),
            "include_all_blocks": bool(stored.get("include_all_blocks", cfg.include_all_blocks)),
            "include_cabecalho": bool(stored.get("include_cabecalho", cfg.include_cabecalho)),
            "include_paciente": bool(stored.get("include_paciente", cfg.include_paciente)),
            "include_profissional": bool(stored.get("include_profissional", cfg.include_profissional)),
            "include_atendimento": bool(stored.get("include_atendimento", cfg.include_atendimento)),
        }

    def save_select_jasper_options(self, options: dict[str, Any]) -> None:
        """Persiste as opções SELECT Jasper no `AppConfig`, `QSettings` e `config.json`."""
        normalized = {
            "boolean_style": str(options.get("boolean_style", self._config.boolean_style) or "coalesce_bool_or"),
            "column_naming": str(options.get("column_naming", self._config.column_naming) or "label_only"),
            "include_obs": bool(options.get("include_obs", options.get("include_observations", True))),
            "include_metadata": bool(options.get("include_metadata", False)),
            "include_all_blocks": bool(options.get("include_all_blocks", True)),
            "include_cabecalho": bool(options.get("include_cabecalho", True)),
            "include_paciente": bool(options.get("include_paciente", True)),
            "include_profissional": bool(options.get("include_profissional", True)),
            "include_atendimento": bool(options.get("include_atendimento", True)),
        }
        self._config.boolean_style = normalized["boolean_style"]
        self._config.column_naming = normalized["column_naming"]
        self._config.include_observations = normalized["include_obs"]
        self._config.include_metadata = normalized["include_metadata"]
        self._config.include_all_blocks = normalized["include_all_blocks"]
        self._config.include_cabecalho = normalized["include_cabecalho"]
        self._config.include_paciente = normalized["include_paciente"]
        self._config.include_profissional = normalized["include_profissional"]
        self._config.include_atendimento = normalized["include_atendimento"]
        self._config.select_jasper_options = dict(normalized)
        self.save(self._config)

    def _notify(self, key: str, value: Any) -> None:
        """Notifica os callbacks inscritos para a chave informada."""
        for sub_key, callback in list(self._subscribers.values()):
            if sub_key in (key, "*"):
                try:
                    if sub_key == "*":
                        try:
                            callback(key, value)
                        except TypeError:
                            callback(value)
                    else:
                        callback(value)
                except Exception as exc:
                    logger.error("Erro ao executar observer para chave '%s': %s", key, exc)
