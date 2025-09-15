from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import apply_premium_theme

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def run():
    app = QApplication(sys.argv)
    apply_premium_theme(app)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
