#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aba 1 – Editar JSON (src/gui/json_editor_tab.py).

Implementa a aba de edição de JSON descrita em spec_json_editor.md:
- ScrolledText editável com fonte monoespaçada, undo, realce de sintaxe e contadores.
- Botões: "Validar & Formatar", "Salvar JSON como…", "Voltar à Tela Inicial"
  (além de suporte a Redefinir, Carregar/Colar e Drag-and-Drop).
- Ao validar/salvar: aplica `uppercase_target_fields` recursivamente e atualiza
  o dicionário compartilhado in-place, sincronizando imediatamente com a Aba 2.
"""

from __future__ import annotations

import copy
import ctypes
import json
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable

from src.utils.json_utils import (
    apply_uppercase_to_text_fields,
    format_json,
    load_json_file,
    save_json_file,
    update_shared_dict_in_place,
    uppercase_target_fields,
    validate_clinical_json_structure,
    validate_json_text,
)


class JsonEditorTab(ttk.Frame):
    """
    Aba 'Editar JSON'.
    Opera diretamente sobre o dicionário compartilhado (`shared_json`) da aplicação.
    """

    def __init__(
        self,
        parent: tk.Misc,
        shared_json: dict[str, Any] | None = None,
        on_json_changed: Callable[[dict[str, Any]], None] | None = None,
        on_back_to_landing: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_json_changed = on_json_changed
        self.on_back_to_landing = on_back_to_landing

        self.current_file: Path | None = None
        self.original_data: dict[str, Any] | None = (
            copy.deepcopy(self.shared_json) if self.shared_json else None
        )
        self._highlight_after_id: str | None = None

        self._build_ui()
        self._setup_drag_and_drop()

        if self.shared_json:
            self.refresh_from_shared()
        else:
            self._update_counts()

    @property
    def json_data(self) -> dict[str, Any] | None:
        """Propriedade de compatibilidade que retorna o dicionário compartilhado ativo."""
        return self.shared_json if self.shared_json else None

    def _build_ui(self) -> None:
        """Constrói a barra de ferramentas superior, o ScrolledText central e a barra de status."""
        # --- Topo: Barra de Ferramentas ---
        toolbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.btn_validate_format = ttk.Button(
            toolbar,
            text="Validar & Formatar",
            command=self.validate_and_format,
        )
        self.btn_validate_format.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_save_as = ttk.Button(
            toolbar,
            text="Salvar JSON como…",
            command=self.save_json_as_dialog,
        )
        self.btn_save_as.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_reset = ttk.Button(
            toolbar,
            text="Redefinir",
            command=self.reset_json,
        )
        self.btn_reset.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_back = ttk.Button(
            toolbar,
            text="Voltar à Tela Inicial",
            command=self._handle_back_to_landing,
        )
        self.btn_back.pack(side=tk.RIGHT, padx=(6, 0))

        self.syntax_highlight_var = tk.BooleanVar(value=True)
        self.chk_highlight = ttk.Checkbutton(
            toolbar,
            text="Realce de sintaxe",
            variable=self.syntax_highlight_var,
            command=self._schedule_highlight,
        )
        self.chk_highlight.pack(side=tk.RIGHT, padx=(6, 6))

        # --- Base: Barra de Status e Contagem de Linhas/Caracteres ---
        status_frame = ttk.Frame(self, padding=(8, 4, 8, 6))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_var = tk.StringVar(
            value="Edite o JSON abaixo e clique em 'Validar & Formatar' para aplicar UPPERCASE e atualizar as abas."
        )
        self.lbl_status = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            anchor=tk.W,
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.counts_var = tk.StringVar(value="Linhas: 1 | Caracteres: 0")
        self.lbl_counts = ttk.Label(
            status_frame,
            textvariable=self.counts_var,
            anchor=tk.E,
        )
        self.lbl_counts.pack(side=tk.RIGHT, padx=(12, 0))

        # --- Centro: Área de Edição de JSON ---
        editor_container = ttk.Frame(self, padding=(8, 4, 8, 4))
        editor_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.text_area = scrolledtext.ScrolledText(
            editor_container,
            wrap=tk.NONE,
            undo=True,
            font=("Consolas", 10),
            bg="#FFFFFF",
            fg="#1E293B",
            insertbackground="#0F172A",
            selectbackground="#BFDBFE",
            padx=8,
            pady=8,
        )
        self.text_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        x_scroll = ttk.Scrollbar(
            editor_container, orient=tk.HORIZONTAL, command=self.text_area.xview
        )
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text_area.configure(xscrollcommand=x_scroll.set)

        # Tags para realce de sintaxe JSON
        self.text_area.tag_configure("json_key", foreground="#0369A1")
        self.text_area.tag_configure("json_string", foreground="#15803D")
        self.text_area.tag_configure("json_number", foreground="#B45309")
        self.text_area.tag_configure("json_boolean", foreground="#7C3AED")
        self.text_area.tag_configure("json_null", foreground="#64748B")

        self.text_area.bind("<KeyRelease>", self._on_text_modified)
        self.text_area.bind("<<Paste>>", lambda _e: self.after(20, self._on_text_modified))
        self.text_area.bind("<<Cut>>", lambda _e: self.after(20, self._on_text_modified))

    # -------------------------------------------------------------------------
    # Suporte a Drag-and-Drop
    # -------------------------------------------------------------------------
    def _setup_drag_and_drop(self) -> None:
        if hasattr(self.text_area, "drop_target_register") and hasattr(
            self.text_area, "dnd_bind"
        ):
            try:
                self.text_area.drop_target_register("DND_Files")  # type: ignore[attr-defined]
                self.text_area.dnd_bind("<<Drop>>", self._on_tkdnd_drop)  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        if sys.platform == "win32":
            try:
                hwnd = self.text_area.winfo_id()
                ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
            except Exception:
                pass

    def _on_tkdnd_drop(self, event: Any) -> None:
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return
        caminho = raw_data.strip()
        if caminho.startswith("{") and caminho.endswith("}"):
            caminho = caminho[1:-1]
        self.handle_dropped_file(caminho)

    def handle_dropped_file(self, file_path: str | Path) -> bool:
        path = Path(str(file_path).strip().strip('"'))
        if path.suffix.lower() != ".json":
            messagebox.showerror(
                "Arquivo Inválido",
                f"Apenas arquivos .json são suportados.\nArquivo recebido: {path.name}",
            )
            self.status_var.set(f"Erro: arquivo '{path.name}' não é um .json.")
            return False

        return self.load_file(path)

    # -------------------------------------------------------------------------
    # Contagem e Realce de Sintaxe
    # -------------------------------------------------------------------------
    def _on_text_modified(self, _event: Any = None) -> None:
        self._update_counts()
        self._schedule_highlight()

    def _update_counts(self) -> None:
        conteudo = self.text_area.get("1.0", "end-1c")
        num_chars = len(conteudo)
        num_lines = conteudo.count("\n") + 1 if conteudo else 1
        self.counts_var.set(f"Linhas: {num_lines} | Caracteres: {num_chars}")

    def _schedule_highlight(self) -> None:
        if self._highlight_after_id is not None:
            try:
                self.after_cancel(self._highlight_after_id)
            except Exception:
                pass
        self._highlight_after_id = self.after(120, self._highlight_json)

    def _highlight_json(self) -> None:
        for tag in ("json_key", "json_string", "json_number", "json_boolean", "json_null"):
            self.text_area.tag_remove(tag, "1.0", tk.END)

        if not self.syntax_highlight_var.get():
            return

        conteudo = self.text_area.get("1.0", "end-1c")
        if not conteudo or len(conteudo) > 200_000:
            return

        for match in re.finditer(r'"(?:\\.|[^"\\])*"(?=\s*:)', conteudo):
            self.text_area.tag_add("json_key", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

        for match in re.finditer(r':\s*("(?:\\.|[^"\\])*")', conteudo):
            self.text_area.tag_add(
                "json_string", f"1.0+{match.start(1)}c", f"1.0+{match.end(1)}c"
            )

        for match in re.finditer(r"\b(true|false)\b", conteudo):
            self.text_area.tag_add(
                "json_boolean", f"1.0+{match.start(1)}c", f"1.0+{match.end(1)}c"
            )

        for match in re.finditer(r"\b(null)\b", conteudo):
            self.text_area.tag_add("json_null", f"1.0+{match.start(1)}c", f"1.0+{match.end(1)}c")

        for match in re.finditer(r"(?<=:\s)(-?\d+(?:\.\d+)?)", conteudo):
            self.text_area.tag_add(
                "json_number", f"1.0+{match.start(1)}c", f"1.0+{match.end(1)}c"
            )

    # -------------------------------------------------------------------------
    # Manipulação do Texto e Sincronização com o Dicionário Compartilhado
    # -------------------------------------------------------------------------
    def get_editor_text(self) -> str:
        """Retorna o texto atual da área de edição."""
        return self.text_area.get("1.0", "end-1c")

    def set_editor_text(self, text: str) -> None:
        """Substitui o texto na área de edição e atualiza contadores/realce."""
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", text)
        self._update_counts()
        self._highlight_json()

    def refresh_from_shared(self) -> None:
        """
        Recarrega a visualização de texto do editor a partir do dicionário
        compartilhado (`self.shared_json`), garantindo UPPERCASE nos campos alvo.
        """
        if not self.shared_json:
            self.set_editor_text("")
            return
        update_shared_dict_in_place(self.shared_json, self.shared_json)
        self.set_editor_text(format_json(self.shared_json))

    def set_json_data(
        self,
        data: dict[str, Any],
        *,
        update_original: bool = False,
        apply_uppercase: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        """
        Atualiza o dicionário compartilhado in-place, formata o texto no editor
        e notifica ouvintes (como a Aba 2).
        """
        if update_original:
            self.original_data = copy.deepcopy(data)

        processed = uppercase_target_fields(data) if apply_uppercase else copy.deepcopy(data)
        if isinstance(processed, dict):
            self.shared_json.clear()
            self.shared_json.update(processed)

        self.set_editor_text(format_json(self.shared_json))

        if notify and self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)

        return self.shared_json

    def get_json_data(self) -> dict[str, Any] | None:
        """Retorna o dicionário compartilhado (ou None se vazio)."""
        return self.shared_json if self.shared_json else None

    def validate_and_format(self, show_dialog_on_success: bool = False) -> bool:
        """
        Valida o JSON presente no ScrolledText, verifica a estrutura mínima
        (`template` e `perguntas`), converte os campos de texto alvo para UPPERCASE,
        formata o JSON e atualiza o dicionário compartilhado.
        """
        raw_text = self.get_editor_text()
        try:
            parsed = validate_json_text(raw_text)
        except json.JSONDecodeError as exc:
            messagebox.showerror(
                "Erro de Validação JSON",
                f"O JSON informado não está bem-formado:\n\n"
                f"Erro: {exc.msg}\n"
                f"Linha: {exc.lineno}, Coluna: {exc.colno}",
            )
            self.status_var.set(
                f"JSON inválido (Linha {exc.lineno}, Coluna {exc.colno}): {exc.msg}"
            )
            return False
        except ValueError as exc:
            messagebox.showerror("Erro de Validação JSON", str(exc))
            self.status_var.set(f"Erro: {exc}")
            return False

        is_valid_struct, struct_msg = validate_clinical_json_structure(parsed)
        if not is_valid_struct:
            messagebox.showerror("Estrutura JSON Inválida", struct_msg)
            self.status_var.set(struct_msg)
            return False

        if self.original_data is None:
            self.original_data = copy.deepcopy(parsed)

        self.set_json_data(parsed, update_original=False, apply_uppercase=True, notify=True)
        self.status_var.set(
            "JSON validado, formatado e atualizado (campos de texto em UPPERCASE)."
        )
        if show_dialog_on_success:
            messagebox.showinfo(
                "JSON Validado",
                "JSON validado, formatado e atualizado com sucesso (textos em UPPERCASE).",
            )
        return True

    # Alias para compatibilidade com chamadas anteriores
    save_changes = validate_and_format

    def save_json_as_dialog(self) -> bool:
        """
        Valida e formata o JSON atual (aplicando UPPERCASE nos campos alvo)
        e abre diálogo 'Salvar como…' para gravar o arquivo .json em disco.
        """
        if not self.validate_and_format(show_dialog_on_success=False):
            return False

        initial_name = self.current_file.name if self.current_file else "ficha_clinica.json"
        save_path = filedialog.asksaveasfilename(
            title="Salvar JSON como…",
            defaultextension=".json",
            initialfile=initial_name,
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if not save_path:
            return False

        try:
            save_json_file(save_path, self.shared_json, apply_uppercase=False)
            self.current_file = Path(save_path)
            self.status_var.set(f"Arquivo salvo com sucesso em: {self.current_file.name}")
            return True
        except OSError as exc:
            messagebox.showerror(
                "Erro ao Salvar Arquivo",
                f"Não foi possível gravar o arquivo:\n{save_path}\n\nDetalhes: {exc}",
            )
            self.status_var.set("Erro ao gravar arquivo no disco.")
            return False

    # Alias para compatibilidade
    export_to_file_dialog = save_json_as_dialog

    def load_file(self, file_path: str | Path) -> bool:
        """Carrega um arquivo .json diretamente no editor, validando-o."""
        path = Path(file_path)
        try:
            raw_content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror(
                "Erro ao Abrir Arquivo",
                f"Não foi possível ler o arquivo:\n{path}\n\nDetalhes: {exc}",
            )
            self.status_var.set(f"Erro ao ler arquivo: {path.name}")
            return False

        try:
            parsed = validate_json_text(raw_content)
        except json.JSONDecodeError as exc:
            self.set_editor_text(raw_content)
            messagebox.showerror(
                "JSON Inválido",
                f"O arquivo '{path.name}' contém JSON malformado:\n"
                f"{exc.msg} (Linha {exc.lineno}, Coluna {exc.colno})",
            )
            self.status_var.set(
                f"Erro de validação em '{path.name}' (linha {exc.lineno}, coluna {exc.colno})."
            )
            return False
        except ValueError as exc:
            messagebox.showerror("JSON Inválido", str(exc))
            self.status_var.set(str(exc))
            return False

        is_valid_struct, struct_msg = validate_clinical_json_structure(parsed)
        if not is_valid_struct:
            messagebox.showerror("Estrutura JSON Inválida", struct_msg)
            self.status_var.set(struct_msg)
            return False

        self.current_file = path
        self.set_json_data(parsed, update_original=True, apply_uppercase=True, notify=True)
        self.status_var.set(f"Arquivo carregado com sucesso: {path.name} (textos em UPPERCASE)")
        return True

    def load_from_file_dialog(self) -> bool:
        file_path = filedialog.askopenfilename(
            title="Carregar JSON de Ficha Clínica",
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if not file_path:
            return False
        return self.load_file(file_path)

    def paste_from_clipboard(self) -> bool:
        try:
            clipboard_text = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning(
                "Área de Transferência Vazia",
                "Não há texto disponível na área de transferência para colar.",
            )
            self.status_var.set("Aviso: área de transferência vazia.")
            return False

        if not clipboard_text.strip():
            messagebox.showwarning(
                "Área de Transferência Vazia",
                "O texto copiado está em branco.",
            )
            return False

        self.set_editor_text(clipboard_text)
        return self.validate_and_format(show_dialog_on_success=False)

    def reset_json(self) -> bool:
        """Restaura o JSON original carregado na sessão atual."""
        if self.original_data is None:
            messagebox.showinfo(
                "Redefinir JSON",
                "Não há JSON original carregado para redefinir.",
            )
            self.status_var.set("Nenhum JSON original para redefinir.")
            return False

        restored = copy.deepcopy(self.original_data)
        self.set_json_data(restored, update_original=False, apply_uppercase=True, notify=True)
        nome_origem = self.current_file.name if self.current_file else "original"
        self.status_var.set(f"JSON redefinido para o estado {nome_origem}.")
        return True

    def _handle_back_to_landing(self) -> None:
        """Aciona o retorno para a Tela Inicial."""
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
