import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from retroarch_overlay.core.retroachievements import RAGameReference
from retroarch_overlay.infrastructure.retroachievements import RAGameTitleMatch
from retroarch_overlay.manager_gui import PluginManagerWindow
from retroarch_overlay.models import MapDocument, MapLayer, MapPosition, MapRegion, MapWaypoint, OverlaySnapshot, PanelAction, PanelRow, PanelSection, RetroArchStatus
from retroarch_overlay.plugin_catalog import PluginCatalogEntry
from retroarch_overlay.ra_plugin_metadata import RAGameSelectionRequired
from retroarch_overlay.retroarch_installation import network_commands_enabled
from retroarch_overlay.ui import (
    append_map_path,
    clamp_overlay_size,
    CoordinateMapWindow,
    SnapshotCadence,
    filter_caught_sections,
    map_source_point,
    map_layer_for_position,
    map_viewport,
    mouse_wheel_units,
    party_detail_row_role,
    preview_section_rows,
    project_map_point,
    record_map_path,
    tracked_map_position,
    waypoint_source_point,
    wrapped_map_delta,
    OverlayWindow,
)


class SnapshotCadenceTests(unittest.TestCase):
    def test_panel_rows_support_optional_hover_details(self) -> None:
        plain = PanelRow("Plain")
        explained = PanelRow("Blaze", tooltip="Deals fire damage to one enemy.")

        self.assertEqual(plain.tooltip, "")
        self.assertEqual(explained.tooltip, "Deals fire damage to one enemy.")

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

    def test_saves_network_command_checkbox_to_retroarch_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            retroarch = Path(directory)
            config = retroarch / "retroarch.cfg"
            config.write_text(
                'network_cmd_enable = "false"\nnetwork_cmd_port = "55355"\n',
                encoding="utf-8",
            )
            manager = PluginManagerWindow.__new__(PluginManagerWindow)
            manager.retroarch_path = Mock()
            manager.retroarch_path.get.return_value = str(retroarch)
            manager.network_commands_enabled = Mock()
            manager.network_commands_enabled.get.return_value = True
            manager.local_settings = Mock()
            manager._sync_retroarch_status = Mock()
            manager.status = Mock()

            manager._save_settings()

            self.assertTrue(network_commands_enabled(config))
            manager.status.set.assert_called_once_with(
                "Saved settings; restart RetroArch"
            )

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

    def test_main_overlay_keeps_all_roles_and_real_species_rows(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_sections = set()
        snapshot = OverlaySnapshot(
            "Pokemon Emerald",
            "Route 104",
            (
                PanelSection(
                    "Party",
                    (PanelRow("Marshtomp"),),
                    role="party",
                    compact_rows=(PanelRow("6 Pokemon"),),
                ),
                PanelSection(
                    "Goals",
                    (PanelRow("Catch Marill"),),
                    role="goals",
                    compact_rows=(PanelRow("1 goal"),),
                ),
                PanelSection(
                    "Water",
                    (PanelRow("Marill Lv 5-15 60%"), PanelRow("Wingull Lv 10 40%")),
                    role="area",
                    compact_rows=(PanelRow("2 species"),),
                ),
            ),
        )

        views = overlay._section_views(snapshot)

        self.assertEqual(
            tuple(section.title for section, _, _, _ in views),
            ("Party", "Goals", "Water"),
        )
        water_rows = next(rows for section, rows, _, _ in views if section.title == "Water")
        self.assertEqual(
            tuple(row.text for row in water_rows),
            ("Marill Lv 5-15 60%", "Wingull Lv 10 40%"),
        )


class MainPanelInteractionTests(unittest.TestCase):
    def test_resize_is_bounded_by_minimum_and_screen(self) -> None:
        self.assertEqual(clamp_overlay_size(100, 100, 1920, 1080), (280, 180))
        self.assertEqual(
            clamp_overlay_size(4000, 3000, 1920, 1080),
            (1896, 1056),
        )
        self.assertEqual(clamp_overlay_size(480, 640, 1920, 1080), (480, 640))

    def test_mouse_wheel_is_normalized_for_windows_and_x11(self) -> None:
        self.assertEqual(mouse_wheel_units(Mock(delta=120, num=0)), -1)
        self.assertEqual(mouse_wheel_units(Mock(delta=-240, num=0)), 2)
        self.assertEqual(mouse_wheel_units(Mock(delta=0, num=4)), -1)
        self.assertEqual(mouse_wheel_units(Mock(delta=0, num=5)), 1)

    def test_content_refresh_never_changes_native_window_geometry(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._collapsed = False
        overlay.root = Mock()
        overlay.canvas = Mock()
        overlay.canvas.bbox.return_value = (0, 0, 480, 1200)

        overlay._resize_to_content()

        overlay.root.geometry.assert_not_called()
        overlay.canvas.configure.assert_called_once_with(
            scrollregion=(0, 0, 480, 1200)
        )

    def test_native_configure_records_size_without_reasserting_geometry(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay.root = Mock()
        overlay.root.winfo_screenwidth.return_value = 1920
        overlay.root.winfo_screenheight.return_value = 1080
        overlay.canvas = Mock()
        overlay.location_label = Mock()
        overlay._section_labels = []
        overlay._row_labels = []
        overlay._window_initialized = True
        overlay._collapsed = False
        overlay._main_geometry_job = None
        event = Mock(widget=overlay.root, width=520, height=700)

        overlay._main_window_configured(event)

        self.assertEqual(overlay._manual_dimensions, (520, 700))
        self.assertEqual(overlay.WIDTH, 520)
        overlay.root.geometry.assert_not_called()


class DetailWindowTests(unittest.TestCase):
    def test_row_tooltip_metadata_can_refresh_without_rebinding(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        label = Mock()
        overlay._row_tooltips = {label: "Old details"}
        overlay._tooltip_widget = label
        overlay._show_row_tooltip = Mock()
        overlay._last_result = None
        overlay._sync_caught_filter = Mock()
        overlay._sync_map_tools = Mock()
        overlay._sync_detail_windows = Mock()
        row = PanelRow("Blaze", tooltip="New details")
        section = PanelSection("Battle", (row,))
        overlay._section_views = Mock(
            return_value=((section, (row,), 0, ("Game", "Battle")),)
        )
        overlay._layout_signature = Mock(return_value=("stable",))
        overlay._rendered_layout = ("stable",)
        overlay.game_label = Mock()
        overlay.location_label = Mock()
        overlay.status_label = Mock()
        overlay._controller = Mock()
        overlay._controller.metrics.snapshot_seconds = 0.01
        overlay._section_labels = [Mock()]
        overlay._row_labels = [label]

        overlay._render(OverlaySnapshot("Game", "Battle", (section,)))

        self.assertEqual(overlay._row_tooltips[label], "New details")
        overlay._show_row_tooltip.assert_called_once_with(label)

    def test_plain_row_can_gain_a_tooltip_on_the_fast_path(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        label = Mock()
        overlay._row_tooltips = {}
        overlay._tooltip_widget = None

        overlay._bind_row_tooltip(label, "")
        overlay._update_row_tooltip(label, "Live battle details")

        self.assertEqual(overlay._row_tooltips[label], "Live battle details")
        self.assertEqual(label.bind.call_count, 4)
        label.configure.assert_called_with(cursor="question_arrow", takefocus=True)

    def test_party_detail_rows_have_explicit_visual_roles(self) -> None:
        self.assertEqual(
            party_detail_row_role(
                "Zapdos | Electric/Flying | EXP 466,560 | 19,711 to Lv 73 | OT BB54"
            ),
            "pokemon",
        )
        self.assertEqual(party_detail_row_role("Stats | HP 219/219 | Atk 160"), "stats")
        self.assertEqual(party_detail_row_role("DVs | HP 0 | Atk 12"), "dvs")
        self.assertEqual(party_detail_row_role("Stat EXP | HP 2135 | Atk 2410"), "stat_exp")
        self.assertEqual(party_detail_row_role("Moves | Thunder 10 PP"), "moves")

    def test_party_detail_role_does_not_restyle_generic_rows(self) -> None:
        self.assertEqual(party_detail_row_role("TODO | Find the Card Key"), "generic")

    def test_completed_detail_rows_follow_hide_completed_toggle(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = True
        overlay._last_result = OverlaySnapshot(
            "Game",
            "Area",
            (),
            supports_caught_filter=True,
        )

        rows = overlay._detail_rows(
            (PanelRow("Done", True), PanelRow("Open", False), PanelRow("Info"))
        )

        self.assertEqual(rows, (PanelRow("Open", False), PanelRow("Info")))

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


class StableLayoutTests(unittest.TestCase):
    def test_walking_does_not_change_section_layout_signature(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._active_layout = None
        overlay._active_role = Mock()
        overlay._active_role.get.return_value = "area"
        overlay._layout_manager = Mock()
        overlay._layout_manager.profile.density = "comfortable"
        overlay._expanded_sections = set()
        section = PanelSection("Current objective", (PanelRow("Keep going"),))
        first = OverlaySnapshot("Game", "Main World · (10,10)", (section,))
        second = OverlaySnapshot("Game", "Main World · (11,10)", (section,))

        first_signature = overlay._layout_signature(overlay._section_views(first))
        second_signature = overlay._layout_signature(overlay._section_views(second))

        self.assertEqual(first_signature, second_signature)

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

    def test_hero_path_records_without_an_open_map_window(self) -> None:
        paths = {}
        document = MapDocument("Game", (self.wrapped_layer,))

        record_map_path(document, MapPosition("Outside", 0, 10, 12, True), paths)
        record_map_path(document, MapPosition("Outside", 0, 11, 12, True), paths)

        self.assertEqual(paths, {"surface": [(120, 136), (136, 136)]})

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

    def test_map_image_cache_evicts_and_closes_oldest_image(self) -> None:
        images = [Mock() for _ in range(5)]
        cache = {}

        for index, image in enumerate(images):
            CoordinateMapWindow._store_cached_image(cache, index, image)

        self.assertEqual(tuple(cache), (1, 2, 3, 4))
        images[0].close.assert_called_once_with()
        for image in images[1:]:
            image.close.assert_not_called()

    def test_hidden_map_updates_state_without_redrawing(self) -> None:
        document = MapDocument("Game", (self.wrapped_layer,))
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.document = document
        window.position = None
        window._indoor_map_id = None
        window._overlay_waypoints = {}
        window.mode = Mock()
        window.window = Mock()
        window.window.state.return_value = "withdrawn"
        window._destroyed = False
        window._redraw = Mock()

        position = MapPosition("Outside", 0, 10, 12, True)
        window.update(position)

        self.assertEqual(window.position, position)
        window._redraw.assert_not_called()

    def test_compact_map_draw_does_not_use_full_map_projection_scale(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        window.canvas.winfo_width.return_value = 184
        window.canvas.winfo_height.return_value = 184
        window._drawn_path_lengths = {}
        window.position = MapPosition("Outside", 0, 10, 12, True)
        window._indoor_map_id = None
        window.compact = True
        window.zoom = 1
        window.layers = {self.wrapped_layer.key: self.wrapped_layer}
        window._map_key = Mock(return_value=self.wrapped_layer.key)
        source = Mock(width=4096, height=4096)
        shifted = Mock()
        crop = Mock()
        rendered = Mock()
        shifted.crop.return_value = crop
        crop.resize.return_value = rendered
        window._image = Mock(return_value=source)
        window._set_hang_context = Mock()
        window._draw_hero_path = Mock()
        window._photo = None
        window._photo_key = None
        window.waypoint_visibility = {"player": Mock()}
        window.waypoint_visibility["player"].get.return_value = True
        window._overlay_waypoints = {}
        window.hide_completed_waypoints = Mock()
        window.credit = Mock()
        window.heading = Mock()

        with (
            patch("retroarch_overlay.ui.ImageChops.offset", return_value=shifted),
            patch("retroarch_overlay.ui.ImageTk.PhotoImage", return_value=Mock()),
        ):
            window._draw()

        window._draw_hero_path.assert_not_called()
        window.canvas.create_image.assert_called_once()
        window.canvas.create_oval.assert_called_once()

    def test_visible_fit_map_updates_only_dynamic_items_while_walking(self) -> None:
        document = MapDocument("Game", (self.wrapped_layer,))
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.document = document
        window.layers = {self.wrapped_layer.key: self.wrapped_layer}
        window.compact = False
        window.zoom = 1
        window.position = MapPosition("Outside", 0, 10, 12, True)
        window._indoor_map_id = None
        window._overlay_waypoints = {}
        window._photo = Mock()
        window.mode = Mock()
        window.mode.get.return_value = self.wrapped_layer.key
        window._is_visible = Mock(return_value=True)
        window._update_dynamic_items = Mock()
        window._redraw = Mock()

        window.update(MapPosition("Outside", 0, 11, 12, True))

        window._update_dynamic_items.assert_called_once_with()
        window._redraw.assert_not_called()

    def test_path_runs_are_chunked_into_bounded_canvas_items(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()

        with patch.object(CoordinateMapWindow, "PATH_CHUNK_POINTS", 4):
            window._create_path_run([(float(index), 0.0) for index in range(8)])

        self.assertEqual(window.canvas.create_line.call_count, 3)

    def test_region_tooltip_does_not_intercept_hover_events(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        window.canvas.create_text.return_value = 10
        window.canvas.bbox.return_value = (10, 10, 100, 50)
        region = MapRegion(0, 0, 16, 16, "Enemies", "Slime", "encounters")

        window._show_region(region, 20, 20)

        self.assertEqual(
            window.canvas.create_text.call_args.kwargs["state"],
            "disabled",
        )
        self.assertEqual(
            window.canvas.create_rectangle.call_args.kwargs["state"],
            "disabled",
        )

    def test_encounter_region_uses_full_cell_and_in_cell_roster(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        region = MapRegion(
            0,
            0,
            16,
            16,
            "Enemies",
            "Low\nSlime (Lv 1), Black Raven (Lv 2)",
            "encounters",
            "#27824a",
            "Slime Lv 1\nBlack Raven Lv 2",
            "Slime\n+1",
        )

        window._create_encounter_region(region, 10, 20, 50, 60, "region-0")

        window.canvas.create_rectangle.assert_called_once_with(
            10,
            20,
            50,
            60,
            fill="#27824a",
            stipple="gray12",
            outline="#27824a",
            width=2,
            tags=("region-0", "region", "encounter-cell"),
        )
        self.assertEqual(window.canvas.create_text.call_count, 2)
        for call in window.canvas.create_text.call_args_list:
            self.assertEqual(call.kwargs["text"], "Slime\n+1")
            self.assertEqual(call.kwargs["state"], "disabled")

    def test_zoomed_encounter_cell_lists_multiple_enemies(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        region = MapRegion(
            0,
            0,
            16,
            16,
            "Enemies",
            kind="encounters",
            label="Slime Lv 1\nBlack Raven Lv 2",
            compact_label="Slime\n+1",
        )

        window._create_encounter_region(region, 0, 0, 100, 100, "region-0")

        for call in window.canvas.create_text.call_args_list:
            self.assertEqual(
                call.kwargs["text"],
                "Slime Lv 1\nBlack Raven Lv 2",
            )

    def test_waypoint_tooltip_does_not_intercept_hover_events(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        window.canvas.create_text.return_value = 10
        window.canvas.bbox.return_value = (10, 10, 100, 50)

        window._show_waypoint(MapWaypoint(1, 2, "Shop"), 20, 20)

        self.assertEqual(
            window.canvas.create_text.call_args.kwargs["state"],
            "disabled",
        )
        self.assertEqual(
            window.canvas.create_rectangle.call_args.kwargs["state"],
            "disabled",
        )

    def test_objective_waypoint_has_persistent_marker_and_flashing_ring(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.canvas = Mock()
        waypoint = MapWaypoint(
            42,
            73,
            "Next: Tedanki",
            kind="objective",
            marker="objective",
        )

        window._create_waypoint_marker(waypoint, 100, 120, "waypoint-0")

        ring = window.canvas.create_oval.call_args
        marker = window.canvas.create_polygon.call_args
        self.assertIn("objective-flash", ring.kwargs["tags"])
        self.assertIn("objective-marker", marker.kwargs["tags"])

    def test_objective_ring_flashes_and_reschedules(self) -> None:
        window = CoordinateMapWindow.__new__(CoordinateMapWindow)
        window.window = Mock()
        window.window.state.return_value = "normal"
        window.window.after.return_value = "next-job"
        window.canvas = Mock()
        window.canvas.find_withtag.return_value = (1,)
        window._destroyed = False
        window._objective_flash_job = None
        window._objective_flash_visible = True

        window._toggle_objective_flash()

        window.canvas.itemconfigure.assert_called_once_with(
            "objective-flash", state="hidden"
        )
        window.window.after.assert_called_once_with(
            CoordinateMapWindow.OBJECTIVE_FLASH_INTERVAL_MS,
            window._toggle_objective_flash,
        )
        self.assertEqual(window._objective_flash_job, "next-job")

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