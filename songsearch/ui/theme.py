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
/* Base surface */
QWidget {
    background-color: #0c0f1c;
    color: #f5f8ff;
    font-family: "Inter", "SF Pro Display", "Segoe UI", sans-serif;
    font-size: 15px;
}

QMainWindow, QWidget#MainContainer {
    background-color: #0c0f1c;
}

/* Header */
#HeaderBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a2135, stop:1 #121727);
    border-bottom: 1px solid #202947;
}

#HeaderTitle {
    font-size: 26px;
    font-weight: 600;
    color: #f9faff;
}

#HeaderSubtitle {
    color: #9aa5c5;
    font-size: 13px;
}

QLabel#SummaryBadge {
    background-color: rgba(77, 118, 255, 0.28);
    color: #e3ebff;
    padding: 6px 16px;
    border-radius: 16px;
    font-size: 13px;
    font-weight: 600;
}

QFrame#ToolbarCard {
    background-color: rgba(24, 31, 52, 220);
    border: 1px solid rgba(86, 115, 196, 90);
    border-radius: 24px;
}

#SearchContainer {
    background-color: rgba(10, 14, 26, 210);
    border-radius: 20px;
    border: 1px solid rgba(90, 116, 196, 80);
}

QLineEdit#SearchField {
    background-color: transparent;
    border: none;
    padding: 8px 12px;
    selection-background-color: #4c6ff6;
    selection-color: #ffffff;
}

QLineEdit#SearchField:focus {
    outline: none;
}

QLabel#SearchHint {
    color: #8f9ac1;
    font-size: 12px;
}

/* Buttons */
QPushButton {
    background-color: rgba(38, 48, 76, 220);
    border-radius: 20px;
    padding: 10px 20px;
    border: 1px solid rgba(95, 116, 180, 60);
    color: #eef1ff;
    font-weight: 500;
}

QPushButton:hover {
    background-color: rgba(52, 66, 104, 240);
}

QPushButton:pressed {
    background-color: rgba(35, 46, 74, 255);
}

QPushButton:disabled {
    background-color: rgba(34, 42, 66, 120);
    color: rgba(224, 228, 248, 90);
    border-color: transparent;
}

QPushButton[toolbarButton="true"] {
    background-color: rgba(73, 98, 182, 210);
    color: #ffffff;
    font-weight: 600;
    padding: 10px 24px;
    border: 1px solid rgba(118, 148, 236, 120);
}

QPushButton[toolbarButton="true"]:hover {
    background-color: rgba(96, 124, 218, 230);
}

QPushButton[toolbarButton="true"]:pressed {
    background-color: rgba(63, 86, 164, 220);
}

QPushButton[helpButton="true"] {
    background-color: rgba(96, 132, 255, 210);
    border: 1px solid rgba(140, 165, 255, 150);
    color: #ffffff;
    font-weight: 600;
}

QPushButton[helpButton="true"]:hover {
    background-color: rgba(118, 152, 255, 230);
}

QPushButton[helpButton="true"]:pressed {
    background-color: rgba(84, 120, 230, 220);
}

QPushButton[secondaryButton="true"] {
    background-color: rgba(30, 38, 60, 220);
    border: 1px solid rgba(76, 98, 158, 80);
    color: #e6e9f9;
}

QPushButton[tonalButton="true"] {
    background-color: rgba(86, 120, 240, 210);
    border: 1px solid rgba(116, 150, 255, 140);
    color: #ffffff;
    font-weight: 600;
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

/* Cards */
QFrame#TableCard,
QFrame#DetailsCard {
    background-color: rgba(18, 23, 39, 240);
    border: 1px solid rgba(60, 74, 120, 120);
    border-radius: 24px;
}

QLabel#CardTitle {
    color: #f4f6ff;
    font-size: 17px;
    font-weight: 600;
}

QLabel#CardSubtitle {
    color: #99a5cb;
    font-size: 13px;
}

QLabel#DetailsHeadline {
    color: #f7f9ff;
    font-size: 20px;
    font-weight: 600;
}

QLabel#DetailsSubheadline {
    color: #a2aed0;
    font-size: 13px;
}

QLabel[formLabel="true"] {
    color: #8a94b6;
    font-weight: 600;
}

QLabel[valueLabel="true"] {
    color: #f1f4ff;
}

QFrame#DetailsActions {
    background-color: rgba(16, 22, 38, 200);
    border: 1px solid rgba(66, 84, 140, 100);
    border-radius: 18px;
}

/* Table */
QTableView {
    background-color: transparent;
    alternate-background-color: rgba(30, 38, 63, 140);
    gridline-color: rgba(46, 60, 100, 160);
    selection-background-color: rgba(80, 120, 230, 200);
    selection-color: #f5f8ff;
    border: none;
}

QTableView::item:hover {
    background-color: rgba(80, 120, 230, 60);
}

QHeaderView::section {
    background-color: transparent;
    color: #9aa5c8;
    border: none;
    border-right: 1px solid rgba(60, 74, 120, 120);
    padding: 6px 10px;
    font-weight: 500;
}

QHeaderView::section:horizontal:last {
    border-right: none;
}

/* Scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 10px 0;
}

QScrollBar::handle:vertical {
    background: rgba(86, 112, 178, 200);
    min-height: 48px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(108, 134, 204, 220);
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
    margin: 0 10px;
}

QScrollBar::handle:horizontal {
    background: rgba(86, 112, 178, 200);
    min-width: 48px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(108, 134, 204, 220);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar::sub-page:horizontal,
QScrollBar::add-page:horizontal {
    background: none;
}

/* Status bar & dialogs */
QStatusBar#MainStatusBar {
    background-color: rgba(18, 23, 39, 240);
    border-top: 1px solid rgba(52, 66, 110, 120);
    color: #9fa9c8;
}

QMessageBox {
    background-color: #12162a;
}

QToolTip {
    background-color: #4c6ff6;
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
