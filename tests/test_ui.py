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
    clamp_opacity,
    clamped_view_origin,
    tooltip_shift,
    view_delta,
    view_origin,
    uses_marker_glyph,
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

    def test_active_tab_filters_sections_by_role(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_sections = set()
        overlay._active_role = Mock()
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
                    "Battle", (PanelRow("Wild Marill"),), role="urgent", priority=1
                ),
                PanelSection(
                    "Water",
                    (PanelRow("Marill Lv 5-15 60%"), PanelRow("Wingull Lv 10 40%")),
                    role="area",
                    compact_rows=(PanelRow("2 species"),),
                ),
            ),
        )

        overlay._active_role.get.return_value = "area"
        area_views = overlay._section_views(snapshot)
        overlay._active_role.get.return_value = "party"
        party_views = overlay._section_views(snapshot)

        self.assertEqual(
            tuple(section.title for section, _, _, _ in area_views),
            ("Battle", "Water"),
        )
        self.assertEqual(
            tuple(section.title for section, _, _, _ in party_views),
            ("Battle", "Party"),
        )
        water_rows = next(
            rows for section, rows, _, _ in area_views if section.title == "Water"
        )
        self.assertEqual(
            tuple(row.text for row in water_rows),
            ("Marill Lv 5-15 60%", "Wingull Lv 10 40%"),
        )

    def test_default_tab_shows_goals_sections_such_as_poc(self) -> None:
        # Regression: the rail defaulted to "area", which silently hid every
        # goals section, including the Professor Oak Challenge.
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_sections = set()
        overlay._active_role = Mock()
        overlay._active_role.get.return_value = "all"
        snapshot = OverlaySnapshot(
            "Pokemon Emerald",
            "Route 104",
            (
                PanelSection("Water", (PanelRow("Marill"),), role="area"),
                PanelSection("Party", (PanelRow("Marshtomp"),), role="party"),
                PanelSection(
                    "Professor Oak Challenge",
                    (PanelRow("Next: Roxanne 12/39"),),
                    role="goals",
                ),
            ),
        )

        titles = tuple(
            section.title for section, _, _, _ in overlay._section_views(snapshot)
        )

        self.assertIn("Professor Oak Challenge", titles)
        self.assertEqual(len(titles), 3)

    def test_unspecialized_sections_ignore_the_active_tab(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_sections = set()
        overlay._active_role = Mock()
        overlay._active_role.get.return_value = "party"
        snapshot = OverlaySnapshot(
            "Simple Game",
            "Area",
            (PanelSection("Status", (PanelRow("All good"),)),),
        )

        views = overlay._section_views(snapshot)

        self.assertEqual(
            tuple(section.title for section, _, _, _ in views), ("Status",)
        )


class OverlayOpacityTests(unittest.TestCase):
    def test_hover_never_makes_an_opaque_rail_transparent(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._idle_opacity = 1.0

        self.assertEqual(overlay._hover_opacity(), 1.0)

    def test_hover_lifts_a_see_through_rail_toward_legibility(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._idle_opacity = 0.5

        self.assertEqual(overlay._hover_opacity(), 0.96)

    def test_setting_opacity_clamps_and_applies_it(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay.root = Mock()

        overlay._set_opacity(0.1)

        self.assertEqual(overlay._idle_opacity, 0.3)
        overlay.root.attributes.assert_called_once_with("-alpha", 0.3)

    def test_the_overlay_defaults_to_fully_opaque(self) -> None:
        import inspect

        default = inspect.signature(OverlayWindow.__init__).parameters["opacity"].default
        self.assertEqual(default, 1.0)


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


class InlineDetailTests(unittest.TestCase):
    @staticmethod
    def _fast_path_overlay(section, row):
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._last_result = None
        overlay._sync_caught_filter = Mock()
        overlay._sync_map_tools = Mock()
        overlay._update_now_strip = Mock()
        overlay._restore_active_role = Mock()
        overlay._queue_alert_toasts = Mock()
        overlay._sync_role_tabs = Mock()
        overlay._expanded_actions = set()
        overlay._detail_filters = {}
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._section_views = Mock(
            return_value=((section, (row,), 0, ("Game", section.title)),)
        )
        overlay._layout_signature = Mock(return_value=("stable",))
        overlay._rendered_layout = ("stable",)
        overlay.game_label = Mock()
        overlay.location_label = Mock()
        overlay.status_label = Mock()
        overlay._controller = Mock()
        overlay._controller.metrics.snapshot_seconds = 0.01
        overlay._section_labels = [Mock()]
        return overlay

    def test_fast_path_updates_row_views_in_place(self) -> None:
        row = PanelRow("Blaze", tooltip="New details")
        section = PanelSection("Battle", (row,))
        overlay = self._fast_path_overlay(section, row)
        row_view = Mock()
        overlay._row_views = [row_view]

        overlay._render(OverlaySnapshot("Game", "Battle", (section,)))

        row_view.update.assert_called_once_with(row)

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

    def test_expanded_action_rows_join_the_fast_path_updates(self) -> None:
        row = PanelRow("Battle Frontier")
        detail_row = PanelRow("Tower · Lv 50 12")
        section = PanelSection(
            "Battle Frontier",
            (row,),
            actions=(PanelAction("OPEN DASHBOARD", "Dashboard", (detail_row,)),),
        )
        overlay = self._fast_path_overlay(section, row)
        overlay._expanded_actions = {
            ("Game", "Battle Frontier", "OPEN DASHBOARD")
        }
        row_view = Mock()
        detail_view = Mock()
        overlay._row_views = [row_view, detail_view]

        overlay._render(OverlaySnapshot("Game", "Route", (section,)))

        row_view.update.assert_called_once_with(row)
        detail_view.update.assert_called_once_with(detail_row)

    def test_expanding_an_action_changes_the_layout_signature(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_actions = set()
        overlay._detail_filters = {}
        section = PanelSection(
            "Section",
            (PanelRow("Row"),),
            actions=(PanelAction("OPEN", "Details", (PanelRow("Detail"),)),),
        )
        snapshot = OverlaySnapshot("Game", "Route", (section,))
        views = ((section, section.rows, 0, ("Game", "Section")),)

        collapsed = overlay._layout_signature(views, snapshot)
        overlay._expanded_actions.add(("Game", "Section", "OPEN"))
        expanded = overlay._layout_signature(views, snapshot)

        self.assertNotEqual(collapsed, expanded)

    def test_detail_filter_narrows_rows_and_signature(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_actions = {("Game", "Section", "OPEN")}
        overlay._detail_filters = {}
        rows = (PanelRow("Treecko · Route 102"), PanelRow("Marill · Route 104"))
        section = PanelSection(
            "Section",
            (PanelRow("Row"),),
            actions=(PanelAction("OPEN", "Details", rows),),
        )
        snapshot = OverlaySnapshot("Game", "Route", (section,))
        view = (section, section.rows, 0, ("Game", "Section"))

        unfiltered = overlay._flat_view_rows(view, snapshot)
        overlay._detail_filters[("Game", "Section", "OPEN")] = "marill"
        filtered = overlay._flat_view_rows(view, snapshot)

        self.assertEqual(
            [row.text for row in unfiltered],
            ["Row", "Treecko · Route 102", "Marill · Route 104"],
        )
        self.assertEqual([row.text for row in filtered], ["Row", "Marill · Route 104"])


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

    def test_expanded_action_from_one_game_does_not_leak_into_another(self) -> None:
        overlay = OverlayWindow.__new__(OverlayWindow)
        overlay._hide_caught = Mock()
        overlay._hide_caught.get.return_value = False
        overlay._expanded_actions = {("Emerald", "Section", "OPEN")}
        overlay._detail_filters = {}
        section = PanelSection(
            "Section",
            (PanelRow("Row"),),
            actions=(PanelAction("OPEN", "Details", (PanelRow("Detail"),)),),
        )
        other_game = OverlaySnapshot("Other Game", "Area", (section,))
        view = (section, section.rows, 0, ("Other Game", "Section"))

        rows = overlay._flat_view_rows(view, other_game)

        self.assertEqual([row.text for row in rows], ["Row"])


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
        crop = Mock()
        rendered = Mock()
        source.crop.return_value = crop
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

        with patch("retroarch_overlay.ui.ImageTk.PhotoImage", return_value=Mock()):
            window._draw()

        window._draw_hero_path.assert_not_called()
        window.canvas.create_image.assert_called_once()
        window.canvas.create_oval.assert_called_once()
        # The minimap crops a clamped window straight out of the source rather
        # than rotating the image, so it can never wrap past an edge.
        source.crop.assert_called_once()
        left, top, right, bottom = source.crop.call_args[0][0]
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(right, source.width)
        self.assertLessEqual(bottom, source.height)

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
        window.canvas.winfo_width.return_value = 400
        window.canvas.winfo_height.return_value = 300
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
        window.canvas.winfo_width.return_value = 400
        window.canvas.winfo_height.return_value = 300

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


class MapMarkerGlyphTests(unittest.TestCase):
    def test_explicit_marker_draws_a_glyph_for_any_kind(self) -> None:
        for kind in ("trainers", "items", "hidden_items", "feebas", "berries"):
            with self.subTest(kind=kind):
                waypoint = MapWaypoint(0, 0, "T", "", kind, False, "boss")
                self.assertTrue(uses_marker_glyph(waypoint))

    def test_npc_waypoints_keep_their_glyph_without_a_marker(self) -> None:
        self.assertTrue(uses_marker_glyph(MapWaypoint(0, 0, "N", "", "npcs")))

    def test_markerless_waypoints_keep_the_plain_dot(self) -> None:
        for kind in ("collectibles", "entrance", "encounters"):
            with self.subTest(kind=kind):
                self.assertFalse(uses_marker_glyph(MapWaypoint(0, 0, "C", "", kind)))


class MapOpacityTests(unittest.TestCase):
    def test_opacity_is_clamped_to_a_visible_range(self) -> None:
        self.assertEqual(clamp_opacity(1.5), 1.0)
        self.assertEqual(clamp_opacity(0.0), 0.3)
        self.assertEqual(clamp_opacity(0.65), 0.65)


class ClampedViewportTests(unittest.TestCase):
    def test_window_is_centred_when_it_fits(self) -> None:
        self.assertEqual(clamped_view_origin(500, 100, 1000), 450)

    def test_window_never_starts_before_the_left_edge(self) -> None:
        self.assertEqual(clamped_view_origin(10, 100, 1000), 0)

    def test_window_never_runs_past_the_right_edge(self) -> None:
        self.assertEqual(clamped_view_origin(995, 100, 1000), 900)

    def test_window_larger_than_the_image_starts_at_zero(self) -> None:
        self.assertEqual(clamped_view_origin(500, 2000, 1000), 0)

    def test_edge_windows_stay_inside_the_image_for_every_zoom(self) -> None:
        source = 640
        for zoom in (2, 4, 8, 16):
            span = source // zoom
            for centre in (0, 1, source // 2, source - 1, source + 50):
                with self.subTest(zoom=zoom, centre=centre):
                    origin = clamped_view_origin(centre, span, source)
                    self.assertGreaterEqual(origin, 0)
                    self.assertLessEqual(origin + span, source)


class TooltipClampingTests(unittest.TestCase):
    def test_tooltip_inside_the_canvas_is_left_alone(self) -> None:
        self.assertEqual(tooltip_shift((50, 50, 150, 90), 400, 300), (0.0, 0.0))

    def test_tooltip_past_the_right_edge_is_pulled_back(self) -> None:
        shift_x, _ = tooltip_shift((320, 50, 420, 90), 400, 300)
        self.assertEqual(shift_x, -26)

    def test_tooltip_above_the_top_edge_is_pushed_down(self) -> None:
        _, shift_y = tooltip_shift((50, -20, 150, 10), 400, 300)
        self.assertEqual(shift_y, 26)

    def test_tooltip_stays_inside_on_every_corner(self) -> None:
        width, height = 400, 300
        for left, top in ((-30, -30), (380, -30), (-30, 280), (380, 280)):
            with self.subTest(corner=(left, top)):
                bounds = (left, top, left + 120, top + 40)
                dx, dy = tooltip_shift(bounds, width, height)
                self.assertGreaterEqual(bounds[0] + dx, 0)
                self.assertGreaterEqual(bounds[1] + dy, 0)
                self.assertLessEqual(bounds[2] + dx, width)
                self.assertLessEqual(bounds[3] + dy, height)


class WrappingLayerTests(unittest.TestCase):
    def test_clamping_layers_stop_at_the_edge(self) -> None:
        self.assertEqual(view_origin(5, 100, 1000, False), 0)
        self.assertEqual(view_delta(20, 0, 1000, False), 20)

    def test_wrapping_layers_stay_centred_on_the_player(self) -> None:
        self.assertEqual(view_origin(5, 100, 1000, True), 955)
        self.assertEqual(view_delta(5, 955, 1000, True), 50)

    def test_wrapping_delta_takes_the_short_way_round(self) -> None:
        self.assertEqual(view_delta(2, 990, 1000, True), 12)
