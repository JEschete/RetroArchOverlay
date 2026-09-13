from PySide6.QtWidgets import QWidget

from retroarch_overlay.core.models import ScreenRect
from retroarch_overlay.presentation.qt import QtGeometryTarget


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