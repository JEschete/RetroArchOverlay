from dataclasses import dataclass

from .models import GameDisplaySpec, LayoutProfile, PanelSection, ScreenRect


@dataclass(frozen=True, slots=True)
class CompanionLayout:
    mode: str
    game_region: ScreenRect
    game_viewport: ScreenRect
    primary_panel: ScreenRect
    secondary_panel: ScreenRect | None = None


def sections_for_role(
    sections: tuple[PanelSection, ...], role: str
) -> tuple[PanelSection, ...]:
    # "all" is the default rail view: every section in one scroll, which is
    # how the panel behaved before the tabs became a filter.
    if role == "all":
        return sections
    specialized = any(
        section.role in {"area", "party", "goals", "urgent"}
        for section in sections
    )
    if not specialized:
        return sections
    accepted = {
        "area": {"area", "context", "urgent"},
        "party": {"party", "urgent"},
        "goals": {"goals", "urgent"},
    }.get(role, {"area", "context", "urgent"})
    return tuple(section for section in sections if section.role in accepted)


def compute_companion_layout(
    work_area: ScreenRect,
    display: GameDisplaySpec,
    profile: LayoutProfile,
    *,
    paused: bool = False,
) -> CompanionLayout:
    mode = _resolved_mode(profile.mode, paused)
    if mode == "pause-drawer":
        drawer_width = max(320, round(work_area.width * 0.6))
        panel = ScreenRect(
            work_area.right - drawer_width,
            work_area.top,
            work_area.right,
            work_area.bottom,
        )
        return CompanionLayout(
            mode,
            work_area,
            _fit_viewport(work_area, display, profile.game_scaling),
            panel,
        )
    if mode == "dual-strips":
        viewport = _fit_viewport(work_area, display, profile.game_scaling)
        left = ScreenRect(work_area.left, work_area.top, viewport.left, work_area.bottom)
        right = ScreenRect(viewport.right, work_area.top, work_area.right, work_area.bottom)
        primary, secondary = (right, left) if profile.rail_side == "right" else (left, right)
        return CompanionLayout(mode, work_area, viewport, primary, secondary)
    if mode == "overlay":
        width = min(max(profile.rail_width, 280), work_area.width)
        panel = _side_rect(work_area, width, profile.rail_side)
        return CompanionLayout(
            mode,
            work_area,
            _fit_viewport(work_area, display, profile.game_scaling),
            panel,
        )

    rail_width = min(max(profile.rail_width, 280), max(work_area.width - 320, 280))
    panel = _side_rect(work_area, rail_width, profile.rail_side)
    if profile.rail_side == "left":
        game_region = ScreenRect(panel.right, work_area.top, work_area.right, work_area.bottom)
    else:
        game_region = ScreenRect(work_area.left, work_area.top, panel.left, work_area.bottom)
    viewport = _fit_viewport(game_region, display, profile.game_scaling)
    return CompanionLayout("rail", game_region, viewport, panel)


def _resolved_mode(mode: str, paused: bool) -> str:
    if paused and mode in {"auto", "pause-drawer"}:
        return "pause-drawer"
    if mode == "auto":
        return "rail"
    if mode not in {"rail", "dual-strips", "pause-drawer", "overlay"}:
        return "overlay"
    return mode


def _side_rect(area: ScreenRect, width: int, side: str) -> ScreenRect:
    if side == "left":
        return ScreenRect(area.left, area.top, area.left + width, area.bottom)
    return ScreenRect(area.right - width, area.top, area.right, area.bottom)


def _fit_viewport(
    area: ScreenRect,
    display: GameDisplaySpec,
    profile_scaling: str,
) -> ScreenRect:
    if display.native_width <= 0 or display.native_height <= 0:
        return area
    scaling = display.scaling if profile_scaling == "auto" else profile_scaling
    if scaling == "integer":
        maximum = min(
            area.width // display.native_width,
            area.height // display.native_height,
        )
        scale = max(1, maximum)
        if display.preferred_integer_scale is not None:
            scale = min(scale, max(1, display.preferred_integer_scale))
        width = min(area.width, display.native_width * scale)
        height = min(area.height, display.native_height * scale)
    else:
        scale = min(
            area.width / display.native_width,
            area.height / display.native_height,
        )
        width = max(1, round(display.native_width * scale))
        height = max(1, round(display.native_height * scale))
    left = area.left + (area.width - width) // 2
    top = area.top + (area.height - height) // 2
    return ScreenRect(left, top, left + width, top + height)