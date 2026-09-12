import pytest
from livescreen_translator.hotkey import parse_combo


def test_parse_simple_and_modifiers():
    assert parse_combo("t") == ([], ord("T"))
    assert parse_combo("F8") == ([], 0x77)
    mods, key = parse_combo("ctrl+shift+t")
    assert set(mods) == {0x11, 0x10} and key == ord("T")


def test_parse_errors():
    for bad in ("", "ctrl", "ctrl+shift", "banana", "a+b"):
        with pytest.raises(ValueError):
            parse_combo(bad)
