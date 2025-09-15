from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class PremiumTokens:
    """Color palette used by the premium SongSearch theme."""

    accent: QColor = QColor("#7385FF")
    accent_hover: QColor = QColor("#8898FF")
    accent_pressed: QColor = QColor("#5C6FE5")
    background: QColor = QColor("#070B13")
    background_raised: QColor = QColor("#0E1422")
    surface: QColor = QColor("#131A2B")
    surface_alt: QColor = QColor("#161F33")
    outline: QColor = QColor("#1E263A")
    outline_soft: QColor = QColor("#272F47")
    text_primary: QColor = QColor("#F2F5FF")
    text_secondary: QColor = QColor("#B1BAD4")
    text_muted: QColor = QColor("#707B94")


def _hex(color: QColor) -> str:
    return QColor(color).name(QColor.HexRgb)


def _hexa(color: QColor, alpha: int) -> str:
    tinted = QColor(color)
    tinted.setAlpha(alpha)
    return tinted.name(QColor.HexArgb)


def _build_palette(colors: PremiumTokens) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, colors.background)
    palette.setColor(QPalette.WindowText, colors.text_primary)
    palette.setColor(QPalette.Base, colors.surface)
    palette.setColor(QPalette.AlternateBase, colors.surface_alt)
    palette.setColor(QPalette.ToolTipBase, colors.surface)
    palette.setColor(QPalette.ToolTipText, colors.text_primary)
    palette.setColor(QPalette.Text, colors.text_primary)
    palette.setColor(QPalette.Button, colors.surface)
    palette.setColor(QPalette.ButtonText, colors.text_primary)
    palette.setColor(QPalette.Highlight, colors.accent)
    palette.setColor(QPalette.HighlightedText, QColor("#0A0E17"))
    palette.setColor(QPalette.Link, colors.accent)
    palette.setColor(QPalette.LinkVisited, QColor("#9BA6FF"))
    palette.setColor(QPalette.PlaceholderText, colors.text_muted)

    palette.setColor(QPalette.Disabled, QPalette.Text, colors.text_muted)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, colors.text_muted)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, colors.text_muted)
    palette.setColor(
        QPalette.Disabled,
        QPalette.Highlight,
        QColor(colors.accent).darker(170),
    )
    palette.setColor(
        QPalette.Disabled,
        QPalette.HighlightedText,
        colors.text_secondary,
    )
    palette.setColor(
        QPalette.Disabled,
        QPalette.PlaceholderText,
        colors.text_muted,
    )
    return palette


def _build_stylesheet(colors: PremiumTokens) -> str:
    background = _hex(colors.background)
    raised = _hex(colors.background_raised)
    surface = _hex(colors.surface)
    outline = _hex(colors.outline)
    outline_soft = _hex(colors.outline_soft)
    text_primary = _hex(colors.text_primary)
    text_secondary = _hex(colors.text_secondary)
    text_muted = _hex(colors.text_muted)
    accent = _hex(colors.accent)
    accent_hover = _hex(colors.accent_hover)
    accent_pressed = _hex(colors.accent_pressed)
    accent_soft = _hexa(colors.accent, 42)
    accent_soft_hover = _hexa(colors.accent, 64)
    accent_soft_pressed = _hexa(colors.accent, 90)
    selection = _hexa(colors.accent, 150)

    return dedent(
        f"""
        QWidget {{
            background-color: {background};
            color: {text_primary};
            font-family: "Inter", "Segoe UI", "Roboto", sans-serif;
            font-size: 13px;
            letter-spacing: 0.2px;
        }}

        QMainWindow, QWidget#MainContainer {{
            background-color: {background};
        }}

        QFrame#HeaderBar {{
            background-color: {raised};
            border-radius: 20px;
            border: 1px solid {outline};
        }}

        QLabel#AppTitle {{
            color: {text_primary};
            font-size: 22px;
            font-weight: 700;
            letter-spacing: 0.4px;
        }}

        QLabel#AppSubtitle {{
            color: {text_secondary};
            font-size: 12.5px;
            letter-spacing: 0.3px;
        }}

        QLabel#HeaderBadge {{
            background-color: {_hexa(colors.accent, 48)};
            color: {accent};
            border-radius: 10px;
            padding: 4px 12px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.6px;
        }}

        QFrame#SearchContainer {{
            background-color: {surface};
            border-radius: 16px;
            border: 1px solid {outline};
        }}
        QFrame#SearchContainer:hover {{
            border-color: {outline_soft};
        }}

        QLabel#SearchIcon {{
            color: {text_secondary};
            font-size: 16px;
            padding-right: 4px;
        }}

        QLabel#SearchHint {{
            color: {text_muted};
            font-size: 11.5px;
            border-left: 1px solid {outline};
            padding-left: 10px;
            margin-left: 6px;
        }}

        QLineEdit#SearchField {{
            background: transparent;
            border: none;
            color: {text_primary};
        }}
        QLineEdit#SearchField:focus {{
            color: {text_primary};
        }}

        QFrame#TableCard, QFrame#DetailsCard {{
            background-color: {raised};
            border-radius: 20px;
            border: 1px solid {outline};
        }}
        QFrame#TableCard:hover, QFrame#DetailsCard:hover {{
            border-color: {outline_soft};
        }}

        QTableView {{
            background-color: transparent;
            alternate-background-color: {surface};
            border: none;
            color: {text_primary};
            gridline-color: {outline};
            selection-background-color: {selection};
            selection-color: {text_primary};
        }}
        QTableView::item {{
            padding: 6px 12px;
        }}

        QHeaderView::section {{
            background-color: {raised};
            color: {text_secondary};
            border: none;
            border-bottom: 1px solid {outline};
            padding: 10px 12px;
            font-weight: 600;
            letter-spacing: 0.8px;
            font-size: 11px;
            text-transform: uppercase;
        }}
        QHeaderView::section:horizontal {{
            border-right: 1px solid {outline};
        }}
        QHeaderView::section:horizontal:last {{
            border-right: none;
        }}
        QTableCornerButton::section {{
            background-color: {raised};
            border: none;
        }}

        QLabel[formLabel="true"] {{
            color: {text_muted};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
        }}
        QLabel[valueLabel="true"] {{
            color: {text_primary};
        }}

        QPushButton {{
            background-color: {accent_soft};
            color: {text_primary};
            border: 1px solid {outline};
            border-radius: 10px;
            padding: 8px 18px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {accent_soft_hover};
            border-color: {outline_soft};
        }}
        QPushButton:pressed {{
            background-color: {accent_soft_pressed};
        }}
        QPushButton:disabled {{
            background-color: {outline};
            border-color: {outline};
            color: {text_muted};
        }}
        QPushButton[accentButton="true"] {{
            background-color: {accent};
            border: none;
            color: #070A12;
        }}
        QPushButton[accentButton="true"]:hover {{
            background-color: {accent_hover};
        }}
        QPushButton[accentButton="true"]:pressed {{
            background-color: {accent_pressed};
        }}

        QStatusBar {{
            background-color: transparent;
            color: {text_secondary};
            border-top: 1px solid {outline};
            padding: 6px 8px 4px;
        }}
        QStatusBar::item {{
            border: none;
        }}

        QSplitter#MainSplitter::handle {{
            background-color: {outline};
            margin: 20px 0;
            width: 1px;
        }}
        QSplitter#MainSplitter::handle:hover {{
            background-color: {accent};
        }}

        QScrollBar:vertical {{
            background: {surface};
            width: 12px;
            margin: 12px 0;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: {outline_soft};
            border-radius: 6px;
            min-height: 32px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {accent};
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
            background: {surface};
            height: 12px;
            margin: 0 12px;
            border-radius: 6px;
        }}
        QScrollBar::handle:horizontal {{
            background: {outline_soft};
            border-radius: 6px;
            min-width: 32px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {accent};
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
            background-color: {surface};
            color: {text_primary};
            border: 1px solid {outline};
            padding: 6px 8px;
            border-radius: 6px;
        }}
        """
    ).strip()


def ensure_styled_background(widget: QWidget, *, minimum_width: int | None = None) -> None:
    """Enable stylesheet-driven backgrounds for *widget*."""

    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    if minimum_width is not None:
        widget.setMinimumWidth(minimum_width)


def apply_premium_theme(app: QApplication) -> None:
    """Apply the premium palette and stylesheet to *app*."""

    colors = PremiumTokens()
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
