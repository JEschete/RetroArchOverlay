import json
import os
from pathlib import Path


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
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"Local settings must contain a JSON object: {self.path}")
        return document

    def _write(self, document: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")