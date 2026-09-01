import unittest
from pathlib import Path

from retroarch_overlay.adapters.emerald.feebas import (
    feebas_spot_ids,
    load_route119_fishing_spots,
    tile_in_front,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FeebasTests(unittest.TestCase):
    def test_route119_has_game_defined_fishing_spot_count(self) -> None:
        spots = load_route119_fishing_spots(PROJECT_ROOT / "pokeemerald")
        self.assertEqual(len(spots), 447)
        self.assertEqual(set(spots.values()), set(range(1, 448)))

    def test_seed_produces_six_accessible_spots(self) -> None:
        spots = feebas_spot_ids(12345)
        self.assertEqual(len(spots), 6)
        self.assertTrue(all(4 <= spot <= 447 for spot in spots))

    def test_facing_tile_removes_map_border_offset(self) -> None:
        self.assertEqual(tile_in_front(25, 25, 2), (18, 17))


if __name__ == "__main__":
    unittest.main()