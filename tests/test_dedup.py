import numpy as np

from livescreen_translator.dedup import (FrameChangeDetector, TextDeduplicator, contains_chinese,
                                         normalize_text, text_hash)


def test_normalize_text():
    assert normalize_text("  你好 \n 世界  ") == "你好 世界"
    assert normalize_text(None) == ""


def test_contains_chinese():
    assert contains_chinese("开始游戏")
    assert contains_chinese("繁體字")
    assert not contains_chinese("Start game 123")


def test_text_hash_stable_and_order_sensitive():
    assert text_hash(["a", " b "]) == text_hash(["a", "b"])
    assert text_hash(["a", "b"]) != text_hash(["b", "a"])


def test_frame_detector_same_frame_not_changed():
    d = FrameChangeDetector(threshold=4.0)
    f = np.full((100, 200, 3), 120, dtype=np.uint8)
    assert d.has_changed(f) is True
    assert d.has_changed(f.copy()) is False
    noisy = f.astype(np.int16) + np.random.randint(-1, 2, f.shape)
    assert d.has_changed(np.clip(noisy, 0, 255).astype(np.uint8)) is False


def test_frame_detector_detects_change():
    d = FrameChangeDetector(threshold=4.0)
    f = np.zeros((100, 200, 3), dtype=np.uint8)
    d.has_changed(f)
    g = f.copy(); g[20:60, 20:180] = 255
    assert d.has_changed(g) is True
    assert d.has_changed(g) is False


def test_frame_detector_handles_grayscale_and_resize():
    d = FrameChangeDetector()
    assert d.has_changed(np.zeros((50, 50), dtype=np.uint8))
    assert d.has_changed(np.zeros((80, 60), dtype=np.uint8))


def test_text_dedup():
    t = TextDeduplicator()
    assert t.is_new(["你好", "世界"])
    assert not t.is_new(["你好 ", "世界"])
    assert t.is_new(["再见"])
    t.reset()
    assert t.is_new(["再见"])



def test_is_noise():
    from livescreen_translator.dedup import is_noise
    assert not is_noise("请点击高亮的格子，将角色移动到指定位置。")
    assert not is_noise("确定")
    assert is_noise("口")
    assert is_noise("图图图图图图图图图图")
    assert is_noise("[INFo] livescreen.pipeline: OCR found 1 stable block(s):图图")
    assert is_noise("block(s):@图图图图图图图图图图图图 [")
    assert not is_noise("HP 100 生命值")
