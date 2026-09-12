"""PaddleOCR wrapper. Supports simplified ('ch') and traditional ('chinese_cht') Chinese.
Compatible with PaddleOCR 2.x (`.ocr`) and 3.x (`.predict`) result formats."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from .dedup import contains_chinese, normalize_text
from .logger import get_logger

log = get_logger("ocr")

SUPPORTED_LANGUAGES = {
    "ch": "Chinese Simplified (also reads most Traditional)",
    "chinese_cht": "Chinese Traditional",
}


class OCRError(Exception):
    pass


@dataclass
class TextBlock:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self):
        return (self.x + self.width / 2, self.y + self.height / 2)


def bbox_from_points(points: Sequence[Sequence[float]]):
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0))


def parse_paddle_result(result, min_confidence: float = 0.5, chinese_only: bool = True) -> List[TextBlock]:
    """Convert raw PaddleOCR output into TextBlocks, filtering low confidence / non-Chinese lines.

    Handles:
      2.x: [[ [points, (text, conf)], ... ]]  or  [ [points, (text, conf)], ... ]
      3.x: [ {"rec_texts": [...], "rec_scores": [...], "dt_polys"/"rec_polys": [...]} ]
    """
    blocks: List[TextBlock] = []
    if not result:
        return blocks

    first = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(first, dict) or hasattr(first, "get"):
        for page in result:
            texts = page.get("rec_texts", []) or []
            scores = page.get("rec_scores", []) or []
            polys = page.get("rec_polys", None) or page.get("dt_polys", []) or []
            for i, text in enumerate(texts):
                conf = float(scores[i]) if i < len(scores) else 1.0
                pts = polys[i] if i < len(polys) else [[0, 0], [1, 0], [1, 1], [0, 1]]
                _append(blocks, text, conf, pts, min_confidence, chinese_only)
        return blocks

    lines = result
    if lines and isinstance(lines[0], list) and lines[0] and isinstance(lines[0][0], list) \
            and len(lines[0][0]) == 2 and isinstance(lines[0][0][1], (tuple, list)):
        lines = lines[0]
    for line in lines or []:
        if not line or len(line) < 2:
            continue
        pts, rec = line[0], line[1]
        if isinstance(rec, (tuple, list)) and len(rec) >= 2:
            text, conf = rec[0], float(rec[1])
        else:
            text, conf = str(rec), 1.0
        _append(blocks, text, conf, pts, min_confidence, chinese_only)
    return blocks


def _append(blocks, text, conf, pts, min_confidence, chinese_only):
    text = normalize_text(str(text))
    if not text or conf < min_confidence:
        return
    if chinese_only and not contains_chinese(text):
        return
    x, y, w, h = bbox_from_points(pts)
    blocks.append(TextBlock(text=text, confidence=conf, x=x, y=y, width=w, height=h))


def merge_lines(blocks: List[TextBlock], line_gap_ratio: float = 0.6) -> List[TextBlock]:
    """Merge vertically adjacent, horizontally overlapping lines into paragraphs for better
    translation context. Keeps the union bbox."""
    if not blocks:
        return []
    ordered = sorted(blocks, key=lambda b: (b.y, b.x))
    merged: List[TextBlock] = [ordered[0]]
    for b in ordered[1:]:
        last = merged[-1]
        gap = b.y - (last.y + last.height)
        avg_h = (last.height + b.height) / 2
        overlap_x = min(last.x + last.width, b.x + b.width) - max(last.x, b.x)
        if 0 <= gap <= avg_h * line_gap_ratio and overlap_x > 0:
            nx, ny = min(last.x, b.x), min(last.y, b.y)
            nx2 = max(last.x + last.width, b.x + b.width)
            ny2 = max(last.y + last.height, b.y + b.height)
            merged[-1] = TextBlock(
                text=f"{last.text}{b.text}",
                confidence=min(last.confidence, b.confidence),
                x=nx, y=ny, width=nx2 - nx, height=ny2 - ny,
            )
        else:
            merged.append(b)
    return merged


class ChineseOCR:
    """Lazy-loading PaddleOCR engine."""

    def __init__(self, language: str = "ch", use_gpu: bool = False, min_confidence: float = 0.55):
        if language not in SUPPORTED_LANGUAGES:
            language = "ch"
        self.language = language
        self.use_gpu = use_gpu
        self.min_confidence = float(min_confidence)
        self._engine = None
        self._api = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        if self._engine is not None:
            return
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise OCRError("PaddleOCR is not installed. Run scripts\\install.bat") from e
        log.info("Loading PaddleOCR (lang=%s, gpu=%s) ...", self.language, self.use_gpu)
        try:
            self._engine = PaddleOCR(use_angle_cls=True, lang=self.language, use_gpu=self.use_gpu,
                                     show_log=False)
            self._api = "v2"
        except TypeError:
            self._engine = PaddleOCR(lang=self.language, use_textline_orientation=True,
                                     use_doc_orientation_classify=False, use_doc_unwarping=False,
                                     device="gpu" if self.use_gpu else "cpu")
            self._api = "v3"
        except Exception as e:
            raise OCRError(f"Failed to initialize PaddleOCR: {e}") from e
        log.info("PaddleOCR ready (api=%s)", self._api)

    def recognize(self, frame: np.ndarray) -> List[TextBlock]:
        self.load()
        try:
            if self._api == "v2":
                raw = self._engine.ocr(frame, cls=True)
            else:
                raw = self._engine.predict(frame)
        except MemoryError as e:
            raise OCRError("Out of memory during OCR. Reduce region size or disable GPU.") from e
        except Exception as e:
            raise OCRError(f"OCR failed: {e}") from e
        return parse_paddle_result(raw, min_confidence=self.min_confidence)
