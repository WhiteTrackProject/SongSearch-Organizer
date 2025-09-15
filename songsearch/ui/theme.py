THEME_CSS = """
QHeaderView::section:horizontal:last {
    border-right: none;
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
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::sub-page:horizontal,
QScrollBar::add-page:horizontal {
    background: none;
}
border-radius: 6px;
}
""".strip()