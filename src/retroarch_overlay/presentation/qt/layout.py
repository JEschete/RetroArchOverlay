from __future__ import annotations

from PySide6.QtCore import QMargins
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from ...app.layout import CompanionLayoutManager, GeometryProvider
from ...core.layout import CompanionLayout
from ...core.models import GameDisplaySpec, LayoutProfile, ScreenRect


class QtGeometryTarget:
    def __init__(self, window: QWidget) -> None:
        self._window = window

    def available_work_area(self) -> ScreenRect:
        screen = self._window.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return ScreenRect(0, 0, max(1, self._window.width()), max(1, self._window.height()))
        geometry = screen.availableGeometry()
        return ScreenRect(
            geometry.left(),
            geometry.top(),
            geometry.left() + geometry.width(),
            geometry.top() + geometry.height(),
        )

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
        super().__init__(profile, geometry_provider)

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


def _client_rect_for_frame(rect: ScreenRect, margins: QMargins) -> ScreenRect:
    left = rect.left + margins.left()
    top = rect.top + margins.top()
    width = max(1, rect.width - margins.left() - margins.right())
    height = max(1, rect.height - margins.top() - margins.bottom())
    return ScreenRect(left, top, left + width, top + height)