import argparse
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
from .adapters.dragon_warrior_3 import DragonWarrior3Adapter
from .core.contracts import GameContext
from .infrastructure.plugin_discovery import discover_plugin_repositories
from .infrastructure.plugin_loader import RepositoryAdapter
from .retroarch import RetroArchClient
from .retroachievements import clear_ra_api_key, get_ra_api_key, load_ra_progress
from .ui import OverlayWindow


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
    parser.add_argument("--opacity", default=0.72, type=float)
    parser.add_argument("--plugin-dir", action="append", type=Path)
    parser.add_argument("--rom-root", action="append", type=Path)
    parser.add_argument("--retroarch-config", type=Path, default=default_retroarch_config())
    parser.add_argument("--reset-ra-key", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    client = RetroArchClient(args.host, args.port)
    rom_roots = tuple(args.rom_root or (Path.home() / "Roms",))
    if args.reset_ra_key:
        clear_ra_api_key(args.retroarch_config)
    api_key = os.environ.get("RETROACHIEVEMENTS_API_KEY", "") or get_ra_api_key(
        args.retroarch_config
    )
    dragon_progress = load_ra_progress(
        args.retroarch_config,
        DragonWarrior3Adapter.ra_game_id,
        api_key,
    )
    plugin_roots = tuple(args.plugin_dir or (Path(__file__).resolve().parents[2] / "plugins",))
    discovery = discover_plugin_repositories(plugin_roots)
    for error in discovery.errors:
        print(f"Plugin unavailable at {error.path}: {error.message}", file=sys.stderr)
    progress_provider = lambda game_id: load_ra_progress(
        args.retroarch_config, game_id, api_key
    )
    plugin_adapters = [
        RepositoryAdapter(
            repository,
            GameContext(
                repository_root=repository.repository_root,
                ra_progress_provider=progress_provider,
            ),
        )
        for repository in discovery.repositories
    ]
    registry = AdapterRegistry(
        [DragonWarrior3Adapter(dragon_progress), *plugin_adapters],
        ContentHashResolver(rom_roots),
    )
    registry.discover()
    OverlayWindow(client, registry, args.opacity).run()


if __name__ == "__main__":
    main()
