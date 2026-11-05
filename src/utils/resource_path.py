#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitário para localização de recursos embutidos (src/utils/resource_path.py).

Suporta execução direta via Python e executáveis empacotados via PyInstaller
(utilizando sys._MEIPASS quando disponível).
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str | Path) -> Path:
    """
    Retorna o caminho absoluto para um recurso do projeto, funcionando tanto
    em ambiente de desenvolvimento quanto no executável gerado pelo PyInstaller.
    """
    rel = Path(relative_path)

    # 1. Se estiver rodando empacotado pelo PyInstaller (_MEIPASS)
    base_meipass = getattr(sys, "_MEIPASS", None)
    if base_meipass:
        meipass_root = Path(base_meipass)
        candidates = [
            meipass_root / rel,
            meipass_root / "src" / "resources" / rel.name,
            meipass_root / "resources" / rel.name,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return meipass_root / rel

    # 2. Ambiente de desenvolvimento: procura a partir da raiz do projeto e src/resources
    module_dir = Path(__file__).resolve().parent        # src/utils
    src_dir = module_dir.parent                         # src
    project_root = src_dir.parent                       # raiz do projeto

    search_candidates = [
        project_root / rel,
        src_dir / "resources" / rel,
        src_dir / "resources" / rel.name,
        project_root / "resources" / rel.name,
        src_dir / rel,
        project_root.parent / "Automatiza Ficha - Exemplos" / rel.name,
    ]

    for candidate in search_candidates:
        if candidate.exists():
            return candidate

    return project_root / rel


def get_skill_file_path() -> Path:
    """Retorna o Path resolvido para o arquivo SKILL.md."""
    return resource_path("SKILL.md")
