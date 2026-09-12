"""Main window: status, region selection, model choice, start/stop, settings, log view."""
from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QGroupBox, QFrame)

from .. import __app_name__, __version__
from ..config import Region, Settings
from ..hotkey import GlobalHotkey
from ..logger import get_logger, log_path, setup_logging
from ..ocr import ChineseOCR
from ..ollama_client import OllamaClient, OllamaError
from ..overlay import OverlayWindow
from ..pipeline import PipelineCallbacks, TranslatedBlock, TranslationPipeline
from ..region_selector import RegionFrame, RegionSelector
from .settings_dialog import SettingsDialog

log = get_logger("ui")

STYLE = """
QMainWindow, QDialog { background: #1e1f26; }
QWidget { color: #e6e6e6; font-family: 'Segoe UI'; font-size: 13px; }
QGroupBox { border: 1px solid #3a3c48; border-radius: 8px; margin-top: 12px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0b4; }
QPushButton { background: #2f3140; border: 1px solid #454858; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #3a3d4f; }
QPushButton:disabled { color: #777; }
QPushButton#primary { background: #2e7dff; border-color: #2e7dff; font-weight: 600; }
QPushButton#primary:hover { background: #4a90ff; }
QPushButton#danger { background: #c9403f; border-color: #c9403f; font-weight: 600; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit { background: #15161c; border: 1px solid #3a3c48; border-radius: 6px; padding: 4px 6px; }
QLabel#status_ok { color: #47d16c; font-weight: 600; }
QLabel#status_bad { color: #ff6b6b; font-weight: 600; }
QLabel#muted { color: #9aa0b4; }
"""


class _Bridge(QObject):
    """Marshals pipeline-thread callbacks onto the Qt main thread via signals."""
    result = Signal(list)
    status = Signal(str)
    error = Signal(str, bool)
    hotkey = Signal()
    manual = Signal()
    clear = Signal()


class _OllamaProbe(QThread):
    done = Signal(bool, str, list)

    def __init__(self, url: str):
        super().__init__(); self.url = url

    def run(self):
        client = OllamaClient(self.url, timeout=6)
        st = client.test_connection()
        models: List[str] = []
        if st.connected:
            try:
                models = client.list_models()
            except OllamaError:
                pass
        self.done.emit(st.connected, st.message, models)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE)

        self.bridge = _Bridge()
        self.bridge.result.connect(self._on_result)
        self.bridge.status.connect(self._on_status)
        self.bridge.error.connect(self._on_error)
        self.bridge.hotkey.connect(self.toggle_translation)
        self.bridge.manual.connect(self.translate_now)
        self.bridge.clear.connect(self.clear_overlay)

        self.overlay = OverlayWindow(settings)
        self.pipeline: Optional[TranslationPipeline] = None
        self.ocr_engine: Optional[ChineseOCR] = None
        self.region_frame: Optional[RegionFrame] = None
        self._selector: Optional[RegionSelector] = None
        self._probe: Optional[_OllamaProbe] = None
        self.hotkey = GlobalHotkey()
        self.manual_hotkey = GlobalHotkey()
        self.clear_hotkey = GlobalHotkey()

        self._build_ui()
        self._apply_hotkey()
        self.refresh_ollama()
        self._poll = QTimer(self); self._poll.setInterval(15000); self._poll.timeout.connect(self.refresh_ollama)
        self._poll.start()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setSpacing(10)

        title = QLabel(f"<b style='font-size:18px'>{__app_name__}</b><br>"
                       "<span style='color:#9aa0b4'>Chinese → English screen overlay. 100% local.</span>")
        root.addWidget(title)

        g = QGroupBox("Status"); l = QVBoxLayout(g)
        row = QHBoxLayout()
        self.lb_ollama = QLabel("Ollama: checking..."); self.lb_ollama.setObjectName("muted")
        self.bt_test = QPushButton("Test Connection"); self.bt_test.clicked.connect(self.refresh_ollama)
        row.addWidget(self.lb_ollama, 1); row.addWidget(self.bt_test)
        l.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Model:"))
        self.cb_model = QComboBox(); self.cb_model.setEditable(True); self.cb_model.setEditText(self.settings.ollama_model)
        self.cb_model.currentTextChanged.connect(self._model_changed)
        self.bt_models = QPushButton("Refresh models"); self.bt_models.clicked.connect(self.refresh_ollama)
        row.addWidget(self.cb_model, 1); row.addWidget(self.bt_models)
        l.addLayout(row)
        self.lb_pipeline = QLabel("Translation: stopped"); self.lb_pipeline.setObjectName("muted")
        l.addWidget(self.lb_pipeline)
        root.addWidget(g)

        g = QGroupBox("Capture region"); l = QVBoxLayout(g)
        row = QHBoxLayout()
        self.lb_region = QLabel(); self._update_region_label()
        self.bt_region = QPushButton("Select Region"); self.bt_region.clicked.connect(self.select_region)
        self.bt_frame = QPushButton("Show/adjust frame"); self.bt_frame.clicked.connect(self.toggle_region_frame)
        row.addWidget(self.lb_region, 1); row.addWidget(self.bt_region); row.addWidget(self.bt_frame)
        l.addLayout(row)
        root.addWidget(g)

        row = QHBoxLayout()
        self.bt_start = QPushButton("Start Translation"); self.bt_start.setObjectName("primary")
        self.bt_start.clicked.connect(self.toggle_translation)
        self.bt_settings = QPushButton("Settings"); self.bt_settings.clicked.connect(self.open_settings)
        self.bt_clear = QPushButton("Clear overlay"); self.bt_clear.clicked.connect(self.clear_overlay)
        self.bt_now = QPushButton("Translate now"); self.bt_now.clicked.connect(self.translate_now)
        row.addWidget(self.bt_start, 2); row.addWidget(self.bt_now); row.addWidget(self.bt_settings); row.addWidget(self.bt_clear)
        root.addLayout(row)
        self.lb_hotkey = QLabel(); self.lb_hotkey.setObjectName("muted"); root.addWidget(self.lb_hotkey)

        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(300)
        self.log_view.setMinimumHeight(140)
        root.addWidget(self.log_view, 1)

        priv = QLabel("🔒 Privacy: screenshots never leave this PC. OCR runs locally (PaddleOCR) and only the "
                      "recognized text is sent to your local Ollama server. No account, no API key, no cloud.")
        priv.setWordWrap(True); priv.setObjectName("muted")
        root.addWidget(priv)
        lp = QLabel(f"Log file: {log_path()}"); lp.setObjectName("muted"); lp.setWordWrap(True)
        root.addWidget(lp)

    def _log(self, msg: str):
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _update_region_label(self):
        r = self.settings.region
        self.lb_region.setText(f"{r.width}×{r.height} at ({r.x}, {r.y})" if r.is_valid() else "No region selected")

    @Slot()
    def refresh_ollama(self):
        if self._probe and self._probe.isRunning():
            return
        self._probe = _OllamaProbe(self.settings.ollama_url)
        self._probe.done.connect(self._probe_done)
        self._probe.start()

    @Slot(bool, str, list)
    def _probe_done(self, ok: bool, msg: str, models: list):
        if ok:
            self.lb_ollama.setText(f"Ollama: Connected  ({msg})"); self.lb_ollama.setObjectName("status_ok")
        else:
            self.lb_ollama.setText(f"Ollama: Offline  ({msg})"); self.lb_ollama.setObjectName("status_bad")
        self.lb_ollama.setStyleSheet(self.styleSheet())
        if models:
            current = self.cb_model.currentText()
            self.cb_model.blockSignals(True)
            self.cb_model.clear(); self.cb_model.addItems(models)
            self.cb_model.setEditText(current or self.settings.ollama_model)
            self.cb_model.blockSignals(False)
            if self.settings.ollama_model not in models and f"{self.settings.ollama_model}:latest" not in models:
                self._log(f"Model '{self.settings.ollama_model}' is not installed. Run: ollama pull {self.settings.ollama_model}")
        elif ok:
            self._log("Ollama is running but has no models. Run: ollama pull qwen3:8b")

    def _model_changed(self, text: str):
        text = text.strip()
        if text and text != self.settings.ollama_model:
            self.settings.ollama_model = text
            self.settings.save()
            if self.pipeline:
                self.pipeline.client.model = text

    @Slot()
    def select_region(self):
        self._hide_region_frame()
        self._selector = RegionSelector()
        self._selector.selected.connect(self._region_selected)
        self._selector.cancelled.connect(lambda: self._log("Region selection cancelled"))
        self._selector.showFullScreen()
        self._selector.activateWindow()

    @Slot(object)
    def _region_selected(self, region: Region):
        self.settings.region = region
        self.settings.save()
        self._update_region_label()
        self._log(f"Region selected: {region.as_tuple()}")
        if self.pipeline:
            self.pipeline.reset_dedup()
        self.overlay.clear()

    def toggle_region_frame(self):
        if self.region_frame and self.region_frame.isVisible():
            self._hide_region_frame(); return
        if not self.settings.region.is_valid():
            self.select_region(); return
        self.region_frame = RegionFrame(self.settings.region)
        self.region_frame.changed.connect(self._region_selected)
        self.region_frame.show()

    def _hide_region_frame(self):
        if self.region_frame:
            self.region_frame.close(); self.region_frame = None

    @Slot()
    def toggle_translation(self):
        if self.pipeline and self.pipeline.running:
            self.stop_translation()
        else:
            self.start_translation()

    def start_translation(self):
        if not self.settings.region.is_valid():
            QMessageBox.warning(self, "No region", "Select a capture region first."); return
        if not self.settings.ollama_model:
            QMessageBox.warning(self, "No model", "Choose an Ollama model first."); return
        self._hide_region_frame()
        cbs = PipelineCallbacks(on_result=self.bridge.result.emit, on_status=self.bridge.status.emit,
                                on_error=self.bridge.error.emit)
        s = self.settings
        s.translate_mode = "manual"
        if (self.ocr_engine is None or self.ocr_engine.language != s.ocr_language
                or self.ocr_engine.use_gpu != s.ocr_use_gpu):
            self.ocr_engine = ChineseOCR(s.ocr_language, s.ocr_use_gpu, s.ocr_min_confidence)
        self.ocr_engine.min_confidence = s.ocr_min_confidence
        self.pipeline = TranslationPipeline(self.settings, cbs, ocr=self.ocr_engine)
        self.pipeline.start()
        self.overlay.apply_settings(self.settings)
        self.overlay.show()
        self.bt_start.setText("Stop Translation"); self.bt_start.setObjectName("danger")
        self.bt_start.setStyleSheet(self.styleSheet())
        self.lb_pipeline.setText("Translation: starting...")
        self._log(f"Translation armed. Press [{self.settings.manual_hotkey.upper()}] to translate the region, "
                  f"[{self.settings.clear_hotkey.upper() or '-'}] to clear.")

    def stop_translation(self):
        if self.pipeline:
            self.pipeline.stop(); self.pipeline = None
        self.overlay.clear(); self.overlay.hide()
        self.bt_start.setText("Start Translation"); self.bt_start.setObjectName("primary")
        self.bt_start.setStyleSheet(self.styleSheet())
        self.lb_pipeline.setText("Translation: stopped"); self._log("Translation stopped")

    @Slot(list)
    def _on_result(self, blocks: List[TranslatedBlock]):
        self.overlay.set_blocks(blocks)
        if blocks:
            src = "cache" if all(b.from_cache for b in blocks) else "Ollama"
            self._log(f"{len(blocks)} block(s) translated via {src}")
            if self.settings.log_text:
                for b in blocks:
                    self._log(f"    {b.original}  →  {b.translation}")

    @Slot(str)
    def _on_status(self, msg: str):
        self.lb_pipeline.setText(f"Translation: {msg}")

    @Slot(str, bool)
    def _on_error(self, msg: str, fatal: bool):
        self._log(("ERROR: " if fatal else "Warning: ") + msg)
        if fatal:
            self.stop_translation()
            self.lb_pipeline.setText("Translation: stopped (error)")

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            was_running = bool(self.pipeline and self.pipeline.running)
            if was_running:
                self.stop_translation()
            self.settings = dlg.result_settings()
            self.settings.save()
            setup_logging(self.settings.log_enabled)
            self.cb_model.blockSignals(True); self.cb_model.setEditText(self.settings.ollama_model); self.cb_model.blockSignals(False)
            self._update_region_label(); self.overlay.apply_settings(self.settings); self._apply_hotkey()
            self.refresh_ollama(); self._log("Settings saved")
            if was_running:
                self.start_translation()

    @Slot()
    def translate_now(self):
        if self.pipeline and self.pipeline.running:
            self._log(f"[{self.settings.manual_hotkey.upper()}] Translate now: capturing region {self.settings.region.as_tuple()}")
            log.info("Manual translate requested (hotkey/button)")
            self.pipeline.request_translation()
        else:
            self._log(f"[{self.settings.manual_hotkey.upper()}] pressed but translation is not running. Press Start Translation first.")

    @Slot()
    def clear_overlay(self):
        n = len(self.overlay.blocks())
        self.overlay.clear()
        if self.pipeline:
            self.pipeline.mark_cleared()
        key = (self.settings.clear_hotkey or "button").upper()
        self._log(f"[{key}] Overlay cleared ({n} block(s) removed)" if n else f"[{key}] Overlay cleared (nothing was shown)")
        log.info("Overlay cleared: %d block(s)", n)

    def _apply_hotkey(self):
        ok = self.hotkey.register(self.settings.hotkey, self.bridge.hotkey.emit)
        txt = f"Start/stop: {self.settings.hotkey}" if ok else f"Start/stop hotkey unavailable ({self.settings.hotkey})"
        ok2 = self.manual_hotkey.register(self.settings.manual_hotkey, self.bridge.manual.emit)
        txt += f"   |   Translate: [{self.settings.manual_hotkey}]" if ok2 \
            else f"   |   Translate hotkey unavailable ({self.settings.manual_hotkey})"
        if self.settings.clear_hotkey:
            ok3 = self.clear_hotkey.register(self.settings.clear_hotkey, self.bridge.clear.emit)
            txt += f"   |   Clear: [{self.settings.clear_hotkey}]" if ok3 else ""
        else:
            self.clear_hotkey.unregister()
        self.lb_hotkey.setText(txt)

    def closeEvent(self, event):
        self.stop_translation()
        self.hotkey.unregister()
        self.manual_hotkey.unregister()
        self.clear_hotkey.unregister()
        self._hide_region_frame()
        self.overlay.close()
        self.settings.save()
        super().closeEvent(event)
