"""Deduplication helpers: frame-change detection and text normalization/hashing."""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Iterable, List, Optional

import numpy as np

_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip so tiny OCR jitter maps to the same key."""
    return _WS_RE.sub(" ", (text or "")).strip()


def contains_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def chinese_char_count(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def similarity(a: str, b: str) -> float:
    """0..1 similarity ratio between two texts (whitespace-normalized)."""
    a, b = normalize_text(a), normalize_text(b)
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def texts_similar(old: List[str], new: List[str], threshold: float) -> bool:
    """True when both lists have the same length and every pair is at least `threshold` similar."""
    if len(old) != len(new):
        return False
    return all(similarity(o, n) >= threshold for o, n in zip(sorted(old), sorted(new)))


_LATIN_RE = re.compile(r"[A-Za-z]")


def is_noise(text: str, min_chinese: int = 2) -> bool:
    """Heuristics for OCR garbage: too few CJK chars, mostly Latin/symbol soup (e.g. a console
    window or log text), or one glyph repeated (□□□ rendered as 图图图/目目目)."""
    t = normalize_text(text)
    cjk = _CJK_RE.findall(t)
    if len(cjk) < min_chinese:
        return True
    visible = [c for c in t if not c.isspace()]
    if len(cjk) / max(1, len(visible)) < 0.35:
        return True
    if len(_LATIN_RE.findall(t)) >= 6:
        return True
    if len(cjk) >= 4:
        top = max(cjk.count(c) for c in set(cjk))
        if top / len(cjk) > 0.6:
            return True
    return False


def text_hash(texts: Iterable[str]) -> str:
    joined = "\n".join(normalize_text(t) for t in texts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


class FrameChangeDetector:
    """Detects whether a new frame differs from the last one using a downscaled grayscale diff."""

    def __init__(self, threshold: float = 4.0, size: int = 48):
        self.threshold = float(threshold)
        self.size = int(size)
        self._last: Optional[np.ndarray] = None
        self._last_shape = None

    def _fingerprint(self, frame: np.ndarray) -> np.ndarray:
        arr = np.asarray(frame)
        if arr.ndim == 3:
            arr = arr[..., :3].mean(axis=2)
        arr = arr.astype(np.float32)
        h, w = arr.shape
        if h == 0 or w == 0:
            return np.zeros((1, 1), dtype=np.float32)
        ys = np.linspace(0, h - 1, min(self.size, h)).astype(int)
        xs = np.linspace(0, w - 1, min(self.size, w)).astype(int)
        return arr[np.ix_(ys, xs)]

    def has_changed(self, frame: np.ndarray) -> bool:
        fp = self._fingerprint(frame)
        shape = tuple(np.asarray(frame).shape[:2])
        if self._last is None or self._last.shape != fp.shape or shape != self._last_shape:
            self._last, self._last_shape = fp, shape
            return True
        diff = float(np.abs(fp - self._last).mean())
        if diff >= self.threshold:
            self._last = fp
            return True
        return False

    def reset(self) -> None:
        self._last = None
        self._last_shape = None


class TextDeduplicator:
    """Remembers the last set of texts so identical OCR output is not re-translated."""

    def __init__(self):
        self._last_hash: Optional[str] = None

    def is_new(self, texts: List[str]) -> bool:
        h = text_hash(texts)
        if h == self._last_hash:
            return False
        self._last_hash = h
        return True

    def reset(self) -> None:
        self._last_hash = None
