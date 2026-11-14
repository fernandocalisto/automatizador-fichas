# -*- coding: utf-8 -*-
"""Configuração compartilhada do pytest para testes PySide6 em modo headless (offscreen)."""

from __future__ import annotations

import os
from typing import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qapp() -> Iterator[QApplication]:
    """Garante que uma instância de QApplication exista para todos os testes."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest", "-platform", "offscreen"])
    yield app  # type: ignore[misc]
