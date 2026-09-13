import unittest

from retroarch_overlay.infrastructure.accessibility import contrast_ratio
from retroarch_overlay.presentation.theme import THEME_PALETTES


class PaletteContrastTests(unittest.TestCase):
    def test_body_and_action_text_meet_wcag_aa(self) -> None:
        self.assertGreaterEqual(contrast_ratio("#20251f", "#f4f1e8"), 4.5)
        self.assertGreaterEqual(contrast_ratio("#bb3e2f", "#f4f1e8"), 4.5)
        self.assertGreaterEqual(contrast_ratio("#9d1717", "#ffe9e5"), 4.5)

    def test_high_contrast_palette_exceeds_aaa(self) -> None:
        self.assertGreaterEqual(contrast_ratio("#000000", "#ffffff"), 7.0)
        self.assertGreaterEqual(contrast_ratio("#0046b8", "#ffffff"), 7.0)

    def test_every_semantic_text_pair_meets_wcag_aa(self) -> None:
        pairs = (
            ("foreground", "background"),
            ("muted", "background"),
            ("accent", "background"),
            ("alert_foreground", "alert_background"),
            ("header_foreground", "header_background"),
            ("success", "background"),
            ("warning", "background"),
            ("danger", "background"),
        )
        failures = []
        for name, palette in THEME_PALETTES.items():
            for foreground, background in pairs:
                ratio = contrast_ratio(palette[foreground], palette[background])
                if ratio < 4.5:
                    failures.append(
                        f"{name}: {foreground}/{background} = {ratio:.2f}"
                    )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()