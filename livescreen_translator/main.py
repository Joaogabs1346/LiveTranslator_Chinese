"""Entry point: `python -m livescreen_translator` or the packaged .exe."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from .config import Settings
    from .logger import setup_logging, get_logger
    from .ui.main_window import MainWindow
    from . import __app_name__, __version__

    settings = Settings.load()
    setup_logging(settings.log_enabled)
    log = get_logger()
    log.info("%s v%s starting", __app_name__, __version__)

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setQuitOnLastWindowClosed(True)
    win = MainWindow(settings)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
