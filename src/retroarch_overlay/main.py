import argparse
import logging
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "retroarch_overlay"

from .adapters import (
    AdapterRegistry,
    ContentHashResolver,
)
from .app.controller import OverlayController, SnapshotCadence
from .cheeves import default_cache_dir
from .core.contracts import GameContext
from .infrastructure.logging_config import configure_logging
from .infrastructure.plugin_discovery import discover_plugin_repositories
from .infrastructure.plugin_loader import RepositoryAdapter
from .local_settings import LocalPluginSettings
from .retroarch import RetroArchClient
from .retroachievements import BackgroundRAProgressProvider, clear_ra_api_key, get_ra_api_key


def default_retroarch_config() -> Path:
    candidates = (
        Path.home() / "LaunchBox" / "Emulators" / "RetroArch" / "retroarch.cfg",
        Path(os.environ.get("APPDATA", "")) / "RetroArch" / "retroarch.cfg",
        Path.cwd() / "retroarch.cfg",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only RetroArch information overlay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=55355, type=int)
    parser.add_argument("--retroarch-timeout", default=0.4, type=float)
    parser.add_argument("--snapshot-interval", default=0.25, type=float)
    parser.add_argument("--opacity", default=1.0, type=float)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    parser.add_argument("--plugin-dir", action="append", type=Path)
    parser.add_argument("--rom-root", action="append", type=Path)
    parser.add_argument("--rom-path", action="append", type=Path)
    parser.add_argument("--retroarch-config", type=Path, default=default_retroarch_config())
    parser.add_argument("--reset-ra-key", action="store_true")
    return parser


def run_qt_overlay(
    controller: OverlayController,
    opacity: float,
    local_settings: LocalPluginSettings,
) -> int:
    if not 0.3 <= opacity <= 1.0:
        raise ValueError("Opacity must be between 0.3 and 1.0")
    try:
        from .presentation.qt import (
            QtOverlayWindow,
            apply_qt_theme,
            create_qt_application,
        )
    except ModuleNotFoundError as error:
        if error.name and error.name.partition(".")[0] == "PySide6":
            raise RuntimeError(
                'The Qt UI requires PySide6-Essentials: pip install "."'
            ) from error
        raise
    application = create_qt_application()
    apply_qt_theme(application, local_settings.theme())
    window = QtOverlayWindow(
        controller,
        opacity=opacity,
        settings=local_settings,
    )
    window.start()
    return application.exec()


def main() -> int:
    args = build_parser().parse_args()
    local_settings = LocalPluginSettings()
    configure_logging(
        local_settings.path.parent / "logs" / "retroarch-overlay.log",
        getattr(logging, args.log_level),
    )
    logger = logging.getLogger(__name__)
    if args.retroarch_timeout <= 0:
        raise ValueError("RetroArch timeout must be positive")
    if args.snapshot_interval <= 0:
        raise ValueError("Snapshot interval must be positive")
    client = RetroArchClient(args.host, args.port, args.retroarch_timeout)
    rom_roots = tuple(args.rom_root or (Path.home() / "Roms",))
    if args.reset_ra_key:
        clear_ra_api_key(args.retroarch_config)
    api_key = os.environ.get("RETROACHIEVEMENTS_API_KEY", "") or get_ra_api_key(
        args.retroarch_config
    )
    plugin_roots = tuple(args.plugin_dir or (Path(__file__).resolve().parents[2] / "plugins",))
    discovery = discover_plugin_repositories(plugin_roots)
    for error in discovery.errors:
        logger.warning("Plugin unavailable at %s: %s", error.path, error.message)
        print(f"Plugin unavailable at {error.path}: {error.message}", file=sys.stderr)
    progress_provider = BackgroundRAProgressProvider(
        args.retroarch_config,
        api_key,
        default_cache_dir() / "progress",
    )
    plugin_rom_paths = {
        repository.manifest.plugin_id: local_settings.rom_path(repository.manifest.plugin_id)
        for repository in discovery.repositories
    }
    plugin_save_paths = {
        repository.manifest.plugin_id: local_settings.save_path(repository.manifest.plugin_id)
        for repository in discovery.repositories
    }
    plugin_adapters = [
        RepositoryAdapter(
            repository,
            GameContext(
                settings={
                    key: value
                    for key, value in (
                        ("rom_path", plugin_rom_paths[repository.manifest.plugin_id]),
                        ("save_path", plugin_save_paths[repository.manifest.plugin_id]),
                    )
                    if value is not None
                },
                repository_root=repository.repository_root,
                state_directory=(
                    local_settings.path.parent
                    / "plugin-state"
                    / repository.manifest.plugin_id
                ),
                ra_progress_provider=progress_provider,
            ),
        )
        for repository in discovery.repositories
    ]
    registry = AdapterRegistry(
        plugin_adapters,
        ContentHashResolver(
            rom_roots,
            tuple(args.rom_path or ())
            + tuple(path for path in plugin_rom_paths.values() if path is not None),
        ),
    )
    registry.discover()
    controller = OverlayController(
        client,
        registry,
        cadence=SnapshotCadence(args.snapshot_interval),
    )
    return run_qt_overlay(
        controller,
        args.opacity,
        local_settings,
    )


if __name__ == "__main__":
    raise SystemExit(main())
