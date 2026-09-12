# LiveScreen Translator

Real-time **Chinese → English** screen translator for Windows 10/11.
Captures a region of your screen, runs OCR locally (PaddleOCR), translates with your **local Ollama** model and shows the result as a transparent, click-through overlay right on top of the original text. Built for games.

```
SCREEN CAPTURE → CHINESE OCR → TEXT DETECTION → LOCAL OLLAMA → ENGLISH → OVERLAY
```

**Privacy:** nothing leaves your PC. No account, no API key, no cloud. Screenshots are never sent anywhere; only the OCR text is sent to `http://localhost:11434`.

---

## 1. Architecture (and why)

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.10–3.12 | PaddleOCR is Python-only; fastest path to a working, maintainable app. |
| GUI / overlay | **PySide6 (Qt 6)** | Native Windows look, real per-pixel transparent windows, `WindowTransparentForInput` + Win32 `WS_EX_TRANSPARENT` for true click-through over games, high-DPI aware. |
| Capture | **mss** | Very fast region-only grabs (no full-screen capture), zero heavy deps. |
| OCR | **PaddleOCR** (`ch` / `chinese_cht`) | Best open-source accuracy for Simplified + Traditional Chinese; runs on CPU or GPU. |
| Translation | **Ollama REST API** (`/api/generate`) | Fully local; user picks any installed model (e.g. `qwen3:8b`). |
| Concurrency | One background daemon thread (`pipeline.py`) + Qt signals | UI thread never blocks; exactly one Ollama request in flight; simple to reason about. |
| Packaging | PyInstaller one-folder `.exe` | Reliable with Paddle's native DLLs. |

Pipeline optimizations: configurable OCR interval (throttle), downscaled frame-diff so unchanged frames skip OCR entirely, text-hash dedup so identical OCR output is never re-translated, LRU translation cache, sequential Ollama requests (no request storms).

```
livescreen_translator/
  config.py          settings dataclass + JSON persistence (%APPDATA%\LiveScreenTranslator)
  capture.py         region capture (mss)
  ocr.py             PaddleOCR wrapper, result parsing (v2/v3), line merging
  dedup.py           frame change detector, text normalization/hash
  cache.py           thread-safe LRU cache
  ollama_client.py   Ollama client, error types, response parsing (strips <think>)
  pipeline.py        capture→diff→OCR→dedup→cache/Ollama loop (background thread)
  overlay.py         click-through overlay window
  region_selector.py drag-to-select + movable/resizable region frame
  hotkey.py          global hotkey (keyboard package)
  logger.py          rotating local log (text logging can be disabled)
  ui/main_window.py  main window; ui/settings_dialog.py  settings
tests/               pytest suite (58 tests)
scripts/             install.bat, run.bat, dev.bat, test.bat, build_exe.bat
LiveScreenTranslator.spec  PyInstaller spec
run.py               launcher
```

---

## 2. Install & start Ollama

1. Download and install Ollama for Windows: <https://ollama.com/download/windows>
2. Ollama starts automatically (tray icon) and listens on `http://localhost:11434`.
   To start it manually: open a terminal and run `ollama serve`.
3. Verify: open <http://localhost:11434> in a browser → you should see `Ollama is running`.

### Install a model

```bat
ollama pull qwen3:8b
```

Recommended models by hardware:

| Model | VRAM/RAM | Notes |
|---|---|---|
| `qwen3:8b` | ~6 GB | Default. Excellent Chinese→English. |
| `qwen3:4b` | ~3 GB | Faster, good for weaker GPUs / CPU-only. |
| `qwen2.5:7b` | ~5 GB | Very good, no "thinking" overhead. |
| `gemma3:4b` | ~3.5 GB | Fast alternative. |

List installed models: `ollama list`.

---

## 3. Install the app (from source)

Requirements: Windows 10/11, **Python 3.10, 3.11 or 3.12** (from python.org, tick *Add Python to PATH*).

```bat
git clone <this repo>  (or unzip the folder)
cd LiveScreenTranslator
scripts\install.bat
```

`install.bat` creates a `.venv`, installs PySide6, mss, PaddleOCR/PaddlePaddle (CPU) and the other dependencies.
This downloads several hundred MB. On first OCR run PaddleOCR downloads its models (~20 MB) into `%USERPROFILE%\.paddleocr`.

Run the app:

```bat
scripts\run.bat
```

Developer loop (installs dev deps, runs tests, launches with console):

```bat
scripts\dev.bat
```

### GPU acceleration for OCR (optional)

CPU OCR is fine for a dialog-box sized region. For large regions on an NVIDIA GPU:

```bat
.venv\Scripts\activate
pip uninstall paddlepaddle
pip install paddlepaddle-gpu
```

then tick **Use GPU for OCR** in Settings.

---

## 4. Build the .exe

```bat
scripts\build_exe.bat
```

Output: **`dist\LiveScreenTranslator\LiveScreenTranslator.exe`**
Distribute the entire `dist\LiveScreenTranslator` folder (it contains Qt and Paddle DLLs). The `.exe` needs no Python installed, but the target PC still needs **Ollama** installed and running.

> The `.exe` must be built **on Windows** (PyInstaller does not cross-compile). This project was developed and tested on Linux CI, so the binary is not included in the zip — run `build_exe.bat` once on your PC.

Troubleshooting builds: set `console=True` in `LiveScreenTranslator.spec` to see errors; if PaddleOCR complains about missing files, the spec already uses `collect_all` for `paddleocr`/`paddle` — make sure you build from inside the `.venv`.

---

## 5. First use

1. Start Ollama and make sure a model is pulled (`ollama pull qwen3:8b`).
2. Launch **LiveScreen Translator**. The status line should read **Ollama: Connected**.
   If it says **Offline**, click **Test Connection** after starting Ollama.
3. Pick the model from the **Model** dropdown (click **Refresh models** to list installed ones).
4. Click **Select Region** and drag a rectangle over the area where Chinese text appears (e.g. a dialog box).
   Use **Show/adjust frame** to move/resize the region later.
5. Click **Start Translation** (or press the global hotkey, default **Ctrl+Shift+T**).
6. The first start loads PaddleOCR (5–20 s). After that, whenever the text in the region changes, the English translation appears over it. Unchanged text is never re-translated.
7. Press the hotkey or **Stop Translation** to stop. **Clear overlay** hides current boxes.

### Translating (manual, on key press)

The app translates **only when you ask**: with translation started, press the translate hotkey (default **F8**, configurable — e.g. `t`, `ctrl+t`) to capture the region, translate it and pin the result on screen until the next press. Nothing is translated automatically. The **Translate now** button does the same. Press the clear hotkey (default **F9**) to remove the current translation from the screen (works in both modes; leave the field empty in Settings to disable).

### Settings

| Setting | Description |
|---|---|
| OCR language | `ch` (Simplified; also reads most Traditional) or `chinese_cht` (Traditional). |
| OCR interval | How often the region is checked (ms). Higher = less CPU. |
| Min. confidence | Drop OCR lines below this confidence. |
| Frame change threshold | Sensitivity of the frame-diff skip (raise if video backgrounds trigger OCR constantly). |
| Ollama URL / model / timeout | Local server settings. |
| Font size, opacity, show original, offset | Overlay appearance and position. |
| Hotkeys | Start/stop, translate (F8) and clear (F9). Any `f1..f24`, letters, digits, with `ctrl`/`shift`/`alt`. Hotkeys are read via Win32 `GetAsyncKeyState`, so they work while games have focus. |
| Region | Manual x, y, w, h. |
| Logs | Enable log file; disable **text logging** for extra privacy (screenshots are never logged). |

Settings file: `%APPDATA%\LiveScreenTranslator\settings.json`
Log file: `%APPDATA%\LiveScreenTranslator\livescreen.log`

---

## 6. Error handling

| Situation | Behaviour |
|---|---|
| Ollama not running | Status shows *Offline*; start is blocked at first request with a clear message. Auto-rechecks every 15 s. |
| Model not installed | Log shows `ollama pull <model>`; translation stops (fatal). |
| Timeout / slow model | Non-fatal warning with suggestion to use a smaller model; status shows per-block latency. |
| Ollama out of memory | Fatal with suggestion (`qwen3:4b`). |
| OCR failure / OOM | Non-fatal; pipeline stops after 10 consecutive errors. |
| Invalid region | Start refused; select a region. |
| Hotkey cannot be registered | UI still works with the button. |
| Hotkeys ignored while the game has focus | The game runs as administrator: start the app with `scripts\run_admin.bat`. |

---

## 7. Tests

```bat
scripts\test.bat          (or: python -m pytest -q)
```

Covers: Ollama communication (mocked HTTP), response parsing (incl. `<think>` stripping), model listing, cache/LRU, frame & text deduplication, PaddleOCR result parsing (v2 and v3 formats), full OCR→translation pipeline with fakes, overlay geometry/flags, settings persistence.

---

## 8. Games: tips

- Run the game in **Borderless / Windowed** mode. Exclusive full-screen hides all overlays (any tool).
- Keep the region tight around the text box — faster OCR, fewer false positives.
- If the overlay covers the original text, use **Show original** or an **offset** (e.g. Y = +40) in Settings.
- Use a smaller model if translations lag behind the dialog.

## License
MIT.
