# -*- coding: utf-8 -*-
"""
Componente de Notificação Toast (src/gui/components/toast.py).

Implementa notificações flutuantes no canto superior direito da janela pai (ou tela),
com suporte a 4 níveis (`info`, `success`, `warning`, `error`), empilhamento vertical
(máximo 3 visíveis + fila), barra de progresso de auto-dismiss, animação de entrada/saída
(200ms) e botão de ação opcional.
"""

from __future__ import annotations

from collections import deque
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

TOAST_STYLES: dict[str, dict[str, str]] = {
    "info": {
        "icon": "ℹ",
        "border": "#3b82f6",
        "bg_light": "#eff6ff",
        "bg_dark": "#1e3a5f",
        "fg_light": "#0f172a",
        "fg_dark": "#f1f5f9",
        "title": "Informação",
    },
    "success": {
        "icon": "✓",
        "border": "#10b981",
        "bg_light": "#ecfdf5",
        "bg_dark": "#064e3b",
        "fg_light": "#0f172a",
        "fg_dark": "#f1f5f9",
        "title": "Sucesso",
    },
    "warning": {
        "icon": "⚠",
        "border": "#f59e0b",
        "bg_light": "#fffbeb",
        "bg_dark": "#78350f",
        "fg_light": "#0f172a",
        "fg_dark": "#f1f5f9",
        "title": "Atenção",
    },
    "error": {
        "icon": "✕",
        "border": "#ef4444",
        "bg_light": "#fef2f2",
        "bg_dark": "#7f1d1d",
        "fg_light": "#0f172a",
        "fg_dark": "#f1f5f9",
        "title": "Erro",
    },
}


class Toast(QFrame):
    """
    Widget de notificação flutuante empilhável no canto superior direito.

    Signals:
        closed (Toast): Emitido quando o toast termina de fechar.
    """

    closed = Signal(object)

    MAX_VISIBLE: int = 3
    MARGIN_TOP: int = 16
    MARGIN_RIGHT: int = 16
    STACK_GAP: int = 8
    ANIMATION_MS: int = 200

    _active_toasts: dict[int, list[Toast]] = {}
    _queued_toasts: dict[int, deque[dict[str, object]]] = {}

    def __init__(
        self,
        parent: QWidget | None,
        message: str,
        level: str = "info",
        duration: int = 4000,
        action_text: str = "",
        action_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = parent
        self.message = message
        self.level = level.lower() if level.lower() in TOAST_STYLES else "info"
        self.duration = max(0, int(duration))
        self.action_text = action_text
        self.action_callback = action_callback
        self._remaining_ms = self.duration
        self._is_closing = False

        if parent is None:
            self.setWindowFlags(
                Qt.WindowType.ToolTip
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        else:
            self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(f"Notificação {self.level}")
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
        self.setFixedWidth(340)

        self._build_ui()
        self._apply_style()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(50)
        self._tick_timer.timeout.connect(self._on_tick)

        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(self.ANIMATION_MS)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _build_ui(self) -> None:
        """Constrói o layout interno do Toast (ícone, título, mensagem, botão fechar, ação e progresso)."""
        style_meta = TOAST_STYLES[self.level]

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 10, 12, 8)
        root_layout.setSpacing(6)

        # Header: Ícone + Título + Botão Fechar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.lbl_icon = QLabel(style_meta["icon"], self)
        icon_font = QFont("Segoe UI", 11)
        icon_font.setBold(True)
        self.lbl_icon.setFont(icon_font)
        self.lbl_icon.setStyleSheet(f"color: {style_meta['border']}; background: transparent;")
        header_layout.addWidget(self.lbl_icon)

        self.lbl_title = QLabel(style_meta["title"], self)
        title_font = QFont("Segoe UI", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.lbl_title.setFont(title_font)
        self.lbl_title.setStyleSheet("background: transparent;")
        header_layout.addWidget(self.lbl_title, 1)

        self.btn_close = QPushButton("×", self)
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Fechar notificação")
        self.btn_close.setAccessibleName("Fechar notificação")
        self.btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 13pt; font-weight: bold; padding: 0px; }"
            "QPushButton:hover { background: rgba(148, 163, 184, 0.25); border-radius: 4px; }"
        )
        self.btn_close.clicked.connect(self.dismiss)
        header_layout.addWidget(self.btn_close)

        root_layout.addLayout(header_layout)

        # Mensagem
        self.lbl_message = QLabel(self.message, self)
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setStyleSheet("background: transparent; font-size: 9.5pt;")
        root_layout.addWidget(self.lbl_message)

        # Rodapé: Botão de Ação opcional + Tempo / Barra de progresso
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 2, 0, 0)
        footer_layout.setSpacing(8)

        self.btn_action: QPushButton | None = None
        if self.action_text:
            self.btn_action = QPushButton(self.action_text, self)
            self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_action.setAccessibleName(self.action_text)
            self.btn_action.setToolTip(self.action_text)
            self.btn_action.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; color: {style_meta['border']}; "
                "text-decoration: underline; font-weight: 600; padding: 2px 4px; text-align: left; }"
            )
            self.btn_action.clicked.connect(self._on_action_clicked)
            footer_layout.addWidget(self.btn_action)

        footer_layout.addStretch(1)

        self.lbl_timer = QLabel("", self)
        self.lbl_timer.setStyleSheet("background: transparent; font-size: 8pt; color: #64748b;")
        if self.duration > 0:
            self.lbl_timer.setText(f"{self.duration / 1000:.1f}s")
        footer_layout.addWidget(self.lbl_timer)

        root_layout.addLayout(footer_layout)

        # Barra de progresso inferior
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, max(1, self.duration))
        self.progress_bar.setValue(max(1, self.duration))
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background-color: rgba(148, 163, 184, 0.25); border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background-color: {style_meta['border']}; border-radius: 2px; }}"
        )
        root_layout.addWidget(self.progress_bar)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 45))
        self.setGraphicsEffect(shadow)

        self.adjustSize()

    def _apply_style(self) -> None:
        """Aplica cores de acordo com o nível e o tema atual da aplicação."""
        style_meta = TOAST_STYLES[self.level]
        is_dark = False
        app = QApplication.instance()
        if isinstance(app, QApplication):
            qss = app.styleSheet()
            if "#020617" in qss or "#0f172a" in qss[:300]:
                is_dark = True

        bg = style_meta["bg_dark"] if is_dark else style_meta["bg_light"]
        fg = style_meta["fg_dark"] if is_dark else style_meta["fg_light"]
        border = style_meta["border"]

        self.setStyleSheet(
            f"Toast {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {border}; border-left: 4px solid {border}; border-radius: 8px; }}"
            f"QLabel {{ color: {fg}; }}"
        )

    def _on_action_clicked(self) -> None:
        """Executa o callback de ação (se fornecido) e fecha o toast."""
        if self.action_callback is not None:
            self.action_callback()
        self.dismiss()

    def _on_tick(self) -> None:
        """Atualiza a barra de progresso linearmente até o auto-dismiss."""
        if self.duration <= 0:
            self._tick_timer.stop()
            return
        self._remaining_ms = max(0, self._remaining_ms - 50)
        self.progress_bar.setValue(self._remaining_ms)
        self.lbl_timer.setText(f"{self._remaining_ms / 1000:.1f}s")
        if self._remaining_ms <= 0:
            self._tick_timer.stop()
            self.dismiss()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Permite fechar o toast ao clicar nele."""
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismiss()

    def start_display(self, target_pos: QPoint) -> None:
        """Inicia a exibição com animação slide-in (200ms) e dispara o timer."""
        self.adjustSize()
        start_pos = QPoint(target_pos.x() + 60, target_pos.y())
        self.move(start_pos)
        super().show()
        self.raise_()

        self._pos_anim.stop()
        self._pos_anim.setStartValue(start_pos)
        self._pos_anim.setEndValue(target_pos)
        self._pos_anim.start()

        if self.duration > 0:
            self._tick_timer.start()

    def dismiss(self) -> None:
        """Anima a saída do toast e remove-o da pilha ativa."""
        if self._is_closing:
            return
        self._is_closing = True
        self._tick_timer.stop()

        end_pos = QPoint(self.x() + 60, self.y())
        self._pos_anim.stop()
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(end_pos)
        self._pos_anim.finished.connect(self._finalize_close)
        self._pos_anim.start()

    def _finalize_close(self) -> None:
        """Remove efetivamente o widget e processa a fila de toasts pendentes."""
        host_key = id(self._host) if self._host is not None else 0
        active_list = self._active_toasts.get(host_key, [])
        if self in active_list:
            active_list.remove(self)

        self.closed.emit(self)
        self.hide()
        self.deleteLater()

        Toast._reposition_stack(self._host)
        Toast._pop_queue(self._host)

    @classmethod
    def _reposition_stack(cls, parent: QWidget | None) -> None:
        """Reposiciona todos os toasts ativos empilhados no canto superior direito."""
        host_key = id(parent) if parent is not None else 0
        active_list = cls._active_toasts.get(host_key, [])
        if not active_list:
            return

        if parent is not None:
            host_width = parent.width()
            base_x = max(16, host_width - 340 - cls.MARGIN_RIGHT)
            current_y = cls.MARGIN_TOP
        else:
            screen = QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            base_x = (avail.right() - 340 - cls.MARGIN_RIGHT) if avail else 800
            current_y = (avail.top() + cls.MARGIN_TOP) if avail else cls.MARGIN_TOP

        for toast in active_list:
            toast.adjustSize()
            target = QPoint(base_x, current_y)
            toast.move(target)
            toast.raise_()
            current_y += toast.height() + cls.STACK_GAP

    @classmethod
    def _pop_queue(cls, parent: QWidget | None) -> None:
        """Exibe o próximo toast da fila se houver vaga na pilha (máx. 3 visíveis)."""
        host_key = id(parent) if parent is not None else 0
        active_list = cls._active_toasts.setdefault(host_key, [])
        queue = cls._queued_toasts.setdefault(host_key, deque())

        while len(active_list) < cls.MAX_VISIBLE and queue:
            params = queue.popleft()
            cls._create_and_display(
                parent=parent,
                message=str(params["message"]),
                level=str(params["level"]),
                duration=int(params["duration"]),  # type: ignore[arg-type]
                action_text=str(params["action_text"]),
                action_callback=params["action_callback"],  # type: ignore[arg-type]
            )

    @classmethod
    def _create_and_display(
        cls,
        parent: QWidget | None,
        message: str,
        level: str = "info",
        duration: int = 4000,
        action_text: str = "",
        action_callback: Callable[[], None] | None = None,
    ) -> Toast:
        host_key = id(parent) if parent is not None else 0
        active_list = cls._active_toasts.setdefault(host_key, [])

        toast = cls(
            parent=parent,
            message=message,
            level=level,
            duration=duration,
            action_text=action_text,
            action_callback=action_callback,
        )
        # Mais recente no topo (index 0)
        active_list.insert(0, toast)

        if parent is not None:
            host_width = parent.width()
            base_x = max(16, host_width - toast.width() - cls.MARGIN_RIGHT)
            base_y = cls.MARGIN_TOP
        else:
            screen = QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
            base_x = (avail.right() - toast.width() - cls.MARGIN_RIGHT) if avail else 800
            base_y = (avail.top() + cls.MARGIN_TOP) if avail else cls.MARGIN_TOP

        toast.start_display(QPoint(base_x, base_y))
        cls._reposition_stack(parent)
        return toast

    @staticmethod
    def show(  # type: ignore[override]
        parent: QWidget | None,
        message: str,
        level: str = "info",
        duration: int = 4000,
        action_text: str = "",
        action_callback: Callable[[], None] | None = None,
    ) -> Toast | None:
        """
        Exibe uma notificação Toast no canto superior direito de `parent`.

        Args:
            parent: Widget pai onde o toast será ancorado (ex.: `MainWindow`).
            message: Texto descritivo da notificação.
            level: Nível da notificação (`"info"`, `"success"`, `"warning"`, `"error"`).
            duration: Tempo em milissegundos até auto-dismiss (`0` para não fechar sozinho).
            action_text: Texto opcional do botão de ação.
            action_callback: Função invocada ao clicar no botão de ação.

        Returns:
            Instância de `Toast` se exibido imediatamente, ou `None` se enfileirado.
        """
        host_key = id(parent) if parent is not None else 0
        active_list = Toast._active_toasts.setdefault(host_key, [])
        queue = Toast._queued_toasts.setdefault(host_key, deque())

        if len(active_list) >= Toast.MAX_VISIBLE:
            queue.append(
                {
                    "message": message,
                    "level": level,
                    "duration": duration,
                    "action_text": action_text,
                    "action_callback": action_callback,
                }
            )
            return None

        return Toast._create_and_display(
            parent=parent,
            message=message,
            level=level,
            duration=duration,
            action_text=action_text,
            action_callback=action_callback,
        )
