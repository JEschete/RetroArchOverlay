import unittest
from pathlib import Path

from retroarch_overlay.adapters.emerald.feebas import (
    feebas_spot_ids,
    load_route119_fishing_spots,
    tile_in_front,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POKEEMERALD_ROOT = PROJECT_ROOT / "pokeemerald"
requires_pokeemerald = unittest.skipUnless(
    (POKEEMERALD_ROOT / "include" / "constants" / "metatile_behaviors.h").is_file(),
    "pokeemerald decomp checkout is not available",
)


class FeebasTests(unittest.TestCase):
    @requires_pokeemerald
    def test_route119_has_game_defined_fishing_spot_count(self) -> None:
        spots = load_route119_fishing_spots(POKEEMERALD_ROOT)
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