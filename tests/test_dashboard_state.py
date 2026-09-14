import json

from retroarch_overlay.app.dashboard import DashboardStore


def _documents(tmp_path) -> DashboardStore:
    static = {
        "schema_version": 1,
        "presentation": {
            "workspaces": [
                {"key": "map", "title": "Atlas", "kind": "map"},
                {"key": "records", "title": "Journal", "kind": "records"},
            ],
            "controls": [
                {
                    "key": "layer",
                    "workspace": "map",
                    "label": "World",
                    "kind": "choice",
                    "default": "overworld",
                    "choices": [
                        {"value": "overworld", "label": "Overworld"},
                        {"value": "underworld", "label": "Underworld"},
                    ],
                }
                ,
                {
                    "key": "enabled",
                    "workspace": "records",
                    "label": "Enabled",
                    "kind": "toggle",
                    "default": False,
                    "status_key": "worker",
                },
                {
                    "key": "revealed",
                    "workspace": "records",
                    "label": "Revealed",
                    "kind": "counter",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 3,
                    "step": 1,
                },
                {
                    "key": "selected",
                    "workspace": "records",
                    "label": "Selection",
                    "kind": "record",
                },
                {
                    "key": "run",
                    "workspace": "records",
                    "label": "Run",
                    "kind": "command",
                    "status_key": "worker",
                },
            ],
        },
    }
    (tmp_path / "static.json").write_text(json.dumps(static), encoding="utf-8")
    (tmp_path / "live.json").write_text(
        json.dumps({"schema_version": 1, "value": 1}),
        encoding="utf-8",
    )
    (tmp_path / "controls.json").write_text(
        json.dumps(
            {
                "workspace": "map",
                "layer": "overworld",
                "completed_features": [],
                "completed_features_by_playthrough": {},
            }
        ),
        encoding="utf-8",
    )
    return DashboardStore(tmp_path)


def test_store_retains_last_valid_document_during_partial_write(tmp_path) -> None:
    store = _documents(tmp_path)
    store.live_path.write_text('{"schema_version":', encoding="utf-8")

    assert not store.refresh()
    assert store.live["value"] == 1
    assert "live" in store.errors

    store.live_path.write_text(
        json.dumps({"schema_version": 1, "value": 2}),
        encoding="utf-8",
    )
    assert store.refresh()
    assert store.live["value"] == 2
    assert "live" not in store.errors


def test_workspace_and_choice_controls_are_schema_validated(tmp_path) -> None:
    store = _documents(tmp_path)

    assert [workspace.key for workspace in store.workspaces] == ["map", "records"]
    assert not store.select_workspace("missing")
    assert store.select_workspace("records")
    assert not store.set_choice("layer", "missing")
    assert store.set_choice("layer", "underworld")

    persisted = json.loads(store.controls_path.read_text(encoding="utf-8"))
    assert persisted["workspace"] == "records"
    assert persisted["layer"] == "underworld"


def test_completion_is_scoped_migrated_and_game_state_has_precedence(tmp_path) -> None:
    store = _documents(tmp_path)
    store.controls["completed_features"] = ["legacy-chest"]
    store._write_controls()

    assert store.completed_ids("slot-one") == {"legacy-chest"}
    assert store.set_completed("new-chest", "slot-one", True)
    assert not store.set_completed(
        "game-chest",
        "slot-one",
        True,
        game_completed=True,
    )
    assert store.completed_ids("slot-one") == {"legacy-chest", "new-chest"}
    assert store.completed_ids("slot-two") == frozenset()

    persisted = json.loads(store.controls_path.read_text(encoding="utf-8"))
    assert persisted["completed_features"] == []
    assert persisted["completed_features_by_playthrough"] == {
        "slot-one": ["legacy-chest", "new-chest"]
    }


def test_unsupported_documents_do_not_replace_last_valid_state(tmp_path) -> None:
    store = _documents(tmp_path)
    store.static_path.write_text(
        json.dumps({"schema_version": 2}),
        encoding="utf-8",
    )

    assert not store.refresh()
    assert len(store.workspaces) == 2
    assert "Unsupported static dashboard schema" in store.errors["static"]


def test_toggles_counters_records_and_commands_are_validated(tmp_path) -> None:
    store = _documents(tmp_path)

    assert store.set_toggle("enabled", True)
    assert not store.set_toggle("missing", True)
    assert store.set_counter("revealed", 99)
    assert store.controls["revealed"] == 3
    assert store.set_record_selection("selected", "record-one", {"record-one"})
    assert not store.set_record_selection("selected", "other", {"record-one"})
    assert store.invoke_command("run", {"record": "record-one"})
    assert not store.invoke_command("missing")

    persisted = json.loads(store.controls_path.read_text(encoding="utf-8"))
    assert persisted["enabled"] is True
    assert persisted["selected"] == "record-one"
    assert persisted["commands"]["run"] == {
        "serial": 1,
        "payload": {"record": "record-one"},
    }


def test_service_status_is_loaded_separately_from_controls(tmp_path) -> None:
    store = _documents(tmp_path)
    store.status_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "services": {"worker": "Ready"},
            }
        ),
        encoding="utf-8",
    )

    assert store.refresh()
    assert store.service_statuses == {"worker": "Ready"}