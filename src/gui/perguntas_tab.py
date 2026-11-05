#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aba 2 – Perguntas & Respostas (src/gui/perguntas_tab.py).

Implementa a visualização e edição interativa de perguntas e respostas descrita em
spec_json_editor.md e spec_perguntas_visualizacao.md:
- Lista de perguntas em cards expansíveis (accordion) dentro de painel com rolagem vertical.
- Edição do nome da pergunta (convertido automaticamente para UPPERCASE) e flag `titulo`.
- Ao expandir uma pergunta, exibe grid/tabela editável com todas as suas respostas:
  - `ordenacao` (somente leitura)
  - `label` (Entry editável -> UPPERCASE ao perder foco, Enter ou Aplicar Alterações)
  - `tipo_campo` (somente leitura)
  - `campo_obrigatorio` / `obrigatorio` (Checkbutton booleano)
  - `observacao` (Checkbutton booleano)
  - `importa_historico` (Checkbutton booleano)
  - `valor_data_atual` (Checkbutton booleano)
  - `valor_hora_atual` (Checkbutton booleano)
  - Informações adicionais (`minimo`, `cid_codigo`, `procedimento_codigo`, etc.)
- Opera diretamente sobre o dicionário JSON compartilhado (`shared_json`).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable


class AnswerRowWidgets:
    """Agrupa as variáveis e widgets de uma linha de resposta no grid editável."""

    def __init__(
        self,
        resposta_dict: dict[str, Any],
        index: int,
        on_modified: Callable[[], None],
    ) -> None:
        self.resposta = resposta_dict
        self.index = index
        self.on_modified = on_modified

        label_inicial = str(resposta_dict.get("label") or "").upper()
        resposta_dict["label"] = label_inicial
        self.label_var = tk.StringVar(value=label_inicial)

        # Suporta tanto 'campo_obrigatorio' (spec/SKILL) quanto 'obrigatorio' (templates legados)
        obrig_val = bool(
            resposta_dict.get(
                "campo_obrigatorio", resposta_dict.get("obrigatorio", False)
            )
        )
        self.obrigatorio_var = tk.BooleanVar(value=obrig_val)
        self.observacao_var = tk.BooleanVar(value=bool(resposta_dict.get("observacao", False)))
        self.importa_historico_var = tk.BooleanVar(
            value=bool(resposta_dict.get("importa_historico", False))
        )
        self.valor_data_atual_var = tk.BooleanVar(
            value=bool(resposta_dict.get("valor_data_atual", False))
        )
        self.valor_hora_atual_var = tk.BooleanVar(
            value=bool(resposta_dict.get("valor_hora_atual", False))
        )

        self.entry_label: ttk.Entry | None = None
        self.chk_obrigatorio: ttk.Checkbutton | None = None
        self.chk_observacao: ttk.Checkbutton | None = None
        self.chk_importa_historico: ttk.Checkbutton | None = None
        self.chk_valor_data_atual: ttk.Checkbutton | None = None
        self.chk_valor_hora_atual: ttk.Checkbutton | None = None

    def commit_label_uppercase(self, _event: Any = None) -> None:
        """Converte o label atual para UPPERCASE e grava no dicionário da resposta."""
        upper_val = self.label_var.get().upper()
        if self.label_var.get() != upper_val:
            self.label_var.set(upper_val)
        if self.resposta.get("label") != upper_val:
            self.resposta["label"] = upper_val
            self.on_modified()
        else:
            self.resposta["label"] = upper_val

    def on_boolean_toggled(self, field_name: str, var: tk.BooleanVar) -> None:
        """Atualiza imediatamente o campo booleano correspondente no dicionário da resposta."""
        val = bool(var.get())
        if field_name == "campo_obrigatorio":
            self.resposta["campo_obrigatorio"] = val
            if "obrigatorio" in self.resposta:
                self.resposta["obrigatorio"] = val
        else:
            self.resposta[field_name] = val
        self.on_modified()


class QuestionAccordionItem(ttk.Frame):
    """
    Card expansível (accordion) representando uma pergunta do JSON e sua grade de respostas.
    """

    def __init__(
        self,
        parent: tk.Misc,
        pergunta_dict: dict[str, Any],
        question_index: int,
        on_modified: Callable[[], None],
        initially_expanded: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, padding=(6, 4), **kwargs)
        self.pergunta = pergunta_dict
        self.question_index = question_index
        self.on_modified = on_modified
        self.is_expanded = False
        self._body_built = False
        self.answer_rows: list[AnswerRowWidgets] = []

        nome_inicial = str(self.pergunta.get("nome") or "").upper()
        self.pergunta["nome"] = nome_inicial
        self.nome_var = tk.StringVar(value=nome_inicial)
        self.titulo_var = tk.BooleanVar(value=bool(self.pergunta.get("titulo", False)))

        self._build_header()
        self.body_frame = ttk.Frame(self, padding=(16, 6, 6, 8))

        if initially_expanded:
            self.expand()

    def _build_header(self) -> None:
        """Constrói o cabeçalho do card da pergunta com botão expandir, Entry de nome e flag título."""
        header = ttk.Frame(self)
        header.pack(fill=tk.X, expand=True)

        respostas = self.pergunta.get("respostas")
        qtd_respostas = len(respostas) if isinstance(respostas, list) else 0

        self.btn_toggle = ttk.Button(
            header,
            text=f"▶ Pergunta {self.question_index}",
            width=16,
            command=self.toggle,
        )
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(header, text="Nome:").pack(side=tk.LEFT, padx=(0, 4))

        self.entry_nome = ttk.Entry(
            header,
            textvariable=self.nome_var,
            width=48,
            font=("Segoe UI", 9, "bold"),
        )
        self.entry_nome.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.entry_nome.bind("<FocusOut>", self.commit_question_name_uppercase)
        self.entry_nome.bind("<Return>", self.commit_question_name_uppercase)

        self.chk_titulo = ttk.Checkbutton(
            header,
            text="É Título (Divisor)",
            variable=self.titulo_var,
            command=self._on_titulo_toggled,
        )
        self.chk_titulo.pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_count = ttk.Label(
            header,
            text=f"({qtd_respostas} resposta{'s' if qtd_respostas != 1 else ''})",
            foreground="#475569",
        )
        self.lbl_count.pack(side=tk.RIGHT)

    def commit_question_name_uppercase(self, _event: Any = None) -> None:
        """Converte o nome da pergunta para UPPERCASE e atualiza o JSON."""
        upper_val = self.nome_var.get().upper()
        if self.nome_var.get() != upper_val:
            self.nome_var.set(upper_val)
        if self.pergunta.get("nome") != upper_val:
            self.pergunta["nome"] = upper_val
            self.on_modified()
        else:
            self.pergunta["nome"] = upper_val

    def _on_titulo_toggled(self) -> None:
        self.pergunta["titulo"] = bool(self.titulo_var.get())
        self.on_modified()

    def toggle(self) -> None:
        """Alterna entre expandir e recolher a grade de respostas desta pergunta."""
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        """Expande o card e constrói a grade de respostas caso ainda não tenha sido criada."""
        if not self._body_built:
            self._build_answers_grid()
            self._body_built = True
        self.body_frame.pack(fill=tk.X, expand=True, pady=(4, 2))
        self.is_expanded = True
        self.btn_toggle.configure(text=f"▼ Pergunta {self.question_index}")

    def collapse(self) -> None:
        """Recolhe a grade de respostas."""
        self.commit_all_fields()
        self.body_frame.pack_forget()
        self.is_expanded = False
        self.btn_toggle.configure(text=f"▶ Pergunta {self.question_index}")

    def _build_answers_grid(self) -> None:
        """Monta a tabela editável com todas as respostas vinculadas à pergunta."""
        for child in self.body_frame.winfo_children():
            child.destroy()
        self.answer_rows.clear()

        respostas = self.pergunta.get("respostas", [])
        if not isinstance(respostas, list) or not respostas:
            ttk.Label(
                self.body_frame,
                text="Nenhuma resposta vinculada a esta pergunta (ex.: divisor de seção).",
                foreground="#64748B",
                font=("Segoe UI", 9, "italic"),
            ).pack(anchor=tk.W, pady=4)
            return

        grid_container = ttk.Frame(self.body_frame)
        grid_container.pack(fill=tk.X, expand=True)
        grid_container.columnconfigure(1, weight=1)

        # Cabeçalhos da grade
        headers = [
            ("# / Ord.", 0),
            ("Label (UPPERCASE)", 1),
            ("Tipo Campo", 2),
            ("Obrigatório", 3),
            ("Observação", 4),
            ("Imp. Histórico", 5),
            ("Data Atual", 6),
            ("Hora Atual", 7),
            ("Detalhes Extras", 8),
        ]
        for text, col in headers:
            lbl = ttk.Label(
                grid_container,
                text=text,
                font=("Segoe UI", 8, "bold"),
                foreground="#1E293B",
            )
            sticky = tk.W if col in (1, 2, 8) else ""
            lbl.grid(row=0, column=col, padx=4, pady=(0, 4), sticky=sticky)

        # Linhas de respostas
        for idx, resp in enumerate(respostas, start=1):
            if not isinstance(resp, dict):
                continue

            row_obj = AnswerRowWidgets(resp, idx, on_modified=self.on_modified)
            self.answer_rows.append(row_obj)

            ordem_val = resp.get("ordenacao", idx)
            ttk.Label(
                grid_container,
                text=str(ordem_val),
                anchor=tk.CENTER,
            ).grid(row=idx, column=0, padx=4, pady=2)

            entry_lbl = ttk.Entry(
                grid_container,
                textvariable=row_obj.label_var,
                width=36,
            )
            entry_lbl.grid(row=idx, column=1, padx=4, pady=2, sticky=tk.EW)
            entry_lbl.bind("<FocusOut>", row_obj.commit_label_uppercase)
            entry_lbl.bind("<Return>", row_obj.commit_label_uppercase)
            row_obj.entry_label = entry_lbl

            tipo_campo = str(resp.get("tipo_campo") or "")
            ttk.Label(
                grid_container,
                text=tipo_campo,
                foreground="#0369A1",
                font=("Consolas", 9, "bold"),
            ).grid(row=idx, column=2, padx=6, pady=2, sticky=tk.W)

            chk_obrig = ttk.Checkbutton(
                grid_container,
                variable=row_obj.obrigatorio_var,
                command=lambda r=row_obj: r.on_boolean_toggled(
                    "campo_obrigatorio", r.obrigatorio_var
                ),
            )
            chk_obrig.grid(row=idx, column=3, padx=4, pady=2)
            row_obj.chk_obrigatorio = chk_obrig

            chk_obs = ttk.Checkbutton(
                grid_container,
                variable=row_obj.observacao_var,
                command=lambda r=row_obj: r.on_boolean_toggled(
                    "observacao", r.observacao_var
                ),
            )
            chk_obs.grid(row=idx, column=4, padx=4, pady=2)
            row_obj.chk_observacao = chk_obs

            chk_hist = ttk.Checkbutton(
                grid_container,
                variable=row_obj.importa_historico_var,
                command=lambda r=row_obj: r.on_boolean_toggled(
                    "importa_historico", r.importa_historico_var
                ),
            )
            chk_hist.grid(row=idx, column=5, padx=4, pady=2)
            row_obj.chk_importa_historico = chk_hist

            chk_data = ttk.Checkbutton(
                grid_container,
                variable=row_obj.valor_data_atual_var,
                command=lambda r=row_obj: r.on_boolean_toggled(
                    "valor_data_atual", r.valor_data_atual_var
                ),
            )
            chk_data.grid(row=idx, column=6, padx=4, pady=2)
            row_obj.chk_valor_data_atual = chk_data

            chk_hora = ttk.Checkbutton(
                grid_container,
                variable=row_obj.valor_hora_atual_var,
                command=lambda r=row_obj: r.on_boolean_toggled(
                    "valor_hora_atual", r.valor_hora_atual_var
                ),
            )
            chk_hora.grid(row=idx, column=7, padx=4, pady=2)
            row_obj.chk_valor_hora_atual = chk_hora

            extras = self._format_extra_fields(resp)
            ttk.Label(
                grid_container,
                text=extras,
                foreground="#64748B",
                font=("Segoe UI", 8),
            ).grid(row=idx, column=8, padx=6, pady=2, sticky=tk.W)

    @staticmethod
    def _format_extra_fields(resp: dict[str, Any]) -> str:
        """Resume campos adicionais relevantes da resposta (minimo, códigos, valores padrão)."""
        parts: list[str] = []
        if "minimo" in resp and resp["minimo"] is not None:
            parts.append(f"min={resp['minimo']}")
        for key in ("cid_codigo", "procedimento_codigo", "exame_id", "referencia", "valor_texto"):
            val = resp.get(key)
            if val is not None and val != "":
                parts.append(f"{key}={val}")
        return ", ".join(parts) if parts else "—"

    def commit_all_fields(self) -> None:
        """Garante que o nome da pergunta e todos os labels de respostas abertos estejam em UPPERCASE no JSON."""
        self.commit_question_name_uppercase()
        for row in self.answer_rows:
            row.commit_label_uppercase()


class PerguntasTab(ttk.Frame):
    """
    Aba 2 – Perguntas & Respostas.
    Exibe a lista expansível (accordion) de perguntas e respostas vinculadas ao
    dicionário JSON compartilhado (`shared_json`).
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

        self.question_items: list[QuestionAccordionItem] = []

        self._build_ui()
        if self.shared_json:
            self.refresh_from_shared()

    def _build_ui(self) -> None:
        """Constrói barra de ações no topo, área rolável de accordions no centro e barra de status."""
        # --- Topo: Barra de Ferramentas ---
        toolbar = ttk.Frame(self, padding=(10, 8, 10, 6))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.summary_var = tk.StringVar(value="Perguntas & Respostas")
        ttk.Label(
            toolbar,
            textvariable=self.summary_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 12))

        self.btn_expand_all = ttk.Button(
            toolbar,
            text="Expandir Todas",
            command=self.expand_all,
        )
        self.btn_expand_all.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_collapse_all = ttk.Button(
            toolbar,
            text="Recolher Todas",
            command=self.collapse_all,
        )
        self.btn_collapse_all.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_apply = ttk.Button(
            toolbar,
            text="Aplicar Alterações",
            command=self.apply_changes,
        )
        self.btn_apply.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_back = ttk.Button(
            toolbar,
            text="Voltar à Tela Inicial",
            command=self._handle_back_to_landing,
        )
        self.btn_back.pack(side=tk.RIGHT)

        # --- Base: Status ---
        status_frame = ttk.Frame(self, padding=(10, 4, 10, 6))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_var = tk.StringVar(
            value="Clique em uma pergunta para expandir e editar suas respostas (textos em UPPERCASE, booleanos via checkbox)."
        )
        ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # --- Centro: Área Rolável com Canvas + Frame Interno ---
        scroll_container = ttk.Frame(self, padding=(10, 4, 10, 4))
        scroll_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            scroll_container,
            highlightthickness=0,
            bd=0,
        )
        self.v_scrollbar = ttk.Scrollbar(
            scroll_container,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
        )
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self._canvas_window_id = self.canvas.create_window(
            (0, 0), window=self.scrollable_frame, anchor=tk.NW
        )
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)

        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_canvas_configure(self, event: Any) -> None:
        """Mantém a largura do frame interno igual à largura do Canvas."""
        self.canvas.itemconfig(self._canvas_window_id, width=event.width)

    def refresh_from_shared(self) -> None:
        """
        Reconstrói a lista de cards expansíveis (perguntas) a partir do
        dicionário compartilhado `self.shared_json`.
        """
        for child in self.scrollable_frame.winfo_children():
            child.destroy()
        self.question_items.clear()

        if not self.shared_json or not isinstance(self.shared_json, dict):
            self.summary_var.set("Nenhum JSON carregado.")
            return

        perguntas = self.shared_json.get("perguntas", [])
        if not isinstance(perguntas, list):
            self.summary_var.set("Lista 'perguntas' não encontrada no JSON.")
            return

        total_respostas = 0
        for idx, p_dict in enumerate(perguntas, start=1):
            if not isinstance(p_dict, dict):
                continue
            respostas = p_dict.get("respostas", [])
            if isinstance(respostas, list):
                total_respostas += len(respostas)

            # Expande automaticamente a primeira pergunta quando houver poucas ou para facilitar visualização imediata
            expand_first = idx == 1 and len(perguntas) <= 25
            card = QuestionAccordionItem(
                self.scrollable_frame,
                pergunta_dict=p_dict,
                question_index=idx,
                on_modified=self._on_item_modified,
                initially_expanded=expand_first,
            )
            card.pack(fill=tk.X, expand=True, pady=3)
            ttk.Separator(self.scrollable_frame, orient=tk.HORIZONTAL).pack(
                fill=tk.X, pady=1
            )
            self.question_items.append(card)

        tmpl = self.shared_json.get("template", {})
        nome_ficha = (
            tmpl.get("nome", "FICHA CLÍNICA")
            if isinstance(tmpl, dict)
            else "FICHA CLÍNICA"
        )
        self.summary_var.set(
            f"{nome_ficha} — {len(self.question_items)} perguntas | {total_respostas} respostas"
        )

    def expand_all(self) -> None:
        """Expande todas as perguntas da lista."""
        for item in self.question_items:
            if not item.is_expanded:
                item.expand()

    def collapse_all(self) -> None:
        """Recolhe todas as perguntas da lista."""
        for item in self.question_items:
            if item.is_expanded:
                item.collapse()

    def apply_changes(self) -> bool:
        """
        Força o commit e conversão para UPPERCASE de todos os campos de texto editáveis
        abertos na aba e propaga a atualização para o JSON compartilhado / Aba 1.
        """
        for item in self.question_items:
            item.commit_all_fields()

        if self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)

        self.status_var.set(
            "Alterações aplicadas ao JSON compartilhado (textos convertidos para UPPERCASE)."
        )
        return True

    def _on_item_modified(self) -> None:
        """Callback acionado imediatamente quando qualquer texto ou checkbox é editado."""
        if self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)
        self.status_var.set("JSON compartilhado atualizado automaticamente.")

    def _handle_back_to_landing(self) -> None:
        """Descarta a sessão de edição atual e retorna à Tela Inicial."""
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
