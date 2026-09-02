import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import keyring as _keyring
except ModuleNotFoundError:
    _keyring = None


KEYRING_SERVICE = "RetroArch Overlay"
BACKLOG_KEYRING_SERVICE = "RAHLTBScraper"
_DEFAULT_BACKEND = object()


@dataclass(frozen=True, slots=True)
class StoredCredentials:
    username: str
    api_key: str


class KeyringCredentialStore:
    def __init__(
        self,
        service: str = KEYRING_SERVICE,
        backend: Any = _DEFAULT_BACKEND,
    ) -> None:
        self._service = service
        self._backend = _keyring if backend is _DEFAULT_BACKEND else backend

    @property
    def available(self) -> bool:
        return self._backend is not None

    def get(self, account: str) -> str:
        if self._backend is None or not account:
            return ""
        return self._backend.get_password(self._service, account) or ""

    def set(self, account: str, secret: str) -> None:
        if self._backend is None:
            raise RuntimeError("The keyring package is not available")
        if not account or not secret:
            raise ValueError("Account and secret are required")
        self._backend.set_password(self._service, account, secret)

    def delete(self, account: str) -> None:
        if self._backend is None or not account:
            return
        try:
            self._backend.delete_password(self._service, account)
        except Exception as error:
            delete_error = getattr(
                getattr(self._backend, "errors", None),
                "PasswordDeleteError",
                None,
            )
            if delete_error is not None and isinstance(error, delete_error):
                return
            raise


def load_backlog_timer_credentials(
    *,
    backend: Any = _DEFAULT_BACKEND,
    fallback_path: Path | None = None,
) -> StoredCredentials | None:
    keyring_backend = _keyring if backend is _DEFAULT_BACKEND else backend
    if keyring_backend is not None:
        try:
            username = keyring_backend.get_password(BACKLOG_KEYRING_SERVICE, "username") or ""
            api_key = keyring_backend.get_password(BACKLOG_KEYRING_SERVICE, "api_key") or ""
        except Exception:
            username = ""
            api_key = ""
        if username and api_key:
            return StoredCredentials(username, api_key)

    path = fallback_path or _backlog_timer_credentials_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    username = document.get("username", "")
    api_key = document.get("api_key", "")
    if isinstance(username, str) and isinstance(api_key, str) and username and api_key:
        return StoredCredentials(username, api_key)
    return None


def _backlog_timer_credentials_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "RA_Backlog_Timer" / ".ra_credentials.json"