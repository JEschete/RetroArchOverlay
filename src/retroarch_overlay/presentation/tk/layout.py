from __future__ import annotations

from typing import Protocol

from ...app.layout import CompanionLayoutManager
from ...core.layout import CompanionLayout
from ...core.models import GameDisplaySpec, LayoutProfile, ScreenRect
from ...infrastructure.windows_geometry import WindowsGeometryProvider


class TkGeometryTarget(Protocol):
    def geometry(self, value: str) -> object: ...

    def winfo_screenwidth(self) -> int: ...

    def winfo_screenheight(self) -> int: ...


class _TkTargetAdapter:
    def __init__(self, target: TkGeometryTarget) -> None:
        self._target = target

    def available_work_area(self) -> ScreenRect:
        return ScreenRect(
            0,
            0,
            self._target.winfo_screenwidth(),
            self._target.winfo_screenheight(),
        )

    def set_geometry(self, rect: ScreenRect) -> None:
        self._target.geometry(
            f"{rect.width}x{rect.height}{rect.left:+d}{rect.top:+d}"
        )


class ResponsiveLayoutManager(CompanionLayoutManager):
    def __init__(
        self,
        profile: LayoutProfile,
        geometry_provider: WindowsGeometryProvider | None = None,
    ) -> None:
        super().__init__(profile, geometry_provider)

    def apply(
        self,
        target: TkGeometryTarget,
        display: GameDisplaySpec,
        *,
        paused: bool = False,
    ) -> tuple[CompanionLayout, bool]:
        return super().apply(
            _TkTargetAdapter(target),
            display,
            paused=paused,
        )
