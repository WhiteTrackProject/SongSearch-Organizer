from __future__ import annotations

"""Application look & feel helpers.

This module centralises the custom Qt style sheet used by the desktop user
interface and exposes a couple of helpers so the rest of the code base does not
need to deal with palette tweaks directly.  The implementation intentionally
keeps the logic simple: applying the style means configuring a dark palette and
attaching a single Qt style sheet, while widgets that should honour the themed
background can opt-in via :func:`ensure_styled_background`.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# --------------------------------------------------------------------------------------
# Qt style sheet
# --------------------------------------------------------------------------------------
THEME_CSS = """
/* Base colours */
QWidget {
    background-color: #0f111a;
    color: #f1f4ff;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 14px;
}

QMainWindow, QWidget#MainContainer {
    background-color: #0f111a;
}

#HeaderBar {
    background-color: #14192b;
    border-bottom: 1px solid #1f2944;
    padding: 12px 18px;
}

#SearchContainer {
    background-color: rgba(10, 13, 22, 160);
    border: 1px solid #1f2944;
    border-radius: 16px;
    padding: 14px 18px;
}

QLineEdit#SearchField {
    background-color: rgba(4, 6, 12, 220);
    border: 1px solid #1f2944;
    border-radius: 18px;
    padding: 8px 14px;
    selection-background-color: #3a6ff1;
    selection-color: #ffffff;
}

QLineEdit#SearchField:focus {
    border: 1px solid #3a6ff1;
}

QLabel#SearchHint {
    color: #7b88a8;
    font-size: 12px;
}

QFrame#TableCard,
QFrame#DetailsCard {
    background-color: #14192b;
    border: 1px solid #1f2944;
    border-radius: 18px;
}

QTableView {
    background-color: transparent;
    alternate-background-color: rgba(29, 38, 66, 120);
    gridline-color: #1f2944;
    selection-background-color: #2b3f87;
    selection-color: #f5f7ff;
}

QTableView::item:hover {
    background-color: rgba(43, 63, 135, 80);
}

QHeaderView::section {
    background-color: transparent;
    color: #9ca6c3;
    border: none;
    border-right: 1px solid #1f2944;
    padding: 6px 10px;
}

QHeaderView::section:horizontal:last {
    border-right: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 8px 0;
}

QScrollBar::handle:vertical {
    background: rgba(70, 82, 118, 180);
    min-height: 48px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(90, 110, 170, 200);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::sub-page:vertical,
QScrollBar::add-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0 8px;
}

QScrollBar::handle:horizontal {
    background: rgba(70, 82, 118, 180);
    min-width: 48px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(90, 110, 170, 200);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar::sub-page:horizontal,
QScrollBar::add-page:horizontal {
    background: none;
}

QPushButton {
    background-color: #202a46;
    border-radius: 18px;
    padding: 8px 18px;
    border: 1px solid transparent;
    color: #e9ecf8;
}

QPushButton:hover {
    background-color: #263152;
}

QPushButton:pressed {
    background-color: #1c2640;
}

QPushButton:disabled {
    background-color: rgba(32, 42, 70, 80);
    color: rgba(233, 236, 248, 70);
    border-color: transparent;
}

QPushButton[accentButton="true"] {
    background-color: #3a6ff1;
    color: #ffffff;
}

QPushButton[accentButton="true"]:hover {
    background-color: #4b7ffc;
}

QPushButton[accentButton="true"]:pressed {
    background-color: #335fd1;
}

QLabel[formLabel="true"] {
    color: #7b88a8;
    font-weight: 600;
}

QLabel[valueLabel="true"] {
    color: #e9ecf8;
}

QStatusBar#MainStatusBar {
    background-color: #14192b;
    border-top: 1px solid #1f2944;
    color: #9ca6c3;
}

QMessageBox {
    background-color: #12162a;
}

QToolTip {
    background-color: #3a6ff1;
    color: #ffffff;
    padding: 6px 8px;
    border-radius: 4px;
}
""".strip()


def _build_dark_palette() -> QPalette:
    """Create a dark palette that matches :data:`THEME_CSS`."""

    base = QColor("#0f111a")
    alt_base = QColor("#14192b")
    text = QColor("#f1f4ff")
    disabled_text = QColor("#7b88a8")
    highlight = QColor("#3a6ff1")
    highlight_text = QColor("#ffffff")

    palette = QPalette()
    palette.setColor(QPalette.Window, base)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, QColor("#12162a"))
    palette.setColor(QPalette.AlternateBase, alt_base)
    palette.setColor(QPalette.ToolTipBase, highlight)
    palette.setColor(QPalette.ToolTipText, highlight_text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, QColor("#202a46"))
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#ff6b6b"))
    palette.setColor(QPalette.Highlight, highlight)
    palette.setColor(QPalette.HighlightedText, highlight_text)

    palette.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, disabled_text)

    return palette


def apply_premium_theme(app: QApplication) -> None:
    """Apply the dark theme to *app*.

    The function is intentionally idempotent so it can be called more than once
    during tests without side effects.
    """

    if app is None:
        raise TypeError("'app' must be a valid QApplication instance")

    app.setPalette(_build_dark_palette())
    app.setStyleSheet(THEME_CSS)


def ensure_styled_background(widget: QWidget) -> None:
    """Force Qt to respect the background colour from the style sheet."""

    widget.setAttribute(Qt.WA_StyledBackground, True)
