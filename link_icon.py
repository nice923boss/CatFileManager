"""Explorer-style arrow badge for NTFS junctions and symlinks."""

import os

from PySide6.QtCore import QFileInfo, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFileIconProvider

_SIZES = (16, 20, 24, 32, 48)


def _draw_badge(painter: QPainter, size: int):
    """White rounded box with a blue up-right arrow, in the bottom-left corner."""
    box = max(7, round(size * 0.55))
    r = QRectF(0.5, size - box - 0.5, box, box)
    painter.setPen(QPen(QColor("#9a9a9a"), 1))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(r, box * 0.15, box * 0.15)

    pad = box * 0.25
    tail = QPointF(r.left() + pad, r.bottom() - pad)
    head = QPointF(r.right() - pad, r.top() + pad)
    pen = QPen(QColor("#1a7fd6"), max(1.5, box * 0.16))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(tail, head)
    wing = box * 0.32
    painter.drawLine(head, QPointF(head.x() - wing, head.y()))
    painter.drawLine(head, QPointF(head.x(), head.y() + wing))


def link_target(path: str) -> str | None:
    """Real folder a junction/symlink points to, or None for a normal path."""
    if not (os.path.isjunction(path) or os.path.islink(path)):
        return None
    return os.path.realpath(path)


def with_link_overlay(base: QIcon) -> QIcon:
    """Return a copy of `base` with the link arrow badge painted on every size."""
    out = QIcon()
    for size in _SIZES:
        src = base.pixmap(size, size)
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, src)
        _draw_badge(painter, size)
        painter.end()
        out.addPixmap(pm)
    return out


class LinkAwareIconProvider(QFileIconProvider):
    """Icon provider for QFileSystemModel that badges junction/symlink entries."""

    def __init__(self):
        super().__init__()
        self._link_folder: QIcon | None = None

    def icon(self, arg):
        base = super().icon(arg)
        if isinstance(arg, QFileInfo) and (arg.isJunction() or arg.isSymbolicLink()):
            if arg.isDir():
                if self._link_folder is None:
                    self._link_folder = with_link_overlay(base)
                return self._link_folder
            return with_link_overlay(base)
        return base
