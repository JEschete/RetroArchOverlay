import json
import os
from pathlib import Path

from .core.models import LayoutProfile, ScreenRect


def default_local_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "RetroArchOverlay" / "local_settings.json"


class LocalPluginSettings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_local_settings_path()).resolve()

    def rom_path(self, plugin_id: str) -> Path | None:
        value = self._plugins().get(plugin_id, {}).get("rom_path")
        return Path(value) if isinstance(value, str) and value else None

    def save_path(self, plugin_id: str) -> Path | None:
        value = self._plugins().get(plugin_id, {}).get("save_path")
        return Path(value) if isinstance(value, str) and value else None

    def retroarch_path(self) -> Path | None:
        value = self._document().get("retroarch_path")
        return Path(value) if isinstance(value, str) and value else None

    def retroarch_config(self) -> Path | None:
        root = self.retroarch_path()
        if root is None:
            return None
        config = root / "retroarch.cfg"
        return config if config.is_file() else None

    def detail_window_position(self, key: str) -> tuple[int, int] | None:
        positions = self._document().get("detail_window_positions", {})
        if not isinstance(positions, dict):
            return None
        position = positions.get(key)
        if not isinstance(position, dict):
            return None
        x = position.get("x")
        y = position.get("y")
        if not isinstance(x, int) or isinstance(x, bool):
            return None
        if not isinstance(y, int) or isinstance(y, bool):
            return None
        return x, y

    def layout_profile(self) -> LayoutProfile:
        value = self._document().get("layout_profile", {})
        if not isinstance(value, dict):
            return LayoutProfile()
        return LayoutProfile(
            mode=_string(value.get("mode"), "auto"),
            rail_side=_string(value.get("rail_side"), "right"),
            rail_width=_integer(value.get("rail_width"), 360),
            density=_string(value.get("density"), "compact"),
            game_scaling=_string(value.get("game_scaling"), "auto"),
            manage_retroarch_window=_boolean(
                value.get("manage_retroarch_window"), True
            ),
        )

    def save_layout_profile(self, profile: LayoutProfile) -> None:
        document = self._document()
        document["layout_profile"] = {
            "mode": profile.mode,
            "rail_side": profile.rail_side,
            "rail_width": profile.rail_width,
            "density": profile.density,
            "game_scaling": profile.game_scaling,
            "manage_retroarch_window": profile.manage_retroarch_window,
        }
        self._write(document)

    def window_geometry(self, key: str) -> ScreenRect | None:
        values = self._document().get("window_geometries", {})
        if not isinstance(values, dict):
            return None
        value = values.get(key)
        if not isinstance(value, dict):
            return None
        coordinates = tuple(value.get(name) for name in ("left", "top", "right", "bottom"))
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in coordinates):
            return None
        left, top, right, bottom = coordinates
        if right <= left or bottom <= top:
            return None
        return ScreenRect(left, top, right, bottom)

    def save_window_geometry(self, key: str, rect: ScreenRect) -> None:
        document = self._document()
        values = document.setdefault("window_geometries", {})
        if not isinstance(values, dict):
            values = {}
            document["window_geometries"] = values
        values[key] = {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
        }
        self._write(document)

    def hero_paths_path(self) -> Path:
        return self.path.with_name("hero_paths.json")

    def hero_paths(self, title: str) -> dict[str, list[tuple[int, int]]]:
        path = self.hero_paths_path()
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(document, dict):
            return {}
        stored = document.get(title)
        if not isinstance(stored, dict):
            return {}
        paths: dict[str, list[tuple[int, int]]] = {}
        for key, points in stored.items():
            if not isinstance(key, str) or not isinstance(points, list):
                continue
            cleaned = [
                (point[0], point[1])
                for point in points
                if isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, int) for value in point)
            ]
            if cleaned:
                paths[key] = cleaned
        return paths

    def save_hero_paths(
        self, title: str, paths: dict[str, list[tuple[int, int]]], limit: int = 20_000
    ) -> None:
        path = self.hero_paths_path()
        document: dict[str, object] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    document = loaded
            except (OSError, json.JSONDecodeError):
                document = {}
        trimmed = {
            key: [list(point) for point in points[-limit:]]
            for key, points in paths.items()
            if points
        }
        if trimmed:
            document[title] = trimmed
        else:
            document.pop(title, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")

    def map_view_state(self, key: str) -> dict[str, object]:
        values = self._document().get("map_view_states", {})
        if not isinstance(values, dict):
            return {}
        value = values.get(key)
        return value if isinstance(value, dict) else {}

    def save_map_view_state(self, key: str, state: dict[str, object]) -> None:
        document = self._document()
        values = document.setdefault("map_view_states", {})
        if not isinstance(values, dict):
            values = {}
            document["map_view_states"] = values
        values[key] = state
        self._write(document)

    def high_contrast_override(self) -> bool | None:
        value = self._document().get("high_contrast")
        return value if isinstance(value, bool) else None

    def save_high_contrast_override(self, value: bool | None) -> None:
        document = self._document()
        if value is None:
            document.pop("high_contrast", None)
        else:
            document["high_contrast"] = value
        self._write(document)

    def save_detail_window_position(self, key: str, x: int, y: int) -> None:
        document = self._document()
        positions = document.setdefault("detail_window_positions", {})
        if not isinstance(positions, dict):
            positions = {}
            document["detail_window_positions"] = positions
        positions[key] = {"x": x, "y": y}
        self._write(document)

    def save_retroarch_path(self, retroarch_path: Path | None) -> None:
        document = self._document()
        if retroarch_path is None:
            document.pop("retroarch_path", None)
        else:
            resolved = retroarch_path.expanduser().resolve()
            if not resolved.is_dir():
                raise NotADirectoryError(f"RetroArch folder does not exist: {resolved}")
            if not (resolved / "retroarch.cfg").is_file():
                raise FileNotFoundError(f"RetroArch folder has no retroarch.cfg: {resolved}")
            document["retroarch_path"] = str(resolved)
        self._write(document)

    def save_rom_path(self, plugin_id: str, rom_path: Path | None) -> None:
        self._save_plugin_file(plugin_id, "rom_path", rom_path, "ROM")

    def save_save_path(self, plugin_id: str, save_path: Path | None) -> None:
        self._save_plugin_file(plugin_id, "save_path", save_path, "Save")

    def _save_plugin_file(
        self, plugin_id: str, key: str, path: Path | None, label: str
    ) -> None:
        plugin_id = plugin_id.strip()
        if not plugin_id:
            raise ValueError(f"Plugin ID is required before saving a {label.lower()} path")
        document = self._document()
        plugins = document.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            document["plugins"] = plugins
        if path is None:
            settings = plugins.get(plugin_id)
            if isinstance(settings, dict):
                settings.pop(key, None)
                if not settings:
                    plugins.pop(plugin_id, None)
        else:
            resolved = path.expanduser().resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"{label} file does not exist: {resolved}")
            settings = plugins.setdefault(plugin_id, {})
            if not isinstance(settings, dict):
                settings = {}
                plugins[plugin_id] = settings
            settings[key] = str(resolved)
        self._write(document)

    def _plugins(self) -> dict[str, dict[str, object]]:
        plugins = self._document().get("plugins", {})
        return plugins if isinstance(plugins, dict) else {}

    def _document(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"schema_version": 1, "plugins": {}}
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "plugins": {}}
        if not isinstance(document, dict):
            raise ValueError(f"Local settings must contain a JSON object: {self.path}")
        return document

    def _write(self, document: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _integer(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _boolean(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default