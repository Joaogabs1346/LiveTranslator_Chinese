"""Thread-safe LRU cache for translations keyed by normalized source text."""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from .dedup import normalize_text, similarity


class TranslationCache:
    def __init__(self, max_size: int = 500):
        self.max_size = max(1, int(max_size))
        self._data: "OrderedDict[str, str]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str) -> str:
        return normalize_text(text)

    def get(self, text: str) -> Optional[str]:
        k = self.key(text)
        with self._lock:
            if k in self._data:
                self._data.move_to_end(k)
                self.hits += 1
                return self._data[k]
            self.misses += 1
            return None

    def get_similar(self, text: str, threshold: float = 0.8) -> Optional[str]:
        """Exact hit first; otherwise the translation of the most similar key above `threshold`.
        Lets slightly different OCR readings of the same line reuse a translation."""
        exact = self.get(text)
        if exact is not None:
            return exact
        k = self.key(text)
        best, best_score = None, 0.0
        with self._lock:
            for key, val in self._data.items():
                if abs(len(key) - len(k)) > max(3, len(k) // 2):
                    continue
                sc = similarity(key, k)
                if sc > best_score:
                    best, best_score = val, sc
        return best if best_score >= threshold else None

    def put(self, text: str, translation: str) -> None:
        k = self.key(text)
        if not k or not translation:
            return
        with self._lock:
            self._data[k] = translation
            self._data.move_to_end(k)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def __contains__(self, text: str) -> bool:
        with self._lock:
            return self.key(text) in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
