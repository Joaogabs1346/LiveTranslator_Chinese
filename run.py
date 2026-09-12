"""Launcher used by PyInstaller and `python run.py`."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from livescreen_translator.main import main
    sys.exit(main())
