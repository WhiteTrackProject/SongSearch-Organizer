from __future__ import annotations
import sys
import logging
from PySide6.QtWidgets import QApplication
from .main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

def run():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
