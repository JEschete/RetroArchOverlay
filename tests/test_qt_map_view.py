from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from retroarch_overlay.core.models import (
    MapDocument,
    MapLayer,
    MapOverlay,
    MapPosition,
    MapRegion,
    MapWaypoint,
)
from retroarch_overlay.presentation.qt import QtMapImageCache, QtMapView


def _image(path: Path, color: tuple[int, int, int] = (20, 40, 60)) -> Path:
    Image.new("RGB", (64, 64), color).save(path)
    return path


def test_document_construction_is_lazy_and_loader_runs_once(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    loader = Mock(return_value=path)
    layer = MapLayer("world", "World", "Outside", path, image_loader=loader)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)

    assert loader.call_count == 0
    view.update_map(MapPosition("Outside", 0, 1, 2, True))
    view.update_map(MapPosition("Outside", 0, 2, 2, True))

    loader.assert_called_once_with()
    assert view.static_build_count == 1
    assert view.dynamic_update_count == 1


def test_wrapping_layer_uses_shared_pixmap_tiles_and_calibrated_player_copies(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        tile_width=16,
        tile_height=16,
        offset_x=-3,
        offset_y=-4,
        anchor_x=8,
        anchor_y=8,
        wrap_width=4,
        wrap_height=4,
        wraps=True,
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)

    view.update_map(MapPosition("Outside", 0, 3, 1, True))

    assert view.image_item_count == 9
    assert len(view.player_scene_positions) == 9
    assert (8.0 + 64, 24.0 + 64) in view.player_scene_positions
    assert view.scene().sceneRect().getRect() == (0.0, 0.0, 192.0, 192.0)


def test_nonwrapping_layer_uses_one_image_and_one_player(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "area.png")
    layer = MapLayer("area", "Area", "Inside", path, map_id=0x34)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)

    view.update_map(MapPosition("Inside", 0x34, 2, 3, False))

    assert view.image_item_count == 1
    assert view.player_scene_positions == ((32.0, 48.0),)


def test_unknown_indoor_map_retains_last_world_layer(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 2, 3, True))

    view.update_map(MapPosition("Unknown", 0x99, 5, 6, False))

    assert view.layer_key == "world"
    assert view.player_scene_positions == ((32.0, 48.0),)


def test_dynamic_overlay_rebuild_does_not_rebuild_static_scene(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    position = MapPosition("Outside", 0, 2, 3, True)
    view.update_map(position)

    view.update_map(
        position,
        (MapOverlay("world", (MapWaypoint(4, 5, "Objective"),)),),
    )

    assert view.static_build_count == 1
    assert view.dynamic_update_count == 1
    assert any(item.toolTip() == "Objective" for item in view.scene().items())


def test_same_layer_movement_updates_player_items_in_place(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 2, 3, True))
    original_items = tuple(view._player_items)

    view.update_map(MapPosition("Outside", 0, 4, 5, True))

    assert tuple(view._player_items) == original_items
    assert view.player_scene_positions == ((64.0, 80.0),)
    assert view._player_items[0].toolTip() == "Player · 4,5"


def test_zoom_is_discrete_bounded_and_changes_drag_mode(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    view = QtMapView(MapDocument("Map", (MapLayer("world", "World", "Outside", path),)))
    qtbot.addWidget(view)
    view.resize(320, 240)
    view.show()
    view.update_map(MapPosition("Outside", 0, 2, 3, True))

    assert view.change_zoom(1) == 2
    assert view.dragMode() == view.DragMode.ScrollHandDrag
    assert view.change_zoom(99) == 16
    assert view.change_zoom(-99) == 1
    assert view.dragMode() == view.DragMode.NoDrag
    with pytest.raises(ValueError, match="Unsupported map zoom"):
        view.set_zoom(3)


def test_image_cache_evicts_least_recent_layer(qapp, tmp_path: Path) -> None:
    cache = QtMapImageCache(maximum_entries=2)
    layers = tuple(
        MapLayer(
            f"layer-{index}",
            f"Layer {index}",
            "Area",
            _image(tmp_path / f"{index}.png", (index * 40, 20, 30)),
        )
        for index in range(3)
    )

    cache.load(layers[0])
    cache.load(layers[1])
    cache.load(layers[0])
    cache.load(layers[2])

    assert cache.keys == ("layer-0", "layer-2")


def test_missing_map_image_is_actionable(qtbot, tmp_path: Path) -> None:
    layer = MapLayer("missing", "Missing", "Area", tmp_path / "missing.png")
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)

    with pytest.raises(ValueError, match="Map image could not be loaded"):
        view.update_map(MapPosition("Area", 0, 0, 0, True))


def test_rendered_view_contains_map_pixels_and_player_marker(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    view.resize(256, 256)
    qtbot.addWidget(view)
    view.show()
    view.update_map(MapPosition("Outside", 0, 2, 2, True))
    qtbot.waitUntil(view.isVisible)

    image = view.viewport().grab().toImage()
    colors = {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(image.width())
    }

    assert "#14283c" in colors
    assert "#f8c24e" in colors


def test_overlay_visibility_and_hide_completed_filter_waypoints(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        waypoints=(
            MapWaypoint(1, 1, "Opened chest", kind="collectibles", completed=True),
            MapWaypoint(2, 2, "Pending chest", kind="collectibles"),
        ),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    assert view.visible_waypoints() == ()
    assert view.set_overlay_visible("collectibles", True)
    assert [item.title for item in view.visible_waypoints()] == [
        "Opened chest",
        "Pending chest",
    ]
    assert view.set_hide_completed(True)
    assert [item.title for item in view.visible_waypoints()] == ["Pending chest"]
    assert not view.set_overlay_visible("unknown", True)


def test_hidden_static_overlay_kinds_materialize_only_when_enabled(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        regions=tuple(
            MapRegion(index, 0, 1, 1, f"Cell {index}", kind="encounters")
            for index in range(4)
        ),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    assert "encounters" not in view._materialized_static_kinds
    assert not any(kind == "encounters" for _, kind, _ in view._static_classified_items)
    builds = view.static_build_count

    view.set_overlay_visible("encounters", True)

    assert "encounters" in view._materialized_static_kinds
    assert sum(kind == "encounters" for _, kind, _ in view._static_classified_items) == 4
    assert view.static_build_count == builds


def test_player_visibility_updates_existing_items(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    player = view._player_items[0]

    assert view.set_overlay_visible("player", False)
    assert not player.isVisible()
    assert view.set_overlay_visible("player", True)
    assert player.isVisible()


def test_player_blinks_by_default_on_full_map_and_stops_when_hidden(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.show()
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    player = view._player_items[0]

    assert view.player_blink_enabled
    assert view.player_timer_active
    assert player.isVisible()

    view._toggle_player_blink()

    assert not player.isVisible()
    view.hide()
    assert not view.player_timer_active
    assert player.isVisible()


def test_hiding_player_stops_blink_until_player_is_enabled(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.show()
    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    view.set_overlay_visible("player", False)

    assert not view.player_timer_active
    assert not view._player_items[0].isVisible()

    view.set_overlay_visible("player", True)

    assert view.player_timer_active
    assert view._player_items[0].isVisible()


def test_hero_path_appends_without_rebuilding_existing_chunks(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    paths = {"world": [(8, 8), (16, 8)]}
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)), hero_paths=paths)
    qtbot.addWidget(view)
    view.set_overlay_visible("path", True)
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    original = tuple(view._path_items)

    paths["world"].append((24, 8))
    view.set_hero_paths(paths)

    assert tuple(view._path_items) == original
    assert len(view._path_increment_items) == 1
    assert view.path_item_count == 2


def test_hidden_hero_path_materializes_only_when_enabled(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    paths = {"world": [(8, 8), (16, 8), (24, 8)]}
    layer = MapLayer("world", "World", "Outside", path)
    view = QtMapView(MapDocument("Map", (layer,)), hero_paths=paths)
    qtbot.addWidget(view)

    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    assert view.path_item_count == 0
    assert view.set_overlay_visible("path", True)
    assert view.path_item_count == 1


def test_wrapped_hero_path_does_not_draw_across_map_seam(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        wrap_width=4,
        wrap_height=4,
        wraps=True,
    )
    paths = {"world": [(60, 32), (2, 32)]}
    view = QtMapView(MapDocument("Map", (layer,)), hero_paths=paths)
    qtbot.addWidget(view)
    view.set_overlay_visible("path", True)

    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    assert view.path_item_count == 0


def test_reduced_motion_keeps_objective_ring_visible_and_stops_timer(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        waypoints=(MapWaypoint(2, 2, "Next", kind="objective"),),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.show()
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    rings = [item for item in view.scene().items() if item.data(0) == "objective-ring"]

    assert rings
    assert view.objective_timer_active
    view.set_objective_animation(False)

    assert not view.objective_timer_active
    assert all(item.isVisible() for item in rings)


def test_hiding_objectives_stops_animation_timer(qtbot, tmp_path: Path) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        waypoints=(MapWaypoint(2, 2, "Next", kind="objective"),),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.show()
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    assert view.objective_timer_active

    view.set_overlay_visible("objective", False)

    assert not view.objective_timer_active


def test_accessible_navigation_centers_calibrated_waypoint_and_region(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    waypoint = MapWaypoint(2, 3, "Shop")
    region = MapRegion(1, 1, 2, 2, "Enemies")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        offset_x=1,
        offset_y=2,
        anchor_x=4,
        anchor_y=6,
        waypoints=(waypoint,),
        regions=(region,),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.update_map(MapPosition("Outside", 0, 1, 1, True))
    centers = []
    view.centerOn = lambda x, y: centers.append((x, y))  # type: ignore[method-assign]

    view.center_on_waypoint(waypoint)
    view.center_on_region(region)

    assert centers == [(52, 86), (48.0, 64.0)]


def test_generic_marker_shapes_symbols_and_encounter_labels_are_preserved(
    qtbot,
    tmp_path: Path,
) -> None:
    path = _image(tmp_path / "world.png")
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        path,
        waypoints=(
            MapWaypoint(1, 1, "Shop", marker="shop"),
            MapWaypoint(2, 1, "Heal", marker="service"),
            MapWaypoint(3, 1, "Quest", marker="quest"),
            MapWaypoint(1, 2, "Boss", marker="boss"),
            MapWaypoint(2, 2, "Objective", kind="objective"),
            MapWaypoint(3, 2, "Chest", kind="collectibles"),
        ),
        regions=(
            MapRegion(
                0,
                0,
                2,
                2,
                "Enemies",
                kind="encounters",
                label="Slime Lv 1",
            ),
        ),
    )
    view = QtMapView(MapDocument("Map", (layer,)))
    qtbot.addWidget(view)
    view.set_overlay_visible("collectibles", True)
    view.set_overlay_visible("encounters", True)

    view.update_map(MapPosition("Outside", 0, 1, 1, True))

    shapes = {str(item.data(1)) for item in view.scene().items() if item.data(1)}
    symbols = {str(item.data(2)) for item in view.scene().items() if item.data(2)}
    tooltips = {item.toolTip() for item in view.scene().items() if item.toolTip()}
    assert {"diamond", "square", "triangle", "circle", "objective", "dot", "symbol"} <= shapes
    assert {"$", "+", "!", "X"} <= symbols
    assert "Enemies" in tooltips
    assert any(
        getattr(item, "text", lambda: "")() == "Slime Lv 1"
        for item in view.scene().items()
    )