from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from ..core.models import ScreenRect, WindowGeometry


class _Rect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class _Point(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _Rect),
        ("rcWork", _Rect),
        ("dwFlags", wintypes.DWORD),
    )


class WindowsGeometryProvider:
    def retroarch_geometry(self) -> WindowGeometry | None:
        if os.name != "nt":
            return None
        user32 = ctypes.windll.user32
        handle = self._find_retroarch_window(user32)
        if not handle:
            return None
        window_rect = _Rect()
        client_rect = _Rect()
        if not user32.GetWindowRect(handle, ctypes.byref(window_rect)):
            return None
        if not user32.GetClientRect(handle, ctypes.byref(client_rect)):
            return None
        origin = _Point(client_rect.left, client_rect.top)
        opposite = _Point(client_rect.right, client_rect.bottom)
        if not user32.ClientToScreen(handle, ctypes.byref(origin)):
            return None
        if not user32.ClientToScreen(handle, ctypes.byref(opposite)):
            return None
        monitor = user32.MonitorFromWindow(handle, 2)
        monitor_info = _MonitorInfo()
        monitor_info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return None
        dpi = 96
        get_dpi = getattr(user32, "GetDpiForWindow", None)
        if get_dpi is not None:
            dpi = int(get_dpi(handle)) or 96
        style = int(user32.GetWindowLongW(handle, -16))
        return WindowGeometry(
            int(handle),
            _screen_rect(window_rect),
            ScreenRect(origin.x, origin.y, opposite.x, opposite.y),
            _screen_rect(monitor_info.rcWork),
            dpi,
            bool(style & 0x00040000),
        )

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        if os.name != "nt" or not handle:
            return False
        flags = 0x0004 | 0x0010
        return bool(
            ctypes.windll.user32.SetWindowPos(
                handle,
                0,
                rect.left,
                rect.top,
                rect.width,
                rect.height,
                flags,
            )
        )

    @staticmethod
    def _find_retroarch_window(user32: object) -> int:
        matches: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(handle: int, _parameter: int) -> bool:
            if not user32.IsWindowVisible(handle):  # type: ignore[attr-defined]
                return True
            class_name = ctypes.create_unicode_buffer(256)
            title = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(handle, class_name, len(class_name))  # type: ignore[attr-defined]
            user32.GetWindowTextW(handle, title, len(title))  # type: ignore[attr-defined]
            if _is_retroarch_window(class_name.value, title.value):
                matches.append(int(handle))
                return False
            return True

        callback = callback_type(visit)
        user32.EnumWindows(callback, 0)  # type: ignore[attr-defined]
        return matches[0] if matches else 0


def _screen_rect(value: _Rect) -> ScreenRect:
    return ScreenRect(value.left, value.top, value.right, value.bottom)


def _is_retroarch_window(class_name: str, title: str) -> bool:
    normalized_class = class_name.strip().casefold()
    normalized_title = title.strip().casefold()
    if "overlay" in normalized_title:
        return False
    return normalized_class == "retroarch" or normalized_title == "retroarch"