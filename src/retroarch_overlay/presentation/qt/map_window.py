from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.map import clamp_opacity
from ...core.models import (
    MapDocument,
    MapOverlay,
    MapPosition,
    MapRegion,
    MapWaypoint,
)
from .map_view import QtMapView
from .theme import apply_qt_theme
from .window_state import (
    WindowStateSettings,
    restore_named_window_geometry,
    save_named_window_geometry,
)


LOGGER = logging.getLogger(__name__)

OVERLAY_LABELS = {
    "player": "Player",
    "path": "Hero's path",
    "objective": "Next objective",
    "entrance": "Entrances",
    "collectibles": "Collectibles",
    "npcs": "NPCs",
    "encounters": "Enemies",
}


class MapWindowSettings(WindowStateSettings, Protocol):
    def map_view_state(self, key: str) -> dict[str, object]: ...

    def save_map_view_state(self, key: str, state: dict[str, object]) -> None: ...


class QtMapWindow(QWidget):
    def __init__(
        self,
        owner: QWidget,
        document: MapDocument,
        *,
        compact: bool = False,
        settings: MapWindowSettings | None = None,
        hero_paths: dict[str, list[tuple[int, int]]] | None = None,
        theme: str = "light",
        animate_objectives: bool = True,
        on_view_change: Callable[[], None] | None = None,
    ) -> None:
        flags = Qt.WindowType.Tool if compact else Qt.WindowType.Window
        if owner.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(owner, flags)
        if not document.layers:
            raise ValueError("Map document must contain at least one layer")
        self.document = document
        self.compact = compact
        self._settings = settings
        self._state_key = "minimap" if compact else "map"
        self._geometry_key = f"{self._state_key}-qt"
        self._on_view_change = on_view_change
        self._pending_position: MapPosition | None = None
        self._pending_overlays: tuple[MapOverlay, ...] = ()
        self._shutting_down = False
        self._marker_objects: list[MapWaypoint | MapRegion] = []
        self.setWindowTitle(f"{document.title} {'Minimap' if compact else 'Map'}")
        self.setAccessibleName(self.windowTitle())
        self.resize(184, 208) if compact else self.resize(760, 800)
        self.setMinimumSize(160, 184) if compact else self.setMinimumSize(320, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toolbar = QFrame(self)
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        self.layer_combo = QComboBox(self.toolbar)
        self.layer_combo.setAccessibleName("Map layer")
        for layer in document.layers:
            if layer.map_id is None:
                self.layer_combo.addItem(layer.title, layer.key)
        self.layer_combo.setVisible(self.layer_combo.count() > 0)
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        toolbar_layout.addWidget(self.layer_combo, 1)
        self.zoom_out = QPushButton("−", self.toolbar)
        self.zoom_out.setAccessibleName("Zoom out")
        self.zoom_out.clicked.connect(lambda: self._change_zoom(-1))
        toolbar_layout.addWidget(self.zoom_out)
        self.zoom_label = QLabel("1×", self.toolbar)
        self.zoom_label.setAccessibleDescription("Current map zoom")
        toolbar_layout.addWidget(self.zoom_label)
        self.zoom_in = QPushButton("+", self.toolbar)
        self.zoom_in.setAccessibleName("Zoom in")
        self.zoom_in.clicked.connect(lambda: self._change_zoom(1))
        toolbar_layout.addWidget(self.zoom_in)
        self.center_button = QPushButton("Center", self.toolbar)
        self.center_button.setAccessibleName("Center map on player")
        self.center_button.clicked.connect(self.map_view_recenter)
        toolbar_layout.addWidget(self.center_button)
        layout.addWidget(self.toolbar)

        self.overlay_bar = QFrame(self)
        self.overlay_layout = QGridLayout(self.overlay_bar)
        overlay_layout = self.overlay_layout
        overlay_layout.setContentsMargins(8, 4, 8, 4)
        overlay_layout.setHorizontalSpacing(10)
        overlay_layout.setVerticalSpacing(2)
        self.overlay_checks: dict[str, QCheckBox] = {}
        self.map_view = QtMapView(
            document,
            hero_paths=hero_paths,
            animate_objectives=animate_objectives,
            blink_player=True,
            parent=self,
        )
        overlay_columns = 4
        for index, kind in enumerate(self.map_view.available_overlay_kinds):
            checkbox = QCheckBox(
                OVERLAY_LABELS.get(kind, kind.replace("_", " ").title()),
                self.overlay_bar,
            )
            checkbox.setAccessibleName(f"Show {checkbox.text()} on map")
            checkbox.setChecked(self.map_view.overlay_visibility[kind])
            checkbox.toggled.connect(
                lambda visible, selected=kind: self._overlay_changed(selected, visible)
            )
            overlay_layout.addWidget(
                checkbox,
                index // overlay_columns,
                index % overlay_columns,
            )
            self.overlay_checks[kind] = checkbox
        settings_row = (
            len(self.map_view.available_overlay_kinds) + overlay_columns - 1
        ) // overlay_columns
        self.hide_completed = QCheckBox("Hide collected", self.overlay_bar)
        self.hide_completed.setAccessibleName("Hide collected map markers")
        self.hide_completed.toggled.connect(self._hide_completed_changed)
        overlay_layout.addWidget(self.hide_completed, settings_row, 0, 1, 2)
        self.opacity_label = QLabel("Opacity", self.overlay_bar)
        overlay_layout.addWidget(self.opacity_label, settings_row, 2)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self.overlay_bar)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setAccessibleName("Map opacity")
        self.opacity_label.setBuddy(self.opacity_slider)
        self.opacity_slider.valueChanged.connect(self._opacity_changed)
        overlay_layout.addWidget(self.opacity_slider, settings_row, 3)
        for column in range(overlay_columns):
            overlay_layout.setColumnStretch(column, 1)
        layout.addWidget(self.overlay_bar)

        self.heading = QLabel(document.title, self)
        self.heading.setContentsMargins(10, 6, 10, 6)
        self.heading.setAccessibleDescription("Map location")
        layout.addWidget(self.heading)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.map_view)
        self.marker_list = QListWidget(splitter)
        self.marker_list.setAccessibleName("Visible map markers")
        self.marker_list.setWordWrap(True)
        self.marker_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.marker_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.marker_list.setMinimumWidth(220)
        self.marker_list.currentRowChanged.connect(self._marker_selected)
        splitter.addWidget(self.marker_list)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes((560, 200))
        layout.addWidget(splitter, 1)
        self.credit_button = QPushButton(self)
        self.credit_button.setFlat(True)
        self.credit_button.setAccessibleName("Open map source")
        self.credit_button.clicked.connect(self._open_source)
        layout.addWidget(self.credit_button)

        if compact:
            self.toolbar.hide()
            self.overlay_bar.hide()
            self.marker_list.hide()
            self.credit_button.hide()
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.set_theme(theme)
        initial_view = (
            settings.map_view_state(self._state_key) if settings is not None else {}
        )
        self._restore_view_state(initial_view)
        if compact and not initial_view:
            for kind in ("collectibles", "npcs"):
                self.map_view.set_overlay_visible(kind, True)
        if settings is not None:
            restore_named_window_geometry(
                self,
                settings,
                self._geometry_key,
                fallback_keys=(self._state_key,),
            )

    def set_theme(self, preference: str) -> str:
        return apply_qt_theme(self, preference)

    def update_map(
        self,
        position: MapPosition,
        overlays: tuple[MapOverlay, ...] = (),
    ) -> None:
        self._pending_position = position
        self._pending_overlays = overlays
        if self.isVisible():
            self._apply_pending_map()

    def show_map(self) -> None:
        self.show()
        self.raise_()
        self._apply_pending_map()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide_map()
        else:
            self.show_map()

    def hide_map(self) -> None:
        self._save_state()
        self.hide()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._save_state()
        self.close()

    def view_state(self) -> dict[str, object]:
        return {
            "layer": self.map_view.layer_key,
            "overlays": self.map_view.overlay_visibility,
            "hide_completed": self.map_view.hide_completed,
            "opacity": round(clamp_opacity(self.windowOpacity()), 2),
        }

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_state()
        if self._shutting_down:
            event.accept()
            super().closeEvent(event)
            return
        self.hide()
        event.ignore()

    def _restore_view_state(self, state: dict[str, object]) -> None:
        layer = state.get("layer")
        if isinstance(layer, str) and layer in self.map_view.layers:
            self.map_view.set_layer(layer, render=False)
            self._sync_layer_combo(layer)
        overlays = state.get("overlays")
        if isinstance(overlays, dict):
            for kind, visible in overlays.items():
                checkbox = self.overlay_checks.get(kind)
                if checkbox is None or not isinstance(visible, bool):
                    continue
                with QSignalBlocker(checkbox):
                    checkbox.setChecked(visible)
                self.map_view.set_overlay_visible(kind, visible)
        hide_completed = state.get("hide_completed")
        if isinstance(hide_completed, bool):
            with QSignalBlocker(self.hide_completed):
                self.hide_completed.setChecked(hide_completed)
            self.map_view.set_hide_completed(hide_completed)
        opacity = state.get("opacity")
        if isinstance(opacity, (int, float)) and not isinstance(opacity, bool):
            value = clamp_opacity(float(opacity))
            with QSignalBlocker(self.opacity_slider):
                self.opacity_slider.setValue(round(value * 100))
            self.setWindowOpacity(value)

    def _apply_pending_map(self) -> None:
        if self._pending_position is None:
            return
        try:
            self.map_view.update_map(self._pending_position, self._pending_overlays)
        except (OSError, ValueError) as error:
            self.heading.setText(f"Map unavailable · {error}")
            LOGGER.warning("Qt map unavailable: %s", error)
            return
        layer = self.map_view.current_layer
        note = " · indoors · last outside" if self.map_view.indoor_map_id is not None else ""
        self.heading.setText(
            f"{layer.title} · ({self._pending_position.x},{self._pending_position.y}){note}"
        )
        self.credit_button.setText(layer.credit)
        self.credit_button.setVisible(bool(layer.credit) and not self.compact)
        self._sync_layer_combo(layer.key)
        self._rebuild_marker_list()

    def _sync_layer_combo(self, key: str) -> None:
        index = self.layer_combo.findData(key)
        with QSignalBlocker(self.layer_combo):
            self.layer_combo.setCurrentIndex(index)

    def _layer_changed(self, index: int) -> None:
        key = self.layer_combo.itemData(index)
        if not isinstance(key, str):
            return
        self.map_view.set_layer(key, render=self.isVisible())
        if self.isVisible() and self._pending_position is not None:
            self.map_view.update_map(self._pending_position, self._pending_overlays)
            self._rebuild_marker_list()
        self._view_changed()

    def _overlay_changed(self, kind: str, visible: bool) -> None:
        self.map_view.set_overlay_visible(kind, visible)
        self._rebuild_marker_list()
        self._view_changed()

    def _hide_completed_changed(self, hidden: bool) -> None:
        self.map_view.set_hide_completed(hidden)
        self._rebuild_marker_list()
        self._view_changed()

    def _opacity_changed(self, value: int) -> None:
        self.setWindowOpacity(clamp_opacity(value / 100))
        self._view_changed()

    def _change_zoom(self, steps: int) -> None:
        zoom = self.map_view.change_zoom(steps)
        self.zoom_label.setText(f"{zoom}×")

    def map_view_recenter(self) -> None:
        self.map_view.recenter()

    def _rebuild_marker_list(self) -> None:
        with QSignalBlocker(self.marker_list):
            self.marker_list.clear()
            self._marker_objects = [
                *self.map_view.visible_waypoints(),
                *self.map_view.visible_regions(),
            ]
            for marker in self._marker_objects:
                detail = f" · {marker.detail}" if marker.detail else ""
                completed = " · complete" if isinstance(marker, MapWaypoint) and marker.completed else ""
                text = f"{marker.title}{detail}{completed}"
                self.marker_list.addItem(text)
                self.marker_list.item(self.marker_list.count() - 1).setToolTip(text)

    def _marker_selected(self, row: int) -> None:
        if not 0 <= row < len(self._marker_objects):
            return
        marker = self._marker_objects[row]
        if isinstance(marker, MapWaypoint):
            self.map_view.center_on_waypoint(marker)
        else:
            self.map_view.center_on_region(marker)

    def _open_source(self) -> None:
        source = self.map_view.current_layer.source_url
        if source:
            QDesktopServices.openUrl(QUrl(source))

    def _view_changed(self) -> None:
        self._save_state()
        if self._on_view_change is not None:
            self._on_view_change()

    def _save_state(self) -> None:
        if self._settings is None:
            return
        try:
            self._settings.save_map_view_state(self._state_key, self.view_state())
            save_named_window_geometry(self, self._settings, self._geometry_key)
        except (OSError, ValueError) as error:
            LOGGER.warning("Unable to save Qt %s state: %s", self._state_key, error)