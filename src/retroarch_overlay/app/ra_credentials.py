from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from ..infrastructure.credentials import (
    KeyringCredentialStore,
    StoredCredentials,
    load_backlog_timer_credentials,
)
from ..infrastructure.retroachievements import (
    RetroAchievementsClient,
    retroarch_setting,
)


class CredentialStore(Protocol):
    @property
    def available(self) -> bool: ...

    def get(self, account: str) -> str: ...

    def set(self, account: str, secret: str) -> None: ...


def create_ra_client(
    config_path: Path,
    cache_dir: Path,
    prompt_api_key: Callable[[str], str],
    *,
    environment: Mapping[str, str] | None = None,
    store: CredentialStore | None = None,
    backlog_loader: Callable[[], StoredCredentials | None] = load_backlog_timer_credentials,
) -> RetroAchievementsClient:
    values = environment if environment is not None else os.environ
    username = retroarch_setting(config_path, "cheevos_username")
    api_key = values.get("RETROACHIEVEMENTS_API_KEY", "").strip()
    credential_store = store or KeyringCredentialStore()
    if not api_key and username:
        api_key = credential_store.get(username).strip()
    if not api_key:
        backlog = backlog_loader()
        if backlog is not None:
            username = username or backlog.username
            api_key = backlog.api_key.strip()
    if not username:
        raise RuntimeError(
            "Configure RetroAchievements in RetroArch or the RA Backlog Timer website first"
        )
    if not api_key:
        api_key = prompt_api_key(username).strip()
        if api_key and credential_store.available:
            credential_store.set(username, api_key)
    if not api_key:
        raise RuntimeError("A RetroAchievements Web API key is required")
    return RetroAchievementsClient(username, api_key, cache_dir=cache_dir)