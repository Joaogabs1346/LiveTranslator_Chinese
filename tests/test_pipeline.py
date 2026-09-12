"""OCR -> translation pipeline with fake capture/OCR/Ollama components."""
import numpy as np

from livescreen_translator.cache import TranslationCache
from livescreen_translator.config import Region, Settings
from livescreen_translator.ocr import TextBlock
from livescreen_translator.ollama_client import OllamaModelNotFound, OllamaTimeout
from livescreen_translator.pipeline import PipelineCallbacks, TranslationPipeline


class FakeCapturer:
    def __init__(self, frames):
        self.frames = list(frames); self.i = 0
    def capture(self, region):
        f = self.frames[min(self.i, len(self.frames) - 1)]; self.i += 1; return f
    def close(self): pass


class FakeOCR:
    def __init__(self, outputs):
        self.outputs = list(outputs); self.calls = 0
    def load(self): pass
    def recognize(self, frame):
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]; self.calls += 1; return out


class FakeClient:
    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}; self.error = error; self.calls = []; self.model = "fake"
    def translate(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.mapping.get(text, f"EN({text})")


def frame(v):
    return np.full((60, 120, 3), v, dtype=np.uint8)


def build(frames, ocr_outputs, client=None):
    s = Settings(); s.region = Region(0, 0, 120, 60); s.change_threshold = 4.0; s.stable_frames = 1
    results, errors, status = [], [], []
    cbs = PipelineCallbacks(on_result=results.append, on_error=lambda m, f: errors.append((m, f)),
                            on_status=status.append)
    client = client or FakeClient()
    p = TranslationPipeline(s, cbs, ocr=FakeOCR(ocr_outputs), client=client,
                            capturer=FakeCapturer(frames), cache=TranslationCache(50))
    return p, results, errors, client


def test_full_pipeline_translates_and_positions():
    blocks = [TextBlock("开始游戏", 0.9, 5, 6, 80, 20)]
    p, results, errors, client = build([frame(0)], [blocks], FakeClient({"开始游戏": "Start Game"}))
    out = p.process_once()
    assert errors == []
    assert len(out) == 1 and out[0].translation == "Start Game"
    assert (out[0].x, out[0].y, out[0].width, out[0].height) == (5, 6, 80, 20)
    assert results[0][0].original == "开始游戏"
    assert client.calls == ["开始游戏"]


def test_unchanged_frame_skips_ocr_and_ollama():
    blocks = [TextBlock("你好", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0), frame(0), frame(0)], [blocks])
    p.process_once(); p.process_once(); p.process_once()
    assert p.ocr.calls == 1
    assert client.calls == ["你好"]
    assert len(results) == 1


def test_same_text_new_frame_not_retranslated():
    blocks = [TextBlock("你好", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0), frame(200)], [blocks, blocks])
    p.process_once(); p.process_once()
    assert p.ocr.calls == 2
    assert client.calls == ["你好"]


def test_cache_used_when_text_reappears():
    a = [TextBlock("你好", 0.9, 0, 0, 10, 10)]
    b = [TextBlock("再见", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0), frame(100), frame(200)], [a, b, a])
    p.process_once(); p.process_once(); p.process_once()
    assert client.calls == ["你好", "再见"]
    assert results[-1][0].from_cache is True
    assert results[-1][0].translation == "EN(你好)"


def test_empty_ocr_with_nothing_shown_is_noop():
    p, results, errors, client = build([frame(0)], [[]])
    assert p.process_once() is None
    assert results == [] and client.calls == []


def test_model_not_found_is_fatal():
    blocks = [TextBlock("你好", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0)], [blocks], FakeClient(error=OllamaModelNotFound("nope")))
    assert p.process_once() is None
    assert errors and errors[0][1] is True
    assert p._stop.is_set()


def test_timeout_is_not_fatal():
    blocks = [TextBlock("你好", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0)], [blocks], FakeClient(error=OllamaTimeout("slow")))
    p.process_once()
    assert errors and errors[0][1] is False
    assert not p._stop.is_set()


def test_invalid_region_reports_error_on_start():
    p, results, errors, client = build([frame(0)], [[]])
    p.settings.region = Region(0, 0, 5, 5)
    p.start()
    assert errors and "region" in errors[0][0].lower() and not p.running


def test_empty_readings_hold_overlay_then_clear():
    blocks = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    frames = [frame(0), frame(50), frame(100), frame(150), frame(200), frame(250)]
    p, results, errors, client = build(frames, [blocks, [], [], [], [], []])
    p.settings.empty_hold_frames = 3
    p.process_once()
    p.process_once(); p.process_once()
    assert results == [results[0]] and len(results) == 1
    p.process_once()
    assert results[-1] == []


def test_similar_ocr_jitter_not_retranslated():
    a = [TextBlock("第二个问题你更倾向秩序还是自由", 0.9, 0, 0, 10, 10)]
    b = [TextBlock("第二个问题你更倾向秩序还是自由?", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0), frame(100)], [a, b])
    p.process_once(); p.process_once()
    assert client.calls == ["第二个问题你更倾向秩序还是自由"]
    assert len(results) == 1


def test_noise_blocks_filtered():
    noise = [TextBlock("口", 0.9, 0, 0, 10, 10), TextBlock("会C", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0)], [noise])
    p.process_once()
    assert client.calls == [] and results == []



def build_stable(frames, ocr_outputs, stable=2):
    p, results, errors, client = build(frames, ocr_outputs)
    p.settings.stable_frames = stable
    return p, results, errors, client


def test_typewriter_text_translated_only_when_complete():
    partials = [[TextBlock(t, 0.9, 0, 0, 10, 10)] for t in ("你", "你好", "你好世", "你好世界", "你好世界")]
    frames = [frame(v) for v in (0, 40, 80, 120, 160)]
    p, results, errors, client = build_stable(frames, partials, stable=2)
    for _ in range(5):
        p.process_once()
    assert client.calls == ["你好世界"]
    assert len(results) == 1


def test_unchanged_frame_confirms_pending_text():
    blocks = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build_stable([frame(0), frame(0)], [blocks], stable=2)
    assert p.process_once() is None
    assert p.process_once() is not None
    assert client.calls == ["你好世界"]


def test_previous_translation_kept_while_new_text_settles():
    a = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    b = [TextBlock("再见朋友", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build_stable([frame(0), frame(0), frame(100), frame(100)], [a, b, b], stable=2)
    p.process_once(); p.process_once()
    p.process_once()
    assert len(results) == 1 and results[0][0].original == "你好世界"
    p.process_once()
    assert results[-1][0].original == "再见朋友"



def test_translate_now_ignores_stabilization_and_keeps_result():
    blocks = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build_stable([frame(0)], [blocks], stable=3)
    out = p.translate_now()
    assert out and out[0].translation == "EN(你好世界)"
    assert client.calls == ["你好世界"] and len(results) == 1


def test_translate_now_no_text_reports_status():
    p, results, errors, client = build([frame(0)], [[]])
    statuses = []
    p.cb.on_status = statuses.append
    assert p.translate_now() is None
    assert any("No Chinese text" in m for m in statuses) and results == []


def test_manual_mode_loop_waits_for_trigger():
    import time
    blocks = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0)], [blocks])
    p.settings.translate_mode = "manual"
    p.start()
    time.sleep(0.4)
    assert client.calls == []
    p.request_translation()
    for _ in range(40):
        if client.calls:
            break
        time.sleep(0.05)
    p.stop()
    assert client.calls == ["你好世界"]



def test_unchanged_translation_is_skipped():
    blocks = [TextBlock("你好世界", 0.9, 0, 0, 10, 10)]
    p, results, errors, client = build([frame(0)], [blocks], FakeClient({"你好世界": "你好世界"}))
    assert p.process_once() == []
    assert results == []
