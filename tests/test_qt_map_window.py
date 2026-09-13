from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QWidget

from retroarch_overlay.core.models import (
    MapDocument,
    MapLayer,
    MapOverlay,
    MapPosition,
    MapRegion,
    MapWaypoint,
    ScreenRect,
)
from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.presentation.qt import QtMapWindow


def _image(path: Path, color: tuple[int, int, int] = (20, 40, 60)) -> Path:
    Image.new("RGB", (64, 64), color).save(path)
    return path


def _document(tmp_path: Path, loader: Mock | None = None) -> MapDocument:
    world = _image(tmp_path / "world.png")
    underworld = _image(tmp_path / "underworld.png", (60, 40, 20))
    return MapDocument(
        "Atlas",
        (
            MapLayer(
                "world",
                "World",
                "Outside",
                world,
                source_url="https://example.invalid/map",
                credit="Map source",
                image_loader=loader,
                waypoints=(
                    MapWaypoint(1, 1, "Shop", "Items", kind="entrance"),
                    MapWaypoint(
                        2,
                        2,
                        "Chest",
                        kind="collectibles",
                        completed=True,
                    ),
                ),
                regions=(MapRegion(1, 1, 2, 2, "Enemies", kind="encounters"),),
            ),
            MapLayer("underworld", "Underworld", "Below", underworld),
        ),
        overlay_kinds=("entrance", "collectibles", "encounters"),
    )


def test_hidden_updates_remain_lazy_until_window_is_shown(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "loaded.png")
    loader = Mock(return_value=path)
    document = _document(tmp_path, loader)
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, document)

    window.update_map(MapPosition("Outside", 0, 1, 1, True))

    loader.assert_not_called()
    window.show_map()
    loader.assert_called_once_with()
    assert window.isVisible()
    window.shutdown()


def test_restores_existing_view_schema_and_legacy_geometry(qtbot, tmp_path: Path) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    settings.save_map_view_state(
        "map",
        {
            "layer": "underworld",
            "overlays": {"collectibles": True, "encounters": False},
            "hide_completed": True,
            "opacity": 0.65,
        },
    )
    settings.save_window_geometry("map", ScreenRect(20, 30, 420, 630))
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path), settings=settings)

    assert window.map_view.layer_key == "underworld"
    assert window.map_view.overlay_visibility["collectibles"]
    assert not window.map_view.overlay_visibility["encounters"]
    assert window.map_view.hide_completed
    assert window.windowOpacity() == pytest.approx(0.65, abs=1 / 255)
    assert window.geometry().getRect() == (20, 30, 400, 600)
    window.shutdown()

    reloaded = LocalPluginSettings(settings.path)
    assert reloaded.window_geometry("map-qt") == ScreenRect(20, 30, 420, 630)
    assert reloaded.window_geometry("map") == ScreenRect(20, 30, 420, 630)


def test_controls_update_state_and_marker_list_navigation(qtbot, tmp_path: Path) -> None:
    changes = Mock()
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path), on_view_change=changes)
    window.update_map(
        MapPosition("Outside", 0, 1, 1, True),
        (MapOverlay("world", (MapWaypoint(3, 3, "Objective", kind="objective"),)),),
    )
    window.show_map()
    window.overlay_checks["collectibles"].setChecked(True)
    window.hide_completed.setChecked(True)
    window.opacity_slider.setValue(75)
    centers = []
    window.map_view.center_on_waypoint = lambda marker: centers.append(marker.title)  # type: ignore[method-assign]
    window.marker_list.setCurrentRow(0)

    state = window.view_state()
    assert state["overlays"]["collectibles"] is True  # type: ignore[index]
    assert state["hide_completed"] is True
    assert state["opacity"] == 0.75
    assert "Chest" not in [item.title for item in window.map_view.visible_waypoints()]
    assert centers
    assert changes.call_count >= 3
    window.shutdown()


def test_source_credit_opens_current_layer_url(qtbot, tmp_path: Path) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path))
    window.update_map(MapPosition("Outside", 0, 1, 1, True))
    window.show_map()

    with patch(
        "retroarch_overlay.presentation.qt.map_window.QDesktopServices.openUrl",
        return_value=True,
    ) as open_url:
        window.credit_button.click()

    assert open_url.call_args.args[0].toString() == "https://example.invalid/map"
    window.shutdown()


def test_compact_window_hides_controls_and_close_only_hides(qtbot, tmp_path: Path) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    document = _document(tmp_path)
    document = replace(
        document,
        overlay_kinds=(*document.overlay_kinds, "npcs"),
    )
    window = QtMapWindow(owner, document, compact=True)
    window.update_map(MapPosition("Outside", 0, 1, 1, True))
    window.show_map()

    assert window.toolbar.isHidden()
    assert window.overlay_bar.isHidden()
    assert window.marker_list.isHidden()
    assert window.map_view.overlay_visibility["collectibles"]
    assert window.map_view.overlay_visibility["npcs"]
    assert not window.map_view.overlay_visibility["encounters"]
    window.close()
    assert window.isHidden()
    window.show_map()
    assert window.isVisible()
    window.shutdown()


def test_control_changes_persist_immediately_with_existing_schema(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path), settings=settings)
    window.update_map(MapPosition("Outside", 0, 1, 1, True))
    window.show_map()

    window.overlay_checks["collectibles"].setChecked(True)
    window.hide_completed.setChecked(True)
    window.opacity_slider.setValue(70)

    persisted = LocalPluginSettings(settings.path).map_view_state("map")
    assert persisted["layer"] == "world"
    assert persisted["overlays"]["collectibles"] is True  # type: ignore[index]
    assert persisted["hide_completed"] is True
    assert persisted["opacity"] == 0.7
    window.shutdown()


def test_visible_markers_are_exposed_as_accessible_list_items(qtbot, tmp_path: Path) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path))
    window.update_map(
        MapPosition("Outside", 0, 1, 1, True),
        (MapOverlay("world", (MapWaypoint(3, 3, "Objective", kind="objective"),)),),
    )
    window.show_map()
    interface = QAccessible.queryAccessibleInterface(window.marker_list)

    assert interface is not None
    assert interface.role() == QAccessible.Role.List
    names = {
        interface.child(index).text(QAccessible.Text.Name)
        for index in range(interface.childCount())
    }
    assert "Shop · Items" in names
    assert "Objective" in names
    window.shutdown()


def test_overlay_controls_use_multiple_rows_at_default_width(qtbot, tmp_path: Path) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path))
    window.resize(760, 800)
    window.show()

    positions = {
        window.overlay_layout.getItemPosition(index)[0]
        for index in range(window.overlay_layout.count())
    }

    assert len(positions) >= 2
    assert window.overlay_bar.sizeHint().width() <= window.width()
    window.shutdown()


def test_long_marker_rows_wrap_and_keep_full_tooltip(qtbot, tmp_path: Path) -> None:
    long_detail = (
        "Entrance at (24,88) with a deliberately long description that must wrap"
    )
    document = _document(tmp_path)
    layer = document.layers[0]
    document = MapDocument(
        document.title,
        (
            MapLayer(
                layer.key,
                layer.title,
                layer.area,
                layer.image_path,
                waypoints=(MapWaypoint(1, 1, "Ali(a)han Town", long_detail),),
            ),
        ),
    )
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, document)
    window.resize(500, 500)
    window.update_map(MapPosition("Outside", 0, 1, 1, True))
    window.show_map()
    qtbot.waitUntil(lambda: window.marker_list.count() == 1)
    item = window.marker_list.item(0)

    assert item.toolTip() == f"Ali(a)han Town · {long_detail}"
    assert window.marker_list.wordWrap()
    assert window.marker_list.textElideMode() == Qt.TextElideMode.ElideNone
    assert window.marker_list.visualItemRect(item).height() > (
        window.marker_list.fontMetrics().height() + 4
    )
    window.shutdown()


def test_map_controls_have_contextual_accessible_names_and_tab_order(
    qtbot,
    tmp_path: Path,
) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, _document(tmp_path))
    window.show_map()
    window.activateWindow()

    assert window.center_button.accessibleName() == "Center map on player"
    assert window.hide_completed.accessibleName() == "Hide collected map markers"
    assert {
        checkbox.accessibleName() for checkbox in window.overlay_checks.values()
    } == {
        "Show Player on map",
        "Show Hero's path on map",
        "Show Entrances on map",
        "Show Collectibles on map",
        "Show Enemies on map",
    }
    assert window.opacity_label.buddy() is window.opacity_slider
    assert window.opacity_slider.accessibleName() == "Map opacity"
    heading = QAccessible.queryAccessibleInterface(window.heading)
    zoom = QAccessible.queryAccessibleInterface(window.zoom_label)
    assert heading is not None
    assert zoom is not None
    assert heading.text(QAccessible.Text.Name) == "Atlas"
    assert heading.text(QAccessible.Text.Description) == "Map location"
    assert zoom.text(QAccessible.Text.Name) == "1×"
    assert zoom.text(QAccessible.Text.Description) == "Current map zoom"

    window.layer_combo.setFocus()
    qtbot.keyClick(window.layer_combo, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.zoom_out
    window.shutdown()


def test_local_only_document_hides_empty_layer_selector(qtbot, tmp_path: Path) -> None:
    document = _document(tmp_path)
    local_layers = tuple(
        replace(layer, map_id=index)
        for index, layer in enumerate(document.layers)
    )
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtMapWindow(owner, replace(document, layers=local_layers))

    assert window.layer_combo.isHidden()
    window.shutdown()