"""Application settings: dataclass + JSON persistence in %APPDATA%\\LiveScreenTranslator."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"

TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. Translate the Chinese text into natural English. "
    "Return ONLY the English translation. Do not explain, summarize, or add anything."
)


def app_data_dir() -> Path:
    """Return a writable per-user data directory (Windows: %APPDATA%)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "LiveScreenTranslator"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Region:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def is_valid(self, min_size: int = 20) -> bool:
        return self.width >= min_size and self.height >= min_size

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass
class Settings:
    ocr_language: str = "ch"
    ocr_interval_ms: int = 700
    ocr_min_confidence: float = 0.55
    ocr_use_gpu: bool = False
    change_threshold: float = 4.0
    min_chinese_chars: int = 2
    empty_hold_frames: int = 4
    text_similarity: float = 0.8
    stable_frames: int = 2
    ollama_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = DEFAULT_MODEL
    ollama_timeout_s: float = 120.0
    slow_model_warning_s: float = 8.0
    font_size: int = 18
    overlay_opacity: float = 0.85
    show_original: bool = False
    overlay_offset_x: int = 0
    overlay_offset_y: int = 0
    overlay_text_color: str = "#FFFFFF"
    overlay_bg_color: str = "#000000"
    translate_mode: str = "manual"
    hotkey: str = "ctrl+shift+t"
    manual_hotkey: str = "f8"
    clear_hotkey: str = "f9"
    region: Region = field(default_factory=Region)
    log_enabled: bool = True
    log_text: bool = True
    cache_size: int = 500

    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = path or cls.path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        region_data = clean.pop("region", None)
        s = cls(**clean)
        if isinstance(region_data, dict):
            s.region = Region(**{k: int(v) for k, v in region_data.items() if k in {"x", "y", "width", "height"}})
        s.translate_mode = "manual"
        s.clamp()
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Optional[Path] = None) -> None:
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def clamp(self) -> None:
        self.ocr_interval_ms = max(150, min(int(self.ocr_interval_ms), 10000))
        self.font_size = max(8, min(int(self.font_size), 96))
        self.overlay_opacity = max(0.1, min(float(self.overlay_opacity), 1.0))
        self.ollama_timeout_s = max(2.0, float(self.ollama_timeout_s))
        self.cache_size = max(10, int(self.cache_size))
        self.min_chinese_chars = max(1, int(self.min_chinese_chars))
        self.empty_hold_frames = max(1, int(self.empty_hold_frames))
        self.text_similarity = max(0.5, min(float(self.text_similarity), 1.0))
        self.stable_frames = max(1, int(self.stable_frames))
        if self.translate_mode not in ("auto", "manual"):
            self.translate_mode = "manual"
        self.ollama_url = self.ollama_url.rstrip("/") or DEFAULT_OLLAMA_URL
