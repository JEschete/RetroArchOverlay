from typing import Any

try:
    import keyring as _keyring
except ModuleNotFoundError:
    _keyring = None


KEYRING_SERVICE = "RetroArch Overlay"
_DEFAULT_BACKEND = object()


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