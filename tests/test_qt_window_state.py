from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QMainWindow, QWidget

from retroarch_overlay.core.models import ScreenRect
from retroarch_overlay.presentation.qt import (
    WindowPresentation,
    apply_window_presentation,
    legacy_window_rect,
    restore_named_window_geometry,
    restore_window_geometry,
    save_named_window_geometry,
    save_window_geometry,
)


def test_legacy_geometry_combines_managed_position_and_native_size() -> None:
    settings = Mock()
    settings.window_geometry.side_effect = lambda key: {
        "main-qt": None,
        "main": ScreenRect(1500, 100, 1860, 1000),
        "main-native": ScreenRect(10, 20, 430, 720),
    }.get(key)

    assert legacy_window_rect(settings) == ScreenRect(1500, 100, 1920, 800)


def test_qt_geometry_wins_over_legacy_values() -> None:
    settings = Mock()
    settings.window_geometry.side_effect = lambda key: {
        "main-qt": ScreenRect(100, 200, 500, 800),
        "main": ScreenRect(10, 20, 310, 620),
    }.get(key)

    assert legacy_window_rect(settings) == ScreenRect(100, 200, 500, 800)


def test_restore_clamps_removed_monitor_geometry(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    settings = Mock()
    settings.window_geometry.side_effect = lambda key: (
        ScreenRect(2300, 200, 2700, 800) if key == "main-qt" else None
    )

    restored = restore_window_geometry(
        window,
        settings,
        work_areas=(ScreenRect(0, 0, 1920, 1040),),
    )

    assert restored == ScreenRect(1520, 200, 1920, 800)
    assert window.geometry().getRect() == (1520, 200, 400, 600)


def test_save_uses_qt_specific_key(qtbot) -> None:
    window = QWidget()
    window.setGeometry(30, 40, 400, 600)
    qtbot.addWidget(window)
    settings = Mock()

    saved = save_window_geometry(window, settings)

    assert saved == ScreenRect(30, 40, 430, 640)
    settings.save_window_geometry.assert_called_once_with("main-qt", saved)


def test_named_geometry_uses_legacy_fallback_and_saves_only_new_key(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    settings = Mock()
    settings.window_geometry.side_effect = lambda key: (
        ScreenRect(20, 30, 420, 630) if key == "map" else None
    )

    restored = restore_named_window_geometry(
        window,
        settings,
        "map-qt",
        fallback_keys=("map",),
        work_areas=(ScreenRect(0, 0, 1920, 1040),),
    )
    saved = save_named_window_geometry(window, settings, "map-qt")

    assert restored == ScreenRect(20, 30, 420, 630)
    assert saved == restored
    settings.save_window_geometry.assert_called_once_with("map-qt", restored)


def test_window_presentation_policies_are_independent(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    presentation = WindowPresentation(
        opacity=0.75,
        always_on_top=True,
        frameless=True,
        show_in_taskbar=False,
    )

    apply_window_presentation(window, presentation)

    assert window.windowOpacity() == pytest.approx(0.75, abs=1 / 255)
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.windowType() == Qt.WindowType.Tool

    apply_window_presentation(
        window,
        replace(
            presentation,
            always_on_top=False,
            frameless=False,
            show_in_taskbar=True,
        ),
    )

    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.windowType() == Qt.WindowType.Window


def test_live_presentation_change_preserves_visibility_and_geometry(
    qtbot,
) -> None:
    window = QMainWindow()
    editor = QLineEdit(window)
    window.setCentralWidget(editor)
    window.setGeometry(40, 50, 420, 300)
    qtbot.addWidget(window)
    window.show()
    editor.setFocus()

    apply_window_presentation(
        window,
        WindowPresentation(
            opacity=0.8,
            always_on_top=True,
            frameless=True,
            show_in_taskbar=False,
        ),
    )

    assert window.isVisible()
    assert window.geometry().getRect() == (40, 50, 420, 300)

    apply_window_presentation(window, WindowPresentation())

    assert window.isVisible()
    assert window.geometry().getRect() == (40, 50, 420, 300)


def test_window_presentation_rejects_invisible_opacity() -> None:
    with pytest.raises(ValueError, match="between 0.3 and 1.0"):
        WindowPresentation(opacity=0.2)