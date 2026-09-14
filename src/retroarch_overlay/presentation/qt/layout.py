from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QMargins, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from ...app.layout import CompanionLayoutManager, GeometryProvider
from ...core.layout import CompanionLayout
from ...core.models import (
    GameDisplaySpec,
    LayoutProfile,
    ScreenRect,
    WindowGeometry,
)
from ...infrastructure.windows_geometry import WindowsGeometryProvider


# A screen as Qt reports it: logical geometry plus its device pixel ratio.
QtScreenScale = tuple[ScreenRect, float]


class QtLogicalGeometryProvider:
    """Maps native (physical pixel) window geometry into Qt logical pixels.

    Qt runs per-monitor DPI aware, so Win32 reports RetroArch's rectangles in
    physical pixels while QWidget geometry is in device-independent pixels. At
    150% scaling a 1920x1080 panel would otherwise be placed 1.5x too far out.
    """

    def __init__(
        self,
        native: GeometryProvider,
        screens: Callable[[], tuple[QtScreenScale, ...]] | None = None,
    ) -> None:
        self._native = native
        self._screens = screens or _qt_screen_scales

    def retroarch_geometry(self) -> WindowGeometry | None:
        geometry = self._native.retroarch_geometry()
        if geometry is None:
            return None
        screen = _screen_for_native_rect(geometry.work_area, self._screens())
        if screen is None:
            return geometry
        return replace(
            geometry,
            window_rect=_native_to_logical(geometry.window_rect, screen),
            client_rect=_native_to_logical(geometry.client_rect, screen),
            work_area=_native_to_logical(geometry.work_area, screen),
            # Logical pixels are already scaled for the monitor's DPI.
            dpi=96,
        )

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        screen = _screen_for_logical_rect(rect, self._screens())
        native = rect if screen is None else _logical_to_native(rect, screen)
        return self._native.place_window(handle, native)


class QtGeometryTarget:
    def __init__(self, window: QWidget) -> None:
        self._window = window

    def available_work_area(self) -> ScreenRect:
        screen = self._window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return ScreenRect(0, 0, max(1, self._window.width()), max(1, self._window.height()))
        return _rect_from_qt(screen.availableGeometry())

    def set_geometry(self, rect: ScreenRect) -> None:
        handle = self._window.windowHandle()
        margins = handle.frameMargins() if handle is not None else QMargins()
        client = _client_rect_for_frame(rect, margins)
        self._window.setGeometry(
            client.left,
            client.top,
            client.width,
            client.height,
        )


class QtResponsiveLayoutManager(CompanionLayoutManager):
    def __init__(
        self,
        profile: LayoutProfile,
        geometry_provider: GeometryProvider | None = None,
    ) -> None:
        super().__init__(
            profile,
            QtLogicalGeometryProvider(
                geometry_provider or WindowsGeometryProvider()
            ),
        )

    def apply(
        self,
        target: QWidget,
        display: GameDisplaySpec,
        *,
        paused: bool = False,
    ) -> tuple[CompanionLayout, bool]:
        return super().apply(
            QtGeometryTarget(target),
            display,
            paused=paused,
        )


def _qt_screen_scales() -> tuple[QtScreenScale, ...]:
    return tuple(
        (_rect_from_qt(screen.geometry()), screen.devicePixelRatio())
        for screen in QGuiApplication.screens()
    )


def _rect_from_qt(rect: QRect) -> ScreenRect:
    return ScreenRect(
        rect.left(),
        rect.top(),
        rect.left() + rect.width(),
        rect.top() + rect.height(),
    )


# Qt keeps each screen's origin in native coordinates and scales distances
# from that origin by the screen's device pixel ratio.
def _native_screen_rect(screen: QtScreenScale) -> ScreenRect:
    logical, ratio = screen
    return ScreenRect(
        logical.left,
        logical.top,
        logical.left + round(logical.width * ratio),
        logical.top + round(logical.height * ratio),
    )


def _native_to_logical(rect: ScreenRect, screen: QtScreenScale) -> ScreenRect:
    logical, ratio = screen
    return _scale_from_origin(rect, logical.left, logical.top, 1 / ratio)


def _logical_to_native(rect: ScreenRect, screen: QtScreenScale) -> ScreenRect:
    logical, ratio = screen
    return _scale_from_origin(rect, logical.left, logical.top, ratio)


def _scale_from_origin(
    rect: ScreenRect, origin_x: int, origin_y: int, factor: float
) -> ScreenRect:
    return ScreenRect(
        origin_x + round((rect.left - origin_x) * factor),
        origin_y + round((rect.top - origin_y) * factor),
        origin_x + round((rect.right - origin_x) * factor),
        origin_y + round((rect.bottom - origin_y) * factor),
    )


def _screen_for_native_rect(
    rect: ScreenRect, screens: tuple[QtScreenScale, ...]
) -> QtScreenScale | None:
    return _best_screen(rect, screens, _native_screen_rect)


def _screen_for_logical_rect(
    rect: ScreenRect, screens: tuple[QtScreenScale, ...]
) -> QtScreenScale | None:
    return _best_screen(rect, screens, lambda screen: screen[0])


def _best_screen(
    rect: ScreenRect,
    screens: tuple[QtScreenScale, ...],
    bounds: Callable[[QtScreenScale], ScreenRect],
) -> QtScreenScale | None:
    if not screens:
        return None

    def score(screen: QtScreenScale) -> tuple[int, int]:
        area = bounds(screen)
        width = max(0, min(rect.right, area.right) - max(rect.left, area.left))
        height = max(0, min(rect.bottom, area.bottom) - max(rect.top, area.top))
        dx = (rect.left + rect.right) - (area.left + area.right)
        dy = (rect.top + rect.bottom) - (area.top + area.bottom)
        return width * height, -(dx * dx + dy * dy)

    return max(screens, key=score)


def _client_rect_for_frame(rect: ScreenRect, margins: QMargins) -> ScreenRect:
    left = rect.left + margins.left()
    top = rect.top + margins.top()
    width = max(1, rect.width - margins.left() - margins.right())
    height = max(1, rect.height - margins.top() - margins.bottom())
    return ScreenRect(left, top, left + width, top + height)