from PySide6.QtCore import QMargins
from PySide6.QtWidgets import QWidget

from retroarch_overlay.core.models import ScreenRect
from retroarch_overlay.presentation.qt import QtGeometryTarget
from retroarch_overlay.presentation.qt.layout import _client_rect_for_frame


def test_frame_target_keeps_native_title_bar_inside_work_area() -> None:
    target = ScreenRect(0, 0, 360, 1040)

    assert _client_rect_for_frame(target, QMargins(0, 45, 0, 8)) == ScreenRect(
        0,
        45,
        360,
        1032,
    )


def test_qt_geometry_target_applies_screen_rect(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    target = QtGeometryTarget(window)

    target.set_geometry(ScreenRect(25, 35, 425, 635))

    assert window.geometry().getRect() == (25, 35, 400, 600)


def test_qt_geometry_target_reports_current_screen_work_area(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    target = QtGeometryTarget(window)
    expected = window.screen().availableGeometry()

    assert target.available_work_area() == ScreenRect(
        expected.left(),
        expected.top(),
        expected.left() + expected.width(),
        expected.top() + expected.height(),
    )