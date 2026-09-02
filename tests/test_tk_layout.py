import unittest

from retroarch_overlay.models import GameDisplaySpec, LayoutProfile, ScreenRect, WindowGeometry
from retroarch_overlay.presentation.tk.layout import ResponsiveLayoutManager


class Target:
    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.width = width
        self.height = height
        self.values: list[str] = []

    def geometry(self, value: str) -> None:
        self.values.append(value)

    def winfo_screenwidth(self) -> int:
        return self.width

    def winfo_screenheight(self) -> int:
        return self.height


class Provider:
    def __init__(self, geometry: WindowGeometry | None) -> None:
        self.geometry = geometry
        self.placements: list[tuple[int, ScreenRect]] = []

    def retroarch_geometry(self) -> WindowGeometry | None:
        return self.geometry

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        self.placements.append((handle, rect))
        return True


class ResponsiveLayoutManagerTests(unittest.TestCase):
    def test_auto_uses_overlay_without_retroarch_window(self) -> None:
        manager = ResponsiveLayoutManager(LayoutProfile(), Provider(None))

        layout, _ = manager.apply(Target(), GameDisplaySpec("gba", 240, 160))

        self.assertEqual(layout.mode, "overlay")
        self.assertEqual(layout.primary_panel.width, 360)

    def test_auto_uses_rail_and_accounts_for_window_chrome(self) -> None:
        geometry = WindowGeometry(
            42,
            ScreenRect(95, 70, 1605, 990),
            ScreenRect(100, 100, 1600, 980),
            ScreenRect(0, 0, 1920, 1080),
            96,
            True,
        )
        provider = Provider(geometry)
        manager = ResponsiveLayoutManager(LayoutProfile(), provider)

        layout, _ = manager.apply(Target(), GameDisplaySpec("gba", 240, 160))

        self.assertEqual(layout.mode, "rail")
        self.assertEqual(
            provider.placements,
            [(42, ScreenRect(-5, -30, 1565, 1090))],
        )

    def test_narrow_pillarboxes_fall_back_to_overlay(self) -> None:
        manager = ResponsiveLayoutManager(LayoutProfile(), Provider(None))

        layout, _ = manager.apply(Target(1366, 768), GameDisplaySpec("gba", 240, 160))

        self.assertEqual(layout.mode, "overlay")
        self.assertEqual(layout.primary_panel.width, 360)


if __name__ == "__main__":
    unittest.main()