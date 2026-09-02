import tempfile
import unittest
from pathlib import Path

from retroarch_overlay.retroarch_installation import (
    network_commands_enabled,
    set_network_commands_enabled,
    supported_cores_for_console,
)


class RetroArchInstallationTests(unittest.TestCase):
    def test_derives_platform_aliases_from_ra_console(self) -> None:
        self.assertEqual(
            supported_cores_for_console("NES/Famicom"),
            ("famicom", "nes", "nes_famicom"),
        )
        self.assertEqual(
            supported_cores_for_console("Game Boy Advance"),
            ("game_boy_advance", "gba"),
        )

    def test_adds_matching_installed_retroarch_core_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = root / "info"
            info.mkdir()
            (info / "mesen_libretro.info").write_text(
                'display_name = "Mesen"\n'
                'corename = "Mesen"\n'
                'systemname = "Nintendo - Nintendo Entertainment System"\n',
                encoding="utf-8",
            )
            (info / "mgba_libretro.info").write_text(
                'display_name = "mGBA"\n'
                'systemname = "Nintendo - Game Boy Advance"\n',
                encoding="utf-8",
            )

            cores = supported_cores_for_console("NES/Famicom", root)

        self.assertIn("nes", cores)
        self.assertIn("mesen", cores)
        self.assertNotIn("mgba", cores)

    def test_enables_network_commands_and_preserves_other_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retroarch.cfg"
            path.write_text(
                'video_fullscreen = "true"\n'
                'network_cmd_enable = "false"\n'
                'network_cmd_port = "12345"\n',
                encoding="utf-8",
            )

            changed = set_network_commands_enabled(path, True, 55355)

            self.assertTrue(changed)
            self.assertTrue(network_commands_enabled(path, 55355))
            self.assertIn(
                'video_fullscreen = "true"', path.read_text(encoding="utf-8")
            )

    def test_network_command_update_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retroarch.cfg"
            path.write_text(
                'network_cmd_enable = "true"\nnetwork_cmd_port = "55355"\n',
                encoding="utf-8",
            )

            self.assertFalse(set_network_commands_enabled(path, True, 55355))

    def test_appends_missing_network_command_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retroarch.cfg"
            path.write_text('video_driver = "gl"', encoding="utf-8")

            set_network_commands_enabled(path, True, 55355)

            self.assertTrue(network_commands_enabled(path, 55355))

    def test_disables_network_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retroarch.cfg"
            path.write_text(
                'network_cmd_enable = "true"\nnetwork_cmd_port = "55355"\n',
                encoding="utf-8",
            )

            changed = set_network_commands_enabled(path, False, 55355)

            self.assertTrue(changed)
            self.assertFalse(network_commands_enabled(path, 55355))


if __name__ == "__main__":
    unittest.main()