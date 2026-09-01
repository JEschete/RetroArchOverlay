import unittest

from retroarch_overlay.adapters.emerald.battle import (
    STATUS_SLEEP,
    TYPE_BUG,
    TYPE_WATER,
    ball_multiplier,
    catch_probability,
)


class BallMultiplierTests(unittest.TestCase):
    def test_conditional_ball_multipliers(self) -> None:
        common = {"level": 20, "types": (0, 0), "caught": False, "underwater": False, "turns": 0}
        self.assertEqual(ball_multiplier(6, **(common | {"types": (TYPE_BUG, TYPE_WATER)})), 30)
        self.assertEqual(ball_multiplier(7, **(common | {"underwater": True})), 35)
        self.assertEqual(ball_multiplier(8, **common), 20)
        self.assertEqual(ball_multiplier(9, **(common | {"caught": True})), 30)
        self.assertEqual(ball_multiplier(10, **(common | {"turns": 50})), 40)


class CatchProbabilityTests(unittest.TestCase):
    def test_master_ball_is_certain(self) -> None:
        self.assertEqual(catch_probability(3, 100, 100, 0, 10, master_ball=True), 1.0)

    def test_low_hp_and_sleep_improve_probability(self) -> None:
        full_hp = catch_probability(45, 100, 100, 0, 10)
        weakened = catch_probability(45, 1, 100, STATUS_SLEEP, 10)
        self.assertGreater(weakened, full_hp)
        self.assertGreater(full_hp, 0)
        self.assertLess(weakened, 1)


if __name__ == "__main__":
    unittest.main()