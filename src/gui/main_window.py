#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de compatibilidade da Janela Principal (src/gui/main_window.py).
Reexporta `MainApp` e `MainWindow` de `src.main`.
"""

from src.main import MainApp, MainWindow, main

__all__ = ["MainApp", "MainWindow", "main"]
