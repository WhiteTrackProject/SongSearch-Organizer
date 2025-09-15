from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class PremiumColors:
    """Curated palette for a polished SongSearch dark theme."""

    accent: QColor = QColor("#6C7CFF")
    accent_hover: QColor = QColor("#8895FF")
    accent_pressed: QColor = QColor("#515FE6")
    background: QColor = QColor("#070B13")
    background_elevated: QColor = QColor("#0E1421")
    surface: QColor = QColor("#131A2C")
    surface_alt: QColor = QColor("#171F33")
    outline: QColor = QColor("#1D2437")
    outline_soft: QColor = QColor("#262F47")
    text_primary: QColor = QColor("#F1F4FD")
    text_secondary: QColor = QColor("#AEB8CF")
    text_muted: QColor = QColor("#6F7B92")


def _hex(color: QColor) -> str:
    return QColor(color).name(QColor.HexRgb)


def _hexa(color: QColor, alpha: int) -> str:
    shaded = QColor(color)
    shaded.setAlpha(alpha)
    return shaded.name(QColor.HexArgb)


def _build_palette(colors: PremiumColors) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, colors.background)
    palette.setColor(QPalette.WindowText, colors.text_primary)
    palette.setColor(QPalette.Base, colors.surface)
    palette.setColor(QPalette.AlternateBase, colors.surface_alt)
    palette.setColor(QPalette.ToolTipBase, colors.surface_alt)
    palette.setColor(QPalette.ToolTipText, colors.text_primary)
    palette.setColor(QPalette.Text, colors.text_primary)
    palette.setColor(QPalette.Button, colors.surface)
    palette.setColor(QPalette.ButtonText, colors.text_primary)
    palette.setColor(QPalette.Highlight, colors.accent)
    palette.setColor(QPalette.HighlightedText, QColor("#0B0F1A"))
    palette.setColor(QPalette.Link, colors.accent)
    palette.setColor(QPalette.LinkVisited, QColor("#92A0FF"))
    palette.setColor(QPalette.PlaceholderText, colors.text_muted)

    palette.setColor(QPalette.Disabled, QPalette.Text, colors.text_muted)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, colors.text_muted)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, colors.text_muted)
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(colors.accent).darker(170))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, colors.text_secondary)
    palette.setColor(QPalette.Disabled, QPalette.PlaceholderText, colors.text_muted)
    return palette


def _build_stylesheet(colors: PremiumColors) -> str:
    return dedent(
        f"""
        QWidget {{
            background-color: {_hex(colors.background)};
            color: {_hex(colors.text_primary)};
            font-family: "Inter", "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif;
            font-size: 13px;
            letter-spacing: 0.2px;
        }}

        QMainWindow, QWidget#MainContainer {{
            background-color: {_hex(colors.background)};
        }}

        QFrame#HeaderBar {{
            background-color: {_hex(colors.background_elevated)};
            border-radius: 20px;
            border: 1px solid {_hex(colors.outline)};
        }}

        QLabel#AppTitle {{
            color: {_hex(colors.text_primary)};
            font-size: 22px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}

        QLabel#AppSubtitle {{
            color: {_hex(colors.text_secondary)};
            font-size: 12.5px;
            letter-spacing: 0.3px;
        }}

        QLabel#HeaderBadge {{
            background-color: {_hexa(colors.accent, 42)};
            color: {_hex(colors.accent)};
            padding: 4px 12px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.8px;
        }}

        QFrame#SearchContainer {{
            background-color: {_hex(colors.surface)};
            border-radius: 16px;
            border: 1px solid {_hex(colors.outline)};
        }}
        QFrame#SearchContainer:hover {{
            border-color: {_hex(colors.outline_soft)};
        }}

        QLabel#SearchIcon {{
            color: {_hex(colors.text_secondary)};
            font-size: 16px;
            padding-right: 4px;
        }}

        QLabel#SearchHint {{
            color: {_hex(colors.text_muted)};
            font-size: 11.5px;
            border-left: 1px solid {_hex(colors.outline)};
            padding-left: 10px;
            margin-left: 6px;
        }}

        QLineEdit#SearchField {{
            background: transparent;
            border: none;
            color: {_hex(colors.text_primary)};
            font-size: 13px;
            padding: 0px;
        }}
        QLineEdit#SearchField:focus {{
            color: {_hex(colors.text_primary)};
        }}

        QFrame#TableCard, QFrame#DetailsCard {{
            background-color: {_hex(colors.background_elevated)};
            border-radius: 20px;
            border: 1px solid {_hex(colors.outline)};
        }}
        QFrame#TableCard:hover, QFrame#DetailsCard:hover {{
            border-color: {_hex(colors.outline_soft)};
        }}

        QTableView {{
            background-color: transparent;
            alternate-background-color: {_hex(colors.surface)};
            border: none;
            color: {_hex(colors.text_primary)};
            gridline-color: {_hex(colors.outline)};
            selection-background-color: {_hexa(colors.accent, 150)};
            selection-color: {_hex(colors.text_primary)};
        }}
        QTableView::item {{
            padding: 6px 12px;
        }}

        QHeaderView::section {{
            background-color: {_hex(colors.background_elevated)};
            color: {_hex(colors.text_secondary)};
            border: none;
            border-bottom: 1px solid {_hex(colors.outline)};
            padding: 10px 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            font-size: 11px;
        }}
        QHeaderView::section:horizontal {{
            border-right: 1px solid {_hex(colors.outline)};
        }}
        QHeaderView::section:horizontal:last {{
            border-right: none;
        }}
        QTableCornerButton::section {{
            background-color: {_hex(colors.background_elevated)};
            border: none;
        }}

        QLabel[formLabel="true"] {{
            color: {_hex(colors.text_muted)};
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1.1px;
            font-weight: 600;
        }}
        QLabel[valueLabel="true"] {{
            color: {_hex(colors.text_primary)};
            font-size: 13px;
        }}

        QPushButton {{
            background-color: {_hexa(colors.accent, 40)};
            color: {_hex(colors.text_primary)};
            border: 1px solid {_hex(colors.outline)};
            border-radius: 10px;
            padding: 8px 18px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            border-color: {_hex(colors.outline_soft)};
            background-color: {_hexa(colors.accent, 64)};
        }}
        QPushButton:pressed {{
            background-color: {_hexa(colors.accent, 90)};
        }}
        QPushButton:disabled {{
            background-color: {_hex(colors.outline)};
            border-color: {_hex(colors.outline)};
            color: {_hex(colors.text_muted)};
        }}
        QPushButton[accentButton="true"] {{
            background-color: {_hex(colors.accent)};
            border: none;
            color: #080B12;
        }}
        QPushButton[accentButton="true"]:hover {{
            background-color: {_hex(colors.accent_hover)};
        }}
        QPushButton[accentButton="true"]:pressed {{
            background-color: {_hex(colors.accent_pressed)};
        }}

        QStatusBar {{
            background-color: transparent;
            color: {_hex(colors.text_secondary)};
            border-top: 1px solid {_hex(colors.outline)};
            padding: 6px 8px 4px;
        }}
        QStatusBar::item {{
            border: none;
        }}

        QSplitter#MainSplitter::handle {{
            background-color: {_hex(colors.outline)};
            margin: 20px 0;
            width: 1px;
        }}
        QSplitter#MainSplitter::handle:hover {{
            background-color: {_hex(colors.accent)};
        }}

        QScrollBar:vertical {{
            background: {_hex(colors.surface)};
            width: 12px;
            margin: 12px 0;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: {_hex(colors.outline_soft)};
            border-radius: 6px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {_hex(colors.accent)};
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
            background: {_hex(colors.surface)};
            height: 12px;
            margin: 0 12px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal {{
            background: {_hex(colors.outline_soft)};
            border-radius: 6px;
            min-width: 32px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {_hex(colors.accent)};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::sub-page:horizontal,
        QScrollBar::add-page:horizontal {{
            background: none;
        }}

        QWidget#DetailsPanel {{
            background-color: transparent;
        }}
        QWidget#DetailsPanel QPushButton {{
            min-height: 36px;
        }}

        QToolTip {{
            background-color: {_hex(colors.surface)};
            color: {_hex(colors.text_primary)};
            border: 1px solid {_hex(colors.outline)};
            padding: 6px 8px;
            border-radius: 6px;
        }}
        """
    ).strip()


def apply_premium_theme(app: QApplication) -> None:
    """Apply a premium dark theme to the Qt application."""

    colors = PremiumColors()
    app.setStyle("Fusion")
    app.setPalette(_build_palette(colors))

    base_font: QFont = app.font()
    if hasattr(base_font, "setFamilies"):
        base_font.setFamilies(["Inter", "Segoe UI", "Roboto", "Helvetica Neue", "Arial"])
    else:
        base_font.setFamily("Inter")

    size = base_font.pointSizeF()
    if size <= 0:
        base_font.setPointSize(11)
    else:
        base_font.setPointSizeF(max(size, 11.0))
    base_font.setLetterSpacing(QFont.PercentageSpacing, 102.0)
    base_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(base_font)

    app.setStyleSheet(_build_stylesheet(colors))
