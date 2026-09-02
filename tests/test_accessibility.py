import unittest

from retroarch_overlay.infrastructure.accessibility import contrast_ratio


class PaletteContrastTests(unittest.TestCase):
    def test_body_and_action_text_meet_wcag_aa(self) -> None:
        self.assertGreaterEqual(contrast_ratio("#20251f", "#f4f1e8"), 4.5)
        self.assertGreaterEqual(contrast_ratio("#bb3e2f", "#f4f1e8"), 4.5)
        self.assertGreaterEqual(contrast_ratio("#9d1717", "#ffe9e5"), 4.5)

    def test_high_contrast_palette_exceeds_aaa(self) -> None:
        self.assertGreaterEqual(contrast_ratio("#000000", "#ffffff"), 7.0)
        self.assertGreaterEqual(contrast_ratio("#0046b8", "#ffffff"), 7.0)


if __name__ == "__main__":
    unittest.main()