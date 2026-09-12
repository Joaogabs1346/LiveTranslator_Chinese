"""Background pipeline: capture -> change detection -> OCR -> dedup -> cache/Ollama -> callbacks.

Runs in one daemon thread so the UI never blocks. Ollama requests are sequential (one in flight),
throttled by the OCR interval and short-circuited by frame diff, text dedup and the LRU cache."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .cache import TranslationCache
from .capture import CaptureError, RegionCapturer
from .config import Settings
from .dedup import FrameChangeDetector, TextDeduplicator, is_noise, normalize_text, texts_similar
from .logger import TextLogFilter, get_logger
from .ocr import ChineseOCR, OCRError, TextBlock, merge_lines
from .ollama_client import (OllamaClient, OllamaError, OllamaModelNotFound, OllamaOffline,
                            OllamaOutOfMemory, OllamaTimeout)

log = get_logger("pipeline")


@dataclass
class TranslatedBlock:
    original: str
    translation: str
    x: int
    y: int
    width: int
    height: int
    from_cache: bool = False


@dataclass
class PipelineCallbacks:
    on_result: Callable[[List[TranslatedBlock]], None] = lambda blocks: None
    on_status: Callable[[str], None] = lambda msg: None
    on_error: Callable[[str, bool], None] = lambda msg, fatal: None


def _is_extension(old: List[str], new: List[str]) -> bool:
    """True when the new reading looks like the old one with more characters appended
    (typewriter effect) -> the text is still being written, not stable yet."""
    if len(old) != len(new):
        return False
    from .dedup import normalize_text
    grew = False
    for o, n in zip(old, new):
        o, n = normalize_text(o), normalize_text(n)
        if n == o:
            continue
        if n.startswith(o) and len(n) > len(o):
            grew = True
        else:
            return False
    return grew


class TranslationPipeline:
    def __init__(self, settings: Settings, callbacks: Optional[PipelineCallbacks] = None,
                 ocr: Optional[ChineseOCR] = None, client: Optional[OllamaClient] = None,
                 capturer: Optional[RegionCapturer] = None, cache: Optional[TranslationCache] = None):
        self.settings = settings
        self.cb = callbacks or PipelineCallbacks()
        self.ocr = ocr or ChineseOCR(settings.ocr_language, settings.ocr_use_gpu, settings.ocr_min_confidence)
        self.client = client or OllamaClient(settings.ollama_url, settings.ollama_model, settings.ollama_timeout_s)
        self.capturer = capturer or RegionCapturer()
        self.cache = cache or TranslationCache(settings.cache_size)
        self.frame_detector = FrameChangeDetector(settings.change_threshold)
        self.text_dedup = TextDeduplicator()
        self.textlog = TextLogFilter(settings.log_text)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._consecutive_errors = 0
        self._last_texts: List[str] = []
        self._empty_count = 0
        self._pending_texts: List[str] = []
        self._pending_blocks: List[TextBlock] = []
        self._pending_count = 0
        self._trigger = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        if not self.settings.region.is_valid():
            self.cb.on_error("Invalid capture region. Select a region first.", True)
            return
        self._stop.clear()
        self.frame_detector.reset()
        self.text_dedup.reset()
        self._consecutive_errors = 0
        self._last_texts, self._empty_count = [], 0
        self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0
        self._thread = threading.Thread(target=self._run, name="TranslationPipeline", daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and threading.current_thread() is not t:
            t.join(join_timeout)
        self._thread = None

    def request_translation(self) -> None:
        """Manual mode: translate the region on the next loop iteration (called from the hotkey)."""
        self._trigger.set()

    def mark_cleared(self) -> None:
        """User hid the overlay: remember the current text as 'seen' so automatic mode does not
        bring the same translation back; a different text will still be translated."""
        self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0

    def reset_dedup(self) -> None:
        """Force the next frame to be processed (e.g., after region/settings change)."""
        self.frame_detector.reset()
        self.text_dedup.reset()
        self._last_texts, self._empty_count = [], 0
        self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0

    def _run(self) -> None:
        self.cb.on_status("Loading OCR engine...")
        try:
            self.ocr.load()
        except OCRError as e:
            self.cb.on_error(str(e), True)
            return
        manual = self.settings.translate_mode == "manual"
        self.cb.on_status(f"Manual mode: press [{self.settings.manual_hotkey}] to translate" if manual
                          else "Translating (idle)")
        self.capturer = self.capturer.__class__() if isinstance(self.capturer, RegionCapturer) else self.capturer
        try:
            while not self._stop.is_set():
                if manual:
                    if not self._trigger.wait(0.25):
                        continue
                    self._trigger.clear()
                    self.translate_now()
                    continue
                started = time.monotonic()
                self.process_once()
                elapsed = time.monotonic() - started
                wait = max(0.0, self.settings.ocr_interval_ms / 1000.0 - elapsed)
                if self._stop.wait(wait):
                    break
        finally:
            try:
                self.capturer.close()
            except Exception:
                pass
            self.cb.on_status("Stopped")

    def process_once(self) -> Optional[List[TranslatedBlock]]:
        """One iteration. Returns translated blocks if new output was produced, else None."""
        try:
            frame = self.capturer.capture(self.settings.region)
        except CaptureError as e:
            self._error(str(e), fatal=False)
            return None
        if not self.frame_detector.has_changed(frame):
            if self._pending_texts:
                self._pending_count += 1
                if self._pending_count >= self.settings.stable_frames:
                    return self._commit_pending()
            return None
        try:
            blocks = self.ocr.recognize(frame)
        except OCRError as e:
            self._error(str(e), fatal=False)
            return None
        blocks = [b for b in blocks if not is_noise(b.text, self.settings.min_chinese_chars)]
        blocks = merge_lines(blocks)
        texts = [b.text for b in blocks]
        if not blocks:
            self._empty_count += 1
            if self._last_texts and self._empty_count >= self.settings.empty_hold_frames:
                self._last_texts = []
                self.text_dedup.reset()
                self.cb.on_result([])
                return []
            return None
        self._empty_count = 0
        if self._last_texts and texts_similar(self._last_texts, texts, self.settings.text_similarity):
            self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0
            return None
        if self._pending_texts and not _is_extension(self._pending_texts, texts) \
                and texts_similar(self._pending_texts, texts, self.settings.text_similarity):
            self._pending_count += 1
        else:
            self._pending_count = 1
        self._pending_texts, self._pending_blocks = texts, blocks
        if self._pending_count < self.settings.stable_frames:
            return None
        return self._commit_pending()

    def translate_now(self) -> Optional[List[TranslatedBlock]]:
        """Capture + OCR + translate the region immediately, ignoring change detection and
        stabilization. Result stays on the overlay until the next call (manual mode)."""
        self.cb.on_status("Translating...")
        t_start = time.monotonic()
        log.info("Manual translate: capturing region %s", self.settings.region.as_tuple())
        try:
            frame = self.capturer.capture(self.settings.region)
        except CaptureError as e:
            self._error(str(e), fatal=False)
            return None
        self.frame_detector.has_changed(frame)
        try:
            blocks = self.ocr.recognize(frame)
        except OCRError as e:
            self._error(str(e), fatal=False)
            return None
        blocks = [b for b in blocks if not is_noise(b.text, self.settings.min_chinese_chars)]
        blocks = merge_lines(blocks)
        self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0
        if not blocks:
            log.info("Manual translate: no Chinese text found (%.2fs)", time.monotonic() - t_start)
            self.cb.on_status("No Chinese text found in the region")
            self.cb.on_error("No Chinese text found in the region", False)
            return None
        texts = [b.text for b in blocks]
        log.info("Manual OCR found %d block(s) in %.2fs: %s", len(blocks), time.monotonic() - t_start,
                 self.textlog.fmt(" | ".join(texts)))
        results = self.translate_blocks(blocks)
        if results:
            self._last_texts = texts
            self.cb.on_result(results)
            self.cb.on_status(f"Done in {time.monotonic() - t_start:.1f}s")
        return results

    def _commit_pending(self) -> Optional[List[TranslatedBlock]]:
        blocks, texts = self._pending_blocks, self._pending_texts
        self._pending_texts, self._pending_blocks, self._pending_count = [], [], 0
        if not blocks:
            return None
        log.info("OCR found %d stable block(s): %s", len(blocks), self.textlog.fmt(" | ".join(texts)))
        results = self.translate_blocks(blocks)
        if results:
            self._last_texts = texts
            self.cb.on_result(results)
        return results

    def translate_blocks(self, blocks: List[TextBlock]) -> Optional[List[TranslatedBlock]]:
        out: List[TranslatedBlock] = []
        with self._busy:
            for b in blocks:
                if self._stop.is_set():
                    return None
                cached = self.cache.get_similar(b.text, self.settings.text_similarity)
                if cached is not None:
                    out.append(TranslatedBlock(b.text, cached, b.x, b.y, b.width, b.height, from_cache=True))
                    continue
                t0 = time.monotonic()
                try:
                    translation = self.client.translate(b.text)
                except OllamaModelNotFound as e:
                    self._error(str(e), fatal=True)
                    return None
                except OllamaOffline as e:
                    self._error(f"Ollama offline: {e}", fatal=True)
                    return None
                except OllamaTimeout as e:
                    self._error(f"{e}. The model may be too slow for this hardware; try a smaller model.", fatal=False)
                    return out or None
                except OllamaOutOfMemory as e:
                    self._error(f"Ollama out of memory: {e}. Use a smaller model (e.g. qwen3:4b).", fatal=True)
                    return None
                except OllamaError as e:
                    self._error(str(e), fatal=False)
                    return out or None
                dt = time.monotonic() - t0
                if dt > self.settings.slow_model_warning_s:
                    self.cb.on_status(f"Warning: model is slow ({dt:.1f}s per block)")
                else:
                    self.cb.on_status(f"Translated in {dt:.1f}s")
                if translation and normalize_text(translation) != normalize_text(b.text):
                    self.cache.put(b.text, translation)
                    out.append(TranslatedBlock(b.text, translation, b.x, b.y, b.width, b.height))
                else:
                    log.info("Skipping block: model returned empty/unchanged text")
                log.info("Translated %s -> %s (%.1fs)", self.textlog.fmt(b.text), self.textlog.fmt(translation), dt)
        self._consecutive_errors = 0
        return out

    def _error(self, msg: str, fatal: bool) -> None:
        self._consecutive_errors += 1
        log.error(msg)
        self.cb.on_error(msg, fatal)
        if fatal or self._consecutive_errors >= 10:
            self._stop.set()
