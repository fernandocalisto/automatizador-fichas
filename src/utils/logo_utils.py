# -*- coding: utf-8 -*-
"""
Utilitários para carregamento e arredondamento de bordas do logo (src/utils/logo_utils.py).

Fornece `create_rounded_pixmap(pixmap, radius)` e helpers para aplicar cantos
arredondados suaves com antialiasing em `QPixmap`, `QIcon`, `QSplashScreen` e `QLabel`.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBitmap, QColor, QIcon, QPainter, QPainterPath, QPixmap

import src.resources.resources_rc  # noqa: F401
from src.utils.resource_path import resource_path

LOGO_RESOURCE_Candidates: tuple[str, ...] = (
    ":/resources/salutem_ferramenta_interna_logo.png",
    ":/salutem_ferramenta_interna_logo.png",
)


def create_rounded_pixmap(pixmap: QPixmap, radius: int | float = 12) -> QPixmap:
    """
    Retorna um novo `QPixmap` com cantos arredondados suaves (`radius` em pixels)
    utilizando `QPainter` + `QPainterPath` com `Antialiasing` e fundo transparente.

    Args:
        pixmap: `QPixmap` de origem.
        radius: Raio de curvatura dos cantos em pixels.

    Returns:
        `QPixmap` com máscara de recorte arredondada e canal alfa transparente.
    """
    if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
        return QPixmap()

    w = pixmap.width()
    h = pixmap.height()
    r = max(0.0, float(radius))

    rounded = QPixmap(w, h)
    rounded.fill(Qt.GlobalColor.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    path = QPainterPath()
    path.addRoundedRect(QRectF(0.0, 0.0, float(w), float(h)), r, r)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()

    return rounded


def create_rounded_mask(size: QSize, radius: int | float = 12) -> QBitmap:
    """
    Cria uma máscara `QBitmap` com retângulo arredondado para uso em `widget.setMask(...)`.

    Args:
        size: Dimensões (`QSize`) do widget ou pixmap.
        radius: Raio dos cantos em pixels.

    Returns:
        `QBitmap` monocromático com a região arredondada preenchida.
    """
    w = max(1, size.width())
    h = max(1, size.height())
    r = max(0.0, float(radius))

    bmp = QBitmap(w, h)
    bmp.fill(Qt.GlobalColor.color0)

    painter = QPainter(bmp)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush( QColor(Qt.GlobalColor.color1) )
    painter.drawRoundedRect(QRectF(0.0, 0.0, float(w), float(h)), r, r)
    painter.end()

    return bmp


def load_raw_logo_pixmap() -> QPixmap:
    """Carrega o `QPixmap` bruto do logo oficial Salutem a partir do qrc ou do disco."""
    for candidate in (
        *LOGO_RESOURCE_Candidates,
        str(resource_path("salutem_ferramenta_interna_logo.png")),
    ):
        pm = QPixmap(candidate)
        if not pm.isNull():
            return pm
    return QPixmap()


def load_logo_pixmap(
    width: int | None = None,
    height: int | None = None,
    radius: int | float | None = None,
) -> QPixmap:
    """
    Carrega o logo da aplicação redimensionado (mantendo aspect ratio) e opcionalmente
    aplica cantos arredondados (`create_rounded_pixmap`).

    Args:
        width: Largura máxima opcional em pixels.
        height: Altura máxima opcional em pixels.
        radius: Raio opcional em pixels para cantos arredondados.

    Returns:
        `QPixmap` processado.
    """
    pm = load_raw_logo_pixmap()
    if pm.isNull():
        return QPixmap()

    if width is not None and height is not None:
        pm = pm.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    elif height is not None:
        pm = pm.scaledToHeight(
            height,
            Qt.TransformationMode.SmoothTransformation,
        )
    elif width is not None:
        pm = pm.scaledToWidth(
            width,
            Qt.TransformationMode.SmoothTransformation,
        )

    if radius is not None and radius > 0:
        pm = create_rounded_pixmap(pm, radius)

    return pm


def load_rounded_app_icon(radius: int | float = 8) -> QIcon:
    """
    Cria o `QIcon` da janela/taskbar/Alt+Tab com cantos arredondados (padrão 8px na escala base 64px).

    Args:
        radius: Raio base em pixels (aplicado proporcionalmente aos tamanhos do ícone).

    Returns:
        `QIcon` contendo múltiplos tamanhos arredondados.
    """
    raw = load_raw_logo_pixmap()
    if raw.isNull():
        return QIcon()

    icon = QIcon()
    base_r = max(1.0, float(radius))
    for sz in (16, 24, 32, 48, 64, 128, 256):
        scaled = raw.scaled(
            sz,
            sz,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Escala o raio proporcionalmente a 64px (ex.: 64px -> 8px, 32px -> 4px, 128px -> 16px)
        scaled_radius = max(2.0, base_r * (sz / 64.0))
        rounded = create_rounded_pixmap(scaled, scaled_radius)
        icon.addPixmap(rounded)

    return icon


__all__ = [
    "create_rounded_mask",
    "create_rounded_pixmap",
    "load_logo_pixmap",
    "load_raw_logo_pixmap",
    "load_rounded_app_icon",
]
