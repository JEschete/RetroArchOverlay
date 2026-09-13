import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.models import LayoutProfile, ScreenRect


class LocalPluginSettingsTests(unittest.TestCase):
    def test_failed_atomic_replace_preserves_existing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            settings = LocalPluginSettings(path)
            settings.save_theme("light")
            original = path.read_bytes()

            with (
                patch(
                    "retroarch_overlay.local_settings.os.replace",
                    side_effect=OSError("replace failed"),
                ),
                self.assertRaisesRegex(OSError, "replace failed"),
            ):
                settings.save_theme("dark")

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(tuple(Path(directory).glob("*.tmp")), ())

    def test_failed_hero_path_replace_preserves_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            settings.save_hero_paths("Game", {"world": [(1, 2)]})
            path = settings.hero_paths_path()
            original = path.read_bytes()

            with (
                patch(
                    "retroarch_overlay.local_settings.os.replace",
                    side_effect=OSError("replace failed"),
                ),
                self.assertRaisesRegex(OSError, "replace failed"),
            ):
                settings.save_hero_paths("Game", {"world": [(3, 4)]})

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(tuple(Path(directory).glob("*.tmp")), ())

    def test_saves_retroarch_folder_and_resolves_config_outside_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            retroarch = root / "RetroArch"
            retroarch.mkdir()
            config = retroarch / "retroarch.cfg"
            config.write_text('network_cmd_enable = "true"\n', encoding="utf-8")
            settings = LocalPluginSettings(root / "profile" / "local_settings.json")

            settings.save_retroarch_path(retroarch)

            self.assertEqual(settings.retroarch_path(), retroarch.resolve())
            self.assertEqual(settings.retroarch_config(), config.resolve())

    def test_rejects_retroarch_folder_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = LocalPluginSettings(root / "local_settings.json")

            with self.assertRaisesRegex(FileNotFoundError, "retroarch.cfg"):
                settings.save_retroarch_path(root)

    def test_saves_only_external_rom_path_in_local_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "RAO_game"
            repository.mkdir()
            manifest = repository / "plugin.toml"
            manifest.write_text('plugin_id = "org.example.game"\n', encoding="utf-8")
            rom = root / "roms" / "game.nes"
            rom.parent.mkdir()
            rom.write_bytes(b"ROM data")
            settings_path = root / "profile" / "local_settings.json"
            settings = LocalPluginSettings(settings_path)

            settings.save_rom_path("org.example.game", rom)

            self.assertEqual(settings.rom_path("org.example.game"), rom.resolve())
            self.assertEqual(tuple(repository.iterdir()), (manifest,))
            self.assertEqual(manifest.read_text(encoding="utf-8"), 'plugin_id = "org.example.game"\n')
            self.assertEqual(rom.read_bytes(), b"ROM data")
            document = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(document["plugins"]["org.example.game"]["rom_path"], str(rom.resolve()))

    def test_blank_rom_path_removes_plugin_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rom = root / "game.gba"
            rom.write_bytes(b"ROM data")
            settings = LocalPluginSettings(root / "local_settings.json")
            settings.save_rom_path("org.example.game", rom)

            settings.save_rom_path("org.example.game", None)

            self.assertIsNone(settings.rom_path("org.example.game"))

    def test_rejects_missing_rom_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            with self.assertRaises(FileNotFoundError):
                settings.save_rom_path("org.example.game", Path(directory) / "missing.nes")

    def test_saves_rom_and_save_paths_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rom = root / "game.nes"
            save = root / "game.srm"
            rom.write_bytes(b"ROM")
            save.write_bytes(b"SRAM")
            settings = LocalPluginSettings(root / "local_settings.json")

            settings.save_rom_path("org.example.game", rom)
            settings.save_save_path("org.example.game", save)
            settings.save_rom_path("org.example.game", None)

            self.assertIsNone(settings.rom_path("org.example.game"))
            self.assertEqual(settings.save_path("org.example.game"), save.resolve())

    def test_saves_layout_and_window_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            profile = LayoutProfile(
                mode="rail",
                rail_side="left",
                rail_width=380,
                density="normal",
                game_scaling="integer",
            )
            rect = ScreenRect(10, 20, 390, 900)

            settings.save_layout_profile(profile)
            settings.save_window_geometry("main", rect)
            settings.save_high_contrast_override(True)
            reloaded = LocalPluginSettings(settings.path)

            self.assertEqual(reloaded.layout_profile(), profile)
            self.assertEqual(reloaded.window_geometry("main"), rect)
            self.assertTrue(reloaded.high_contrast_override())

    def test_malformed_json_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            path.write_text("{broken", encoding="utf-8")

            settings = LocalPluginSettings(path)

            self.assertEqual(settings.layout_profile(), LayoutProfile())
            self.assertIsNone(settings.rom_path("org.example.game"))


class ThemeAndRoleTests(unittest.TestCase):
    def test_overlay_preferences_are_saved_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            profile = LayoutProfile(
                mode="rail",
                rail_side="left",
                rail_width=420,
                density="normal",
                game_scaling="integer",
                manage_retroarch_window=False,
            )

            settings.save_overlay_preferences(profile, "dark", 0.75)

            reloaded = LocalPluginSettings(settings.path)
            self.assertEqual(reloaded.layout_profile(), profile)
            self.assertEqual(reloaded.theme(), "dark")
            self.assertEqual(reloaded.overlay_opacity(), 0.75)

    def test_theme_defaults_to_auto_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            self.assertEqual(settings.theme(), "auto")
            settings.save_theme("dark")

            self.assertEqual(LocalPluginSettings(settings.path).theme(), "dark")

    def test_legacy_high_contrast_flag_migrates_to_a_theme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            settings.save_high_contrast_override(True)

            self.assertEqual(
                LocalPluginSettings(settings.path).theme(), "high-contrast"
            )

    def test_an_explicit_theme_wins_over_the_legacy_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            settings.save_high_contrast_override(True)
            settings.save_theme("light")

            self.assertEqual(LocalPluginSettings(settings.path).theme(), "light")

    def test_overlay_opacity_round_trips_and_clamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            self.assertIsNone(settings.overlay_opacity())
            settings.save_overlay_opacity(0.85)
            self.assertEqual(
                LocalPluginSettings(settings.path).overlay_opacity(), 0.85
            )

            settings.save_overlay_opacity(5.0)
            self.assertEqual(LocalPluginSettings(settings.path).overlay_opacity(), 1.0)

    def test_out_of_range_stored_opacity_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            path.write_text(json.dumps({"overlay_opacity": 0.05}), encoding="utf-8")

            self.assertIsNone(LocalPluginSettings(path).overlay_opacity())

    def test_active_role_is_remembered_per_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            settings.save_active_role("Pokémon Emerald", "goals")
            settings.save_active_role("Dragon Warrior III", "party")

            reloaded = LocalPluginSettings(settings.path)
            self.assertEqual(reloaded.active_role("Pokémon Emerald"), "goals")
            self.assertEqual(reloaded.active_role("Dragon Warrior III"), "party")
            self.assertIsNone(reloaded.active_role("Unplayed Game"))

    def test_a_nameless_game_does_not_create_a_role_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            settings.save_active_role("", "goals")

            self.assertIsNone(LocalPluginSettings(settings.path).active_role(""))


class MapViewStateTests(unittest.TestCase):
    def test_map_view_state_round_trips_per_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")
            state = {
                "layer": "route119",
                "overlays": {"trainers": False, "items": True},
                "hide_completed": True,
                "opacity": 0.75,
            }

            settings.save_map_view_state("map", state)

            self.assertEqual(settings.map_view_state("map"), state)
            self.assertEqual(settings.map_view_state("minimap"), {})

    def test_map_view_state_survives_a_new_settings_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            LocalPluginSettings(path).save_map_view_state("map", {"opacity": 0.5})

            self.assertEqual(
                LocalPluginSettings(path).map_view_state("map"), {"opacity": 0.5}
            )

    def test_corrupt_map_view_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            path.write_text(json.dumps({"map_view_states": "nonsense"}), encoding="utf-8")

            self.assertEqual(LocalPluginSettings(path).map_view_state("map"), {})


if __name__ == "__main__":
    unittest.main()
