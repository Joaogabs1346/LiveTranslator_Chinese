"""Screen capture of a user-selected region using mss (fast, GDI/DXGI-backed on Windows)."""
from __future__ import annotations

from typing import Optional

import numpy as np

from .config import Region


class CaptureError(Exception):
    pass


class RegionCapturer:
    """Captures ONLY the configured region. Creates its mss instance lazily in the calling thread
    (mss objects are not thread-safe, so the pipeline thread owns its own capturer)."""

    def __init__(self):
        self._sct = None

    def _get(self):
        if self._sct is None:
            import mss
            self._sct = mss.mss()
        return self._sct

    def capture(self, region: Region) -> np.ndarray:
        """Return an RGB uint8 array (H, W, 3) of the region."""
        if not region.is_valid():
            raise CaptureError(f"Invalid region: {region.as_tuple()} (min 20x20)")
        sct = self._get()
        monitor = {"left": int(region.x), "top": int(region.y),
                   "width": int(region.width), "height": int(region.height)}
        try:
            shot = sct.grab(monitor)
        except Exception as e:
            raise CaptureError(f"Capture failed: {e}") from e
        frame = np.asarray(shot)
        return np.ascontiguousarray(frame[..., :3][..., ::-1])

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
