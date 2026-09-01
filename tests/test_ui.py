import unittest

from retroarch_overlay.models import MapPosition, PanelAction, PanelRow, PanelSection
from retroarch_overlay.ui import (
    CoordinateMapWindow,
    filter_caught_sections,
    map_source_point,
    map_viewport,
    preview_section_rows,
    project_map_point,
    tracked_map_position,
    wrapped_map_delta,
)


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


class MapProjectionTests(unittest.TestCase):
    def test_world_source_point_uses_romaly_castle_calibration(self) -> None:
        position = MapPosition("World", 0, 53, 89, True)

        self.assertEqual(map_source_point(position, "world"), (808, 1368))

    def test_world_source_point_wraps_at_map_edges(self) -> None:
        position = MapPosition("World", 0, 2, 3, True)

        self.assertEqual(map_source_point(position, "world"), (4088, 4088))

    def test_full_map_supports_two_deeper_zoom_levels(self) -> None:
        self.assertEqual(CoordinateMapWindow.ZOOM_LEVELS, (1, 2, 4, 8, 16))

    def test_panned_marker_uses_shortest_wrapped_distance(self) -> None:
        self.assertEqual(wrapped_map_delta(10, 20, 256), -10)
        self.assertEqual(wrapped_map_delta(250, 5, 256), -11)
        self.assertEqual(wrapped_map_delta(5, 250, 256), 11)

    def test_entering_town_retains_last_overworld_position(self) -> None:
        outside = MapPosition("World", 0, 53, 89, True)
        inside = MapPosition("Dungeon / town", 0x1234, 7, 9, False)

        self.assertIs(tracked_map_position(outside, inside), outside)

    def test_leaving_town_resumes_live_world_position(self) -> None:
        previous = MapPosition("World", 0, 53, 89, True)
        current = MapPosition("World", 0, 54, 89, True)

        self.assertIs(tracked_map_position(previous, current), current)

    def test_underworld_source_point_preserves_map_border(self) -> None:
        position = MapPosition("Underworld", 0, 12, 34, True)

        self.assertEqual(map_source_point(position, "underworld"), (216, 568))

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