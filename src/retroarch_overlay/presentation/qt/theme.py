from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..theme import THEME_PALETTES, accessible_text_color, resolve_theme


def qt_palette(preference: str) -> tuple[str, QPalette]:
    name = resolve_theme(preference)
    colors = THEME_PALETTES[name]
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["foreground"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["background"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["foreground"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["foreground"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["foreground"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(
        QPalette.ColorRole.HighlightedText,
        QColor(accessible_text_color(colors["accent"], colors["header_foreground"])),
    )
    palette.setColor(QPalette.ColorRole.Link, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(colors["danger"]))
    return name, palette


def apply_qt_theme(
    target: QApplication | QWidget,
    preference: str,
) -> str:
    name, palette = qt_palette(preference)
    target.setStyleSheet(qt_style_sheet(name))
    target.setPalette(palette)
    return name


def qt_style_sheet(preference: str) -> str:
    name = resolve_theme(preference)
    colors = THEME_PALETTES[name]
    selected_text = accessible_text_color(
        colors["accent"],
        colors["header_foreground"],
    )
    return f"""
        QWidget {{
            color: {colors['foreground']};
        }}
        QFrame#urgentSummary, QFrame#alertToast {{
            background: {colors['alert_background']};
            border: 1px solid {colors['alert_foreground']};
        }}
        QLabel#urgentSummaryLabel, QLabel#alertToastTitle {{
            color: {colors['alert_foreground']};
            font-weight: 600;
        }}
        QLabel#alertToastDetail {{
            color: {colors['foreground']};
        }}
        QScrollArea, QListView {{
            background: {colors['background']};
        }}
        QTableView, QPlainTextEdit, QComboBox {{
            background: {colors['background']};
            color: {colors['foreground']};
            border: 1px solid {colors['divider']};
            selection-background-color: {colors['accent']};
            selection-color: {selected_text};
        }}
        QHeaderView::section {{
            background: {colors['surface']};
            color: {colors['foreground']};
            border: 0;
            border-right: 1px solid {colors['divider']};
            border-bottom: 1px solid {colors['divider']};
            padding: 5px 7px;
        }}
        QTabWidget::pane {{
            background: {colors['background']};
            border: 1px solid {colors['divider']};
        }}
        QTabBar::tab {{
            background: {colors['surface']};
            color: {colors['foreground']};
            border: 1px solid {colors['divider']};
            padding: 6px 10px;
        }}
        QTabBar::tab:selected {{
            background: {colors['background']};
            color: {colors['accent']};
            border-bottom-color: {colors['background']};
        }}
        QCheckBox {{
            color: {colors['foreground']};
            spacing: 6px;
        }}
        QComboBox::drop-down {{
            border: 0;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background: {colors['background']};
            color: {colors['foreground']};
            selection-background-color: {colors['accent']};
            selection-color: {selected_text};
        }}
        QPushButton {{
            background: {colors['surface']};
            color: {colors['foreground']};
            border: 2px solid {colors['divider']};
            border-radius: 3px;
            padding: 5px 8px;
        }}
        QPushButton:hover, QPushButton:focus {{
            border-color: {colors['accent']};
        }}
        QPushButton:checked {{
            background: {colors['accent']};
            color: {selected_text};
            border-color: {colors['accent']};
        }}
        QLineEdit, QPlainTextEdit, QComboBox {{
            background: {colors['background']};
            color: {colors['foreground']};
            border: 2px solid {colors['divider']};
            border-radius: 3px;
            padding: 4px 6px;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
            border-color: {colors['accent']};
        }}
        QToolTip {{
            background: {colors['surface']};
            color: {colors['foreground']};
            border: 1px solid {colors['divider']};
        }}
    """