import json
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt

from retroarch_overlay.app.dashboard import DashboardStore
from retroarch_overlay.presentation.qt import (
    QtDashboardCardsView,
    QtDashboardMapView,
    QtDashboardOverviewView,
    QtDashboardRecordsView,
    QtDashboardWindow,
)


def _documents(tmp_path: Path) -> tuple[DashboardStore, dict, dict]:
    image_path = tmp_path / "map.png"
    Image.new("RGB", (64, 64), (34, 92, 58)).save(image_path)
    record_path = tmp_path / "record.json"
    record_path.write_text(
        json.dumps({"result": "victory", "samples": [1, 2, 3]}),
        encoding="utf-8",
    )
    workspaces = [
        {"key": "map", "title": "Map", "kind": "map"},
        {"key": "cards", "title": "Cards", "kind": "cards"},
        {"key": "overview", "title": "Overview", "kind": "overview"},
        {"key": "journal", "title": "Journal", "kind": "records"},
        {"key": "records", "title": "Records", "kind": "records"},
        {"key": "archive", "title": "Archive", "kind": "overview"},
    ]
    static = {
        "schema_version": 1,
        "game": "Test Companion",
        "maps": [
            {
                "key": "area-01",
                "title": "Test Area",
                "area": "Inside",
                "path": str(image_path),
                "map_id": 1,
                "width": 4,
                "height": 4,
                "tile_width": 16,
                "tile_height": 16,
            }
        ],
        "presentation": {
            "title": "Test Companion",
            "subtitle": "Generic dashboard",
            "workspaces": workspaces,
            "controls": [
                {
                    "key": "layer",
                    "workspace": "map",
                    "label": "Layer",
                    "kind": "choice",
                    "default": "area-01",
                    "choices": [
                        {"value": "area-01", "label": "Test Area"},
                        {"value": "area-02", "label": "Other Area"},
                    ],
                }
            ],
        },
    }
    live = {
        "schema_version": 1,
        "playthrough": "slot-one",
        "presentation": {
            "status": {
                "title": "Test Area",
                "mode": "AREA",
                "detail": "Memory: verified",
            },
            "workspaces": {
                "map": {
                    "heading": "Living Map",
                    "subtitle": "Current area",
                    "map": {
                        "key": "area-01",
                        "title": "Test Area",
                        "area": "Inside",
                        "image_path": str(image_path),
                        "map_id": 1,
                        "x": 1,
                        "y": 2,
                        "is_world": False,
                    },
                    "items": [
                        {
                            "key": "chest-one",
                            "title": "Treasure",
                            "subtitle": "(2,3)",
                            "detail": "Available",
                            "kind": "collectibles",
                            "marker": "treasure",
                            "x": 2,
                            "y": 3,
                            "game_completed": False,
                            "can_complete": True,
                        },
                        {
                            "key": "chest-two",
                            "title": "Opened treasure",
                            "subtitle": "(3,3)",
                            "detail": "Looted",
                            "kind": "collectibles",
                            "x": 3,
                            "y": 3,
                            "game_completed": True,
                            "can_complete": True,
                        },
                    ],
                    "sections": [],
                },
                "cards": {
                    "heading": "Party",
                    "subtitle": "One member",
                    "cards": [
                        {
                            "key": "hero",
                            "title": "Hero",
                            "subtitle": "Active · Level 8",
                            "status": "Ready",
                            "metrics": [
                                {"label": "HP", "value": "40 / 50", "progress": 0.8}
                            ],
                            "rows": [{"label": "Weapon", "value": "Sword"}],
                        }
                    ],
                },
                "overview": {
                    "heading": "Journey",
                    "subtitle": "Chapter 2",
                    "progress": {"value": 2, "maximum": 5, "labels": ["1", "2", "3", "4", "5"]},
                    "metrics": [{"label": "Gold", "value": "100"}],
                    "sections": [
                        {
                            "key": "travel",
                            "title": "Travel",
                            "rows": [{"label": "Boat", "value": "Ready"}],
                        }
                    ],
                },
                "journal": {
                    "heading": "Journal",
                    "subtitle": "Dialogue",
                    "search_placeholder": "Search dialogue",
                    "records": [
                        {
                            "key": "line-one",
                            "title": "Town",
                            "subtitle": "Welcome",
                            "detail": "Welcome to town.",
                            "search": "town welcome",
                        },
                        {
                            "key": "line-two",
                            "title": "Castle",
                            "subtitle": "The king awaits",
                            "detail": "The king awaits.",
                            "search": "castle king",
                        },
                    ],
                },
                "records": {
                    "heading": "Combat",
                    "subtitle": "Completed fights",
                    "sections": [],
                    "records": [
                        {
                            "key": "fight-one",
                            "title": "Victory",
                            "subtitle": "One enemy",
                            "meta": "3 frames",
                            "detail": "20 XP",
                            "detail_path": str(record_path),
                            "search": "victory enemy",
                        }
                    ],
                },
                "archive": {
                    "heading": "Archive",
                    "subtitle": "Evidence",
                    "sections": [
                        {
                            "key": "sources",
                            "title": "Sources",
                            "rows": [{"label": "ROM", "value": "Available"}],
                        }
                    ],
                },
            },
        },
    }
    controls = {
        "workspace": "map",
        "layer": "area-01",
        "completed_features": [],
        "completed_features_by_playthrough": {},
        "dashboard_open": True,
    }
    (tmp_path / "static.json").write_text(json.dumps(static), encoding="utf-8")
    (tmp_path / "live.json").write_text(json.dumps(live), encoding="utf-8")
    (tmp_path / "controls.json").write_text(json.dumps(controls), encoding="utf-8")
    return DashboardStore(tmp_path), static, live


def test_window_materializes_declared_workspace_kinds_and_persists_selection(
    qtbot,
    tmp_path: Path,
) -> None:
    store, _, _ = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    window.show()

    assert window.workspace_keys == (
        "map",
        "cards",
        "overview",
        "journal",
        "records",
        "archive",
    )
    assert isinstance(window.workspace_widget("map"), QtDashboardMapView)
    assert isinstance(window.workspace_widget("cards"), QtDashboardCardsView)
    assert isinstance(window.workspace_widget("overview"), QtDashboardOverviewView)
    assert isinstance(window.workspace_widget("journal"), QtDashboardRecordsView)
    assert window.select_workspace("journal")
    assert window.active_workspace == "journal"
    assert json.loads(store.controls_path.read_text(encoding="utf-8"))["workspace"] == (
        "journal"
    )

    window.close()
    assert not json.loads(store.controls_path.read_text(encoding="utf-8"))[
        "dashboard_open"
    ]


def test_live_card_values_update_in_place(qtbot, tmp_path: Path) -> None:
    store, _, live = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    cards = window.workspace_widget("cards")
    assert isinstance(cards, QtDashboardCardsView)
    hp_label = cards._labels[("hero", "HP")]

    live["presentation"]["workspaces"]["cards"]["cards"][0]["metrics"][0].update(
        value="25 / 50",
        progress=0.5,
    )
    store.live_path.write_text(json.dumps(live), encoding="utf-8")
    window.poll()

    assert cards._labels[("hero", "HP")] is hp_label
    assert hp_label.text() == "HP  25 / 50"
    assert cards._bars[("hero", "HP")].value() == 500


def test_map_view_renders_features_and_persists_manual_completion(
    qtbot,
    tmp_path: Path,
) -> None:
    store, _, _ = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    map_workspace = window.workspace_widget("map")
    assert isinstance(map_workspace, QtDashboardMapView)
    assert map_workspace.map_view is not None

    assert map_workspace.map_view.layer_key == "area-01"
    assert map_workspace.map_view.image_item_count == 1
    assert map_workspace.map_view.player_scene_positions == ((16.0, 32.0),)
    assert map_workspace.feature_count == 2
    assert not bool(
        map_workspace.features.item(1).flags() & Qt.ItemFlag.ItemIsEnabled
    )

    map_workspace.features.item(0).setCheckState(Qt.CheckState.Checked)

    assert store.completed_ids("slot-one") == {"chest-one"}
    assert any(
        waypoint.title == "Treasure" and waypoint.completed
        for waypoint in map_workspace.map_view.visible_waypoints()
    )


def test_records_filter_and_load_declared_detail_file(qtbot, tmp_path: Path) -> None:
    store, _, _ = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    journal = window.workspace_widget("journal")
    records = window.workspace_widget("records")
    assert isinstance(journal, QtDashboardRecordsView)
    assert isinstance(records, QtDashboardRecordsView)

    journal.search.setText("castle")
    assert journal.list.item(0).isHidden()
    assert not journal.list.item(1).isHidden()
    journal.sort.setCurrentIndex(journal.sort.findData("title"))
    assert journal.list.item(0).text().startswith("Castle")
    assert records.record_count == 1
    assert "20 XP" in records.detail.toPlainText()
    assert '"result": "victory"' in records.detail.toPlainText()


def test_workspace_ui_state_is_separate_and_restored(qtbot, tmp_path: Path) -> None:
    store, _, _ = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    map_workspace = window.workspace_widget("map")
    journal = window.workspace_widget("journal")
    assert isinstance(map_workspace, QtDashboardMapView)
    assert isinstance(journal, QtDashboardRecordsView)
    assert map_workspace.map_view is not None
    map_workspace.map_view.set_zoom(4)
    journal.search.setText("castle")
    journal.sort.setCurrentIndex(journal.sort.findData("title"))
    window.resize(1110, 710)
    window.close()

    persisted = json.loads(store.controls_path.read_text(encoding="utf-8"))
    assert persisted["completed_features_by_playthrough"] == {}
    assert persisted["ui"]["map"]["zoom"] == 4
    assert persisted["ui"]["journal"]["query"] == "castle"
    assert persisted["ui"]["journal"]["sort"] == "title"
    assert persisted["ui"]["window"] == {"width": 1110, "height": 710}

    restored_store = DashboardStore(tmp_path)
    restored = QtDashboardWindow(restored_store, poll_interval_ms=10_000)
    qtbot.addWidget(restored)
    restored_map = restored.workspace_widget("map")
    restored_journal = restored.workspace_widget("journal")
    assert isinstance(restored_map, QtDashboardMapView)
    assert isinstance(restored_journal, QtDashboardRecordsView)
    assert restored_map.map_view is not None
    assert restored_map.map_view.zoom == 4
    assert restored_journal.search.text() == "castle"
    assert restored_journal.sort.currentData() == "title"
    assert restored.size().width() == 1110
    assert restored.size().height() == 710


def test_waiting_document_hides_stale_workspace_content(qtbot, tmp_path: Path) -> None:
    store, _, live = _documents(tmp_path)
    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    assert window.content_stack.currentIndex() == 0

    live.update(
        mode="waiting",
        presentation={
            "status": {
                "title": "Waiting for readable memory",
                "mode": "WAITING",
                "detail": "Descriptor unavailable",
            },
            "workspaces": {},
        },
    )
    store.live_path.write_text(json.dumps(live), encoding="utf-8")
    window.poll()

    assert window.content_stack.currentIndex() == 1
    assert window.waiting_title.text() == "Waiting for readable memory"
    assert window.waiting_detail.text() == "Descriptor unavailable"


def test_missing_first_live_document_starts_on_waiting_page(
    qtbot,
    tmp_path: Path,
) -> None:
    store, _, _ = _documents(tmp_path)
    store.live_path.unlink()
    store = DashboardStore(tmp_path)

    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)

    assert window.content_stack.currentIndex() == 1
    assert "live.json" in window.waiting_detail.text()


def test_missing_map_image_replaces_scene_with_error_state(
    qtbot,
    tmp_path: Path,
) -> None:
    store, static, live = _documents(tmp_path)
    Path(static["maps"][0]["path"]).unlink()
    store = DashboardStore(tmp_path)

    window = QtDashboardWindow(store, poll_interval_ms=10_000)
    qtbot.addWidget(window)
    workspace = window.workspace_widget("map")
    assert isinstance(workspace, QtDashboardMapView)

    assert workspace.map_stack.currentWidget() is workspace.map_error
    assert "could not be loaded" in workspace.map_error.text()