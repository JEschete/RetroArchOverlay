from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from ...core.layout import constrain_window_rect
from ...core.models import ScreenRect


QT_MAIN_GEOMETRY_KEY = "main-qt"
LEGACY_MAIN_GEOMETRY_KEY = "main"
LEGACY_NATIVE_GEOMETRY_KEY = "main-native"


class WindowStateSettings(Protocol):
    def window_geometry(self, key: str) -> ScreenRect | None: ...

    def save_window_geometry(self, key: str, rect: ScreenRect) -> None: ...


@dataclass(frozen=True, slots=True)
class WindowPresentation:
    opacity: float = 1.0
    always_on_top: bool = False
    frameless: bool = False
    show_in_taskbar: bool = True

    def __post_init__(self) -> None:
        if not 0.3 <= self.opacity <= 1.0:
            raise ValueError("Opacity must be between 0.3 and 1.0")


def apply_window_presentation(
    window: QWidget,
    presentation: WindowPresentation,
) -> None:
    was_visible = window.isVisible()
    was_active = window.isActiveWindow()
    focused = window.focusWidget()
    geometry = window.geometry()
    window.setWindowFlag(
        Qt.WindowType.WindowStaysOnTopHint,
        presentation.always_on_top,
    )
    window.setWindowFlag(
        Qt.WindowType.FramelessWindowHint,
        presentation.frameless,
    )
    window.setWindowFlag(
        Qt.WindowType.Tool,
        not presentation.show_in_taskbar,
    )
    window.setWindowOpacity(presentation.opacity)
    if was_visible:
        window.show()
    window.setGeometry(geometry)
    if was_visible and (was_active or focused is not None):
        window.raise_()
        window.activateWindow()
    if focused is not None:
        QTimer.singleShot(
            0,
            focused,
            lambda: focused.setFocus(Qt.FocusReason.OtherFocusReason),
        )


def legacy_window_rect(settings: WindowStateSettings) -> ScreenRect | None:
    qt_rect = settings.window_geometry(QT_MAIN_GEOMETRY_KEY)
    if qt_rect is not None:
        return qt_rect
    placement = settings.window_geometry(LEGACY_MAIN_GEOMETRY_KEY)
    native_size = settings.window_geometry(LEGACY_NATIVE_GEOMETRY_KEY)
    if placement is not None and native_size is not None:
        return ScreenRect(
            placement.left,
            placement.top,
            placement.left + native_size.width,
            placement.top + native_size.height,
        )
    return placement or native_size


def restore_window_geometry(
    window: QWidget,
    settings: WindowStateSettings,
    *,
    work_areas: tuple[ScreenRect, ...] | None = None,
) -> ScreenRect | None:
    stored = legacy_window_rect(settings)
    if stored is None:
        return None
    areas = work_areas if work_areas is not None else _qt_work_areas()
    restored = constrain_window_rect(stored, areas)
    window.setGeometry(_qrect(restored))
    return restored


def restore_named_window_geometry(
    window: QWidget,
    settings: WindowStateSettings,
    key: str,
    *,
    fallback_keys: tuple[str, ...] = (),
    work_areas: tuple[ScreenRect, ...] | None = None,
) -> ScreenRect | None:
    stored = settings.window_geometry(key)
    if stored is None:
        stored = next(
            (
                candidate
                for fallback_key in fallback_keys
                if (candidate := settings.window_geometry(fallback_key)) is not None
            ),
            None,
        )
    if stored is None:
        return None
    areas = work_areas if work_areas is not None else _qt_work_areas()
    restored = constrain_window_rect(stored, areas)
    window.setGeometry(_qrect(restored))
    return restored


def save_window_geometry(
    window: QWidget,
    settings: WindowStateSettings,
) -> ScreenRect | None:
    geometry = (
        window.normalGeometry()
        if window.isMaximized() or window.isFullScreen()
        else window.geometry()
    )
    rect = _screen_rect(geometry)
    return save_window_rect(settings, rect)


def save_window_rect(
    settings: WindowStateSettings,
    rect: ScreenRect,
) -> ScreenRect | None:
    if rect.width <= 1 or rect.height <= 1:
        return None
    settings.save_window_geometry(QT_MAIN_GEOMETRY_KEY, rect)
    return rect


def save_named_window_geometry(
    window: QWidget,
    settings: WindowStateSettings,
    key: str,
) -> ScreenRect | None:
    geometry = (
        window.normalGeometry()
        if window.isMaximized() or window.isFullScreen()
        else window.geometry()
    )
    rect = _screen_rect(geometry)
    if rect.width <= 1 or rect.height <= 1:
        return None
    settings.save_window_geometry(key, rect)
    return rect


def _qt_work_areas() -> tuple[ScreenRect, ...]:
    return tuple(
        _screen_rect(screen.availableGeometry())
        for screen in QGuiApplication.screens()
    )


def _screen_rect(rect: QRect) -> ScreenRect:
    return ScreenRect(rect.left(), rect.top(), rect.left() + rect.width(), rect.top() + rect.height())


def _qrect(rect: ScreenRect) -> QRect:
    return QRect(rect.left, rect.top, rect.width, rect.height)