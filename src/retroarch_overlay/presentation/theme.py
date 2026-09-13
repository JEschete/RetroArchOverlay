from types import MappingProxyType
from typing import Mapping

from ..infrastructure.accessibility import (
    contrast_ratio,
    windows_dark_mode_enabled,
    windows_high_contrast_enabled,
)


THEME_PALETTES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "light": MappingProxyType(
            {
                "background": "#f4f1e8",
                "surface": "#e6e1d4",
                "foreground": "#20251f",
                "muted": "#687064",
                "accent": "#bb3e2f",
                "divider": "#cbc8bd",
                "alert_background": "#ffe9e5",
                "alert_foreground": "#9d1717",
                "header_background": "#20251f",
                "header_foreground": "#ffffff",
                "success": "#23733f",
                "warning": "#855700",
                "danger": "#b3261e",
                "track": "#d8d4c8",
            }
        ),
        "dark": MappingProxyType(
            {
                "background": "#191d1a",
                "surface": "#242923",
                "foreground": "#e6e4dc",
                "muted": "#9aa294",
                "accent": "#e0705e",
                "divider": "#3a4038",
                "alert_background": "#3c211d",
                "alert_foreground": "#ff9c8a",
                "header_background": "#10130f",
                "header_foreground": "#f2f0e8",
                "success": "#63c78a",
                "warning": "#e0ab4e",
                "danger": "#ef6e64",
                "track": "#333831",
            }
        ),
        "high-contrast": MappingProxyType(
            {
                "background": "#ffffff",
                "surface": "#ffffff",
                "foreground": "#000000",
                "muted": "#333333",
                "accent": "#0046b8",
                "divider": "#000000",
                "alert_background": "#ffffff",
                "alert_foreground": "#a00000",
                "header_background": "#000000",
                "header_foreground": "#ffffff",
                "success": "#00600f",
                "warning": "#7a4f00",
                "danger": "#a00000",
                "track": "#bbbbbb",
            }
        ),
    }
)

THEME_CHOICES = ("auto", "light", "dark", "high-contrast")


def resolve_theme(preference: str) -> str:
    if preference in THEME_PALETTES:
        return preference
    if windows_high_contrast_enabled():
        return "high-contrast"
    return "dark" if windows_dark_mode_enabled() else "light"


def progress_bar_color(
    fraction: float, palette: Mapping[str, str], explicit: str = ""
) -> str:
    if explicit:
        return palette.get(explicit, explicit)
    if fraction > 0.5:
        return palette["success"]
    if fraction > 0.2:
        return palette["warning"]
    return palette["danger"]


def accessible_text_color(
    background: str,
    requested: str,
    minimum_ratio: float = 4.5,
) -> str:
    if contrast_ratio(requested, background) >= minimum_ratio:
        return requested
    candidates = ("#000000", "#ffffff")
    return max(candidates, key=lambda color: contrast_ratio(color, background))