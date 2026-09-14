from PySide6.QtCore import QMargins
from PySide6.QtWidgets import QWidget

from retroarch_overlay.app.layout import CompanionLayoutManager
from retroarch_overlay.core.models import (
    GameDisplaySpec,
    LayoutProfile,
    ScreenRect,
    WindowGeometry,
)
from retroarch_overlay.presentation.qt import QtGeometryTarget
from retroarch_overlay.presentation.qt.layout import (
    QtLogicalGeometryProvider,
    _client_rect_for_frame,
)


# A 1920x1080 handheld panel at Windows' recommended 150% scaling.
HANDHELD_SCREEN = ((ScreenRect(0, 0, 1280, 720), 1.5),)


class NativeProvider:
    def __init__(self, geometry: WindowGeometry | None) -> None:
        self.geometry = geometry
        self.placements: list[tuple[int, ScreenRect]] = []

    def retroarch_geometry(self) -> WindowGeometry | None:
        return self.geometry

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        self.placements.append((handle, rect))
        return True


class RecordingTarget:
    def __init__(self) -> None:
        self.geometries: list[ScreenRect] = []

    def available_work_area(self) -> ScreenRect:
        raise AssertionError("RetroArch geometry should provide the work area")

    def set_geometry(self, rect: ScreenRect) -> None:
        self.geometries.append(rect)


def test_native_retroarch_geometry_is_mapped_to_qt_logical_pixels() -> None:
    native = NativeProvider(
        WindowGeometry(
            7,
            ScreenRect(0, 0, 1920, 1080),
            ScreenRect(0, 0, 1920, 1080),
            ScreenRect(0, 0, 1920, 1032),
            144,
            False,
        )
    )
    provider = QtLogicalGeometryProvider(native, lambda: HANDHELD_SCREEN)

    assert provider.retroarch_geometry() == WindowGeometry(
        7,
        ScreenRect(0, 0, 1280, 720),
        ScreenRect(0, 0, 1280, 720),
        ScreenRect(0, 0, 1280, 688),
        96,
        False,
    )


def test_overlay_panel_stays_on_a_scaled_handheld_screen() -> None:
    native = NativeProvider(
        WindowGeometry(
            7,
            ScreenRect(300, 200, 1100, 800),
            ScreenRect(308, 231, 1092, 792),
            ScreenRect(0, 0, 1920, 1032),
            144,
            False,
        )
    )
    manager = CompanionLayoutManager(
        LayoutProfile(mode="overlay"),
        QtLogicalGeometryProvider(native, lambda: HANDHELD_SCREEN),
    )
    target = RecordingTarget()

    manager.apply(target, GameDisplaySpec("gba", 240, 160))

    assert target.geometries == [ScreenRect(920, 0, 1280, 688)]


def test_managed_retroarch_placement_is_converted_back_to_native_pixels() -> None:
    native = NativeProvider(None)
    provider = QtLogicalGeometryProvider(native, lambda: HANDHELD_SCREEN)

    provider.place_window(7, ScreenRect(0, 0, 920, 688))

    assert native.placements == [(7, ScreenRect(0, 0, 1380, 1032))]


def test_mixed_dpi_monitors_scale_from_the_matching_screen_origin() -> None:
    screens = (
        (ScreenRect(0, 0, 1920, 1080), 1.0),
        (ScreenRect(1920, 0, 3200, 720), 1.5),
    )
    native = NativeProvider(
        WindowGeometry(
            7,
            ScreenRect(1920, 0, 3840, 1080),
            ScreenRect(1920, 0, 3840, 1080),
            ScreenRect(1920, 0, 3840, 1032),
        )
    )
    provider = QtLogicalGeometryProvider(native, lambda: screens)

    geometry = provider.retroarch_geometry()
    provider.place_window(7, ScreenRect(1920, 0, 2560, 688))

    assert geometry is not None
    assert geometry.work_area == ScreenRect(1920, 0, 3200, 688)
    assert native.placements == [(7, ScreenRect(1920, 0, 2880, 1032))]


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