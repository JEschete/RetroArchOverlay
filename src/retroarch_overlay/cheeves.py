import argparse
import os
from pathlib import Path

from .app.cheeves import export_cheeves_by_hash
from .core.errors import RetroAchievementsError
from .infrastructure.credentials import KeyringCredentialStore
from .infrastructure.ra_code_notes import SavedCodeNotesRepository
from .infrastructure.retroachievements import RetroAchievementsClient, retroarch_setting


def prompt_ra_api_key(username: str) -> str:
    from .presentation.qt.credentials import prompt_ra_api_key as prompt

    return prompt(username)


def default_retroarch_config() -> Path:
    candidates = (
        Path.home() / "LaunchBox" / "Emulators" / "RetroArch" / "retroarch.cfg",
        Path(os.environ.get("APPDATA", "")) / "RetroArch" / "retroarch.cfg",
        Path.cwd() / "retroarch.cfg",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def default_cache_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else Path.home() / ".cache"
    return root / "RetroArchOverlay" / "ra-api"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export RetroAchievements set metadata and saved memory notes by game hash"
    )
    parser.add_argument("game_hash", help="32-character RetroAchievements MD5 game hash")
    parser.add_argument("--console-id", type=int, help="Limit public hash lookup to one RA console ID")
    parser.add_argument("--related-game-id", action="append", type=int, default=[])
    parser.add_argument("--code-notes-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--retroarch-config", type=Path, default=default_retroarch_config())
    parser.add_argument("--username")
    parser.add_argument("--prompt-for-api-key", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    username = args.username or retroarch_setting(args.retroarch_config, "cheevos_username")
    store = KeyringCredentialStore()
    api_key = os.environ.get("RETROACHIEVEMENTS_API_KEY", "")
    if not api_key and username:
        api_key = store.get(username)
    if not api_key and username and args.prompt_for_api_key:
        api_key = prompt_ra_api_key(username).strip()
        if api_key and store.available:
            store.set(username, api_key)
    if not username or not api_key:
        parser.error(
            "RA username and Web API key are required; configure RetroArch, set "
            "RETROACHIEVEMENTS_API_KEY, or use --username --prompt-for-api-key"
        )

    client = RetroAchievementsClient(
        username,
        api_key,
        cache_dir=args.cache_dir,
        refresh_cache=args.refresh_cache,
    )
    notes = SavedCodeNotesRepository(args.code_notes_dir) if args.code_notes_dir else None
    try:
        result = export_cheeves_by_hash(
            client,
            args.game_hash,
            args.output_dir,
            console_id=args.console_id,
            related_game_ids=args.related_game_id,
            code_notes=notes,
        )
    except (OSError, ValueError, RetroAchievementsError) as error:
        parser.exit(1, f"Could not export achievements: {error}\n")
    print(result.path)


if __name__ == "__main__":
    main()