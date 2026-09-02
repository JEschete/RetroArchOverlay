import tempfile
import unittest
from pathlib import Path

from retroarch_overlay.retroarch_installation import supported_cores_for_console


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


if __name__ == "__main__":
    unittest.main()