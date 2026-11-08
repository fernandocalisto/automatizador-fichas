#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tela Inicial (Landing) do Automatizador de Fichas (src/gui/landing.py).

Implementa a interface inicial descrita em spec_json_editor.md:
- Título: "Automatizador de Fichas – Carregar JSON"
- Botão "Baixar Skill" com Tooltip explicativo detalhado no hover
- Área de explicação curta (2-3 linhas) abaixo do botão
- Botão "Carregar JSON de Arquivo"
- Botão "Colar JSON da Área de Transferência"
- Barra de status inferior ("Aguardando JSON…" ou erro de validação)
"""

from __future__ import annotations

import json
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from src.utils.json_utils import parse_and_validate_clinical_json
from src.utils.resource_path import get_skill_file_path

SKILL_TOOLTIP_TEXT = (
    "Esta skill ensina a IA a extrair fichas clínicas de PDFs/imagens/texto e "
    "gerar o JSON estruturado esperado pelo sistema.\n\n"
    "Como usar:\n"
    "1. Baixe este arquivo.\n"
    "2. Anexe/o envie para a IA de sua preferência (Claude, ChatGPT, modelos gratuitos via OpenRouter, etc.).\n"
    "3. Envie o PDF da ficha clínica para a IA.\n"
    "4. A IA, seguindo a skill, vai conversar com você para validar campos, tipos, labels, etc.\n"
    "5. Quando vocês chegarem a um acordo, a IA gerará o JSON final.\n"
    "6. Copie/cole ou carregue esse JSON aqui."
)

SHORT_EXPLANATION_TEXT = (
    "1) Baixe o arquivo SKILL.md acima e envie-o junto com o PDF da ficha clínica para a IA de sua preferência.\n"
    "2) Valide os campos e tipos com a IA até que ela gere o JSON final da ficha no padrão Salutem.\n"
    "3) Carregue o arquivo .json gerado ou cole o conteúdo diretamente da área de transferência abaixo."
)


class ToolTip:
    """Tooltip flutuante exibido ao passar o mouse (hover) sobre um widget Tkinter."""

    def __init__(self, widget: tk.Widget, text: str, wraplength: int = 440) -> None:
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tip_window: tk.Toplevel | None = None

        self.widget.bind("<Enter>", self.show_tooltip, add="+")
        self.widget.bind("<Leave>", self.hide_tooltip, add="+")
        self.widget.bind("<ButtonPress>", self.hide_tooltip, add="+")

    def show_tooltip(self, _event: Any = None) -> None:
        """Exibe a janela flutuante do tooltip próxima ao widget."""
        if self.tip_window is not None or not self.text:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        frame = tk.Frame(
            tw,
            background="#FEFCE8",
            highlightbackground="#CA8A04",
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        frame.pack(fill=tk.BOTH, expand=True)

        label = tk.Label(
            frame,
            text=self.text,
            justify=tk.LEFT,
            background="#FEFCE8",
            foreground="#1E293B",
            font=("Segoe UI", 9),
            wraplength=self.wraplength,
        )
        label.pack(anchor=tk.W)

    def hide_tooltip(self, _event: Any = None) -> None:
        """Oculta e destrói a janela flutuante do tooltip."""
        if self.tip_window is not None:
            try:
                self.tip_window.destroy()
            except tk.TclError:
                pass
            self.tip_window = None


class LandingFrame(ttk.Frame):
    """
    Tela Inicial (Landing) onde o usuário baixa a SKILL.md e carrega ou cola o JSON.
    Quando um JSON válido é carregado, invoca `on_json_loaded(json_dict, file_path)`.
    """

    def __init__(
        self,
        parent: tk.Misc,
        on_json_loaded: Callable[[dict[str, Any], Path | None], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)
        self.on_json_loaded = on_json_loaded
        self.status_var = tk.StringVar(value="Aguardando JSON…")

        self._build_ui()

    def _build_ui(self) -> None:
        """Constrói os elementos visuais da Tela Inicial conforme a especificação."""
        # Container centralizado
        center_card = ttk.Frame(self, padding=(36, 28))
        center_card.pack(fill=tk.BOTH, expand=True)

        # Título principal
        self.lbl_title = ttk.Label(
            center_card,
            text="Automatizador de Fichas – Carregar JSON",
            font=("Segoe UI", 16, "bold"),
            anchor=tk.CENTER,
        )
        self.lbl_title.pack(pady=(12, 20))

        # Seção 1: Download da Skill + Explicação
        skill_group = ttk.LabelFrame(
            center_card,
            text="1. Instruções para Extração via IA (Skill)",
            padding=(18, 14),
        )
        skill_group.pack(fill=tk.X, padx=24, pady=(0, 18))

        btn_row = ttk.Frame(skill_group)
        btn_row.pack(fill=tk.X, pady=(0, 10))

        self.btn_download_skill = ttk.Button(
            btn_row,
            text="Baixar Skill (SKILL.md)",
            command=self.download_skill,
        )
        self.btn_download_skill.pack(side=tk.LEFT)

        self.skill_tooltip = ToolTip(self.btn_download_skill, SKILL_TOOLTIP_TEXT)

        lbl_hover_hint = ttk.Label(
            btn_row,
            text="ℹ Passe o mouse sobre o botão para ver o passo a passo completo",
            foreground="#64748B",
            font=("Segoe UI", 9, "italic"),
        )
        lbl_hover_hint.pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_explanation = ttk.Label(
            skill_group,
            text=SHORT_EXPLANATION_TEXT,
            justify=tk.LEFT,
            foreground="#334155",
            font=("Segoe UI", 9),
            wraplength=680,
        )
        self.lbl_explanation.pack(fill=tk.X, anchor=tk.W)

        # Seção 2: Carregar ou Colar JSON
        load_group = ttk.LabelFrame(
            center_card,
            text="2. Importar JSON da Ficha Clínica",
            padding=(18, 18),
        )
        load_group.pack(fill=tk.X, padx=24, pady=(0, 18))

        actions_frame = ttk.Frame(load_group)
        actions_frame.pack(fill=tk.X, pady=4)

        self.btn_load_file = ttk.Button(
            actions_frame,
            text="Carregar JSON de Arquivo",
            command=self.load_json_from_file_dialog,
        )
        self.btn_load_file.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 8), ipady=6)

        self.btn_paste_clipboard = ttk.Button(
            actions_frame,
            text="Colar JSON da Área de Transferência",
            command=self.paste_json_from_clipboard,
        )
        self.btn_paste_clipboard.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 0), ipady=6)

        # Barra de status na parte inferior
        status_bar = ttk.Frame(self, padding=(12, 6))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status = ttk.Label(
            status_bar,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(8, 4),
        )
        self.lbl_status.pack(fill=tk.X)

    # -------------------------------------------------------------------------
    # Ações da Tela Inicial
    # -------------------------------------------------------------------------
    def download_skill(self, destination_path: str | Path | None = None) -> bool:
        """
        Faz o download/cópia do arquivo SKILL.md embutido nos recursos do projeto
        para o caminho escolhido pelo usuário.
        """
        source_path = get_skill_file_path()
        if not source_path.exists():
            messagebox.showerror(
                "Recurso Não Encontrado",
                f"O arquivo SKILL.md não foi encontrado em:\n{source_path}",
            )
            self.status_var.set("Erro: arquivo SKILL.md não encontrado nos recursos.")
            return False

        if destination_path is None:
            selected = filedialog.asksaveasfilename(
                title="Salvar Arquivo da Skill",
                defaultextension=".md",
                initialfile="SKILL.md",
                filetypes=[
                    ("Markdown (SKILL.md)", "*.md"),
                    ("Todos os arquivos", "*.*"),
                ],
            )
            if not selected:
                return False
            dest = Path(selected)
        else:
            dest = Path(destination_path)

        try:
            shutil.copyfile(source_path, dest)
            self.status_var.set(f"Skill salva com sucesso em: {dest}")
            messagebox.showinfo(
                "Download Concluído",
                f"O arquivo '{dest.name}' foi salvo com sucesso em:\n{dest}",
            )
            return True
        except OSError as exc:
            messagebox.showerror(
                "Erro ao Salvar Skill",
                f"Não foi possível salvar o arquivo em:\n{dest}\n\nDetalhes: {exc}",
            )
            self.status_var.set(f"Erro ao salvar SKILL.md: {exc}")
            return False

    def load_json_from_file_dialog(self) -> bool:
        """Abre diálogo de seleção de arquivo .json e valida o conteúdo."""
        file_path = filedialog.askopenfilename(
            title="Carregar JSON de Ficha Clínica",
            filetypes=[("Arquivos JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if not file_path:
            return False
        return self.load_json_from_path(file_path)

    def load_json_from_path(self, file_path: str | Path) -> bool:
        """Lê, valida e carrega um arquivo JSON a partir do caminho informado."""
        path = Path(file_path)
        try:
            raw_text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            msg = f"Não foi possível ler o arquivo:\n{path}\n\nDetalhes: {exc}"
            self.status_var.set(f"Erro ao ler arquivo: {path.name}")
            messagebox.showerror("Erro ao Abrir Arquivo", msg)
            return False

        return self._process_raw_json(raw_text, source_path=path)

    def paste_json_from_clipboard(self) -> bool:
        """Lê o texto da área de transferência, valida o JSON e avança se válido."""
        try:
            raw_text = self.clipboard_get()
        except tk.TclError:
            msg = "Não há texto disponível na área de transferência."
            self.status_var.set(f"Erro: {msg}")
            messagebox.showerror("Área de Transferência Vazia", msg)
            return False

        return self._process_raw_json(raw_text, source_path=None)

    def _process_raw_json(self, raw_text: str, source_path: Path | None = None) -> bool:
        """
        Valida se o texto é um JSON bem-formado com a estrutura mínima (`template` + `perguntas`).
        Se inválido, exibe messagebox.showerror com linha/coluna ou motivo.
        Se válido, aciona o callback para transição à janela principal com abas.
        """
        try:
            validated_data = parse_and_validate_clinical_json(
                raw_text,
                require_clinical_structure=True,
                apply_uppercase=True,
            )
        except json.JSONDecodeError as exc:
            origem = f" no arquivo '{source_path.name}'" if source_path else ""
            detalhe = (
                f"O JSON informado{origem} contém erro de sintaxe:\n\n"
                f"Erro: {exc.msg}\n"
                f"Linha: {exc.lineno}, Coluna: {exc.colno}"
            )
            self.status_var.set(
                f"Erro de validação JSON (Linha {exc.lineno}, Coluna {exc.colno}): {exc.msg}"
            )
            messagebox.showerror("JSON Inválido", detalhe)
            return False
        except ValueError as exc:
            self.status_var.set(f"Erro de validação: {exc}")
            messagebox.showerror("JSON Inválido", str(exc))
            return False

        self.status_var.set("JSON válido carregado com sucesso!")
        if self.on_json_loaded is not None:
            self.on_json_loaded(validated_data, source_path)
        return True
