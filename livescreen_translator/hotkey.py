"""Global hotkeys that work while games have focus.

Windows backend: polls the keyboard state with GetAsyncKeyState (no hooks, no window messages).
Games cannot block it, it works with DirectInput/raw-input titles and does not require admin unless
the game itself runs elevated (then run scripts\\run_admin.bat). Non-Windows fallback: `keyboard`.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from .logger import get_logger

log = get_logger("hotkey")

_VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "page up": 0x21, "pagedown": 0x22, "page down": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pause": 0x13, "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91, "printscreen": 0x2C,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _i in range(1, 25):
    _VK[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK[_c] = ord(_c.upper())
for _d in "0123456789":
    _VK[_d] = ord(_d)
    _VK[f"num{_d}"] = 0x60 + int(_d)
_MODIFIERS = {0x11, 0x10, 0x12, 0x5B}


def parse_combo(combo: str) -> Tuple[List[int], int]:
    """'ctrl+shift+t' -> ([0x11, 0x10], ord('T')). Raises ValueError on unknown keys."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods, key = [], None
    for p in parts:
        if p not in _VK:
            raise ValueError(f"unknown key '{p}'")
        vk = _VK[p]
        if vk in _MODIFIERS:
            mods.append(vk)
        else:
            if key is not None:
                raise ValueError("only one non-modifier key allowed")
            key = vk
    if key is None:
        raise ValueError("hotkey needs a non-modifier key (e.g. f8, t)")
    return mods, key


class _Win32Poller:
    """Single background thread polling all registered combos (~120 Hz). Edge-triggered."""

    _instance: Optional["_Win32Poller"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "_Win32Poller":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        import ctypes
        self._user32 = ctypes.windll.user32
        self._combos: Dict[int, Tuple[List[int], int, Callable[[], None], str]] = {}
        self._next_id = 1
        self._pressed: Dict[int, bool] = {}
        self._clock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="HotkeyPoller", daemon=True)
        self._thread.start()

    def _down(self, vk: int) -> bool:
        return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)

    def add(self, mods: List[int], key: int, cb: Callable[[], None], name: str) -> int:
        with self._clock:
            hid = self._next_id; self._next_id += 1
            self._combos[hid] = (mods, key, cb, name)
            self._pressed[hid] = False
            return hid

    def remove(self, hid: int) -> None:
        with self._clock:
            self._combos.pop(hid, None); self._pressed.pop(hid, None)

    def _run(self) -> None:
        while True:
            time.sleep(0.008)
            with self._clock:
                items = list(self._combos.items())
            for hid, (mods, key, cb, name) in items:
                active = self._down(key) and all(self._down(m) for m in mods)
                if active:
                    others = [m for m in (0x11, 0x10, 0x12) if m not in mods]
                    if any(self._down(m) for m in others):
                        active = False
                was = self._pressed.get(hid, False)
                if active and not was:
                    self._pressed[hid] = True
                    log.info("Hotkey pressed: %s", name)
                    try:
                        cb()
                    except Exception as e:
                        log.warning("Hotkey callback failed: %s", e)
                elif not active and was:
                    self._pressed[hid] = False


class GlobalHotkey:
    def __init__(self):
        self._handle = None
        self._backend: Optional[str] = None
        self._combo: Optional[str] = None

    def register(self, combo: str, callback: Callable[[], None]) -> bool:
        self.unregister()
        combo = (combo or "").strip()
        if not combo:
            return False
        if sys.platform == "win32":
            try:
                mods, key = parse_combo(combo)
            except ValueError as e:
                log.warning("Invalid hotkey %r: %s", combo, e)
                return False
            try:
                self._handle = _Win32Poller.get().add(mods, key, callback, combo)
                self._backend = "win32"
                self._combo = combo
                log.info("Registered global hotkey %s (win32 polling)", combo)
                return True
            except Exception as e:
                log.warning("Win32 hotkey backend failed (%s); falling back to `keyboard`", e)
        try:
            import keyboard
            self._handle = keyboard.add_hotkey(combo, callback, suppress=False, trigger_on_release=True)
            self._backend = "keyboard"
            self._combo = combo
            log.info("Registered global hotkey %s (keyboard hook)", combo)
            return True
        except ImportError:
            log.warning("`keyboard` package not installed; global hotkey disabled")
        except Exception as e:
            log.warning("Failed to register hotkey %r: %s", combo, e)
        self._handle = None
        return False

    def unregister(self) -> None:
        if self._handle is None:
            return
        try:
            if self._backend == "win32":
                _Win32Poller.get().remove(self._handle)
            else:
                import keyboard
                keyboard.remove_hotkey(self._handle)
        except Exception:
            pass
        self._handle = None; self._backend = None; self._combo = None
