from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Protocol

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeyEvent,
    QKeySequence,
    QMoveEvent,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...app.controller import ControllerEvent, DiagnosticCode, OverlayDiagnostic
from ...app.notifications import AlertNotification, AlertTracker, urgent_summary
from ...core.map import record_map_path
from ...core.models import (
    LayoutProfile,
    MapDocument,
    MapOverlay,
    MapPosition,
    OverlaySnapshot,
    RetroArchStatus,
    ScreenRect,
)
from .controller_bridge import ControllerEventBridge, ControllerEventSource
from .layout import QtResponsiveLayoutManager
from .map_window import QtMapWindow
from .notifications import QtToastQueue
from .overlay_settings_dialog import QtOverlaySettingsDialog
from .panel_document_view import PanelDocumentView
from .secondary_window import QtSecondaryPanelWindow
from .theme import apply_qt_theme
from .window_drag import QtWindowDragHandle
from ..theme import THEME_PALETTES
from .window_state import (
    WindowPresentation,
    WindowStateSettings,
    apply_window_presentation,
    restore_window_geometry,
    save_window_rect,
    save_window_geometry,
)


ROLE_NAMES = ("all", "area", "party", "goals")
MANAGED_PRIMARY_MODES = frozenset({"rail", "dual-strips", "pause-drawer"})
LOGGER = logging.getLogger(__name__)


class OverlaySettings(WindowStateSettings, Protocol):
    def theme(self) -> str: ...

    def overlay_opacity(self) -> float | None: ...

    def active_role(self, game: str) -> str | None: ...

    def save_active_role(self, game: str, role: str) -> None: ...

    def save_overlay_preferences(
        self,
        profile: LayoutProfile,
        theme: str,
        opacity: float,
    ) -> None: ...

    def layout_profile(self) -> LayoutProfile: ...

    def map_view_state(self, key: str) -> dict[str, object]: ...

    def save_map_view_state(self, key: str, state: dict[str, object]) -> None: ...

    def hero_paths(self, title: str) -> dict[str, list[tuple[int, int]]]: ...

    def save_hero_paths(
        self,
        title: str,
        paths: dict[str, list[tuple[int, int]]],
        limit: int = 20_000,
    ) -> None: ...


class OverlayEventSource(ControllerEventSource, Protocol):
    @property
    def content_key(self) -> tuple[str, str, str] | None: ...

    @property
    def last_status(self) -> RetroArchStatus | None: ...


class QtOverlayWindow(QMainWindow):
    def __init__(
        self,
        controller: OverlayEventSource,
        *,
        bridge_interval_ms: int = 100,
        theme: str | None = None,
        opacity: float = 1.0,
        settings: OverlaySettings | None = None,
        presentation: WindowPresentation | None = None,
        layout_manager: QtResponsiveLayoutManager | None = None,
        animate_map_objectives: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._settings = settings
        self._current_game = ""
        self._active_roles: dict[str, str] = {}
        self._closed = False
        self._collapsed = False
        self._applying_layout_geometry = True
        self._manual_layout_override = False
        self._last_snapshot: OverlaySnapshot | None = None
        self._last_content_scope = ""
        self._secondary_window: QtSecondaryPanelWindow | None = None
        self._map_document: MapDocument | None = None
        self._map_position: MapPosition | None = None
        self._map_overlays: tuple[MapOverlay, ...] = ()
        self._map_window: QtMapWindow | None = None
        self._minimap_window: QtMapWindow | None = None
        self._hero_paths: dict[str, list[tuple[int, int]]] = {}
        self._hero_paths_title = ""
        self._animate_map_objectives = animate_map_objectives
        self._alert_tracker = AlertTracker()
        self._settings_dialog: QtOverlaySettingsDialog | None = None
        self.setWindowTitle("RetroArch Overlay")
        self.setMinimumSize(280, 180)
        self.resize(360, 640)
        stored_opacity = settings.overlay_opacity() if settings is not None else None
        resolved_opacity = stored_opacity if stored_opacity is not None else opacity
        presentation = replace(
            presentation or WindowPresentation(always_on_top=True),
            opacity=resolved_opacity,
        )
        apply_window_presentation(self, presentation)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(central)

        self.header = QtWindowDragHandle(central)
        self.header.drag_started.connect(self._begin_manual_move)
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 8)
        header_layout.setSpacing(2)
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        self.game_label = QLabel("RETROARCH OVERLAY", self.header)
        self.game_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.game_label.setAccessibleDescription("Active game")
        title_layout.addWidget(self.game_label, 1)
        self.settings_button = QPushButton("Settings", self.header)
        self.settings_button.setAccessibleName("Open overlay settings")
        self.settings_button.clicked.connect(self._show_overlay_settings)
        title_layout.addWidget(self.settings_button)
        self.location_label = QLabel("Waiting for RetroArch", self.header)
        self.location_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.location_label.setWordWrap(True)
        self.location_label.setAccessibleDescription("Current location or status")
        header_layout.addLayout(title_layout)
        header_layout.addWidget(self.location_label)
        layout.addWidget(self.header)

        self.controls = QFrame(central)
        controls_layout = QHBoxLayout(self.controls)
        controls_layout.setContentsMargins(8, 4, 8, 4)
        controls_layout.setSpacing(4)
        self.role_buttons: dict[str, QPushButton] = {}
        for role in ROLE_NAMES:
            button = QPushButton(role.upper(), self.controls)
            button.setCheckable(True)
            button.setAccessibleName(f"Show {role} sections")
            button.clicked.connect(
                lambda _checked=False, selected=role: self._select_role(selected)
            )
            controls_layout.addWidget(button)
            self.role_buttons[role] = button
        self.role_buttons["all"].setChecked(True)
        self.hide_caught = QCheckBox("Hide completed", self.controls)
        self.hide_caught.toggled.connect(self._set_hide_caught)
        controls_layout.addWidget(self.hide_caught)
        self.map_button = QPushButton("Map", self.controls)
        self.map_button.setAccessibleName("Open map")
        self.map_button.clicked.connect(self._show_map)
        self.map_button.hide()
        controls_layout.addWidget(self.map_button)
        self.minimap_button = QPushButton("Minimap", self.controls)
        self.minimap_button.setAccessibleName("Open minimap")
        self.minimap_button.clicked.connect(self._show_minimap)
        self.minimap_button.hide()
        controls_layout.addWidget(self.minimap_button)
        self.controls.hide()
        layout.addWidget(self.controls)

        self.status_label = QLabel("Not connected", central)
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleDescription("Connection status")
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        self.urgent_strip = QFrame(central)
        self.urgent_strip.setObjectName("urgentSummary")
        self.urgent_strip.setAutoFillBackground(True)
        urgent_layout = QVBoxLayout(self.urgent_strip)
        urgent_layout.setContentsMargins(12, 6, 12, 6)
        self.urgent_label = QLabel(self.urgent_strip)
        self.urgent_label.setObjectName("urgentSummaryLabel")
        self.urgent_label.setWordWrap(True)
        self.urgent_label.setAccessibleDescription("Urgent summary")
        urgent_layout.addWidget(self.urgent_label)
        self.urgent_strip.hide()
        layout.addWidget(self.urgent_strip)

        self.document_view = PanelDocumentView(central)
        self.document_view.hide()
        layout.addWidget(self.document_view, 1)

        self.toast_queue = QtToastQueue(self)

        self.bridge = ControllerEventBridge(
            controller,
            poll_interval_ms=bridge_interval_ms,
            parent=self,
        )
        self.bridge.event_ready.connect(self.render_event)
        resolved_theme = theme or (settings.theme() if settings is not None else "light")
        self._theme_preference = resolved_theme
        self._overlay_opacity = resolved_opacity
        self._theme_name = self.set_theme(resolved_theme)
        profile = (
            settings.layout_profile()
            if settings is not None
            else LayoutProfile(mode="overlay", manage_retroarch_window=False)
        )
        self._layout_manager = layout_manager or QtResponsiveLayoutManager(profile)
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(500)
        self._layout_timer.timeout.connect(self._refresh_layout)
        self._map_shortcut = QShortcut(QKeySequence("Alt+M"), self)
        self._map_shortcut.activated.connect(self._show_map)
        self._minimap_shortcut = QShortcut(QKeySequence("Alt+N"), self)
        self._minimap_shortcut.activated.connect(self._show_minimap)
        if settings is not None:
            restore_window_geometry(self, settings)
        self._unmanaged_geometry = _widget_rect(self)
        self._applying_layout_geometry = False

    def start(self) -> None:
        self.show()
        self.bridge.start()
        self._layout_timer.start()

    @property
    def theme_name(self) -> str:
        return self._theme_name

    def set_theme(self, preference: str) -> str:
        self._theme_preference = preference
        name = apply_qt_theme(self, preference)
        colors = THEME_PALETTES[name]
        alert_palette = self.urgent_strip.palette()
        alert_palette.setColor(
            alert_palette.ColorRole.Window,
            QColor(colors["alert_background"]),
        )
        alert_palette.setColor(
            alert_palette.ColorRole.WindowText,
            QColor(colors["alert_foreground"]),
        )
        self.urgent_strip.setPalette(alert_palette)
        self.urgent_label.setPalette(alert_palette)
        self.toast_queue.set_theme(name)
        self.document_view.set_theme(name)
        if self._secondary_window is not None:
            self._secondary_window.set_theme(name)
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.set_theme(name)
        self._theme_name = name
        return name

    @Slot(object)
    def render_event(self, event: ControllerEvent) -> None:
        if isinstance(event, OverlaySnapshot):
            self._render_snapshot(event)
            return
        if isinstance(event, OverlayDiagnostic):
            self._render_diagnostic(event)
            return
        self._render_diagnostic(
            OverlayDiagnostic(
                code=DiagnosticCode.INTERNAL_ERROR,
                title="Overlay error",
                message=f"Unsupported controller event: {type(event).__name__}",
            )
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closed:
            self._closed = True
            self._layout_timer.stop()
            self.bridge.stop()
            self.toast_queue.close()
            if self._settings_dialog is not None:
                self._settings_dialog.close()
                self._settings_dialog = None
            managed = (
                self._layout_manager.current is not None
                and self._layout_manager.current.mode in MANAGED_PRIMARY_MODES
            )
            self._layout_manager.close()
            self._save_hero_paths()
            self._destroy_map_windows()
            if self._secondary_window is not None:
                self._secondary_window.close()
                self._secondary_window = None
            if self._settings is not None:
                try:
                    if managed or self._collapsed:
                        save_window_rect(self._settings, self._unmanaged_geometry)
                    else:
                        save_window_geometry(self, self._settings)
                except (OSError, ValueError) as error:
                    LOGGER.warning("Unable to save Qt window geometry: %s", error)
        event.accept()
        super().closeEvent(event)

    def _render_snapshot(self, snapshot: OverlaySnapshot) -> None:
        content_scope = _content_scope(self._controller.content_key, snapshot.game)
        if snapshot == self._last_snapshot and content_scope == self._last_content_scope:
            return
        if self._current_game and self._current_game != snapshot.game:
            self._active_roles[self._current_game] = self.document_view.state.active_role
        self._current_game = snapshot.game
        self._last_snapshot = snapshot
        self._last_content_scope = content_scope
        self._sync_map_tools(snapshot)
        self._set_urgent_summary(urgent_summary(snapshot))
        self.toast_queue.enqueue(self._alert_tracker.observe(snapshot, content_scope))
        self.document_view.set_snapshot(
            snapshot,
            content_scope=content_scope,
        )
        role = self._active_roles.get(snapshot.game)
        if role is None and self._settings is not None:
            role = self._settings.active_role(snapshot.game)
        if role not in ROLE_NAMES:
            role = "all"
        self.document_view.set_active_role(role)
        self._sync_role_buttons(role)
        specialized = any(
            section.role in {"area", "party", "goals", "urgent"}
            for section in snapshot.sections
        )
        map_available = self._map_document is not None and self._map_position is not None
        self.controls.setVisible(
            not self._collapsed
            and (specialized or snapshot.supports_caught_filter or map_available)
        )
        self.hide_caught.setVisible(snapshot.supports_caught_filter)
        self.map_button.setVisible(map_available)
        self.minimap_button.setVisible(map_available)
        self.game_label.setText(snapshot.game.upper())
        self.location_label.setText(snapshot.location)
        self.status_label.setText("Live · read-only")
        self.document_view.setVisible(not self._collapsed)
        self._refresh_layout()
        self._sync_role_button_visibility(snapshot, specialized)

    def _render_diagnostic(self, diagnostic: OverlayDiagnostic) -> None:
        self._last_snapshot = None
        self._last_content_scope = ""
        self._clear_map_tools()
        self._layout_manager.deactivate()
        self._hide_secondary_window()
        self._set_urgent_summary(None)
        self.toast_queue.clear()
        self.location_label.setText(diagnostic.title)
        self.status_label.setText(diagnostic.message)
        self.controls.hide()
        self.document_view.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_Escape:
                self._toggle_collapsed()
                event.accept()
                return
            if event.key() == Qt.Key.Key_PageUp:
                self._scroll_page(-1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_PageDown:
                self._scroll_page(1)
                event.accept()
                return
        role_keys = {
            Qt.Key.Key_1: "all",
            Qt.Key.Key_2: "area",
            Qt.Key.Key_3: "party",
            Qt.Key.Key_4: "goals",
        }
        role = role_keys.get(event.key())
        if (
            role is not None
            and event.modifiers()
            in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
            and not self._collapsed
            and self.role_buttons[role].isVisible()
        ):
            self._select_role(role)
            event.accept()
            return
        super().keyPressEvent(event)

    def _select_role(self, role: str) -> None:
        if role not in ROLE_NAMES:
            return
        self.document_view.set_active_role(role)
        if self._current_game:
            self._active_roles[self._current_game] = role
            if self._settings is not None:
                try:
                    self._settings.save_active_role(self._current_game, role)
                except (OSError, ValueError) as error:
                    LOGGER.warning("Unable to save Qt active role: %s", error)
        self._sync_role_buttons(role)

    def _sync_role_buttons(self, role: str) -> None:
        for name, button in self.role_buttons.items():
            button.setChecked(name == role)

    def _set_hide_caught(self, hidden: bool) -> None:
        self.document_view.set_hide_caught(hidden)

    def _show_overlay_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = QtOverlaySettingsDialog(
            self._layout_manager.profile,
            self._theme_preference,
            self._overlay_opacity,
            self._save_overlay_settings,
            self,
        )
        self._settings_dialog = dialog
        dialog.destroyed.connect(
            lambda _object=None, candidate=dialog: self._forget_settings_dialog(
                candidate
            )
        )
        dialog.show()

    def _forget_settings_dialog(self, dialog: QtOverlaySettingsDialog) -> None:
        if self._settings_dialog is dialog:
            self._settings_dialog = None

    def _save_overlay_settings(
        self,
        profile: LayoutProfile,
        theme: str,
        opacity: float,
    ) -> None:
        if self._settings is not None:
            self._settings.save_overlay_preferences(profile, theme, opacity)
        self._manual_layout_override = False
        self._layout_manager.deactivate()
        self._layout_manager.profile = profile
        self._overlay_opacity = opacity
        self.setWindowOpacity(opacity)
        self.set_theme(theme)
        self._refresh_layout()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._begin_manual_move()
        self._remember_unmanaged_geometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._begin_manual_move()
        self._remember_unmanaged_geometry()
        self.toast_queue.reposition()

    def _begin_manual_move(self) -> None:
        if self._applying_layout_geometry or not hasattr(self, "_layout_manager"):
            return
        current = self._layout_manager.current
        if current is None or current.mode not in MANAGED_PRIMARY_MODES:
            return
        self._layout_manager.deactivate()
        self._manual_layout_override = True
        self._hide_secondary_window()

    def _toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self._applying_layout_geometry = True
        try:
            if self._collapsed:
                self.controls.hide()
                self.status_label.hide()
                self.urgent_strip.hide()
                self.document_view.hide()
                self._hide_secondary_window()
                collapsed_height = self.header.sizeHint().height()
                self.setMinimumHeight(collapsed_height)
                self.setMaximumHeight(collapsed_height)
                self.resize(self.width(), collapsed_height)
                return
            self.setMaximumHeight(16_777_215)
            self.setMinimumHeight(180)
            self.setGeometry(
                self._unmanaged_geometry.left,
                self._unmanaged_geometry.top,
                self._unmanaged_geometry.width,
                self._unmanaged_geometry.height,
            )
            self.status_label.show()
            snapshot = self._last_snapshot
            if snapshot is not None:
                specialized = any(
                    section.role in {"area", "party", "goals", "urgent"}
                    for section in snapshot.sections
                )
                map_available = (
                    self._map_document is not None and self._map_position is not None
                )
                self.controls.setVisible(
                    specialized or snapshot.supports_caught_filter or map_available
                )
                self.document_view.show()
                self._set_urgent_summary(urgent_summary(snapshot))
        finally:
            self._applying_layout_geometry = False
        self._refresh_layout()

    def _scroll_page(self, direction: int) -> None:
        if self._collapsed:
            return
        scroll_bar = self.document_view.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() + direction * scroll_bar.pageStep())

    def _set_urgent_summary(self, summary: AlertNotification | None) -> None:
        if summary is None:
            self.urgent_label.clear()
            self.urgent_strip.hide()
            return
        text = summary.title.upper()
        if summary.detail:
            text = f"{text} · {summary.detail}"
        self.urgent_label.setText(text)
        self.urgent_label.setAccessibleName(
            summary.title + (f": {summary.detail}" if summary.detail else "")
        )
        self.urgent_strip.setVisible(not self._collapsed)

    def _remember_unmanaged_geometry(self) -> None:
        if self._applying_layout_geometry:
            return
        current = self._layout_manager.current
        if current is None or current.mode not in MANAGED_PRIMARY_MODES:
            rect = _widget_rect(self)
            if self._collapsed:
                self._unmanaged_geometry = ScreenRect(
                    rect.left,
                    rect.top,
                    rect.left + self._unmanaged_geometry.width,
                    rect.top + self._unmanaged_geometry.height,
                )
                return
            if rect.width > 1 and rect.height > 1:
                self._unmanaged_geometry = rect

    def _refresh_layout(self) -> None:
        snapshot = self._last_snapshot
        if self._collapsed:
            self._hide_secondary_window()
            return
        if self._manual_layout_override:
            self._hide_secondary_window()
            return
        if snapshot is None or snapshot.display_spec is None:
            if self._layout_manager.current is not None:
                self._layout_manager.deactivate()
            self._hide_secondary_window()
            if snapshot is not None:
                self._sync_role_button_visibility(
                    snapshot,
                    any(
                        section.role in {"area", "party", "goals", "urgent"}
                        for section in snapshot.sections
                    ),
                )
            return
        previous = self._layout_manager.current
        if previous is None or previous.mode not in MANAGED_PRIMARY_MODES:
            self._unmanaged_geometry = _widget_rect(self)
        status = self._controller.last_status
        self._applying_layout_geometry = True
        try:
            layout, _ = self._layout_manager.apply(
                self,
                snapshot.display_spec,
                paused=status is not None and status.state == "PAUSED",
            )
        finally:
            self._applying_layout_geometry = False
        if layout.mode not in MANAGED_PRIMARY_MODES:
            self._unmanaged_geometry = _widget_rect(self)
        if layout.secondary_panel is None:
            self._hide_secondary_window()
        else:
            if self._secondary_window is None:
                self._secondary_window = QtSecondaryPanelWindow(
                    self,
                    theme=self._theme_name,
                )
            self._secondary_window.update_snapshot(
                snapshot,
                _content_scope(self._controller.content_key, snapshot.game),
                layout.secondary_panel,
            )
        self._sync_role_button_visibility(
            snapshot,
            any(
                section.role in {"area", "party", "goals", "urgent"}
                for section in snapshot.sections
            ),
        )

    def _sync_role_button_visibility(
        self,
        snapshot: OverlaySnapshot,
        specialized: bool,
    ) -> None:
        dual_strips = (
            snapshot.display_spec is not None
            and self._layout_manager.current is not None
            and self._layout_manager.current.mode == "dual-strips"
        )
        for button in self.role_buttons.values():
            button.setVisible(specialized and not dual_strips)

    def _hide_secondary_window(self) -> None:
        if self._secondary_window is not None:
            self._secondary_window.hide()

    def _sync_map_tools(self, snapshot: OverlaySnapshot) -> None:
        position = snapshot.map_position
        document = snapshot.map_document
        if position is None or document is None:
            self._clear_map_tools()
            return
        if document != self._map_document:
            if self._map_document is not None and document.title != self._map_document.title:
                self._save_hero_paths()
                self._hero_paths = {}
            self._destroy_map_windows()
        if document.title != self._hero_paths_title:
            self._save_hero_paths()
            self._hero_paths = (
                self._settings.hero_paths(document.title)
                if self._settings is not None
                else {}
            )
            self._hero_paths_title = document.title
        self._map_document = document
        self._map_position = position
        self._map_overlays = snapshot.map_overlays
        record_map_path(document, position, self._hero_paths)
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.map_view.set_hero_paths(self._hero_paths)
                window.update_map(position, self._map_overlays)

    def _clear_map_tools(self) -> None:
        self._map_document = None
        self._map_position = None
        self._map_overlays = ()
        self.map_button.hide()
        self.minimap_button.hide()
        self._destroy_map_windows()

    def _show_map(self) -> None:
        if self._map_document is None or self._map_position is None:
            return
        if self._map_window is None:
            self._map_window = QtMapWindow(
                self,
                self._map_document,
                settings=self._settings,
                hero_paths=self._hero_paths,
                theme=self._theme_name,
                animate_objectives=self._animate_map_objectives,
            )
        self._map_window.update_map(self._map_position, self._map_overlays)
        self._map_window.toggle()

    def _show_minimap(self) -> None:
        if self._map_document is None or self._map_position is None:
            return
        if self._minimap_window is None:
            self._minimap_window = QtMapWindow(
                self,
                self._map_document,
                compact=True,
                settings=self._settings,
                hero_paths=self._hero_paths,
                theme=self._theme_name,
                animate_objectives=False,
            )
        self._minimap_window.update_map(self._map_position, self._map_overlays)
        self._minimap_window.toggle()

    def _destroy_map_windows(self) -> None:
        for window in (self._map_window, self._minimap_window):
            if window is not None:
                window.shutdown()
        self._map_window = None
        self._minimap_window = None

    def _save_hero_paths(self) -> None:
        if (
            self._settings is None
            or not self._hero_paths_title
            or not self._hero_paths
        ):
            return
        try:
            self._settings.save_hero_paths(
                self._hero_paths_title,
                self._hero_paths,
            )
        except (OSError, ValueError) as error:
            LOGGER.warning("Unable to save Qt hero paths: %s", error)


def _content_scope(
    content_key: tuple[str, str, str] | None,
    game: str,
) -> str:
    if content_key is None:
        return game
    return json.dumps(content_key, ensure_ascii=False, separators=(",", ":"))


def _widget_rect(window: QWidget) -> ScreenRect:
    rect = window.geometry()
    return ScreenRect(
        rect.left(),
        rect.top(),
        rect.left() + rect.width(),
        rect.top() + rect.height(),
    )