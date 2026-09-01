from pathlib import Path
from typing import Callable

from .core.retroachievements import RAProgress
from .infrastructure.credentials import KEYRING_SERVICE, KeyringCredentialStore
from .infrastructure.retroachievements import load_ra_progress, retroarch_setting
from .presentation.tk.credentials import prompt_ra_api_key


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
    "KEYRING_SERVICE",
    "RAProgress",
    "clear_ra_api_key",
    "get_ra_api_key",
    "load_ra_progress",
    "retroarch_setting",
]