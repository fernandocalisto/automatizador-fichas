# -*- coding: utf-8 -*-
"""
Serviço de Logging Rotativo e Excepthook Global (src/services/log_service.py).

Configura logging em `%LOCALAPPDATA%/AutomatizadorFichas/logs/app.log` com
`RotatingFileHandler` (5 MB x 10 backups, UTF-8), níveis configuráveis por módulo,
captura global de exceções não tratadas (`sys.excepthook`) e emissão para a UI.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from src.services.config_service import AppConfig

DEFAULT_MODULE_LEVELS: dict[str, str] = {
    "sql_insert": "INFO",
    "sql_select": "INFO",
    "connections": "DEBUG",
    "autocomplete": "DEBUG",
    "schema_service": "INFO",
    "update_service": "INFO",
    "gui": "INFO",
    "services": "INFO",
}

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 10


class QtLogSignalBridge(QObject):
    """Ponte Qt para emitir mensagens de log em tempo real para o painel inferior."""

    log_emitted = Signal(str, str)  # (level_name, formatted_message)


class QtSignalLogHandler(logging.Handler):
    """Handler de logging que encaminha registros formatados para um `QtLogSignalBridge`."""

    def __init__(self, bridge: QtLogSignalBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.bridge.log_emitted.emit(record.levelname, msg)
        except Exception:
            self.handleError(record)


def get_default_log_dir(app_name: str = "AutomatizadorFichas") -> Path:
    """Retorna o diretório padrão de logs em `%LOCALAPPDATA%/<app_name>/logs`."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / app_name / "logs"


class LogService:
    """
    Serviço gerenciador de logging rotativo, níveis por módulo e `sys.excepthook`.
    """

    _initialized: bool = False
    _log_file_path: Path | None = None
    _bridge: QtLogSignalBridge | None = None
    _file_handler: RotatingFileHandler | None = None

    def __init__(self, log_dir: Path | None = None) -> None:
        self._custom_log_dir = log_dir

    @classmethod
    def get_signal_bridge(cls) -> QtLogSignalBridge:
        """Retorna o `QtLogSignalBridge` global para assinatura na UI."""
        if cls._bridge is None:
            cls._bridge = QtLogSignalBridge()
        return cls._bridge

    @classmethod
    def get_log_file_path(cls) -> Path:
        """Retorna o caminho completo do arquivo `app.log` ativo."""
        if cls._log_file_path is None:
            cls._log_file_path = get_default_log_dir() / "app.log"
        return cls._log_file_path

    @classmethod
    def setup(
        cls,
        app_name: str = "AutomatizadorFichas",
        config: AppConfig | None = None,
        log_dir: Path | None = None,
    ) -> logging.Logger:
        """
        Configura o logger raiz, `RotatingFileHandler` (5MB x 10), níveis por módulo e `sys.excepthook`.

        Args:
            app_name: Nome da aplicação para criação do diretório de logs.
            config: Instância de `AppConfig` contendo `log_level` e `log_module_levels`.
            log_dir: Diretório customizado opcional (útil para testes).

        Returns:
            Logger principal configurado.
        """
        target_dir = log_dir or get_default_log_dir(app_name)
        target_dir.mkdir(parents=True, exist_ok=True)
        log_file = target_dir / "app.log"
        cls._log_file_path = log_file

        root_logger = logging.getLogger()
        base_level_name = (config.log_level if config else "INFO").upper()
        base_level = getattr(logging, base_level_name, logging.INFO)
        root_logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(LOG_FORMAT)

        # Remove RotatingFileHandlers anteriores caso setup seja chamado novamente
        for handler in list(root_logger.handlers):
            if isinstance(handler, (RotatingFileHandler, QtSignalLogHandler)):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(base_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        cls._file_handler = file_handler

        # Handler para UI (Painel Inferior -> Saída/Log)
        bridge = cls.get_signal_bridge()
        qt_handler = QtSignalLogHandler(bridge)
        qt_handler.setLevel(base_level)
        qt_handler.setFormatter(formatter)
        root_logger.addHandler(qt_handler)

        # Níveis por módulo
        module_levels = dict(DEFAULT_MODULE_LEVELS)
        if config and config.log_module_levels:
            module_levels.update(config.log_module_levels)

        for module_name, level_str in module_levels.items():
            cls.set_module_level(module_name, level_str)

        # Instala excepthook global
        cls.install_excepthook()
        cls._initialized = True

        app_logger = cls.get_logger(app_name)
        app_logger.info(
            "LogService inicializado em '%s' (nível=%s, maxBytes=%d, backups=%d)",
            log_file,
            base_level_name,
            MAX_BYTES,
            BACKUP_COUNT,
        )
        return app_logger

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Obtém um logger nomeado.

        Args:
            name: Nome do módulo ou componente.

        Returns:
            Instância de `logging.Logger`.
        """
        return logging.getLogger(name)

    @classmethod
    def set_module_level(cls, module: str, level: str) -> None:
        """
        Define o nível de log para um módulo específico.

        Args:
            module: Nome do logger/módulo (ex.: `"sql_insert"`, `"gui"`).
            level: Nível de log (`"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`).
        """
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        logging.getLogger(module).setLevel(numeric_level)
        logging.getLogger(f"src.{module}").setLevel(numeric_level)

    @classmethod
    def install_excepthook(
        cls,
        custom_callback: Callable[[type[BaseException], BaseException, TracebackType | None], None]
        | None = None,
    ) -> None:
        """
        Instala o `sys.excepthook` global para registrar exceções não tratadas em `app.log`.

        Args:
            custom_callback: Callback adicional opcional invocado após registrar o erro.
        """

        def _handle_exception(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_tb: TracebackType | None,
        ) -> None:
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_tb)
                return

            logger = cls.get_logger("excepthook")
            logger.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_tb),
            )
            if cls._file_handler is not None:
                try:
                    cls._file_handler.flush()
                except Exception:
                    pass
            if custom_callback is not None:
                try:
                    custom_callback(exc_type, exc_value, exc_tb)
                except Exception:
                    pass

        sys.excepthook = _handle_exception
