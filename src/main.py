#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ponto de entrada principal da aplicação Automatizador de Fichas (src/main.py).

Implementa a classe `MainApp(tk.Tk)` conforme spec_json_editor.md:
- Inicia exibindo a Tela Inicial (`LandingFrame`).
- Mantém um único dicionário compartilhado (`self.json_data: dict[str, Any]`) como
  ponto único de verdade entre as abas.
- Ao carregar ou colar um JSON válido na Tela Inicial, faz a transição para o
  `ttk.Notebook` com duas abas sincronizadas:
  1. Editar JSON (`JsonEditorTab`)
  2. Perguntas & Respostas (`PerguntasTab`)
- Suporta o botão "Voltar à Tela Inicial" em ambas as abas.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from src.gui.json_editor_tab import JsonEditorTab
from src.gui.landing import LandingFrame
from src.gui.perguntas_tab import PerguntasTab
from src.gui.sql_insert_tab import SqlInsertTab
from src.gui.sql_select_tab import SqlSelectTab
from src.utils.json_utils import update_shared_dict_in_place


class MainApp(tk.Tk):
    """
    Janela principal do Automatizador de Fichas.
    Gerencia a transição entre a Tela Inicial (Landing) e o Notebook de duas abas,
    compartilhando a mesma instância de dicionário Python (`self.json_data`).
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("Automatizador de Fichas – Carregar JSON")
        self.geometry("1080x740")
        self.minsize(860, 580)

        # Único ponto de verdade do JSON compartilhado in-place entre as abas
        self.json_data: dict[str, Any] = {}
        self.current_view: str = "landing"
        self._listeners: list[Callable[[dict[str, Any] | None], None]] = []

        self._build_ui()
        self.show_landing()

    def _build_ui(self) -> None:
        """Cria o frame da Tela Inicial e o container do Notebook com as duas abas."""
        # 1. Tela Inicial (Landing)
        self.landing_frame = LandingFrame(
            self,
            on_json_loaded=self._on_landing_json_loaded,
        )

        # 2. Container Principal (exibido após JSON válido carregado)
        self.main_container = ttk.Frame(self)

        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Aba 1 – Editar JSON
        self.json_editor_tab = JsonEditorTab(
            self.notebook,
            shared_json=self.json_data,
            on_json_changed=self._on_json_updated_from_editor_tab,
            on_back_to_landing=self.show_landing,
        )
        self.notebook.add(self.json_editor_tab, text="Editar JSON")

        # Aba 2 – Perguntas & Respostas
        self.perguntas_tab = PerguntasTab(
            self.notebook,
            shared_json=self.json_data,
            on_json_changed=self._on_json_updated_from_perguntas_tab,
            on_back_to_landing=self.show_landing,
        )
        self.notebook.add(self.perguntas_tab, text="Perguntas & Respostas")

        # Aba 3 – Gerar SQL INSERT
        self.sql_insert_tab = SqlInsertTab(
            self.notebook,
            shared_json=self.json_data,
            on_back_to_landing=self.show_landing,
        )
        self.notebook.add(self.sql_insert_tab, text="Gerar SQL INSERT")

        # Aba 4 – Gerar SELECT Jasper
        self.sql_select_tab = SqlSelectTab(
            self.notebook,
            shared_json=self.json_data,
            on_back_to_landing=self.show_landing,
        )
        self.notebook.add(self.sql_select_tab, text="Gerar SELECT Jasper")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # -------------------------------------------------------------------------
    # Navegação entre Tela Inicial e Janela Principal com Abas
    # -------------------------------------------------------------------------
    def show_landing(self) -> None:
        """Oculta o Notebook de abas, limpa o estado não salvo e exibe a Tela Inicial."""
        self.main_container.pack_forget()
        self.json_data.clear()
        self.sql_insert_tab.clear_preview()
        self.sql_select_tab.clear_preview()
        self.landing_frame.status_var.set("Aguardando JSON…")
        self.landing_frame.pack(fill=tk.BOTH, expand=True)
        self.title("Automatizador de Fichas – Carregar JSON")
        self.current_view = "landing"
        self._notify_listeners()

    def show_notebook(self) -> None:
        """Oculta a Tela Inicial e exibe o Notebook com as abas Editar JSON e Perguntas & Respostas."""
        self.landing_frame.pack_forget()
        self.main_container.pack(fill=tk.BOTH, expand=True)
        tmpl = self.json_data.get("template", {})
        nome_ficha = (
            tmpl.get("nome", "Ficha Carregada")
            if isinstance(tmpl, dict)
            else "Ficha Carregada"
        )
        self.title(f"Automatizador de Fichas – {nome_ficha}")
        self.current_view = "notebook"

    def _on_landing_json_loaded(
        self, validated_data: dict[str, Any], source_path: Path | None = None
    ) -> None:
        """
        Callback invocado pela LandingFrame quando um JSON válido é carregado ou colado.
        Popula o dicionário compartilhado in-place, sincroniza as abas e abre o Notebook.
        """
        update_shared_dict_in_place(self.json_data, validated_data)
        self.json_editor_tab.current_file = source_path
        self.json_editor_tab.set_json_data(
            self.json_data,
            update_original=True,
            apply_uppercase=True,
            notify=False,
        )
        self.perguntas_tab.refresh_from_shared()
        self.sql_insert_tab.clear_preview()
        self.sql_select_tab.clear_preview()
        self.show_notebook()
        self.notebook.select(0)
        self._notify_listeners()

    # -------------------------------------------------------------------------
    # Sincronização do Dicionário Compartilhado entre Abas
    # -------------------------------------------------------------------------
    def _on_json_updated_from_editor_tab(self, updated_data: dict[str, Any]) -> None:
        """Quando a Aba 1 (Editar JSON) valida/formata, atualiza a Aba 2 (Perguntas & Respostas)."""
        if updated_data is not self.json_data:
            update_shared_dict_in_place(self.json_data, updated_data)
        self.perguntas_tab.refresh_from_shared()
        self._notify_listeners()

    def _on_json_updated_from_perguntas_tab(self, updated_data: dict[str, Any]) -> None:
        """Quando a Aba 2 (Perguntas & Respostas) edita campos, atualiza o texto da Aba 1."""
        if updated_data is not self.json_data:
            update_shared_dict_in_place(self.json_data, updated_data)
        self.json_editor_tab.refresh_from_shared()
        self._notify_listeners()

    def _on_tab_changed(self, _event: Any = None) -> None:
        """Garante que ao alternar de aba os dados mais recentes estejam visíveis."""
        if not self.json_data:
            return
        selected_idx = self.notebook.index(self.notebook.select())
        if selected_idx == 0:
            self.perguntas_tab.apply_changes()
            self.json_editor_tab.refresh_from_shared()
        elif selected_idx in (2, 3):
            self.perguntas_tab.apply_changes()

    # -------------------------------------------------------------------------
    # Métodos utilitários e de compatibilidade
    # -------------------------------------------------------------------------
    def get_json_data(self) -> dict[str, Any] | None:
        """Retorna o dicionário compartilhado ativo (ou None se estiver vazio)."""
        return self.json_data if self.json_data else None

    def set_json_data(
        self, data: dict[str, Any], *, update_editor: bool = True
    ) -> dict[str, Any]:
        """Define os dados do dicionário compartilhado in-place e sincroniza ambas as abas."""
        update_shared_dict_in_place(self.json_data, data)
        if update_editor:
            self.json_editor_tab.set_json_data(
                self.json_data,
                update_original=True,
                apply_uppercase=False,
                notify=False,
            )
        self.perguntas_tab.refresh_from_shared()
        if self.current_view == "landing":
            self.show_notebook()
        self._notify_listeners()
        return self.json_data

    def register_json_listener(
        self, callback: Callable[[dict[str, Any] | None], None]
    ) -> None:
        """Registra um callback chamado quando o JSON compartilhado muda."""
        self._listeners.append(callback)

    def _notify_listeners(self) -> None:
        active = self.json_data if self.json_data else None
        for callback in self._listeners:
            callback(active)


# Alias de compatibilidade
MainWindow = MainApp


def main() -> None:
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
