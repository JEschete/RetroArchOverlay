from pathlib import Path
from unittest.mock import Mock

import pytest

from retroarch_overlay.app.ra_credentials import create_ra_client
from retroarch_overlay.infrastructure.credentials import StoredCredentials


def _config(path: Path, username: str = "Player") -> Path:
    path.write_text(f'cheevos_username = "{username}"\n', encoding="utf-8")
    return path


def test_environment_key_has_priority_without_prompt(tmp_path: Path) -> None:
    prompt = Mock()
    store = Mock(available=True)

    client = create_ra_client(
        _config(tmp_path / "retroarch.cfg"),
        tmp_path / "cache",
        prompt,
        environment={"RETROACHIEVEMENTS_API_KEY": "environment-key"},
        store=store,
        backlog_loader=lambda: None,
    )

    assert client.username == "Player"
    prompt.assert_not_called()
    store.get.assert_not_called()


def test_keyring_precedes_backlog_and_prompt(tmp_path: Path) -> None:
    prompt = Mock()
    store = Mock(available=True)
    store.get.return_value = "stored-key"
    backlog = Mock()

    client = create_ra_client(
        _config(tmp_path / "retroarch.cfg"),
        tmp_path / "cache",
        prompt,
        environment={},
        store=store,
        backlog_loader=backlog,
    )

    assert client.username == "Player"
    store.get.assert_called_once_with("Player")
    backlog.assert_not_called()
    prompt.assert_not_called()


def test_backlog_supplies_missing_username_and_key(tmp_path: Path) -> None:
    config = _config(tmp_path / "retroarch.cfg", "")
    store = Mock(available=True)

    client = create_ra_client(
        config,
        tmp_path / "cache",
        Mock(),
        environment={},
        store=store,
        backlog_loader=lambda: StoredCredentials("Backlog", "backlog-key"),
    )

    assert client.username == "Backlog"


def test_prompted_key_is_persisted_when_store_is_available(tmp_path: Path) -> None:
    store = Mock(available=True)
    store.get.return_value = ""

    client = create_ra_client(
        _config(tmp_path / "retroarch.cfg"),
        tmp_path / "cache",
        lambda username: " prompted-key ",
        environment={},
        store=store,
        backlog_loader=lambda: None,
    )

    assert client.username == "Player"
    store.set.assert_called_once_with("Player", "prompted-key")


def test_missing_username_or_canceled_key_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Configure RetroAchievements"):
        create_ra_client(
            _config(tmp_path / "missing-user.cfg", ""),
            tmp_path / "cache",
            Mock(),
            environment={},
            store=Mock(available=False),
            backlog_loader=lambda: None,
        )

    store = Mock(available=False)
    store.get.return_value = ""
    with pytest.raises(RuntimeError, match="API key is required"):
        create_ra_client(
            _config(tmp_path / "missing-key.cfg"),
            tmp_path / "cache",
            lambda _username: "",
            environment={},
            store=store,
            backlog_loader=lambda: None,
        )