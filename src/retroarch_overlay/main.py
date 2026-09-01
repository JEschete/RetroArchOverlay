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
    DragonWarrior3Adapter,
    EmeraldAdapter,
)
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
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Read-only RetroArch information overlay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=55355, type=int)
    parser.add_argument("--opacity", default=0.72, type=float)
    parser.add_argument("--pokeemerald-root", type=Path, default=project_root / "pokeemerald")
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
    emerald_progress = load_ra_progress(
        args.retroarch_config,
        EmeraldAdapter.ra_game_id,
        api_key,
    )
    registry = AdapterRegistry(
        [EmeraldAdapter(args.pokeemerald_root, emerald_progress), DragonWarrior3Adapter(dragon_progress)],
        ContentHashResolver(rom_roots),
    )
    registry.discover()
    OverlayWindow(client, registry, args.opacity).run()


if __name__ == "__main__":
    main()
