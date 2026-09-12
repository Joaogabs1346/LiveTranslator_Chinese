"""Full-screen rubber-band selector + a resizable/movable frame showing the current region."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QCursor
from PySide6.QtWidgets import QWidget

from .config import Region


class RegionSelector(QWidget):
    """Dim the whole desktop and let the user drag a rectangle. Emits `selected(Region)`."""

    selected = Signal(object)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(QCursor(Qt.CrossCursor))
        rect = QRect()
        for s in QGuiApplication.screens():
            rect = rect.united(s.geometry())
        self.setGeometry(rect if not rect.isNull() else QRect(0, 0, 1920, 1080))
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._origin and self._current:
            sel = QRect(self._origin, self._current).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(sel, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(0, 170, 255), 2))
            p.drawRect(sel)
            p.setPen(QColor(255, 255, 255))
            p.drawText(sel.bottomLeft() + QPoint(4, 18), f"{sel.width()} x {sel.height()}")
        else:
            p.setPen(QColor(255, 255, 255))
            p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                       "Drag to select the region to translate. Esc to cancel.")
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._origin is not None:
            sel = QRect(self._origin, e.position().toPoint()).normalized()
            self._origin = self._current = None
            self.close()
            region = Region(sel.x() + self.x(), sel.y() + self.y(), sel.width(), sel.height())
            if region.is_valid():
                self.selected.emit(region)
            else:
                self.cancelled.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()


class RegionFrame(QWidget):
    """A movable/resizable transparent frame showing the region. Emits `changed(Region)`."""

    changed = Signal(object)
    HANDLE = 12

    def __init__(self, region: Region):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setGeometry(region.x, region.y, max(region.width, 40), max(region.height, 40))
        self._drag_mode: Optional[str] = None
        self._drag_start = QPoint()
        self._start_geom = QRect()

    def region(self) -> Region:
        g = self.geometry()
        return Region(g.x(), g.y(), g.width(), g.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor(0, 170, 255), 3))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.fillRect(QRect(self.width() - self.HANDLE, self.height() - self.HANDLE, self.HANDLE, self.HANDLE),
                   QColor(0, 170, 255))
        p.setPen(QColor(255, 255, 255))
        p.fillRect(QRect(4, 4, 260, 20), QColor(0, 0, 0, 160))
        p.drawText(QRect(8, 4, 260, 20), Qt.AlignVCenter,
                   f"Drag to move, corner to resize. {self.width()}x{self.height()}")
        p.end()

    def _in_handle(self, pos: QPoint) -> bool:
        return pos.x() >= self.width() - self.HANDLE and pos.y() >= self.height() - self.HANDLE

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pos = e.position().toPoint()
            self._drag_mode = "resize" if self._in_handle(pos) else "move"
            self._drag_start = e.globalPosition().toPoint()
            self._start_geom = self.geometry()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        self.setCursor(Qt.SizeFDiagCursor if self._in_handle(pos) else Qt.SizeAllCursor)
        if self._drag_mode is None:
            return
        delta = e.globalPosition().toPoint() - self._drag_start
        g = QRect(self._start_geom)
        if self._drag_mode == "move":
            g.moveTopLeft(g.topLeft() + delta)
        else:
            g.setWidth(max(40, g.width() + delta.x()))
            g.setHeight(max(40, g.height() + delta.y()))
        self.setGeometry(g)

    def mouseReleaseEvent(self, e):
        if self._drag_mode is not None:
            self._drag_mode = None
            self.changed.emit(self.region())
