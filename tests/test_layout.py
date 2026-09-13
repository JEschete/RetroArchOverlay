import unittest

from retroarch_overlay.core.layout import (
    compute_companion_layout,
    constrain_window_rect,
    sections_for_role,
)
from retroarch_overlay.infrastructure.windows_geometry import _is_retroarch_window
from retroarch_overlay.models import GameDisplaySpec, LayoutProfile, PanelSection, ScreenRect


class CompanionLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.screen = ScreenRect(0, 0, 1920, 1080)
        self.profile = LayoutProfile(mode="rail", rail_width=360)

    def test_4_3_game_fits_full_height_beside_rail(self) -> None:
        display = GameDisplaySpec("nes", 4, 3)

        layout = compute_companion_layout(self.screen, display, self.profile)

        self.assertEqual(layout.game_region, ScreenRect(0, 0, 1560, 1080))
        self.assertEqual(layout.game_viewport, ScreenRect(60, 0, 1500, 1080))
        self.assertEqual(layout.primary_panel, ScreenRect(1560, 0, 1920, 1080))

    def test_gba_integer_mode_uses_pixel_perfect_6x(self) -> None:
        display = GameDisplaySpec("gba", 240, 160, "integer", 6)

        layout = compute_companion_layout(self.screen, display, self.profile)

        self.assertEqual(layout.game_viewport, ScreenRect(60, 60, 1500, 1020))

    def test_gba_fill_mode_uses_available_width(self) -> None:
        display = GameDisplaySpec("gba", 240, 160, "fit")

        layout = compute_companion_layout(self.screen, display, self.profile)

        self.assertEqual(layout.game_viewport, ScreenRect(0, 20, 1560, 1060))

    def test_dual_strips_use_existing_pillarboxes(self) -> None:
        display = GameDisplaySpec("gba", 240, 160, "fit")
        profile = LayoutProfile(mode="dual-strips", rail_side="right")

        layout = compute_companion_layout(self.screen, display, profile)

        self.assertEqual(layout.secondary_panel, ScreenRect(0, 0, 150, 1080))
        self.assertEqual(layout.primary_panel, ScreenRect(1770, 0, 1920, 1080))

    def test_auto_mode_becomes_pause_drawer_while_paused(self) -> None:
        display = GameDisplaySpec("gba", 240, 160, "fit")

        layout = compute_companion_layout(
            self.screen, display, LayoutProfile(), paused=True
        )

        self.assertEqual(layout.mode, "pause-drawer")
        self.assertEqual(layout.primary_panel, ScreenRect(768, 0, 1920, 1080))


class WindowRestoreTests(unittest.TestCase):
    def test_keeps_valid_geometry_on_its_existing_monitor(self) -> None:
        areas = (
            ScreenRect(-1920, 0, 0, 1080),
            ScreenRect(0, 0, 1920, 1040),
        )

        self.assertEqual(
            constrain_window_rect(ScreenRect(-1800, 100, -1400, 700), areas),
            ScreenRect(-1800, 100, -1400, 700),
        )

    def test_moves_removed_monitor_geometry_to_nearest_available_area(self) -> None:
        areas = (ScreenRect(0, 0, 1920, 1040),)

        self.assertEqual(
            constrain_window_rect(ScreenRect(2300, 200, 2700, 800), areas),
            ScreenRect(1520, 200, 1920, 800),
        )

    def test_clamps_oversized_window_to_work_area(self) -> None:
        areas = (ScreenRect(100, 50, 900, 650),)

        self.assertEqual(
            constrain_window_rect(ScreenRect(-100, -100, 1300, 900), areas),
            ScreenRect(100, 50, 900, 650),
        )


class WindowsGeometryMatchingTests(unittest.TestCase):
    def test_does_not_match_overlay_window(self) -> None:
        self.assertFalse(_is_retroarch_window("TkTopLevel", "RetroArch Overlay"))
        self.assertTrue(_is_retroarch_window("RetroArch", "Pokemon Emerald"))


class SemanticSectionTests(unittest.TestCase):
    def test_urgent_sections_are_visible_in_every_role(self) -> None:
        sections = (
            PanelSection("Alert", (), role="urgent"),
            PanelSection("Route", (), role="area"),
            PanelSection("Party", (), role="party"),
            PanelSection("POC", (), role="goals"),
        )

        self.assertEqual(
            tuple(section.title for section in sections_for_role(sections, "party")),
            ("Alert", "Party"),
        )
        self.assertEqual(
            tuple(section.title for section in sections_for_role(sections, "goals")),
            ("Alert", "POC"),
        )

    def test_all_keeps_every_section_including_goals(self) -> None:
        sections = (
            PanelSection("Alert", (), role="urgent"),
            PanelSection("Route", (), role="area"),
            PanelSection("Party", (), role="party"),
            PanelSection("Professor Oak Challenge", (), role="goals"),
        )

        self.assertEqual(sections_for_role(sections, "all"), sections)


if __name__ == "__main__":
    unittest.main()