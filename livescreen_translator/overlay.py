"""Transparent, always-on-top, click-through overlay that draws translations near the OCR positions."""
from __future__ import annotations

import sys
from typing import List

from PySide6.QtCore import QRect, Qt, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QGuiApplication
from PySide6.QtWidgets import QWidget

from .config import Settings
from .pipeline import TranslatedBlock


def _apply_windows_click_through(widget: QWidget) -> None:
    """Add WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE so clicks pass through to games."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


class OverlayWindow(QWidget):
    """Covers the whole virtual desktop; paints translation boxes at absolute screen coordinates."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._blocks: List[TranslatedBlock] = []
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.fit_to_virtual_desktop()

    def fit_to_virtual_desktop(self) -> None:
        rect = QRect()
        for screen in QGuiApplication.screens():
            rect = rect.united(screen.geometry())
        if rect.isNull():
            rect = QRect(0, 0, 1920, 1080)
        self.setGeometry(rect)

    def showEvent(self, event):
        super().showEvent(event)
        _apply_windows_click_through(self)

    @Slot(list)
    def set_blocks(self, blocks: List[TranslatedBlock]) -> None:
        self._blocks = list(blocks or [])
        self.update()

    def clear(self) -> None:
        self.set_blocks([])

    def blocks(self) -> List[TranslatedBlock]:
        return list(self._blocks)

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.update()

    def block_screen_rect(self, b: TranslatedBlock) -> QRect:
        """Absolute rect where the block's translation should be drawn."""
        r = self.settings.region
        x = r.x + b.x + self.settings.overlay_offset_x - self.x()
        y = r.y + b.y + self.settings.overlay_offset_y - self.y()
        return QRect(x, y, max(b.width, 40), max(b.height, 10))

    def compute_layout(self, b: TranslatedBlock) -> tuple:
        """Return (bg_rect, translation_text, original_text). Pure function of settings; testable."""
        font = QFont("Segoe UI", self.settings.font_size)
        fm = QFontMetrics(font)
        base = self.block_screen_rect(b)
        text = b.translation
        max_w = max(base.width(), 160)
        flags = Qt.TextWordWrap
        text_rect = fm.boundingRect(QRect(0, 0, max_w, 10_000), flags, text)
        h = text_rect.height() + 8
        w = text_rect.width() + 12
        original = b.original if self.settings.show_original else ""
        if original:
            small = QFont("Segoe UI", max(8, int(self.settings.font_size * 0.7)))
            sfm = QFontMetrics(small)
            orect = sfm.boundingRect(QRect(0, 0, max_w, 10_000), flags, original)
            h += orect.height() + 4
            w = max(w, orect.width() + 12)
        x, y = base.x(), base.y()
        x = min(max(0, x), max(0, self.width() - w))
        y = min(max(0, y), max(0, self.height() - h))
        return QRect(x, y, w, h), text, original

    def paintEvent(self, event):
        if not self._blocks:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        bg = QColor(self.settings.overlay_bg_color)
        bg.setAlphaF(self.settings.overlay_opacity)
        fg = QColor(self.settings.overlay_text_color)
        font = QFont("Segoe UI", self.settings.font_size)
        small = QFont("Segoe UI", max(8, int(self.settings.font_size * 0.7)))
        for b in self._blocks:
            rect, text, original = self.compute_layout(b)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, 6, 6)
            inner = rect.adjusted(6, 4, -6, -4)
            p.setPen(QPen(fg))
            if original:
                p.setFont(small)
                ofm = QFontMetrics(small)
                orect = ofm.boundingRect(QRect(inner.x(), inner.y(), inner.width(), 10_000), Qt.TextWordWrap, original)
                dim = QColor(fg); dim.setAlphaF(0.7)
                p.setPen(QPen(dim))
                p.drawText(orect, Qt.TextWordWrap, original)
                inner.setTop(orect.bottom() + 4)
                p.setPen(QPen(fg))
            p.setFont(font)
            p.drawText(inner, Qt.TextWordWrap, text)
        p.end()
