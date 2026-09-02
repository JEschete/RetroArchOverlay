import json
import tempfile
import unittest
from pathlib import Path

from retroarch_overlay.local_settings import LocalPluginSettings


class LocalPluginSettingsTests(unittest.TestCase):
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

    def test_saves_and_loads_detail_window_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = LocalPluginSettings(Path(directory) / "local_settings.json")

            settings.save_detail_window_position("Emerald|POC", 42, 137)

            reloaded = LocalPluginSettings(settings.path)
            self.assertEqual(
                reloaded.detail_window_position("Emerald|POC"),
                (42, 137),
            )

    def test_ignores_malformed_detail_window_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_settings.json"
            path.write_text(
                json.dumps({"detail_window_positions": {"Emerald|POC": {"x": "42", "y": 137}}}),
                encoding="utf-8",
            )

            self.assertIsNone(
                LocalPluginSettings(path).detail_window_position("Emerald|POC")
            )


if __name__ == "__main__":
    unittest.main()