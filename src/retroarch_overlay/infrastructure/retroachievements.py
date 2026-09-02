import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..core.errors import RetroAchievementsError
from ..core.retroachievements import (
    RAAchievement,
    RAConsole,
    RAGame,
    RAGameReference,
    RAProgress,
)


USER_AGENT = "RetroArchOverlay/0.1"
API_BASE_URL = "https://retroachievements.org/API"
DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MD5_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True, slots=True)
class RAGameTitleMatch:
    game: RAGameReference
    score: float
    exact: bool


class RetroAchievementsClient:
    def __init__(
        self,
        username: str,
        api_key: str,
        *,
        opener: Callable[..., object] = urlopen,
        cache_dir: Path | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        refresh_cache: bool = False,
    ) -> None:
        if not username or not api_key:
            raise ValueError("RetroAchievements username and Web API key are required")
        self.username = username
        self._api_key = api_key
        self._opener = opener
        self._cache_dir = cache_dir
        self._cache_ttl_seconds = cache_ttl_seconds
        self._refresh_cache = refresh_cache

    def get_consoles(self) -> tuple[RAConsole, ...]:
        document = self._get_json(
            "API_GetConsoleIDs.php",
            {"a": 1, "g": 1},
            cache_name="active-game-systems.json",
        )
        if not isinstance(document, list):
            raise RetroAchievementsError("Console list response was not an array")
        return tuple(
            RAConsole(
                int(entry["ID"]),
                str(entry["Name"]),
                bool(entry.get("Active", True)),
                bool(entry.get("IsGameSystem", True)),
            )
            for entry in document
            if isinstance(entry, dict) and entry.get("ID") and entry.get("Name")
        )

    def get_game_list(self, console_id: int) -> tuple[dict[str, Any], ...]:
        if console_id <= 0:
            raise ValueError("Console ID must be positive")
        document = self._get_json(
            "API_GetGameList.php",
            {"i": console_id, "f": 1, "h": 1},
            cache_name=f"console-{console_id}-games-with-hashes.json",
        )
        if not isinstance(document, list):
            raise RetroAchievementsError(f"Game list for console {console_id} was not an array")
        return tuple(entry for entry in document if isinstance(entry, dict))

    def resolve_game_hash(
        self,
        game_hash: str,
        *,
        console_id: int | None = None,
    ) -> RAGameReference:
        normalized_hash = game_hash.strip().casefold()
        if not MD5_PATTERN.fullmatch(normalized_hash):
            raise ValueError("Game hash must be a 32-character MD5 value")
        consoles = (
            (RAConsole(console_id, f"Console {console_id}"),)
            if console_id is not None
            else self.get_consoles()
        )
        for console in consoles:
            for entry in self.get_game_list(console.console_id):
                hashes = entry.get("Hashes", ())
                if not isinstance(hashes, list):
                    continue
                if normalized_hash not in {str(value).casefold() for value in hashes}:
                    continue
                return RAGameReference(
                    int(entry["ID"]),
                    str(entry.get("Title", f"Game {entry['ID']}")),
                    int(entry.get("ConsoleID", console.console_id)),
                    str(entry.get("ConsoleName", console.name)),
                )
        scope = f"console {console_id}" if console_id is not None else "active game systems"
        raise RetroAchievementsError(f"No RetroAchievements game matched hash {normalized_hash} in {scope}")

    def resolve_game_title(
        self,
        title: str,
        *,
        console_id: int | None = None,
    ) -> RAGameReference:
        matches = self.find_game_titles(title, console_id=console_id)
        exact_matches = [match.game for match in matches if match.exact]
        if len(exact_matches) == 1:
            return exact_matches[0]
        scope = f"console {console_id}" if console_id else "active game systems"
        if not matches:
            raise RetroAchievementsError(f"No RetroAchievements game matched title {title!r} in {scope}")
        choices = ", ".join(f"{match.game.game_id}: {match.game.title}" for match in matches[:5])
        raise RetroAchievementsError(f"RetroAchievements title {title!r} requires selection: {choices}")

    def find_game_titles(
        self,
        title: str,
        *,
        console_id: int | None = None,
        limit: int = 20,
    ) -> tuple[RAGameTitleMatch, ...]:
        normalized_title = _normalize_game_title(title)
        if not normalized_title:
            raise ValueError("Game title is required")
        if limit <= 0:
            raise ValueError("Title match limit must be positive")
        consoles = (
            (RAConsole(console_id, f"Console {console_id}"),)
            if console_id is not None
            else self.get_consoles()
        )
        matches: list[RAGameTitleMatch] = []
        for console in consoles:
            for entry in self.get_game_list(console.console_id):
                candidate_title = str(entry.get("Title", ""))
                candidate_normalized = _normalize_game_title(candidate_title)
                score = SequenceMatcher(None, normalized_title, candidate_normalized).ratio()
                exact = candidate_normalized == normalized_title
                if exact or score >= 0.4:
                    matches.append(
                        RAGameTitleMatch(
                            RAGameReference(
                                int(entry["ID"]),
                                candidate_title,
                                int(entry.get("ConsoleID", console.console_id)),
                                str(entry.get("ConsoleName", console.name)),
                            ),
                            1.0 if exact else score,
                            exact,
                        )
                    )
        matches.sort(key=lambda match: (-match.score, match.game.game_id))
        return tuple(matches[:limit])

    def get_game_hashes(self, game_id: int) -> tuple[str, ...]:
        if game_id <= 0:
            raise ValueError("Game ID must be positive")
        document = self._get_json(
            "API_GetGameHashes.php",
            {"i": game_id},
            cache_name=f"game-{game_id}-hashes.json",
        )
        if not isinstance(document, dict) or not isinstance(document.get("Results"), list):
            raise RetroAchievementsError(f"Hash list for game {game_id} was not valid")
        return tuple(
            str(entry["MD5"]).casefold()
            for entry in document["Results"]
            if isinstance(entry, dict) and MD5_PATTERN.fullmatch(str(entry.get("MD5", "")))
        )

    def get_game_extended(self, game_id: int) -> RAGame:
        if game_id <= 0:
            raise ValueError("Game ID must be positive")
        document = self._get_json(
            "API_GetGameExtended.php",
            {"i": game_id},
            cache_name=f"game-{game_id}-extended.json",
        )
        if not isinstance(document, dict) or not document.get("ID"):
            raise RetroAchievementsError(f"No RetroAchievements game found for ID {game_id}")
        raw_achievements = document.get("Achievements", {})
        achievement_entries = (
            raw_achievements.values()
            if isinstance(raw_achievements, dict)
            else raw_achievements
            if isinstance(raw_achievements, list)
            else ()
        )
        achievements = []
        for entry in achievement_entries:
            if not isinstance(entry, dict) or not entry.get("ID"):
                continue
            achievements.append(
                RAAchievement(
                    int(entry["ID"]),
                    str(entry.get("Title", "")),
                    str(entry.get("Description", "")),
                    int(entry.get("Points", 0)),
                    str(entry.get("type", entry.get("Type", "standard")) or "standard"),
                    str(entry.get("Author", "") or ""),
                    int(entry.get("DisplayOrder", 0)),
                    str(entry.get("MemAddr", "") or ""),
                )
            )
        achievements.sort(key=lambda value: (value.display_order, value.achievement_id))
        parent = document.get("ParentGameID")
        return RAGame(
            int(document["ID"]),
            str(document.get("Title", f"Game {game_id}")),
            int(document.get("ConsoleID", 0)),
            str(document.get("ConsoleName", "")),
            int(parent) if parent else None,
            tuple(achievements),
        )

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, object],
        *,
        cache_name: str | None = None,
    ) -> object:
        cached = self._read_cache(cache_name) if cache_name else None
        if cached is not None:
            return cached
        query = urlencode({"z": self.username, "y": self._api_key, **params})
        request = Request(
            f"{API_BASE_URL}/{endpoint}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=15) as response:
                document = json.load(response)
        except (OSError, ValueError) as error:
            stale = self._read_cache(cache_name, allow_stale=True) if cache_name else None
            if stale is not None:
                return stale
            raise RetroAchievementsError(f"RetroAchievements request failed for {endpoint}: {error}") from error
        if cache_name:
            self._write_cache(cache_name, document)
        return document

    def _read_cache(self, cache_name: str, *, allow_stale: bool = False) -> object | None:
        if self._cache_dir is None or (self._refresh_cache and not allow_stale):
            return None
        path = self._cache_dir / cache_name
        try:
            age = time.time() - path.stat().st_mtime
            if age > self._cache_ttl_seconds and not allow_stale:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, cache_name: str, document: object) -> None:
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / cache_name).write_text(
                json.dumps(document, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as error:
            raise RetroAchievementsError(f"Could not write RA cache: {error}") from error


def retroarch_setting(config_path: Path, name: str) -> str:
    if not config_path.is_file():
        return ""
    match = re.search(
        rf'^{re.escape(name)}\s*=\s*"([^"]*)"',
        config_path.read_text(encoding="utf-8", errors="replace"),
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def _normalize_game_title(value: str) -> str:
    roman = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(roman.get(word, word) for word in words)


def load_ra_progress(
    config_path: Path,
    game_id: int,
    api_key: str,
    opener: Callable[..., object] = urlopen,
) -> RAProgress:
    username = retroarch_setting(config_path, "cheevos_username")
    if not username:
        return RAProgress("", frozenset(), "RetroAchievements username not configured")
    if not api_key:
        return RAProgress(username, frozenset(), "RA account progress not loaded")

    query = urlencode({"z": username, "y": api_key, "u": username, "g": game_id})
    request = Request(
        "https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php?" + query,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with opener(request, timeout=8) as response:
            document = json.load(response)
    except (OSError, ValueError) as error:
        return RAProgress(username, frozenset(), f"Account progress unavailable: {error}")

    achievements = document.get("Achievements", {})
    unlocked = frozenset(
        int(achievement_id)
        for achievement_id, details in achievements.items()
        if details.get("DateEarned") or details.get("DateEarnedHardcore")
    )
    return RAProgress(username, unlocked)