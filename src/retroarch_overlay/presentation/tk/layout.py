from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ...core.layout import CompanionLayout, compute_companion_layout
from ...core.models import GameDisplaySpec, LayoutProfile, ScreenRect
from ...infrastructure.windows_geometry import WindowsGeometryProvider


class TkGeometryTarget(Protocol):
    def geometry(self, value: str) -> object: ...

    def winfo_screenwidth(self) -> int: ...

    def winfo_screenheight(self) -> int: ...


class ResponsiveLayoutManager:
    def __init__(
        self,
        profile: LayoutProfile,
        geometry_provider: WindowsGeometryProvider | None = None,
    ) -> None:
        self.profile = profile
        self._provider = geometry_provider or WindowsGeometryProvider()
        self.current: CompanionLayout | None = None
        self._original_window: tuple[int, ScreenRect] | None = None
        self._managed_target: ScreenRect | None = None

    def apply(
        self,
        target: TkGeometryTarget,
        display: GameDisplaySpec,
        *,
        paused: bool = False,
    ) -> tuple[CompanionLayout, bool]:
        geometry = self._provider.retroarch_geometry()
        work_area = (
            geometry.work_area
            if geometry is not None
            else ScreenRect(0, 0, target.winfo_screenwidth(), target.winfo_screenheight())
        )
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
        if (
            layout.mode == "dual-strips"
            and layout.primary_panel.width < 140
        ):
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
            if self._original_window is None:
                self._original_window = (geometry.handle, geometry.window_rect)
            outer_rect = _outer_rect_for_client(layout.game_region, geometry)
            if self._managed_target != outer_rect:
                self._provider.place_window(geometry.handle, outer_rect)
                self._managed_target = outer_rect
        elif self._managed_target is not None:
            self.restore_retroarch_window()

        panel = layout.primary_panel
        target.geometry(
            f"{panel.width}x{panel.height}{panel.left:+d}{panel.top:+d}"
        )
        return layout, changed

    def restore_retroarch_window(self) -> None:
        if self._original_window is not None:
            handle, rect = self._original_window
            self._provider.place_window(handle, rect)
        self._managed_target = None

    def close(self) -> None:
        self.restore_retroarch_window()


def _outer_rect_for_client(client_target: ScreenRect, geometry: object) -> ScreenRect:
    window = geometry.window_rect
    client = geometry.client_rect
    return ScreenRect(
        client_target.left - (client.left - window.left),
        client_target.top - (client.top - window.top),
        client_target.right + (window.right - client.right),
        client_target.bottom + (window.bottom - client.bottom),
    )