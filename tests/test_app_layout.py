from retroarch_overlay.app.layout import CompanionLayoutManager
from retroarch_overlay.core.models import (
    GameDisplaySpec,
    LayoutProfile,
    ScreenRect,
    WindowGeometry,
)


class Target:
    def __init__(self, work_area: ScreenRect) -> None:
        self.work_area = work_area
        self.geometries: list[ScreenRect] = []

    def available_work_area(self) -> ScreenRect:
        return self.work_area

    def set_geometry(self, rect: ScreenRect) -> None:
        self.geometries.append(rect)


class Provider:
    def __init__(self, geometry: WindowGeometry | None) -> None:
        self.geometry = geometry
        self.placements: list[tuple[int, ScreenRect]] = []
        self.place_result = True

    def retroarch_geometry(self) -> WindowGeometry | None:
        return self.geometry

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        self.placements.append((handle, rect))
        return self.place_result


def _geometry(handle: int, window: ScreenRect | None = None) -> WindowGeometry:
    return WindowGeometry(
        handle,
        window or ScreenRect(95, 70, 1605, 990),
        ScreenRect(100, 100, 1600, 980),
        ScreenRect(0, 0, 1920, 1080),
        96,
        True,
    )


def test_unchanged_layout_does_not_reassert_target_geometry() -> None:
    target = Target(ScreenRect(0, 0, 1920, 1080))
    manager = CompanionLayoutManager(LayoutProfile(mode="overlay"), Provider(None))
    display = GameDisplaySpec("gba", 240, 160)

    first = manager.apply(target, display)
    second = manager.apply(target, display)

    assert first[1]
    assert not second[1]
    assert target.geometries == [ScreenRect(1560, 0, 1920, 1080)]


def test_failed_native_placement_is_retried() -> None:
    provider = Provider(_geometry(42))
    provider.place_result = False
    manager = CompanionLayoutManager(LayoutProfile(), provider)
    target = Target(ScreenRect(0, 0, 1920, 1080))
    display = GameDisplaySpec("gba", 240, 160)

    manager.apply(target, display)
    manager.apply(target, display)

    assert len(provider.placements) == 2


def test_new_retroarch_handle_gets_its_own_managed_placement() -> None:
    provider = Provider(_geometry(42))
    manager = CompanionLayoutManager(LayoutProfile(), provider)
    target = Target(ScreenRect(0, 0, 1920, 1080))
    display = GameDisplaySpec("gba", 240, 160)
    manager.apply(target, display)

    provider.geometry = _geometry(84, ScreenRect(200, 150, 1700, 1050))
    manager.apply(target, display)

    assert [handle for handle, _ in provider.placements] == [42, 84]
    manager.close()
    assert provider.placements[-1] == (84, ScreenRect(200, 150, 1700, 1050))


def test_restoration_clears_baseline_for_later_management_session() -> None:
    provider = Provider(_geometry(42))
    manager = CompanionLayoutManager(LayoutProfile(), provider)
    target = Target(ScreenRect(0, 0, 1920, 1080))
    display = GameDisplaySpec("gba", 240, 160)
    manager.apply(target, display)
    manager.restore_retroarch_window()

    later = ScreenRect(300, 200, 1800, 1100)
    provider.geometry = _geometry(42, later)
    manager.apply(target, display)
    manager.close()

    assert provider.placements[-1] == (42, later)