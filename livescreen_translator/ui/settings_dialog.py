"""Settings dialog."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ..config import Settings
from ..ocr import SUPPORTED_LANGUAGES
from ..ollama_client import OllamaClient, OllamaError


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.settings = settings
        s = settings
        root = QVBoxLayout(self)

        g_ocr = QGroupBox("OCR (PaddleOCR, local)")
        f = QFormLayout(g_ocr)
        self.cb_lang = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self.cb_lang.addItem(f"{label} [{code}]", code)
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(s.ocr_language)))
        f.addRow("OCR language", self.cb_lang)
        self.sp_interval = QSpinBox(); self.sp_interval.setRange(150, 10000); self.sp_interval.setSingleStep(50)
        self.sp_interval.setSuffix(" ms"); self.sp_interval.setValue(s.ocr_interval_ms)
        f.addRow("OCR interval", self.sp_interval)
        self.sp_conf = QDoubleSpinBox(); self.sp_conf.setRange(0.1, 1.0); self.sp_conf.setSingleStep(0.05)
        self.sp_conf.setValue(s.ocr_min_confidence)
        f.addRow("Min. confidence", self.sp_conf)
        self.sp_change = QDoubleSpinBox(); self.sp_change.setRange(0.5, 60.0); self.sp_change.setValue(s.change_threshold)
        f.addRow("Frame change threshold", self.sp_change)
        self.sp_hold = QSpinBox(); self.sp_hold.setRange(1, 50); self.sp_hold.setValue(s.empty_hold_frames)
        f.addRow("Keep overlay for N empty readings", self.sp_hold)
        self.sp_sim = QDoubleSpinBox(); self.sp_sim.setRange(0.5, 1.0); self.sp_sim.setSingleStep(0.05); self.sp_sim.setValue(s.text_similarity)
        f.addRow("Text similarity (same text)", self.sp_sim)
        self.sp_stable = QSpinBox(); self.sp_stable.setRange(1, 20); self.sp_stable.setValue(s.stable_frames)
        f.addRow("Stable readings before translating", self.sp_stable)
        self.sp_minch = QSpinBox(); self.sp_minch.setRange(1, 10); self.sp_minch.setValue(s.min_chinese_chars)
        f.addRow("Min. Chinese chars per block", self.sp_minch)
        self.ck_gpu = QCheckBox("Use GPU for OCR (requires paddlepaddle-gpu)"); self.ck_gpu.setChecked(s.ocr_use_gpu)
        f.addRow("", self.ck_gpu)
        root.addWidget(g_ocr)

        g_ol = QGroupBox("Ollama (local translation)")
        f = QFormLayout(g_ol)
        self.ed_url = QLineEdit(s.ollama_url)
        f.addRow("Ollama URL", self.ed_url)
        row = QHBoxLayout()
        self.cb_model = QComboBox(); self.cb_model.setEditable(True); self.cb_model.setEditText(s.ollama_model)
        self.bt_refresh = QPushButton("Refresh models")
        self.bt_refresh.clicked.connect(self.refresh_models)
        row.addWidget(self.cb_model, 1); row.addWidget(self.bt_refresh)
        f.addRow("Ollama model", row)
        self.sp_timeout = QDoubleSpinBox(); self.sp_timeout.setRange(2, 600); self.sp_timeout.setSuffix(" s")
        self.sp_timeout.setValue(s.ollama_timeout_s)
        f.addRow("Timeout", self.sp_timeout)
        self.lb_models = QLabel(""); f.addRow("", self.lb_models)
        root.addWidget(g_ol)

        g_ov = QGroupBox("Overlay")
        f = QFormLayout(g_ov)
        self.sp_font = QSpinBox(); self.sp_font.setRange(8, 96); self.sp_font.setValue(s.font_size)
        f.addRow("Font size", self.sp_font)
        self.sp_opacity = QSpinBox(); self.sp_opacity.setRange(10, 100); self.sp_opacity.setSuffix(" %")
        self.sp_opacity.setValue(int(round(s.overlay_opacity * 100)))
        f.addRow("Background opacity", self.sp_opacity)
        self.ck_orig = QCheckBox("Show original Chinese text"); self.ck_orig.setChecked(s.show_original)
        f.addRow("", self.ck_orig)
        row = QHBoxLayout()
        self.sp_offx = QSpinBox(); self.sp_offx.setRange(-3000, 3000); self.sp_offx.setValue(s.overlay_offset_x)
        self.sp_offy = QSpinBox(); self.sp_offy.setRange(-3000, 3000); self.sp_offy.setValue(s.overlay_offset_y)
        row.addWidget(QLabel("X")); row.addWidget(self.sp_offx); row.addWidget(QLabel("Y")); row.addWidget(self.sp_offy)
        f.addRow("Position offset (px)", row)
        root.addWidget(g_ov)

        g_misc = QGroupBox("Mode, hotkeys, region & logs")
        f = QFormLayout(g_misc)
        f.addRow("Translation mode", QLabel("Manual — translate only when you press the hotkey"))
        self.ed_hotkey = QLineEdit(s.hotkey); self.ed_hotkey.setPlaceholderText("e.g. ctrl+shift+t")
        f.addRow("Start/stop hotkey", self.ed_hotkey)
        self.ed_manual = QLineEdit(s.manual_hotkey); self.ed_manual.setPlaceholderText("e.g. f8, t, ctrl+t")
        f.addRow("Manual translate hotkey", self.ed_manual)
        self.ed_clear = QLineEdit(s.clear_hotkey); self.ed_clear.setPlaceholderText("e.g. f9, q (empty = disabled)")
        f.addRow("Clear overlay hotkey", self.ed_clear)
        row = QHBoxLayout()
        self.sp_rx = QSpinBox(); self.sp_ry = QSpinBox(); self.sp_rw = QSpinBox(); self.sp_rh = QSpinBox()
        for sp, v in ((self.sp_rx, s.region.x), (self.sp_ry, s.region.y), (self.sp_rw, s.region.width), (self.sp_rh, s.region.height)):
            sp.setRange(-10000, 20000); sp.setValue(v); row.addWidget(sp)
        f.addRow("Region (x, y, w, h)", row)
        self.ck_log = QCheckBox("Enable log file"); self.ck_log.setChecked(s.log_enabled)
        self.ck_logtext = QCheckBox("Log recognized/translated text (disable for privacy)"); self.ck_logtext.setChecked(s.log_text)
        f.addRow("", self.ck_log); f.addRow("", self.ck_logtext)
        root.addWidget(g_misc)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def refresh_models(self):
        client = OllamaClient(self.ed_url.text().strip(), timeout=8)
        try:
            models = client.list_models()
        except OllamaError as e:
            self.lb_models.setText(f"Could not list models: {e}")
            return
        current = self.cb_model.currentText()
        self.cb_model.clear(); self.cb_model.addItems(models)
        if current:
            self.cb_model.setEditText(current)
        self.lb_models.setText(f"{len(models)} model(s) found" if models else "No models installed. Run: ollama pull qwen3:8b")

    def result_settings(self) -> Settings:
        s = self.settings
        s.ocr_language = self.cb_lang.currentData()
        s.ocr_interval_ms = self.sp_interval.value()
        s.ocr_min_confidence = self.sp_conf.value()
        s.change_threshold = self.sp_change.value()
        s.ocr_use_gpu = self.ck_gpu.isChecked()
        s.empty_hold_frames = self.sp_hold.value(); s.text_similarity = self.sp_sim.value()
        s.min_chinese_chars = self.sp_minch.value(); s.stable_frames = self.sp_stable.value()
        s.ollama_url = self.ed_url.text().strip()
        s.ollama_model = self.cb_model.currentText().strip()
        s.ollama_timeout_s = self.sp_timeout.value()
        s.font_size = self.sp_font.value()
        s.overlay_opacity = self.sp_opacity.value() / 100.0
        s.show_original = self.ck_orig.isChecked()
        s.overlay_offset_x = self.sp_offx.value(); s.overlay_offset_y = self.sp_offy.value()
        s.hotkey = self.ed_hotkey.text().strip() or "ctrl+shift+t"
        s.translate_mode = "manual"
        s.manual_hotkey = self.ed_manual.text().strip() or "f8"
        s.clear_hotkey = self.ed_clear.text().strip()
        s.region.x, s.region.y = self.sp_rx.value(), self.sp_ry.value()
        s.region.width, s.region.height = self.sp_rw.value(), self.sp_rh.value()
        s.log_enabled = self.ck_log.isChecked(); s.log_text = self.ck_logtext.isChecked()
        s.clamp()
        return s
