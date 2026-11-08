#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aba 4 – Gerar SELECT Jasper (src/gui/sql_select_tab.py).

Implementa a interface gráfica para geração da consulta SQL SELECT para Jasper Reports
(Padrão Ouro) conforme `spec_sql_select.md`:
- Botão "Gerar SELECT Jasper" (lê `select_padrao_ouro_jasper.sql` via `resource_path` e `shared_json`)
- Área `ScrolledText` editável (state=NORMAL) com fonte monoespaçada e realce de sintaxe PostgreSQL
- Botão "Validar Sintaxe" (chama `validate_postgres_syntax`)
- Botão "Copiar para Área de Transferência"
- Botão "Salvar como .sql" (grava em UTF-8)
- Botão "Voltar à Tela Inicial"
- Status bar com contagem de linhas/caracteres e feedback de geração/validação
- Dicionário `self.generation_options` preparado para checkboxes futuros.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable

from src.core.sql_select import (
    MODEL_RESOURCE_NAME,
    apply_syntax_highlighting,
    find_unknown_field_types,
    generate_select_jasper,
    validate_postgres_syntax,
)
from src.utils.resource_path import resource_path


class SqlSelectTab(ttk.Frame):
    """
    Aba 'Gerar SELECT Jasper'.
    Gera, exibe (com realce de sintaxe e edição), valida, copia e salva o script SQL
    SELECT para Jasper Reports a partir do modelo padrão ouro e do dicionário compartilhado (`shared_json`).
    """

    def __init__(
        self,
        parent: tk.Misc,
        shared_json: dict[str, Any] | None = None,
        on_sql_generated: Callable[[str], None] | None = None,
        on_back_to_landing: Callable[[], None] | None = None,
        model_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_sql_generated = on_sql_generated
        self.on_back_to_landing = on_back_to_landing
        self.model_path: Path = (
            Path(model_path) if model_path is not None else resource_path(MODEL_RESOURCE_NAME)
        )

        self.generated_sql: str = ""
        self.current_sql_file: Path | None = None

        # Estrutura preparada para futuras opções configuráveis (spec_sql_select.md)
        self.generation_options: dict[str, Any] = {
            "include_obs": True,
            "only_non_title": False,
            "short_aliases": False,
            "group_by_type": False,
        }

        self._build_ui()

    def _build_ui(self) -> None:
        """Constrói a barra de ferramentas, área ScrolledText editável e barra de status."""
        # --- Topo: Barra de Ferramentas ---
        toolbar = ttk.Frame(self, padding=(10, 8, 10, 6))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.btn_generate = ttk.Button(
            toolbar,
            text="Gerar SELECT Jasper",
            command=self.generate_sql,
        )
        self.btn_generate.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_validate = ttk.Button(
            toolbar,
            text="Validar Sintaxe",
            command=self.validate_syntax,
        )
        self.btn_validate.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_copy = ttk.Button(
            toolbar,
            text="Copiar para Área de Transferência",
            command=self.copy_to_clipboard,
            state=tk.DISABLED,
        )
        self.btn_copy.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_save = ttk.Button(
            toolbar,
            text="Salvar como .sql",
            command=self.save_as_sql_dialog,
            state=tk.DISABLED,
        )
        self.btn_save.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_back = ttk.Button(
            toolbar,
            text="Voltar à Tela Inicial",
            command=self._handle_back_to_landing,
        )
        self.btn_back.pack(side=tk.RIGHT)

        # --- Base: Barra de Status ---
        status_frame = ttk.Frame(self, padding=(10, 4, 10, 6))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_var = tk.StringVar(
            value="Clique em 'Gerar SELECT Jasper' para gerar a consulta SQL a partir do JSON carregado."
        )
        self.lbl_status = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            anchor=tk.W,
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.counts_var = tk.StringVar(value="Linhas: 0 | Caracteres: 0")
        self.lbl_counts = ttk.Label(
            status_frame,
            textvariable=self.counts_var,
            anchor=tk.E,
        )
        self.lbl_counts.pack(side=tk.RIGHT, padx=(12, 0))

        # --- Centro: Área Editável (ScrolledText Monospace, state=NORMAL) ---
        preview_container = ttk.Frame(self, padding=(10, 4, 10, 4))
        preview_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.preview_text = scrolledtext.ScrolledText(
            preview_container,
            wrap=tk.NONE,
            font=("Consolas", 10),
            bg="#F8FAFC",
            fg="#0F172A",
            insertbackground="#0F172A",
            selectbackground="#BFDBFE",
            padx=8,
            pady=8,
            state=tk.NORMAL,
            undo=True,
        )
        self.preview_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.preview_text.bind("<KeyRelease>", self._on_text_edited)

        x_scroll = ttk.Scrollbar(
            preview_container,
            orient=tk.HORIZONTAL,
            command=self.preview_text.xview,
        )
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.preview_text.configure(xscrollcommand=x_scroll.set)

        apply_syntax_highlighting(self.preview_text)

    def _update_counts(self, sql_text: str) -> None:
        """Atualiza o contador de linhas e caracteres na barra de status."""
        num_chars = len(sql_text)
        num_lines = sql_text.count("\n") + 1 if sql_text else 0
        self.counts_var.set(f"Linhas: {num_lines} | Caracteres: {num_chars}")

    def _on_text_edited(self, _event: Any = None) -> None:
        """Atualiza contadores, botões e realce de sintaxe quando o usuário edita o SQL manualmente."""
        current = self.get_preview_text()
        self.generated_sql = current
        self._update_counts(current)
        apply_syntax_highlighting(self.preview_text)
        has_content = bool(current.strip())
        self.btn_copy.configure(state=tk.NORMAL if has_content else tk.DISABLED)
        self.btn_save.configure(state=tk.NORMAL if has_content else tk.DISABLED)

    def get_preview_text(self) -> str:
        """Retorna o texto SQL exibido atualmente na área editável."""
        return self.preview_text.get("1.0", "end-1c")

    def set_preview_text(self, sql_text: str) -> None:
        """Atualiza o conteúdo do ScrolledText (mantendo-o editável) e aplica realce de sintaxe."""
        self.preview_text.configure(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        if sql_text:
            self.preview_text.insert("1.0", sql_text)
        apply_syntax_highlighting(self.preview_text)
        self._update_counts(sql_text)

    def clear_preview(self) -> None:
        """Limpa o preview e desabilita os botões de cópia e salvamento."""
        self.generated_sql = ""
        self.set_preview_text("")
        self.btn_copy.configure(state=tk.DISABLED)
        self.btn_save.configure(state=tk.DISABLED)
        self.status_var.set(
            "Clique em 'Gerar SELECT Jasper' para gerar a consulta SQL a partir do JSON carregado."
        )

    def generate_sql(self, show_error_dialog: bool = True) -> bool:
        """
        Gera o script SQL SELECT Jasper a partir de `self.shared_json` e do modelo
        `select_padrao_ouro_jasper.sql`, atualiza a área editável com realce de sintaxe
        e habilita os botões 'Copiar' e 'Salvar como .sql'.
        """
        if not self.shared_json or not isinstance(self.shared_json, dict):
            msg = "Erro: Nenhum JSON carregado para gerar o SELECT Jasper."
            self.status_var.set(msg)
            if show_error_dialog:
                messagebox.showerror("Erro ao Gerar SELECT", msg)
            return False

        model_file = self.model_path or resource_path(MODEL_RESOURCE_NAME)
        if not model_file.exists():
            err_msg = f"Erro: modelo não encontrado em '{model_file}'."
            self.status_var.set(err_msg)
            if show_error_dialog:
                messagebox.showerror("Modelo SQL Não Encontrado", err_msg)
            return False

        try:
            model_content = model_file.read_text(encoding="utf-8-sig")
            sql_script = generate_select_jasper(
                self.shared_json,
                model_sql=model_content,
                options=self.generation_options,
            )
        except ValueError as exc:
            err_msg = str(exc)
            self.status_var.set(f"Erro: {err_msg}")
            if show_error_dialog:
                messagebox.showerror("Erro ao Gerar SELECT", err_msg)
            return False
        except Exception as exc:
            err_msg = f"Erro inesperado ao gerar SELECT: {exc}"
            self.status_var.set(err_msg)
            if show_error_dialog:
                messagebox.showerror("Erro ao Gerar SELECT", err_msg)
            return False

        self.generated_sql = sql_script
        self.set_preview_text(sql_script)
        self.btn_copy.configure(state=tk.NORMAL)
        self.btn_save.configure(state=tk.NORMAL)

        unknown_types = find_unknown_field_types(self.shared_json)
        if unknown_types:
            self.status_var.set(
                f"SELECT gerado com sucesso (Aviso: tipo_campo desconhecido usou fallback TEXTO: {', '.join(unknown_types)})"
            )
        else:
            self.status_var.set("SELECT gerado com sucesso")

        if self.on_sql_generated is not None:
            self.on_sql_generated(sql_script)

        return True

    def validate_syntax(self, show_dialog: bool = False) -> bool:
        """
        Valida a sintaxe básica PostgreSQL do SELECT atual na área editável
        chamando `validate_postgres_syntax()` e atualiza a barra de status.
        """
        sql_text = self.get_preview_text() or self.generated_sql
        is_valid, message = validate_postgres_syntax(sql_text)
        apply_syntax_highlighting(self.preview_text)
        self.status_var.set(message)

        if show_dialog:
            if is_valid:
                messagebox.showinfo("Validação de Sintaxe PostgreSQL", message)
            else:
                messagebox.showerror("Erro de Sintaxe PostgreSQL", message)

        return is_valid

    def copy_to_clipboard(self) -> bool:
        """Copia o SELECT atual para a área de transferência do sistema."""
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.status_var.set("Aviso: Nenhum SELECT gerado para copiar.")
            return False

        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(sql_text)
        root.update_idletasks()
        self.status_var.set("SELECT copiado para a área de transferência!")
        return True

    def save_sql_to_path(self, file_path: str | Path) -> bool:
        """Grava o SELECT atual no caminho especificado com codificação UTF-8."""
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.status_var.set("Aviso: Nenhum SELECT gerado para salvar.")
            return False

        path = Path(file_path)
        try:
            path.write_text(sql_text, encoding="utf-8")
            self.current_sql_file = path
            self.status_var.set(f"Arquivo SQL salvo com sucesso em: {path.name}")
            return True
        except OSError as exc:
            messagebox.showerror(
                "Erro ao Salvar SQL",
                f"Não foi possível gravar o arquivo:\n{path}\n\nDetalhes: {exc}",
            )
            self.status_var.set("Erro ao gravar arquivo .sql no disco.")
            return False

    def save_as_sql_dialog(self) -> bool:
        """Abre diálogo 'Salvar como .sql' e grava o script SELECT em UTF-8."""
        sql_text = self.get_preview_text() or self.generated_sql
        if not sql_text.strip():
            self.status_var.set("Aviso: Gere o SELECT antes de salvar.")
            return False

        initial_name = "select_ficha_clinica_jasper.sql"
        if self.current_sql_file is not None:
            initial_name = self.current_sql_file.name

        save_path = filedialog.asksaveasfilename(
            title="Salvar como .sql",
            defaultextension=".sql",
            initialfile=initial_name,
            filetypes=[("SQL", "*.sql"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return False

        return self.save_sql_to_path(save_path)

    def _handle_back_to_landing(self) -> None:
        """Retorna à Tela Inicial."""
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
