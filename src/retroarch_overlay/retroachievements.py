import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Callable, cast

from .core.retroachievements import RAProgress
from .infrastructure.credentials import KEYRING_SERVICE, KeyringCredentialStore
from .infrastructure.retroachievements import load_ra_progress, retroarch_setting


def prompt_ra_api_key(username: str) -> str:
    from .presentation.qt.credentials import prompt_ra_api_key as prompt

    return prompt(username)


class _LiveRAProgress:
    def __init__(self, initial: RAProgress) -> None:
        self._value = initial

    @property
    def username(self) -> str:
        return self._value.username

    @property
    def unlocked_ids(self) -> frozenset[int]:
        return self._value.unlocked_ids

    @property
    def message(self) -> str:
        return self._value.message

    def update(self, value: RAProgress) -> None:
        self._value = value


class BackgroundRAProgressProvider:
    def __init__(
        self,
        config_path: Path,
        api_key: str,
        cache_dir: Path,
        *,
        cache_ttl_seconds: int = 300,
        loader: Callable[[Path, int, str], RAProgress] = load_ra_progress,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config_path = config_path
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._cache_ttl_seconds = cache_ttl_seconds
        self._loader = loader
        self._clock = clock
        self._progress: dict[int, _LiveRAProgress] = {}
        self._lock = threading.Lock()

    def __call__(self, game_id: int) -> RAProgress:
        with self._lock:
            existing = self._progress.get(game_id)
            if existing is not None:
                return cast(RAProgress, existing)
            cached, fresh = self._read_cache(game_id)
            initial = cached or RAProgress("", frozenset(), "Loading RetroAchievements progress...")
            live = _LiveRAProgress(initial)
            self._progress[game_id] = live
            if not fresh:
                threading.Thread(target=self._refresh, args=(game_id, live), daemon=True).start()
            return cast(RAProgress, live)

    def _refresh(self, game_id: int, live: _LiveRAProgress) -> None:
        progress = self._loader(self._config_path, game_id, self._api_key)
        live.update(progress)
        self._write_cache(game_id, progress)

    def _cache_path(self, game_id: int) -> Path:
        username = retroarch_setting(self._config_path, "cheevos_username")
        identity = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()[:12]
        return self._cache_dir / f"progress-{identity}-{game_id}.json"

    def _read_cache(self, game_id: int) -> tuple[RAProgress | None, bool]:
        path = self._cache_path(game_id)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            progress = RAProgress(
                str(document["username"]),
                frozenset(int(value) for value in document["unlocked_ids"]),
                str(document.get("message", "")),
            )
            return progress, self._clock() - path.stat().st_mtime <= self._cache_ttl_seconds
        except (KeyError, OSError, TypeError, ValueError):
            return None, False

    def _write_cache(self, game_id: int, progress: RAProgress) -> None:
        try:
            path = self._cache_path(game_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "username": progress.username,
                        "unlocked_ids": sorted(progress.unlocked_ids),
                        "message": progress.message,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            return


def clear_ra_api_key(config_path: Path) -> None:
    username = retroarch_setting(config_path, "cheevos_username")
    KeyringCredentialStore().delete(username)


def get_ra_api_key(
    config_path: Path,
    prompt: Callable[[str], str] = prompt_ra_api_key,
) -> str:
    username = retroarch_setting(config_path, "cheevos_username")
    if not username:
        return ""
    store = KeyringCredentialStore()
    if not store.available:
        return ""
    stored = store.get(username)
    if stored:
        return stored
    api_key = prompt(username).strip()
    if api_key:
        store.set(username, api_key)
    return api_key


__all__ = [
    "BackgroundRAProgressProvider",
    "KEYRING_SERVICE",
    "RAProgress",
    "clear_ra_api_key",
    "get_ra_api_key",
    "load_ra_progress",
    "retroarch_setting",
]