from __future__ import annotations

from textwrap import dedent

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT_COLOR = QColor("#3D7DCE")
BACKGROUND_COLOR = QColor("#0F131A")
SURFACE_COLOR = QColor("#141B24")
SURFACE_ELEVATED_COLOR = QColor("#111821")
BASE_TEXT_COLOR = QColor("#E6EBF3")
MUTED_TEXT_COLOR = QColor("#9AA6B8")
DISABLED_TEXT_COLOR = QColor("#5C6775")
GRIDLINE_COLOR = QColor("#1F2732")
BUTTON_COLOR = QColor("#182130")
BUTTON_HOVER_COLOR = QColor("#203047")
BUTTON_PRESSED_COLOR = QColor("#2B4363")
SCROLLBAR_TRACK_COLOR = QColor("#0F141C")
SCROLLBAR_HANDLE_COLOR = QColor("#243248")
SCROLLBAR_HANDLE_HOVER_COLOR = QColor("#345079")


def _build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, BACKGROUND_COLOR)
    palette.setColor(QPalette.WindowText, BASE_TEXT_COLOR)
    palette.setColor(QPalette.Base, QColor("#0B1118"))
    palette.setColor(QPalette.AlternateBase, QColor("#121821"))
    palette.setColor(QPalette.ToolTipBase, SURFACE_ELEVATED_COLOR)
    palette.setColor(QPalette.ToolTipText, BASE_TEXT_COLOR)
    palette.setColor(QPalette.Text, BASE_TEXT_COLOR)
    palette.setColor(QPalette.Button, SURFACE_COLOR)
    palette.setColor(QPalette.ButtonText, BASE_TEXT_COLOR)
    palette.setColor(QPalette.Highlight, ACCENT_COLOR)
    palette.setColor(QPalette.HighlightedText, QColor("#F6F8FB"))
    palette.setColor(QPalette.Link, ACCENT_COLOR)
    palette.setColor(QPalette.LinkVisited, QColor("#6E8FCE"))

    palette.setColor(QPalette.Disabled, QPalette.Text, DISABLED_TEXT_COLOR)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, DISABLED_TEXT_COLOR)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, DISABLED_TEXT_COLOR)
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#29313C"))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor("#8C939E"))
    return palette


def _build_stylesheet() -> str:
    return dedent(
        f"""
        * {{
            color: {BASE_TEXT_COLOR.name()};
            font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        }}

        QMainWindow, QWidget#MainContainer {{
            background-color: {BACKGROUND_COLOR.name()};
        }}

        QLineEdit {{
            background-color: #151B23;
            border: 1px solid #1F2630;
            border-radius: 10px;
            padding: 8px 12px;
            selection-background-color: {ACCENT_COLOR.name()};
            selection-color: #ffffff;
        }}
        QLineEdit:hover {{
            border-color: #2F3B4B;
        }}
        QLineEdit:focus {{
            border-color: {ACCENT_COLOR.name()};
        }}

        QTableView {{
            background-color: #10161F;
            alternate-background-color: #0B121B;
            border: 1px solid {GRIDLINE_COLOR.name()};
            border-radius: 12px;
            gridline-color: {GRIDLINE_COLOR.name()};
            selection-background-color: rgba(61, 125, 206, 140);
            selection-color: #F6F8FB;
        }}
        QTableView::item {{
            padding: 6px;
        }}

        QHeaderView::section {{
            background-color: #141C27;
            color: #CED6E1;
            padding: 8px 6px;
            border: none;
            border-bottom: 1px solid {GRIDLINE_COLOR.name()};
        }}
        QHeaderView::section:horizontal {{
            border-right: 1px solid {GRIDLINE_COLOR.name()};
        }}
        QHeaderView::section:horizontal:last {{
            border-right: none;
        }}

        QTableCornerButton::section {{
            background-color: #141C27;
            border: none;
            border-bottom: 1px solid {GRIDLINE_COLOR.name()};
        }}

        QStatusBar {{
            background-color: {BACKGROUND_COLOR.name()};
            border-top: 1px solid {GRIDLINE_COLOR.name()};
            color: {MUTED_TEXT_COLOR.name()};
        }}
        QStatusBar::item {{
            border: none;
        }}

        QWidget#DetailsPanel {{
            background-color: {SURFACE_ELEVATED_COLOR.name()};
            border: 1px solid {GRIDLINE_COLOR.name()};
            border-radius: 12px;
        }}

        QWidget#DetailsPanel QPushButton {{
            min-height: 32px;
        }}

        QPushButton {{
            background-color: {BUTTON_COLOR.name()};
            border: 1px solid #283142;
            border-radius: 8px;
            padding: 6px 16px;
            color: #DFE6F1;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {BUTTON_HOVER_COLOR.name()};
            border-color: {ACCENT_COLOR.name()};
        }}
        QPushButton:pressed {{
            background-color: {BUTTON_PRESSED_COLOR.name()};
        }}
        QPushButton:disabled {{
            background-color: #141B26;
            color: #5E6B7C;
            border-color: #1A202B;
        }}

        QLabel[formLabel="true"] {{
            color: {MUTED_TEXT_COLOR.name()};
            font-weight: 600;
            letter-spacing: 0.4px;
        }}
        QLabel[valueLabel="true"] {{
            color: #F5F7FA;
            font-weight: 500;
        }}

        QSplitter::handle {{
            background-color: #0B1018;
            margin: 0px;
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:horizontal:hover {{
            background-color: {ACCENT_COLOR.name()};
        }}

        QScrollBar:vertical {{
            background: {SCROLLBAR_TRACK_COLOR.name()};
            width: 12px;
            margin: 4px 0 4px 0;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: {SCROLLBAR_HANDLE_COLOR.name()};
            min-height: 24px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {SCROLLBAR_HANDLE_HOVER_COLOR.name()};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::sub-page:vertical,
        QScrollBar::add-page:vertical {{
            background: none;
        }}

        QScrollBar:horizontal {{
            background: {SCROLLBAR_TRACK_COLOR.name()};
            height: 12px;
            margin: 0 4px 0 4px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal {{
            background: {SCROLLBAR_HANDLE_COLOR.name()};
            min-width: 24px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {SCROLLBAR_HANDLE_HOVER_COLOR.name()};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::sub-page:horizontal,
        QScrollBar::add-page:horizontal {{
            background: none;
        }}

        QToolTip {{
            background-color: #1A2130;
            color: {BASE_TEXT_COLOR.name()};
            border: 1px solid {ACCENT_COLOR.name()};
            padding: 6px;
            border-radius: 6px;
        }}
        """
    ).strip()


def apply_premium_theme(app: QApplication) -> None:
    """Apply a polished dark theme to the Qt application."""

    app.setStyle("Fusion")
    app.setPalette(_build_palette())

    base_font: QFont = app.font()
    if base_font.pointSizeF() <= 0:
        base_font.setPointSize(10)
    else:
        base_font.setPointSizeF(max(base_font.pointSizeF(), 10.5))
    app.setFont(base_font)

    app.setStyleSheet(_build_stylesheet())
