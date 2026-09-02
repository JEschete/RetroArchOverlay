import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from retroarch_overlay.core.retroachievements import RAGameReference
from retroarch_overlay.infrastructure.retroachievements import RAGameTitleMatch
from retroarch_overlay.manager_gui import PluginManagerWindow
from retroarch_overlay.models import MapDocument, MapLayer, MapPosition, MapWaypoint, OverlaySnapshot, PanelAction, PanelRow, PanelSection, RetroArchStatus
from retroarch_overlay.plugin_catalog import PluginCatalogEntry
from retroarch_overlay.ra_plugin_metadata import RAGameSelectionRequired
from retroarch_overlay.ui import (
    append_map_path,
    CoordinateMapWindow,
    SnapshotCadence,
    filter_caught_sections,
    map_source_point,
    map_layer_for_position,
    map_viewport,
    preview_section_rows,
    project_map_point,
    tracked_map_position,
    waypoint_source_point,
    wrapped_map_delta,
    OverlayWindow,
)


class SnapshotCadenceTests(unittest.TestCase):
    def test_snapshots_immediately_on_game_switch_then_four_times_per_second(self) -> None:
        cadence = SnapshotCadence()
        first = RetroArchStatus("PLAYING", "core", "First Game", "11111111")
        second = RetroArchStatus("PLAYING", "core", "Second Game", "22222222")

        self.assertTrue(cadence.should_snapshot(first, 10.0))
        self.assertFalse(cadence.should_snapshot(first, 10.2))
        self.assertTrue(cadence.should_snapshot(first, 10.25))
        self.assertTrue(cadence.should_snapshot(second, 10.3))

    def test_paused_game_does_not_repeat_memory_snapshots(self) -> None:
        cadence = SnapshotCadence()
        paused = RetroArchStatus("PAUSED", "core", "Game", "11111111")

        self.assertTrue(cadence.should_snapshot(paused, 10.0))
        self.assertFalse(cadence.should_snapshot(paused, 20.0))


class PluginManagerRATests(unittest.TestCase):
    def test_selected_catalog_game_is_installed_from_advertised_repository(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        entry = PluginCatalogEntry(
            "org.example.game",
            "game",
            "Example Game",
            "https://github.com/example/RAO_game.git",
        )
        manager.catalog_selection = Mock()
        manager.catalog_selection.get.return_value = "Example Game  |  Available"
        manager._catalog_by_label = {"Example Game  |  Available": entry}
        manager._manifests = {}
        manager._install_repository = Mock()

        manager._install_catalog_plugin()

        manager._install_repository.assert_called_once_with(
            entry.repository,
            catalog_entry=entry,
        )

    def test_catalog_labels_games_by_installed_plugin_id(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        entry = PluginCatalogEntry(
            "org.example.game",
            "game",
            "Example Game",
            "https://github.com/example/RAO_game.git",
        )
        manager._catalog_entries = (entry,)
        manager._catalog_by_label = {}
        manager._manifests = {Path("plugin"): Mock(plugin_id=entry.plugin_id)}
        manager.catalog_picker = Mock()
        manager.catalog_selection = Mock()
        manager.catalog_selection.get.return_value = ""

        manager._render_catalog()

        label = "Example Game  |  Installed"
        manager.catalog_picker.configure.assert_called_once_with(values=(label,))
        manager.catalog_selection.set.assert_called_once_with(label)

    def test_game_clicks_never_inspect_git_repository(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        manager._manifests = {}
        first = Path("RAO_first").resolve()
        second = Path("RAO_second").resolve()
        first_manifest = Mock()
        second_manifest = Mock()

        with (
            patch(
                "retroarch_overlay.manager_gui.parse_plugin_manifest",
                side_effect=(first_manifest, second_manifest),
            ) as parse,
            patch("retroarch_overlay.manager_gui.inspect_plugin_repository") as inspect,
        ):
            manager._repository_manifest(first)
            manager._repository_manifest(second)
            repeated = manager._repository_manifest(first)

        self.assertIs(repeated, first_manifest)
        self.assertEqual(parse.call_count, 2)
        inspect.assert_not_called()

    def test_selection_required_retries_discovery_with_chosen_game(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        manager._busy = True
        manager._choose_ra_game = Mock(return_value=1667)
        manager._discover_ra = Mock()
        manager.status = Mock()
        selection = RAGameSelectionRequired(
            "Dragon Warrior 3",
            (
                RAGameTitleMatch(
                    RAGameReference(1667, "Dragon Quest III", 7, "NES/Famicom"),
                    0.7,
                    False,
                ),
            ),
        )

        manager._task_failed(selection)

        self.assertFalse(manager._busy)
        manager._choose_ra_game.assert_called_once_with(selection)
        manager._discover_ra.assert_called_once_with(1667)

    def test_saves_retroarch_folder_to_local_settings(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        manager.retroarch_path = Mock()
        manager.retroarch_path.get.return_value = r"C:\RetroArch"
        manager.local_settings = Mock()
        manager._sync_retroarch_status = Mock()
        manager.status = Mock()

        manager._save_settings()

        manager.local_settings.save_retroarch_path.assert_called_once_with(Path(r"C:\RetroArch"))
        manager._sync_retroarch_status.assert_called_once_with()
        manager.status.set.assert_called_once_with("Saved local settings")

    def test_create_uses_generated_plugin_id_for_local_paths(self) -> None:
        manager = PluginManagerWindow.__new__(PluginManagerWindow)
        values = {
            "game_name": "Example Game",
            "slug": "example_game",
            "holder": "Example Author",
            "license": "MIT",
            "plugin_id": "",
            "ra_game_id": "",
            "cores": "",
            "hints": "",
            "hashes": "",
            "decomp_url": "",
            "decomp_revision": "",
        }
        manager.fields = {}
        for key, value in values.items():
            manager.fields[key] = Mock()
            manager.fields[key].get.return_value = value
        manager.plugin_root = Mock()
        manager.plugin_root.get.return_value = "plugins"
        manager.required = Mock()
        manager.required.get.return_value = False
        rom_path = Path("example.rom")
        save_path = Path("example.sav")
        manager._rom_path_value = Mock(return_value=rom_path)
        manager._save_path_value = Mock(return_value=save_path)
        manager._csv = Mock(return_value=())
        manager._required_file_values = Mock(return_value=())
        manager.local_settings = Mock()
        manager.refresh = Mock()
        manager.status = Mock()
        manager._show_error = Mock()
        repository = Path("plugins/RAO_example_game")

        with patch("retroarch_overlay.manager_gui.create_plugin", return_value=repository):
            manager._create_plugin()

        plugin_id = "org.jeschete.retroarch-overlay.example_game"
        manager.local_settings.save_rom_path.assert_called_once_with(plugin_id, rom_path)
        manager.local_settings.save_save_path.assert_called_once_with(plugin_id, save_path)
        manager._show_error.assert_not_called()


class CaughtFilterTests(unittest.TestCase):
    def test_hides_caught_rows_and_empty_sections(self) -> None:
        action = PanelAction("OPEN", "Details", (PanelRow("Detail"),))
        sections = (
            PanelSection("Land", (PanelRow("Caught", True), PanelRow("Needed", False)), actions=(action,)),
            PanelSection("Water", (PanelRow("Known", True),)),
            PanelSection("Unknown", (PanelRow("No dex support"),)),
        )

        filtered = filter_caught_sections(sections, True)

        self.assertEqual(tuple(section.title for section in filtered), ("Land", "Unknown"))
        self.assertEqual(filtered[0].rows, (PanelRow("Needed", False),))
        self.assertEqual(filtered[0].actions, (action,))
        self.assertEqual(filtered[1].rows, (PanelRow("No dex support"),))

    def test_returns_original_sections_when_disabled(self) -> None:
        sections = (PanelSection("Land", (PanelRow("Caught", True),)),)

        self.assertIs(filter_caught_sections(sections, False), sections)

    def test_preview_can_expand_and_show_all_rows(self) -> None:
        section = PanelSection(
            "Route trainers",
            tuple(PanelRow(f"Trainer {index}") for index in range(7)),
            4,
        )

        preview, hidden_count = preview_section_rows(section, False)
        expanded, expanded_hidden_count = preview_section_rows(section, True)

        self.assertEqual(len(preview), 4)
        self.assertEqual(hidden_count, 3)
        self.assertEqual(expanded, section.rows)
        self.assertEqual(expanded_hidden_count, 0)


class DetailWindowTests(unittest.TestCase):
    def test_open_detail_window_refreshes_from_latest_snapshot_action(self) -> None:
        window = OverlayWindow.__new__(OverlayWindow)
        body = Mock()
        original_rows = (PanelRow("Original route"),)
        window._detail_windows = {
            ("Game", "OPEN", "Details"): (Mock(), body, original_rows)
        }
        window._render_detail_rows = Mock()
        rows = (PanelRow("Updated route"),)
        snapshot = OverlaySnapshot(
            "Game",
            "Route 2",
            (PanelSection("Section", (), actions=(PanelAction("OPEN", "Details", rows),)),),
        )

        window._sync_detail_windows(snapshot)

        window._render_detail_rows.assert_called_once_with(body, rows)

    def test_unchanged_detail_rows_are_not_redrawn_while_walking(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        detail = Mock()
        body = Mock()
        rows = (PanelRow("Same route"),)
        overlay._detail_windows = {
            ("Game", "OPEN", "Details"): (detail, body, rows)
        }
        overlay._render_detail_rows = Mock()
        snapshot = OverlaySnapshot(
            "Game",
            "Route",
            (PanelSection("Section", (), actions=(PanelAction("OPEN", "Details", rows),)),),
        )

        overlay._sync_detail_windows(snapshot)

        overlay._render_detail_rows.assert_not_called()

    def test_detail_window_closes_when_game_closes(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        detail = Mock()
        detail.winfo_x.return_value = 123
        detail.winfo_y.return_value = 234
        overlay._local_settings = Mock()
        overlay._detail_position_jobs = {}
        overlay._detail_windows = {
            ("Game", "OPEN", "Details"): (detail, Mock(), ())
        }

        overlay._sync_detail_windows("RetroArch is stopped")

        detail.destroy.assert_called_once_with()
        overlay._local_settings.save_detail_window_position.assert_called_once_with(
            "Game|OPEN|Details", 123, 234
        )
        self.assertEqual(overlay._detail_windows, {})

    def test_detail_window_stays_open_during_same_game_battle_snapshot(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        detail = Mock()
        body = Mock()
        key = ("Emerald", "OPEN POC DETAILS", "Professor Oak Challenge")
        overlay._detail_windows = {key: (detail, body, ())}
        overlay._render_detail_rows = Mock()
        battle = OverlaySnapshot(
            "Emerald",
            "Battle · Route 102",
            (PanelSection("Battle", (PanelRow("Wild Pokémon"),)),),
        )

        overlay._sync_detail_windows(battle)

        detail.destroy.assert_not_called()
        overlay._render_detail_rows.assert_not_called()
        self.assertEqual(overlay._detail_windows, {key: (detail, body, ())})

    def test_detail_window_closes_instead_of_crossing_to_another_game(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        detail = Mock()
        overlay._detail_windows = {
            ("Emerald", "OPEN", "Details"): (detail, Mock(), ())
        }
        other_game = OverlaySnapshot(
            "Other Game",
            "Area",
            (
                PanelSection(
                    "Section",
                    (),
                    actions=(PanelAction("OPEN", "Details", (PanelRow("Other"),)),),
                ),
            ),
        )

        overlay._sync_detail_windows(other_game)

        detail.destroy.assert_called_once_with()
        self.assertEqual(overlay._detail_windows, {})


class MapProjectionTests(unittest.TestCase):
    wrapped_layer = MapLayer(
        "surface",
        "Surface",
        "Outside",
        Path("surface.png"),
        offset_x=-3,
        offset_y=-4,
        anchor_x=8,
        anchor_y=8,
    )
    bordered_layer = MapLayer(
        "depths",
        "Depths",
        "Depths",
        Path("depths.png"),
        anchor_x=24,
        anchor_y=24,
    )

    def test_source_point_applies_layer_calibration(self) -> None:
        position = MapPosition("World", 0, 53, 89, True)

        self.assertEqual(map_source_point(position, self.wrapped_layer), (808, 1368))

    def test_source_point_wraps_at_layer_edges(self) -> None:
        position = MapPosition("World", 0, 2, 3, True)

        self.assertEqual(map_source_point(position, self.wrapped_layer), (4088, 4088))

    def test_full_map_supports_two_deeper_zoom_levels(self) -> None:
        self.assertEqual(CoordinateMapWindow.ZOOM_LEVELS, (1, 2, 4, 8, 16))

    def test_hero_path_skips_stationary_samples_but_keeps_revisited_tiles(self) -> None:
        points = []

        for point in ((10, 10), (10, 10), (11, 10), (10, 10)):
            append_map_path(points, point)

        self.assertEqual(points, [(10, 10), (11, 10), (10, 10)])

    def test_panned_marker_uses_shortest_wrapped_distance(self) -> None:
        self.assertEqual(wrapped_map_delta(10, 20, 256), -10)
        self.assertEqual(wrapped_map_delta(250, 5, 256), -11)
        self.assertEqual(wrapped_map_delta(5, 250, 256), 11)

    def test_entering_town_retains_last_overworld_position(self) -> None:
        outside = MapPosition("World", 0, 53, 89, True)
        inside = MapPosition("Dungeon / town", 0x1234, 7, 9, False)

        self.assertIs(tracked_map_position(outside, inside), outside)

    def test_indoor_layer_is_selected_by_map_id(self) -> None:
        area = MapLayer(
            "area-34",
            "Map 34",
            "Dungeon / town",
            Path("area-34.png"),
            map_id=0x34,
        )
        document = MapDocument("Game", (self.wrapped_layer, area))
        position = MapPosition("Dungeon / town", 0x34, 7, 9, False)

        self.assertIs(map_layer_for_position(document, position), area)

    def test_unknown_indoor_map_has_no_matching_layer(self) -> None:
        document = MapDocument("Game", (self.wrapped_layer,))
        position = MapPosition("Dungeon / town", 0x34, 7, 9, False)

        self.assertIsNone(map_layer_for_position(document, position))

    def test_lazy_layer_image_is_loaded_once(self) -> None:
        image_path = Path("generated.png")
        loader = Mock(return_value=image_path)
        layer = MapLayer(
            "area-34",
            "Map 34",
            "Dungeon / town",
            image_path,
            map_id=0x34,
            image_loader=loader,
        )
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.layers = {layer.key: layer}
        window._images = {}
        image = Mock()
        converted = Mock()
        image.convert.return_value = converted

        with patch("retroarch_overlay.ui.Image.open", return_value=image) as open_image:
            first = window._image(layer.key)
            second = window._image(layer.key)

        self.assertIs(first, converted)
        self.assertIs(second, converted)
        loader.assert_called_once_with()
        open_image.assert_called_once_with(image_path)

    def test_leaving_town_resumes_live_world_position(self) -> None:
        previous = MapPosition("World", 0, 53, 89, True)
        current = MapPosition("World", 0, 54, 89, True)

        self.assertIs(tracked_map_position(previous, current), current)

    def test_source_point_preserves_layer_border(self) -> None:
        position = MapPosition("Underworld", 0, 12, 34, True)

        self.assertEqual(map_source_point(position, self.bordered_layer), (216, 568))

    def test_waypoint_uses_same_tile_calibration_as_player(self) -> None:
        waypoint = MapWaypoint(12, 34, "Stairs", "To B2", "stairs")

        self.assertEqual(waypoint_source_point(waypoint, self.bordered_layer), (216, 568))

    def test_world_viewport_covers_nes_coordinate_space(self) -> None:
        position = MapPosition("World", 0, 12, 34, True)
        self.assertEqual(map_viewport(position, False), (0, 0, 255, 255))

    def test_local_viewport_moves_by_chunks(self) -> None:
        first = MapPosition("World", 0, 12, 34, True)
        nearby = MapPosition("World", 0, 15, 39, True)
        distant = MapPosition("World", 0, 16, 39, True)
        self.assertEqual(map_viewport(first, True), map_viewport(nearby, True))
        self.assertNotEqual(map_viewport(first, True), map_viewport(distant, True))

    def test_projection_places_world_corners_inside_padding(self) -> None:
        viewport = (0, 0, 255, 255)
        self.assertEqual(project_map_point(0, 0, viewport, 304, 304), (24.0, 24.0))
        self.assertEqual(project_map_point(255, 255, viewport, 304, 304), (280.0, 280.0))


if __name__ == "__main__":
    unittest.main()