import pytest
from PySide6.QtWidgets import QApplication

from livescreen_translator.config import Region, Settings
from livescreen_translator.overlay import OverlayWindow
from livescreen_translator.pipeline import TranslatedBlock


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_overlay(app, **kw):
    s = Settings(); s.region = Region(100, 200, 400, 300)
    for k, v in kw.items():
        setattr(s, k, v)
    ov = OverlayWindow(s)
    ov.setGeometry(0, 0, 1920, 1080)
    return ov


def test_set_and_clear_blocks(app):
    ov = make_overlay(app)
    ov.set_blocks([TranslatedBlock("你好", "Hello", 10, 20, 80, 30)])
    assert len(ov.blocks()) == 1
    ov.clear()
    assert ov.blocks() == []


def test_block_positioned_near_original(app):
    ov = make_overlay(app, overlay_offset_x=5, overlay_offset_y=-5)
    b = TranslatedBlock("你好", "Hello", 10, 20, 80, 30)
    r = ov.block_screen_rect(b)
    assert (r.x(), r.y()) == (100 + 10 + 5, 200 + 20 - 5)
    rect, text, original = ov.compute_layout(b)
    assert text == "Hello" and original == ""
    assert abs(rect.x() - r.x()) <= 0 and abs(rect.y() - r.y()) <= 0


def test_show_original_and_font_size_affect_layout(app):
    b = TranslatedBlock("你好世界", "Hello world", 10, 20, 80, 30)
    small = make_overlay(app, font_size=12).compute_layout(b)[0]
    big = make_overlay(app, font_size=36).compute_layout(b)[0]
    assert big.height() > small.height()
    with_orig = make_overlay(app, font_size=12, show_original=True)
    rect, text, original = with_orig.compute_layout(b)
    assert original == "你好世界" and rect.height() > small.height()


def test_layout_kept_on_screen(app):
    ov = make_overlay(app)
    b = TranslatedBlock("x", "Hello", 5000, 5000, 80, 30)
    rect, _, _ = ov.compute_layout(b)
    assert rect.right() <= ov.width() and rect.bottom() <= ov.height()


def test_click_through_flags(app):
    from PySide6.QtCore import Qt
    ov = make_overlay(app)
    assert ov.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert ov.testAttribute(Qt.WA_TranslucentBackground)
    assert ov.windowFlags() & Qt.WindowStaysOnTopHint
    assert ov.windowFlags() & Qt.WindowTransparentForInput


def test_settings_roundtrip(tmp_path):
    s = Settings(); s.font_size = 33; s.region = Region(1, 2, 300, 400); s.overlay_opacity = 5.0
    s.clamp(); s.save(tmp_path / "s.json")
    t = Settings.load(tmp_path / "s.json")
    assert t.font_size == 33 and t.region.as_tuple() == (1, 2, 300, 400) and t.overlay_opacity == 1.0
