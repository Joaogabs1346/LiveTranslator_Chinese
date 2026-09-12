import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

datas, binaries, hiddenimports = [], [], []
for pkg in ("paddleocr", "paddle", "shapely", "pyclipper", "skimage", "scipy", "lmdb", "imgaug",
            "rapidfuzz", "cv2"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass
hiddenimports += collect_submodules("livescreen_translator")
hiddenimports += ["keyboard", "mss", "mss.windows", "PySide6.QtSvg"]

a = Analysis(
    ["run.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "notebook", "PyQt5", "PyQt6", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LiveScreenTranslator",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico" if os.path.exists("assets/icon.ico") else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LiveScreenTranslator")
