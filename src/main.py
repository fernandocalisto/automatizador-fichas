#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ponto de entrada principal da aplicação Automatizador de Fichas em PySide6 (src/main.py).

Fluxo de inicialização (Spec 00):
1. Bootstrap do `QApplication`
2. Exibição imediata do `QSplashScreen` com o logo oficial dos recursos
3. Inicialização dos serviços centrais (`ConfigService`, `LogService`, `ThemeService`, `HelpService`)
4. Criação e exibição da `MainWindow` (`src.gui.main_window`)
5. Garantia de exibição mínima de 1.5s (1500ms) da splash screen e fade-out suave de 300ms após `MainWindow.show()`
"""

from __future__ import annotations

import sys
import time
from typing import Sequence

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

import src.resources.resources_rc  # noqa: F401
from src.gui.main_window import (
    APP_TITLE_BASE,
    APP_VERSION,
    AboutDialog,
    MainApp,
    MainWindow,
    load_app_icon,
    load_app_logo_pixmap,
)
from src.services.config_service import ConfigService
from src.services.help_service import HelpService
from src.services.log_service import LogService
from src.services.theme_service import ThemeService

SPLASH_MIN_DURATION_MS: int = 1500
SPLASH_FADE_DURATION_MS: int = 300


def build_splash_pixmap(width: int = 480, height: int = 280) -> QPixmap:
    """
    Constrói o `QPixmap` da Splash Screen combinando o logo dos recursos,
    título da aplicação e versão sobre um fundo escuro estilizado.
    """
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#0f172a"))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # Borda sutil
    painter.setPen(QColor("#334155"))
    painter.drawRect(0, 0, width - 1, height - 1)

    # Logo centralizado
    logo_pm = load_app_logo_pixmap(height=110)
    if not logo_pm.isNull():
        logo_x = (width - logo_pm.width()) // 2
        logo_y = 32
        painter.drawPixmap(logo_x, logo_y, logo_pm)

    # Título principal
    title_font = QFont("Segoe UI", 15, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.setPen(QColor("#f8fafc"))
    painter.drawText(
        0,
        160,
        width,
        30,
        Qt.AlignmentFlag.AlignCenter,
        APP_TITLE_BASE,
    )

    # Subtítulo e versão
    sub_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
    painter.setFont(sub_font)
    painter.setPen(QColor("#38bdf8"))
    painter.drawText(
        0,
        190,
        width,
        24,
        Qt.AlignmentFlag.AlignCenter,
        f"Ferramenta Interna Salutem — {APP_VERSION}",
    )

    painter.end()
    return canvas


def create_splash_screen() -> QSplashScreen:
    """Cria e configura o `QSplashScreen` inicial com o logo da aplicação."""
    pixmap = build_splash_pixmap()
    splash = QSplashScreen(
        pixmap,
        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.SplashScreen,
    )
    splash.setAccessibleName("Tela de Abertura Automatizador de Fichas")
    splash.showMessage(
        "Iniciando aplicação…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    return splash


def fade_out_splash(
    splash: QSplashScreen,
    main_window: QWidget,
    start_monotonic: float | None = None,
    min_duration_ms: int = SPLASH_MIN_DURATION_MS,
    fade_duration_ms: int = SPLASH_FADE_DURATION_MS,
) -> QPropertyAnimation:
    """
    Aguarda o tempo mínimo restante de exibição (`min_duration_ms` = 1500ms) e executa
    animação de fade-out (`fade_duration_ms` = 300ms) no `QSplashScreen` após `main_window.show()`.
    """
    elapsed_ms = (
        int((time.monotonic() - start_monotonic) * 1000)
        if start_monotonic is not None
        else min_duration_ms
    )
    remaining_ms = max(0, min_duration_ms - elapsed_ms)

    anim = QPropertyAnimation(splash, b"windowOpacity", splash)
    anim.setDuration(fade_duration_ms)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: splash.finish(main_window))

    # Mantém referência na splash para evitar coleta de lixo durante a animação
    setattr(splash, "_fade_animation", anim)

    if remaining_ms > 0:
        QTimer.singleShot(remaining_ms, anim.start)
    else:
        anim.start()

    return anim


def get_or_create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Retorna a instância ativa de `QApplication` ou cria uma nova configurada."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setOrganizationName(ConfigService.ORGANIZATION)
    app.setApplicationName(ConfigService.APPLICATION)
    app.setApplicationDisplayName(APP_TITLE_BASE)
    app.setApplicationVersion(APP_VERSION)

    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    return app


def main(argv: Sequence[str] | None = None) -> int:
    """
    Função principal de bootstrap PySide6:
    1. Inicializa `QApplication`
    2. Exibe `QSplashScreen` imediatamente
    3. Inicializa `ConfigService`, `LogService`, `ThemeService` e `HelpService`
    4. Instancia e exibe `MainWindow`
    5. Executa fade-out (300ms) da splash após mínimo de 1.5s
    """
    app = get_or_create_application(argv)

    # 1. QSplashScreen FIRST
    splash_start = time.monotonic()
    splash = create_splash_screen()
    splash.show()
    app.processEvents()

    # 2. Inicializa Serviços
    splash.showMessage(
        "Carregando configurações…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    app.processEvents()
    config_service = ConfigService()

    splash.showMessage(
        "Inicializando serviço de logs…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    app.processEvents()
    LogService.setup(
        app_name=ConfigService.APPLICATION,
        config=config_service.config,
    )
    log_service = LogService()

    splash.showMessage(
        "Aplicando tema visual…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    app.processEvents()
    theme_service = ThemeService(config_service)
    theme_service.apply_app_theme(config_service.config.app_theme, persist=False)

    splash.showMessage(
        "Carregando serviço de ajuda…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    app.processEvents()
    help_service = HelpService()

    # 3. Cria MainWindow e exibe
    splash.showMessage(
        "Construindo interface principal…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#94a3b8"),
    )
    app.processEvents()
    window = MainWindow(
        config_service=config_service,
        theme_service=theme_service,
        log_service=log_service,
        help_service=help_service,
    )
    window.show()
    app.processEvents()

    # 4. Fade-out da Splash após MainWindow.show() (respeitando 1.5s mín. + 300ms fade)
    fade_out_splash(
        splash=splash,
        main_window=window,
        start_monotonic=splash_start,
        min_duration_ms=SPLASH_MIN_DURATION_MS,
        fade_duration_ms=SPLASH_FADE_DURATION_MS,
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
