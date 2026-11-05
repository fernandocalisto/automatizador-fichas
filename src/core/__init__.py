#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pacote core de geração SQL do Automatizador de Fichas (src/core/__init__.py).
"""

from src.core.sql_insert import (
    POSTGRES_FUNCTIONS,
    POSTGRES_KEYWORDS,
    TIPOS_VALIDOS,
    apply_syntax_highlighting,
    generate_insert_sql,
    limpar_ocr_texto,
    validate_postgres_syntax,
)
from src.core.sql_select import (
    generate_select_jasper,
    gerar_projecao_resposta,
    gerar_secao_perguntas,
    normalizar_slug,
    sufixo_tipo,
)

__all__ = [
    "POSTGRES_FUNCTIONS",
    "POSTGRES_KEYWORDS",
    "TIPOS_VALIDOS",
    "apply_syntax_highlighting",
    "generate_insert_sql",
    "generate_select_jasper",
    "gerar_projecao_resposta",
    "gerar_secao_perguntas",
    "limpar_ocr_texto",
    "normalizar_slug",
    "sufixo_tipo",
    "validate_postgres_syntax",
]
