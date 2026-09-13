from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_DASHBOARD_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class DashboardWorkspace:
    key: str
    title: str
    kind: str
    subtitle: str = ""


@dataclass(frozen=True, slots=True)
class DashboardChoice:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class DashboardChoiceControl:
    key: str
    workspace: str
    label: str
    default: str
    choices: tuple[DashboardChoice, ...]


class DashboardStore:
    def __init__(self, state_directory: Path) -> None:
        self.state_directory = state_directory
        self.static_path = state_directory / "static.json"
        self.live_path = state_directory / "live.json"
        self.controls_path = state_directory / "controls.json"
        self.static: dict[str, Any] = {}
        self.live: dict[str, Any] = {}
        self.controls: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self._signatures: dict[str, tuple[int, int]] = {}
        self.refresh()

    def refresh(self) -> bool:
        changed = False
        for name, path in (
            ("static", self.static_path),
            ("live", self.live_path),
            ("controls", self.controls_path),
        ):
            try:
                stat = path.stat()
            except OSError as error:
                self.errors[name] = str(error)
                continue
            signature = (stat.st_mtime_ns, stat.st_size)
            if self._signatures.get(name) == signature:
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError(f"{path.name} must contain a JSON object")
                self._validate_schema(name, value)
            except (OSError, json.JSONDecodeError, ValueError) as error:
                self.errors[name] = str(error)
                continue
            setattr(self, name, value)
            self._signatures[name] = signature
            self.errors.pop(name, None)
            changed = True
        return changed

    @property
    def workspaces(self) -> tuple[DashboardWorkspace, ...]:
        presentation = self.static.get("presentation", {})
        values = presentation.get("workspaces", []) if isinstance(presentation, dict) else []
        workspaces = []
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            key = value.get("key")
            title = value.get("title")
            kind = value.get("kind")
            if not all(isinstance(item, str) and item for item in (key, title, kind)):
                continue
            workspaces.append(
                DashboardWorkspace(
                    key,
                    title,
                    kind,
                    str(value.get("subtitle", "")),
                )
            )
        return tuple(workspaces)

    @property
    def choice_controls(self) -> tuple[DashboardChoiceControl, ...]:
        presentation = self.static.get("presentation", {})
        values = presentation.get("controls", []) if isinstance(presentation, dict) else []
        controls = []
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict) or value.get("kind") != "choice":
                continue
            choices = tuple(
                DashboardChoice(str(choice["value"]), str(choice["label"]))
                for choice in value.get("choices", [])
                if isinstance(choice, dict)
                and isinstance(choice.get("value"), str)
                and isinstance(choice.get("label"), str)
            )
            key = value.get("key")
            workspace = value.get("workspace")
            label = value.get("label")
            default = value.get("default")
            if (
                not choices
                or not all(
                    isinstance(item, str) and item
                    for item in (key, workspace, label, default)
                )
                or default not in {choice.value for choice in choices}
            ):
                continue
            controls.append(
                DashboardChoiceControl(
                    key,
                    workspace,
                    label,
                    default,
                    choices,
                )
            )
        return tuple(controls)

    def open(self) -> None:
        self.controls["dashboard_open"] = True
        self._write_controls()

    def close(self) -> None:
        self.controls["dashboard_open"] = False
        self._write_controls()

    def select_workspace(self, key: str) -> bool:
        if key not in {workspace.key for workspace in self.workspaces}:
            return False
        if self.controls.get("workspace") == key:
            return False
        self.controls["workspace"] = key
        self._write_controls()
        return True

    def set_choice(self, key: str, value: str) -> bool:
        control = next(
            (candidate for candidate in self.choice_controls if candidate.key == key),
            None,
        )
        if control is None or value not in {choice.value for choice in control.choices}:
            return False
        if self.controls.get(key, control.default) == value:
            return False
        self.controls[key] = value
        self._write_controls()
        return True

    def completed_ids(self, scope: str) -> frozenset[str]:
        scoped = self.controls.get("completed_features_by_playthrough", {})
        legacy = self.controls.get("completed_features", [])
        if scope and isinstance(scoped, dict):
            values = scoped.get(scope)
            if values is None and isinstance(legacy, list) and legacy:
                values = [value for value in legacy if isinstance(value, str)]
                scoped[scope] = values
                self.controls["completed_features"] = []
                self._write_controls()
        else:
            values = legacy
        if not isinstance(values, list):
            return frozenset()
        return frozenset(value for value in values if isinstance(value, str))

    def set_completed(
        self,
        item_key: str,
        scope: str,
        completed: bool,
        *,
        allowed: bool = True,
        game_completed: bool = False,
    ) -> bool:
        if not item_key or not allowed or game_completed:
            return False
        values = set(self.completed_ids(scope))
        before = set(values)
        if completed:
            values.add(item_key)
        else:
            values.discard(item_key)
        if values == before:
            return False
        if scope:
            scoped = self.controls.setdefault(
                "completed_features_by_playthrough",
                {},
            )
            if not isinstance(scoped, dict):
                scoped = {}
                self.controls["completed_features_by_playthrough"] = scoped
            scoped[scope] = sorted(values)
        else:
            self.controls["completed_features"] = sorted(values)
        self._write_controls()
        return True

    def ui_state(self, key: str) -> dict[str, Any]:
        values = self.controls.get("ui", {})
        if not isinstance(values, dict):
            return {}
        value = values.get(key, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_ui_states(self, states: dict[str, dict[str, Any]]) -> None:
        values = self.controls.setdefault("ui", {})
        if not isinstance(values, dict):
            values = {}
            self.controls["ui"] = values
        for key, state in states.items():
            values[key] = dict(state)
        self._write_controls()

    def _write_controls(self) -> None:
        _write_json_atomic(self.controls_path, self.controls)
        stat = self.controls_path.stat()
        self._signatures["controls"] = (stat.st_mtime_ns, stat.st_size)
        self.errors.pop("controls", None)

    @staticmethod
    def _validate_schema(name: str, value: dict[str, Any]) -> None:
        if name == "controls":
            return
        version = value.get("schema_version")
        if version != SUPPORTED_DASHBOARD_SCHEMA:
            raise ValueError(
                f"Unsupported {name} dashboard schema {version!r}; "
                f"expected {SUPPORTED_DASHBOARD_SCHEMA}"
            )


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise