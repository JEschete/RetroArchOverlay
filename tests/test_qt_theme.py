import pytest
from PySide6.QtGui import QPalette

from retroarch_overlay.infrastructure.accessibility import contrast_ratio
from retroarch_overlay.presentation.qt import (
    apply_qt_theme,
    qt_palette,
    qt_style_sheet,
)
from retroarch_overlay.presentation.theme import (
    THEME_PALETTES,
    accessible_text_color,
)


def test_shared_theme_palettes_are_immutable() -> None:
    with pytest.raises(TypeError):
        THEME_PALETTES["light"]["foreground"] = "#ffffff"  # type: ignore[index]


def test_inaccessible_requested_text_uses_best_black_or_white_fallback() -> None:
    repaired = accessible_text_color("#f5f5f5", "#eeeeee")

    assert repaired == "#000000"
    assert contrast_ratio(repaired, "#f5f5f5") >= 4.5


def test_qt_palette_maps_shared_semantic_tokens() -> None:
    name, palette = qt_palette("high-contrast")

    assert name == "high-contrast"
    assert palette.color(QPalette.ColorRole.Window).name() == "#ffffff"
    assert palette.color(QPalette.ColorRole.WindowText).name() == "#000000"
    assert palette.color(QPalette.ColorRole.Highlight).name() == "#0046b8"
    assert contrast_ratio(
        palette.color(QPalette.ColorRole.HighlightedText).name(),
        palette.color(QPalette.ColorRole.Highlight).name(),
    ) >= 4.5


def test_apply_theme_updates_qapplication_palette(qapp) -> None:
    name = apply_qt_theme(qapp, "dark")

    assert name == "dark"
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#191d1a"


def test_checked_button_style_uses_project_accent_and_contrast_safe_text() -> None:
    style = qt_style_sheet("light")

    assert "QPushButton:checked" in style
    assert "background: #bb3e2f" in style
    assert "color: #ffffff" in style