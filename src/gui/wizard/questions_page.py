# -*- coding: utf-8 -*-
"""
Página 2 do Wizard — QuestionsPage (src/gui/wizard/questions_page.py).

Implementa a visualização e edição interativa de perguntas e respostas em PySide6:
- Lista de perguntas em cards expansíveis (accordion) dentro de `QScrollArea`.
- Edição do nome da pergunta (convertido automaticamente para UPPERCASE) e flag `titulo`.
- Grade editável de respostas com `ordenacao`, `label` (UPPERCASE), `tipo_campo` (ComboBox com tipos válidos) e checkboxes
  (`campo_obrigatorio`, `observacao`, `importa_historico`, `valor_data_atual`, `valor_hora_atual`).
- Botão "Redefinir Alterações" para restaurar o estado original.
- Opera diretamente sobre o dicionário JSON compartilhado (`shared_json`).
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("gui.wizard.questions")

# Tipos válidos de campo conforme spec_sql_insert.md
TIPOS_CAMPO_VALIDOS = [
    "TEXTO",
    "TEXTO_LONGO",
    "INTEIRO",
    "DECIMAL",
    "BOOLEANO",
    "DATA",
    "HORA",
    "DATA_HORA",
    "CID",
    "PROCEDIMENTO",
    "EXAME",
    "SINAL_VITAL",
]


class _StringVarAdapter:
    """Adaptador compatível com `.get()` / `.set(str)` sobre `QLineEdit` ou `QLabel`."""

    def __init__(
        self,
        getter: Callable[[], str],
        setter: Callable[[str], None],
    ) -> None:
        self._getter = getter
        self._setter = setter

    def get(self) -> str:
        return self._getter()

    def set(self, value: str) -> None:
        self._setter(str(value))


class _BoolVarAdapter:
    """Adaptador compatível com `.get()` / `.set(bool)` sobre `QCheckBox`."""

    def __init__(
        self,
        getter: Callable[[], bool],
        setter: Callable[[bool], None],
    ) -> None:
        self._getter = getter
        self._setter = setter

    def get(self) -> bool:
        return bool(self._getter())

    def set(self, value: bool) -> None:
        self._setter(bool(value))


class AnswerRowWidgets:
    """Agrupa os widgets e adaptadores de uma linha de resposta na grade editável."""

    def __init__(
        self,
        resposta_dict: dict[str, Any],
        index: int,
        on_modified: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self.resposta = resposta_dict
        self.index = index
        self.on_modified = on_modified

        label_inicial = str(resposta_dict.get("label") or "").upper()
        resposta_dict["label"] = label_inicial

        obrig_val = bool(
            resposta_dict.get(
                "campo_obrigatorio", resposta_dict.get("obrigatorio", False)
            )
        )
        obs_val = bool(resposta_dict.get("observacao", False))
        hist_val = bool(resposta_dict.get("importa_historico", False))
        data_val = bool(resposta_dict.get("valor_data_atual", False))
        hora_val = bool(resposta_dict.get("valor_hora_atual", False))

        self.entry_label = QLineEdit(label_inicial, parent)
        self.entry_label.setAccessibleName(f"Label da resposta {index}")
        self.entry_label.editingFinished.connect(self.commit_label_uppercase)

        # ComboBox para tipo_campo
        self.combo_tipo_campo = QComboBox(parent)
        self.combo_tipo_campo.addItems(TIPOS_CAMPO_VALIDOS)
        tipo_atual = str(resposta_dict.get("tipo_campo") or "TEXTO")
        if tipo_atual in TIPOS_CAMPO_VALIDOS:
            self.combo_tipo_campo.setCurrentText(tipo_atual)
        else:
            self.combo_tipo_campo.setCurrentText("TEXTO")
        self.combo_tipo_campo.currentTextChanged.connect(self.on_tipo_campo_changed)

        self.chk_obrigatorio = QCheckBox(parent)
        self.chk_obrigatorio.setChecked(obrig_val)
        self.chk_obrigatorio.toggled.connect(
            lambda _checked: self.on_boolean_toggled("campo_obrigatorio", self.obrigatorio_var)
        )

        self.chk_observacao = QCheckBox(parent)
        self.chk_observacao.setChecked(obs_val)
        self.chk_observacao.toggled.connect(
            lambda _checked: self.on_boolean_toggled("observacao", self.observacao_var)
        )

        self.chk_importa_historico = QCheckBox(parent)
        self.chk_importa_historico.setChecked(hist_val)
        self.chk_importa_historico.toggled.connect(
            lambda _checked: self.on_boolean_toggled(
                "importa_historico", self.importa_historico_var
            )
        )

        self.chk_valor_data_atual = QCheckBox(parent)
        self.chk_valor_data_atual.setChecked(data_val)
        self.chk_valor_data_atual.toggled.connect(
            lambda _checked: self.on_boolean_toggled(
                "valor_data_atual", self.valor_data_atual_var
            )
        )

        self.chk_valor_hora_atual = QCheckBox(parent)
        self.chk_valor_hora_atual.setChecked(hora_val)
        self.chk_valor_hora_atual.toggled.connect(
            lambda _checked: self.on_boolean_toggled(
                "valor_hora_atual", self.valor_hora_atual_var
            )
        )

        self.label_var = _StringVarAdapter(
            self.entry_label.text, self.entry_label.setText
        )
        self.obrigatorio_var = _BoolVarAdapter(
            self.chk_obrigatorio.isChecked, self.chk_obrigatorio.setChecked
        )
        self.observacao_var = _BoolVarAdapter(
            self.chk_observacao.isChecked, self.chk_observacao.setChecked
        )
        self.importa_historico_var = _BoolVarAdapter(
            self.chk_importa_historico.isChecked, self.chk_importa_historico.setChecked
        )
        self.valor_data_atual_var = _BoolVarAdapter(
            self.chk_valor_data_atual.isChecked, self.chk_valor_data_atual.setChecked
        )
        self.valor_hora_atual_var = _BoolVarAdapter(
            self.chk_valor_hora_atual.isChecked, self.chk_valor_hora_atual.setChecked
        )

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

    def on_boolean_toggled(self, field_name: str, var: _BoolVarAdapter) -> None:
        """Atualiza imediatamente o campo booleano correspondente no dicionário da resposta."""
        val = bool(var.get())
        if field_name == "campo_obrigatorio":
            self.resposta["campo_obrigatorio"] = val
            if "obrigatorio" in self.resposta:
                self.resposta["obrigatorio"] = val
        else:
            self.resposta[field_name] = val
        self.on_modified()

    def on_tipo_campo_changed(self, new_tipo: str) -> None:
        """Atualiza o tipo_campo no dicionário da resposta quando o ComboBox muda."""
        self.resposta["tipo_campo"] = new_tipo
        self.on_modified()


class QuestionAccordionItem(QFrame):
    """Card expansível (accordion) representando uma pergunta do JSON e sua grade de respostas."""

    def __init__(
        self,
        parent: QWidget | None,
        pergunta_dict: dict[str, Any],
        question_index: int,
        on_modified: Callable[[], None],
        initially_expanded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.pergunta = pergunta_dict
        self.question_index = question_index
        self.on_modified = on_modified
        self.is_expanded = False
        self._body_built = False
        self.answer_rows: list[AnswerRowWidgets] = []

        self.setFrameShape(QFrame.Shape.StyledPanel)
        nome_inicial = str(self.pergunta.get("nome") or "").upper()
        self.pergunta["nome"] = nome_inicial

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(10, 8, 10, 8)
        self._root_layout.setSpacing(6)

        self._build_header(nome_inicial)
        self.body_frame = QWidget(self)
        self.body_frame.setVisible(False)
        self._root_layout.addWidget(self.body_frame)

        self.nome_var = _StringVarAdapter(self.entry_nome.text, self.entry_nome.setText)
        self.titulo_var = _BoolVarAdapter(
            self.chk_titulo.isChecked, self.chk_titulo.setChecked
        )

        if initially_expanded:
            self.expand()

    def _build_header(self, nome_inicial: str) -> None:
        header = QHBoxLayout()
        header.setSpacing(8)

        respostas = self.pergunta.get("respostas")
        qtd_respostas = len(respostas) if isinstance(respostas, list) else 0

        self.btn_toggle = QPushButton(f"▶ Pergunta {self.question_index}", self)
        self.btn_toggle.setFixedWidth(135)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle)
        header.addWidget(self.btn_toggle)

        header.addWidget(QLabel("Nome:", self))

        self.entry_nome = QLineEdit(nome_inicial, self)
        self.entry_nome.setAccessibleName(f"Nome da pergunta {self.question_index}")
        self.entry_nome.setStyleSheet("font-weight: 600;")
        self.entry_nome.editingFinished.connect(self.commit_question_name_uppercase)
        header.addWidget(self.entry_nome, 1)

        self.chk_titulo = QCheckBox("É Título (Divisor)", self)
        self.chk_titulo.setChecked(bool(self.pergunta.get("titulo", False)))
        self.chk_titulo.toggled.connect(self._on_titulo_toggled)
        header.addWidget(self.chk_titulo)

        self.lbl_count = QLabel(
            f"({qtd_respostas} resposta{'s' if qtd_respostas != 1 else ''})",
            self,
        )
        self.lbl_count.setStyleSheet("color: #64748b;")
        header.addWidget(self.lbl_count)

        self._root_layout.addLayout(header)

    def commit_question_name_uppercase(self, _event: Any = None) -> None:
        """Converte o nome da pergunta para UPPERCASE e atualiza o JSON."""
        upper_val = self.entry_nome.text().upper()
        if self.entry_nome.text() != upper_val:
            self.entry_nome.setText(upper_val)
        if self.pergunta.get("nome") != upper_val:
            self.pergunta["nome"] = upper_val
            self.on_modified()
        else:
            self.pergunta["nome"] = upper_val

    def _on_titulo_toggled(self, checked: bool) -> None:
        self.pergunta["titulo"] = bool(checked)
        self.on_modified()

    def toggle(self) -> None:
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        if not self._body_built:
            self._build_answers_grid()
            self._body_built = True
        self.body_frame.setVisible(True)
        self.is_expanded = True
        self.btn_toggle.setText(f"▼ Pergunta {self.question_index}")

    def collapse(self) -> None:
        self.commit_all_fields()
        self.body_frame.setVisible(False)
        self.is_expanded = False
        self.btn_toggle.setText(f"▶ Pergunta {self.question_index}")

    def _build_answers_grid(self) -> None:
        self.answer_rows.clear()
        layout = QVBoxLayout(self.body_frame)
        layout.setContentsMargins(16, 4, 4, 4)

        respostas = self.pergunta.get("respostas", [])
        if not isinstance(respostas, list) or not respostas:
            lbl_empty = QLabel(
                "Nenhuma resposta vinculada a esta pergunta (ex.: divisor de seção).",
                self.body_frame,
            )
            lbl_empty.setStyleSheet("color: #64748b; font-style: italic;")
            layout.addWidget(lbl_empty)
            return

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

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
            lbl = QLabel(text, self.body_frame)
            lbl.setStyleSheet("font-weight: 600; font-size: 8.5pt;")
            grid.addWidget(lbl, 0, col)

        for idx, resp in enumerate(respostas, start=1):
            if not isinstance(resp, dict):
                continue

            row_obj = AnswerRowWidgets(
                resp, idx, on_modified=self.on_modified, parent=self.body_frame
            )
            self.answer_rows.append(row_obj)

            ordem_val = resp.get("ordenacao", idx)
            grid.addWidget(QLabel(str(ordem_val), self.body_frame), idx, 0)
            grid.addWidget(row_obj.entry_label, idx, 1)

            grid.addWidget(row_obj.combo_tipo_campo, idx, 2)

            grid.addWidget(row_obj.chk_obrigatorio, idx, 3, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(row_obj.chk_observacao, idx, 4, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(row_obj.chk_importa_historico, idx, 5, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(row_obj.chk_valor_data_atual, idx, 6, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(row_obj.chk_valor_hora_atual, idx, 7, Qt.AlignmentFlag.AlignCenter)

            extras = self._format_extra_fields(resp)
            lbl_extra = QLabel(extras, self.body_frame)
            lbl_extra.setStyleSheet("color: #64748b; font-size: 8.5pt;")
            grid.addWidget(lbl_extra, idx, 8)

        layout.addLayout(grid)

    @staticmethod
    def _format_extra_fields(resp: dict[str, Any]) -> str:
        parts: list[str] = []
        if "minimo" in resp and resp["minimo"] is not None:
            parts.append(f"min={resp['minimo']}")
        for key in (
            "cid_codigo",
            "procedimento_codigo",
            "exame_id",
            "referencia",
            "valor_texto",
        ):
            val = resp.get(key)
            if val is not None and val != "":
                parts.append(f"{key}={val}")
        return ", ".join(parts) if parts else "—"

    def commit_all_fields(self) -> None:
        self.commit_question_name_uppercase()
        for row in self.answer_rows:
            row.commit_label_uppercase()


class _CallableButton(QPushButton):
    """`QPushButton` com método `.invoke()` de compatibilidade para testes."""

    def invoke(self) -> None:
        self.click()


class QuestionsPage(QWidget):
    """
    Página 2 do Wizard: Perguntas & Respostas em cards expansíveis (accordion).

    Signals:
        json_changed (dict): Emitido quando o JSON compartilhado é modificado.
        back_to_landing_requested (): Emitido ao clicar em Voltar à Tela Inicial.
    """

    json_changed = Signal(dict)
    back_to_landing_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        shared_json: dict[str, Any] | None = None,
        on_json_changed: Callable[[dict[str, Any]], None] | None = None,
        on_back_to_landing: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.shared_json: dict[str, Any] = shared_json if shared_json is not None else {}
        self.on_json_changed = on_json_changed
        self.on_back_to_landing = on_back_to_landing
        self.question_items: list[QuestionAccordionItem] = []
        self._original_state: dict[str, Any] | None = None  # Para reset

        self.setAccessibleName("Perguntas e Respostas")
        self._build_ui()

        self.summary_var = _StringVarAdapter(self.lbl_summary.text, self.lbl_summary.setText)
        self.status_var = _StringVarAdapter(self.lbl_status.text, self.lbl_status.setText)

        if self.shared_json:
            self.refresh_from_shared()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(8)

        # Barra de ferramentas superior
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.lbl_summary = QLabel("Perguntas & Respostas", self)
        self.lbl_summary.setStyleSheet("font-weight: 700; font-size: 10.5pt;")
        toolbar.addWidget(self.lbl_summary)

        self.btn_expand_all = _CallableButton("Expandir Todas", self)
        self.btn_expand_all.setAccessibleName("Expandir Todas as Perguntas")
        self.btn_expand_all.clicked.connect(self.expand_all)
        toolbar.addWidget(self.btn_expand_all)

        self.btn_collapse_all = _CallableButton("Recolher Todas", self)
        self.btn_collapse_all.setAccessibleName("Recolher Todas as Perguntas")
        self.btn_collapse_all.clicked.connect(self.collapse_all)
        toolbar.addWidget(self.btn_collapse_all)

        self.btn_apply = _CallableButton("Aplicar Alterações", self)
        self.btn_apply.setProperty("variant", "primary")
        self.btn_apply.setAccessibleName("Aplicar Alterações nas Perguntas")
        self.btn_apply.clicked.connect(self.apply_changes)
        toolbar.addWidget(self.btn_apply)

        self.btn_reset = _CallableButton("Redefinir Alterações", self)
        self.btn_reset.setAccessibleName("Redefinir Alterações para o Estado Original")
        self.btn_reset.setToolTip("Descarta todas as alterações e restaura o JSON original carregado")
        self.btn_reset.clicked.connect(self.reset_changes)
        toolbar.addWidget(self.btn_reset)

        toolbar.addStretch(1)

        self.btn_back = _CallableButton("Voltar à Tela Inicial", self)
        self.btn_back.setAccessibleName("Voltar à Tela Inicial")
        self.btn_back.clicked.connect(self._handle_back_to_landing)
        toolbar.addWidget(self.btn_back)

        root_layout.addLayout(toolbar)

        # Área rolável central
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scrollable_frame = QWidget(self.scroll_area)
        self.cards_layout = QVBoxLayout(self.scrollable_frame)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)

        self.scroll_area.setWidget(self.scrollable_frame)
        root_layout.addWidget(self.scroll_area, 1)

        # Status inferior
        self.lbl_status = QLabel(
            "Clique em uma pergunta para expandir e editar suas respostas (textos em UPPERCASE, booleanos via checkbox).",
            self,
        )
        self.lbl_status.setAccessibleName("Status de Perguntas e Respostas")
        root_layout.addWidget(self.lbl_status)

    def refresh_from_shared(self) -> None:
        """Reconstrói a lista de cards expansíveis a partir de `self.shared_json`."""
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self.question_items.clear()

        if not self.shared_json or not isinstance(self.shared_json, dict):
            self.lbl_summary.setText("Nenhum JSON carregado.")
            self.cards_layout.addStretch(1)
            self._original_state = None
            return

        perguntas = self.shared_json.get("perguntas", [])
        if not isinstance(perguntas, list):
            self.lbl_summary.setText("Lista 'perguntas' não encontrada no JSON.")
            self.cards_layout.addStretch(1)
            self._original_state = None
            return

        # Salva cópia profunda do estado original para reset
        self._original_state = copy.deepcopy(self.shared_json)

        total_respostas = 0
        for idx, p_dict in enumerate(perguntas, start=1):
            if not isinstance(p_dict, dict):
                continue
            respostas = p_dict.get("respostas", [])
            if isinstance(respostas, list):
                total_respostas += len(respostas)

            card = QuestionAccordionItem(
                self.scrollable_frame,
                pergunta_dict=p_dict,
                question_index=idx,
                on_modified=self._on_item_modified,
                initially_expanded=False,
            )
            self.cards_layout.addWidget(card)
            self.question_items.append(card)

        self.cards_layout.addStretch(1)

        tmpl = self.shared_json.get("template", {})
        nome_ficha = (
            tmpl.get("nome", "FICHA CLÍNICA")
            if isinstance(tmpl, dict)
            else "FICHA CLÍNICA"
        )
        self.lbl_summary.setText(
            f"{nome_ficha} — {len(self.question_items)} perguntas | {total_respostas} respostas"
        )

    def expand_all(self) -> None:
        for item in self.question_items:
            if not item.is_expanded:
                item.expand()

    def collapse_all(self) -> None:
        for item in self.question_items:
            if item.is_expanded:
                item.collapse()

    def apply_changes(self) -> bool:
        for item in self.question_items:
            item.commit_all_fields()

        if self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)
        self.json_changed.emit(self.shared_json)

        self.lbl_status.setText(
            "Alterações aplicadas ao JSON compartilhado (textos convertidos para UPPERCASE)."
        )
        return True

    def _on_item_modified(self) -> None:
        if self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)
        self.json_changed.emit(self.shared_json)
        self.lbl_status.setText("JSON compartilhado atualizado automaticamente.")

    def _handle_back_to_landing(self) -> None:
        if self.on_back_to_landing is not None:
            self.on_back_to_landing()
        self.back_to_landing_requested.emit()

    def reset_changes(self) -> bool:
        """Redefine todas as alterações, restaurando o JSON ao estado original carregado."""
        if self._original_state is None:
            self.lbl_status.setText("Nenhum estado original salvo para restaurar.")
            return False

        # Restaura o estado original no shared_json in-place
        self.shared_json.clear()
        self.shared_json.update(copy.deepcopy(self._original_state))

        # Reconstrói a UI a partir do estado restaurado
        self.refresh_from_shared()

        # Notifica listeners
        if self.on_json_changed is not None:
            self.on_json_changed(self.shared_json)
        self.json_changed.emit(self.shared_json)

        self.lbl_status.setText("Alterações descartadas — JSON restaurado ao estado original.")
        return True
