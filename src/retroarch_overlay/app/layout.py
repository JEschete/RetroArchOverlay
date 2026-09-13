from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ..core.layout import CompanionLayout, compute_companion_layout
from ..core.models import (
    GameDisplaySpec,
    LayoutProfile,
    ScreenRect,
    WindowGeometry,
)
from ..infrastructure.windows_geometry import WindowsGeometryProvider


class GeometryProvider(Protocol):
    def retroarch_geometry(self) -> WindowGeometry | None: ...

    def place_window(self, handle: int, rect: ScreenRect) -> bool: ...


class CompanionGeometryTarget(Protocol):
    def available_work_area(self) -> ScreenRect: ...

    def set_geometry(self, rect: ScreenRect) -> None: ...


class CompanionLayoutManager:
    def __init__(
        self,
        profile: LayoutProfile,
        geometry_provider: GeometryProvider | None = None,
    ) -> None:
        self.profile = profile
        self._provider = geometry_provider or WindowsGeometryProvider()
        self.current: CompanionLayout | None = None
        self._original_window: tuple[int, ScreenRect] | None = None
        self._managed_target: tuple[int, ScreenRect] | None = None

    def apply(
        self,
        target: CompanionGeometryTarget,
        display: GameDisplaySpec,
        *,
        paused: bool = False,
    ) -> tuple[CompanionLayout, bool]:
        geometry = self._provider.retroarch_geometry()
        work_area = geometry.work_area if geometry is not None else target.available_work_area()
        dpi = geometry.dpi if geometry is not None else 96
        profile = replace(
            self.profile,
            rail_width=max(280, round(self.profile.rail_width * dpi / 96)),
        )
        if profile.mode == "auto" and not paused:
            if geometry is None:
                automatic_mode = "overlay"
            elif geometry.resizable and profile.manage_retroarch_window:
                automatic_mode = "rail"
            elif (
                geometry.client_rect.width >= geometry.work_area.width * 0.9
                and geometry.client_rect.height >= geometry.work_area.height * 0.9
            ):
                automatic_mode = "dual-strips"
            else:
                automatic_mode = "overlay"
            profile = replace(profile, mode=automatic_mode)
        layout = compute_companion_layout(work_area, display, profile, paused=paused)
        if layout.mode == "dual-strips" and layout.primary_panel.width < 140:
            profile = replace(profile, mode="overlay")
            layout = compute_companion_layout(work_area, display, profile, paused=paused)
        changed = layout != self.current
        self.current = layout

        should_manage = (
            geometry is not None
            and geometry.resizable
            and profile.manage_retroarch_window
            and layout.mode == "rail"
        )
        if should_manage:
            if self._original_window is None or self._original_window[0] != geometry.handle:
                self._original_window = (geometry.handle, geometry.window_rect)
                self._managed_target = None
            outer_rect = _outer_rect_for_client(layout.game_region, geometry)
            managed_target = (geometry.handle, outer_rect)
            if self._managed_target != managed_target and self._provider.place_window(
                geometry.handle, outer_rect
            ):
                self._managed_target = managed_target
        elif self._managed_target is not None:
            self.restore_retroarch_window()

        if changed:
            target.set_geometry(layout.primary_panel)
        return layout, changed

    def restore_retroarch_window(self) -> None:
        if self._original_window is not None:
            handle, rect = self._original_window
            self._provider.place_window(handle, rect)
        self._original_window = None
        self._managed_target = None

    def deactivate(self) -> None:
        self.restore_retroarch_window()
        self.current = None

    def close(self) -> None:
        self.restore_retroarch_window()


def _outer_rect_for_client(
    client_target: ScreenRect,
    geometry: WindowGeometry,
) -> ScreenRect:
    window = geometry.window_rect
    client = geometry.client_rect
    return ScreenRect(
        client_target.left - (client.left - window.left),
        client_target.top - (client.top - window.top),
        client_target.right + (window.right - client.right),
        client_target.bottom + (window.bottom - client.bottom),
    )