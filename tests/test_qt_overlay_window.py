from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QLineEdit

from retroarch_overlay.app.controller import DiagnosticCode, OverlayDiagnostic
from retroarch_overlay.app.notifications import AlertNotification
from retroarch_overlay.core.models import (
    GameDisplaySpec,
    LayoutProfile,
    MapDocument,
    MapLayer,
    MapOverlay,
    MapPosition,
    MapWaypoint,
    OverlaySnapshot,
    PanelRow,
    PanelSection,
    RetroArchStatus,
    ScreenRect,
    WindowGeometry,
)
from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.presentation.qt import QtOverlayWindow, QtResponsiveLayoutManager
from retroarch_overlay.presentation.theme import THEME_PALETTES


class StubController:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.starts = 0
        self.stops = 0
        self.content_key: tuple[str, str, str] | None = None
        self.last_status: RetroArchStatus | None = None

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def drain_latest(self) -> object | None:
        if not self.events:
            return None
        latest = self.events[-1]
        self.events.clear()
        return latest


def _snapshot(game: str = "Game", value: str = "One") -> OverlaySnapshot:
    return OverlaySnapshot(
        game,
        "Area",
        (
            PanelSection("Urgent", (PanelRow("Warning"),), role="urgent", key="urgent"),
            PanelSection("Party", (PanelRow(value),), role="party", key="party"),
            PanelSection("Goals", (PanelRow("Goal"),), role="goals", key="goals"),
        ),
        supports_caught_filter=True,
    )


def test_bridge_event_renders_snapshot_with_exact_content_scope(qtbot) -> None:
    controller = StubController()
    controller.content_key = ("core", "path/to/game", "12345678")
    controller.events.append(_snapshot())
    window = QtOverlayWindow(controller, bridge_interval_ms=1)
    qtbot.addWidget(window)

    window.start()
    qtbot.waitUntil(lambda: window.location_label.text() == "Area")

    assert controller.starts == 1
    assert window.game_label.text() == "GAME"
    assert window.status_label.text() == "Live · read-only"
    assert window.document_view.state.content_scope == (
        '["core","path/to/game","12345678"]'
    )
    assert not window.document_view.isHidden()


def test_identical_snapshot_skips_work_only_within_the_same_content_scope(
    qtbot,
    monkeypatch,
) -> None:
    controller = StubController()
    controller.content_key = ("core", "first", "11111111")
    window = QtOverlayWindow(controller)
    qtbot.addWidget(window)
    window.show()
    snapshot = _snapshot()
    window.render_event(snapshot)
    original = window.document_view.set_snapshot
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(window.document_view, "set_snapshot", record)

    window.render_event(snapshot)
    assert calls == []

    controller.content_key = ("core", "second", "22222222")
    window.render_event(snapshot)
    assert len(calls) == 1
    assert window.document_view.state.content_scope == (
        '["core","second","22222222"]'
    )


def test_escape_collapses_to_header_and_restores_expanded_geometry(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.setGeometry(40, 50, 360, 640)
    window.show()
    window.render_event(_snapshot())

    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert window._collapsed
    assert window.header.isVisible()
    assert window.status_label.isHidden()
    assert window.urgent_strip.isHidden()
    assert window.document_view.isHidden()
    assert window.height() == window.header.sizeHint().height()

    qtbot.keyClick(window, Qt.Key.Key_Escape)

    assert not window._collapsed
    assert window.geometry().getRect() == (40, 50, 360, 640)
    assert window.status_label.isVisible()
    assert window.urgent_strip.isVisible()
    assert window.document_view.isVisible()


def test_numeric_role_shortcuts_do_not_capture_text_input(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())

    qtbot.keyClick(window, Qt.Key.Key_3)
    assert window.document_view.state.active_role == "party"

    editor = QLineEdit(window)
    editor.show()
    editor.setFocus()
    qtbot.keyClicks(editor, "4")

    assert editor.text() == "4"
    assert window.document_view.state.active_role == "party"


def test_page_shortcuts_scroll_the_main_document(qtbot) -> None:
    sections = tuple(
        PanelSection(
            f"Section {index}",
            tuple(PanelRow(f"Row {row}") for row in range(8)),
            preview_limit=8,
            key=f"section-{index}",
        )
        for index in range(8)
    )
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.resize(320, 240)
    window.show()
    window.render_event(OverlaySnapshot("Game", "Area", sections))
    scroll_bar = window.document_view.verticalScrollBar()
    qtbot.waitUntil(lambda: scroll_bar.maximum() > 0)

    qtbot.keyClick(window, Qt.Key.Key_PageDown)
    assert scroll_bar.value() > 0
    qtbot.keyClick(window, Qt.Key.Key_PageUp)
    assert scroll_bar.value() == 0


def test_role_controls_follow_visual_tab_order(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())
    window.activateWindow()
    window.role_buttons["all"].setFocus()

    qtbot.keyClick(window.role_buttons["all"], Qt.Key.Key_Tab)

    assert window.focusWidget() is window.role_buttons["area"]


def test_typed_diagnostic_hides_snapshot_content(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())

    window.render_event(
        OverlayDiagnostic(
            DiagnosticCode.CONNECTION_FAILED,
            "Not connected",
            "RetroArch did not respond",
        )
    )

    assert window.location_label.text() == "Not connected"
    assert window.status_label.text() == "RetroArch did not respond"
    assert window.document_view.isHidden()
    assert window.controls.isHidden()
    assert window.urgent_strip.isHidden()


def test_urgent_summary_is_pinned_and_new_alert_is_queued(qtbot) -> None:
    controller = StubController()
    controller.content_key = ("core", "game", "crc")
    window = QtOverlayWindow(controller)
    qtbot.addWidget(window)
    window.show()

    first = _snapshot()
    window.render_event(first)

    assert window.urgent_strip.isVisible()
    assert window.urgent_label.text() == "URGENT · Warning"
    assert window.toast_queue.active is None

    alert = PanelSection(
        "Low health",
        (PanelRow("Heal now"),),
        alert=True,
        priority=1,
        key="low-health",
    )
    window.render_event(replace(first, sections=first.sections + (alert,)))

    assert window.urgent_label.text() == "LOW HEALTH · Heal now"
    assert window.toast_queue.active == AlertNotification("Low health", "Heal now")
    assert window.toast_queue.visible


def test_dynamic_shell_values_reach_the_accessibility_interface(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())

    expected = (
        (window.game_label, "GAME", "Active game"),
        (window.location_label, "Area", "Current location or status"),
        (window.status_label, "Live · read-only", "Connection status"),
        (window.urgent_label, "Urgent: Warning", "Urgent summary"),
    )
    for widget, name, description in expected:
        interface = QAccessible.queryAccessibleInterface(widget)
        assert interface is not None
        assert interface.text(QAccessible.Text.Name) == name
        assert interface.text(QAccessible.Text.Description) == description


def test_role_selection_is_remembered_per_game(qtbot) -> None:
    controller = StubController()
    window = QtOverlayWindow(controller)
    qtbot.addWidget(window)
    window.show()
    controller.content_key = ("core", "first", "11111111")
    window.render_event(_snapshot("First"))
    window.role_buttons["party"].click()
    assert [view.section.key for view in window.document_view.state.section_views] == [
        "urgent",
        "party",
    ]

    controller.content_key = ("core", "second", "22222222")
    window.render_event(_snapshot("Second"))
    assert window.document_view.state.active_role == "all"

    controller.content_key = ("core", "first", "11111111")
    window.render_event(_snapshot("First", "Updated"))
    assert window.document_view.state.active_role == "party"
    assert window.role_buttons["party"].isChecked()


def test_close_stops_bridge_and_controller_once(qtbot) -> None:
    controller = StubController()
    window = QtOverlayWindow(controller)
    qtbot.addWidget(window)
    window.start()

    assert window._layout_timer.isActive()
    window.toast_queue.enqueue((AlertNotification("Alert"),))
    assert window.toast_queue._timer.isActive()

    window.close()
    window.close()

    assert controller.stops == 1
    assert not window.bridge.is_running
    assert not window._layout_timer.isActive()
    assert not window.toast_queue._timer.isActive()


def test_theme_propagates_to_document_rows_and_can_change_at_runtime(qtbot) -> None:
    window = QtOverlayWindow(StubController(), theme="high-contrast")
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())
    section_state = window.document_view.state.section_views[0]
    section = window.document_view.section_widget(section_state.identity)
    assert section is not None

    assert window.theme_name == "high-contrast"
    assert section.row_view.row_delegate.theme_name == "high-contrast"
    assert window.palette().window().color().name() == "#ffffff"

    resolved = window.set_theme("dark")

    assert resolved == "dark"
    assert section.row_view.row_delegate.theme_name == "dark"
    assert window.palette().window().color().name() == THEME_PALETTES["dark"]["background"]
    assert window.urgent_strip.palette().window().color().name() == THEME_PALETTES["dark"][
        "alert_background"
    ]
    assert window.toast_queue._frame.palette().window().color().name() == THEME_PALETTES[
        "dark"
    ]["alert_background"]


def test_real_settings_restore_legacy_state_and_save_qt_geometry(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    settings.save_theme("high-contrast")
    settings.save_overlay_opacity(0.65)
    settings.save_active_role("Game", "party")
    settings.save_window_geometry("main", ScreenRect(40, 50, 400, 700))
    settings.save_window_geometry("main-native", ScreenRect(0, 0, 420, 600))
    controller = StubController()
    window = QtOverlayWindow(controller, opacity=1.0, settings=settings)
    qtbot.addWidget(window)
    window.show()
    window.render_event(_snapshot())

    assert window.theme_name == "high-contrast"
    assert window.windowOpacity() == pytest.approx(0.65, abs=1 / 255)
    assert window.geometry().getRect() == (40, 50, 420, 600)
    assert window.document_view.state.active_role == "party"

    window.role_buttons["goals"].click()
    window.setGeometry(60, 70, 440, 620)
    window.close()

    reloaded = LocalPluginSettings(settings.path)
    assert reloaded.active_role("Game") == "goals"
    assert reloaded.window_geometry("main-qt") == ScreenRect(60, 70, 500, 690)
    assert reloaded.window_geometry("main") == ScreenRect(40, 50, 400, 700)


def test_overlay_is_topmost_by_default(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)

    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


class GeometryProvider:
    def __init__(self, geometry: WindowGeometry) -> None:
        self.geometry = geometry
        self.placements: list[tuple[int, ScreenRect]] = []

    def retroarch_geometry(self) -> WindowGeometry:
        return self.geometry

    def place_window(self, handle: int, rect: ScreenRect) -> bool:
        self.placements.append((handle, rect))
        return True


def _window_geometry(*, resizable: bool) -> WindowGeometry:
    return WindowGeometry(
        42,
        ScreenRect(95, 70, 1605, 990),
        ScreenRect(100, 100, 1600, 980),
        ScreenRect(0, 0, 1920, 1080),
        96,
        resizable,
    )


def test_live_rail_layout_restores_retroarch_and_preserves_unmanaged_geometry(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    original_qt = ScreenRect(40, 50, 460, 650)
    settings.save_window_geometry("main-qt", original_qt)
    settings.save_layout_profile(LayoutProfile(mode="auto"))
    provider = GeometryProvider(_window_geometry(resizable=True))
    manager = QtResponsiveLayoutManager(settings.layout_profile(), provider)
    controller = StubController()
    controller.content_key = ("core", "game", "crc")
    controller.last_status = RetroArchStatus("PLAYING", "core", "game", "crc")
    window = QtOverlayWindow(
        controller,
        settings=settings,
        layout_manager=manager,
    )
    qtbot.addWidget(window)
    window.show()
    snapshot = replace(
        _snapshot(),
        display_spec=GameDisplaySpec("nes", 256, 240),
    )

    window.render_event(snapshot)

    assert manager.current is not None
    assert manager.current.mode == "rail"
    assert window.frameGeometry().getRect() == (1560, 0, 360, 1080)
    assert provider.placements[0][0] == 42
    window.close()

    assert provider.placements[-1] == (42, ScreenRect(95, 70, 1605, 990))
    assert LocalPluginSettings(settings.path).window_geometry("main-qt") == original_qt


def test_dragging_managed_overlay_undocks_and_preserves_manual_geometry(
    qtbot,
) -> None:
    provider = GeometryProvider(_window_geometry(resizable=True))
    manager = QtResponsiveLayoutManager(LayoutProfile(mode="auto"), provider)
    controller = StubController()
    controller.content_key = ("core", "game", "crc")
    controller.last_status = RetroArchStatus("PLAYING", "core", "game", "crc")
    window = QtOverlayWindow(controller, layout_manager=manager)
    qtbot.addWidget(window)
    window.show()
    window.render_event(
        replace(_snapshot(), display_spec=GameDisplaySpec("nes", 256, 240))
    )

    window.header.drag_started.emit()
    window.move(80, 90)
    window._refresh_layout()

    assert manager.current is None
    assert window._manual_layout_override
    assert window.frameGeometry().topLeft().x() == 80
    assert provider.placements[-1] == (42, ScreenRect(95, 70, 1605, 990))


def test_dual_strip_layout_renders_compact_secondary_window(qtbot) -> None:
    provider = GeometryProvider(_window_geometry(resizable=False))
    manager = QtResponsiveLayoutManager(LayoutProfile(mode="dual-strips"), provider)
    controller = StubController()
    controller.content_key = ("core", "game", "crc")
    controller.last_status = RetroArchStatus("PLAYING", "core", "game", "crc")
    window = QtOverlayWindow(controller, layout_manager=manager)
    qtbot.addWidget(window)
    window.show()
    snapshot = replace(
        _snapshot(),
        display_spec=GameDisplaySpec("gba", 240, 160),
    )

    window.render_event(snapshot)

    assert manager.current is not None
    assert manager.current.mode == "dual-strips"
    assert window._secondary_window is not None
    assert window._secondary_window.isVisible()
    assert window._secondary_window.geometry().getRect() == (0, 0, 150, 1080)
    assert [
        view.section.key for view in window._secondary_window.document_view.state.section_views
    ] == ["urgent", "party", "goals"]
    assert all(button.isHidden() for button in window.role_buttons.values())

    manager.profile = LayoutProfile(mode="overlay", manage_retroarch_window=False)
    window._refresh_layout()

    assert window._secondary_window.isHidden()
    assert all(button.isVisible() for button in window.role_buttons.values())
    window.close()


def _map_snapshot(tmp_path: Path, *, title: str = "Atlas", x: int = 1) -> OverlaySnapshot:
    image = tmp_path / f"{title}.png"
    Image.new("RGB", (64, 64), (20, 40, 60)).save(image)
    layer = MapLayer(
        "world",
        "World",
        "Outside",
        image,
        waypoints=(MapWaypoint(2, 2, "Shop", kind="entrance"),),
    )
    return replace(
        _snapshot(),
        map_position=MapPosition("Outside", 0, x, 1, True),
        map_document=MapDocument(title, (layer,), ("entrance",)),
        map_overlays=(MapOverlay("world", (MapWaypoint(3, 3, "Goal", kind="objective"),)),),
    )


def test_map_tools_record_hidden_path_and_open_map_and_minimap(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    controller = StubController()
    controller.content_key = ("core", "game", "crc")
    window = QtOverlayWindow(controller, settings=settings)
    qtbot.addWidget(window)
    window.show()

    window.render_event(_map_snapshot(tmp_path))

    assert window.map_button.isVisible()
    assert window.minimap_button.isVisible()
    assert window._map_window is None
    assert window._minimap_window is None
    assert window._hero_paths == {"world": [(16, 16)]}

    window._map_shortcut.activated.emit()
    window._minimap_shortcut.activated.emit()

    assert window._map_window is not None and window._map_window.isVisible()
    assert window._minimap_window is not None and window._minimap_window.isVisible()
    assert window._map_window.map_view.visible_waypoints()[0].title == "Shop"

    window.render_event(_map_snapshot(tmp_path, x=2))
    assert window._hero_paths == {"world": [(16, 16), (32, 16)]}
    assert window._map_window.map_view.position == MapPosition("Outside", 0, 2, 1, True)

    window.close()
    assert LocalPluginSettings(settings.path).hero_paths("Atlas") == {
        "world": [(16, 16), (32, 16)]
    }


def test_changed_map_document_retires_old_windows_and_diagnostic_clears_tools(
    qtbot,
    tmp_path: Path,
) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.render_event(_map_snapshot(tmp_path, title="First"))
    window.map_button.click()
    first = window._map_window
    assert first is not None

    window.render_event(_map_snapshot(tmp_path, title="Second"))

    assert window._map_window is None
    assert first.isHidden()
    assert window.map_button.isVisible()

    window.render_event(
        OverlayDiagnostic(
            DiagnosticCode.CONNECTION_FAILED,
            "Not connected",
            "Offline",
        )
    )

    assert window._map_document is None
    assert window.map_button.isHidden()
    assert window.minimap_button.isHidden()
    window.close()