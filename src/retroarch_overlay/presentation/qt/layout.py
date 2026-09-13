from __future__ import annotations

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
        self._window.setGeometry(rect.left, rect.top, rect.width, rect.height)


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