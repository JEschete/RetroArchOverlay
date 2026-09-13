from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QAccessible

from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.presentation.qt import QtManagerSettingsDialog
from retroarch_overlay.retroarch_installation import network_commands_enabled


def _retroarch(root: Path, enabled: bool = False) -> Path:
    root.mkdir()
    (root / "retroarch.cfg").write_text(
        f'network_cmd_enable = "{str(enabled).lower()}"\nnetwork_cmd_port = "55355"\n',
        encoding="utf-8",
    )
    return root


def test_dialog_loads_configured_folder_and_network_state(qtbot, tmp_path: Path) -> None:
    retroarch = _retroarch(tmp_path / "RetroArch", enabled=True)
    settings = LocalPluginSettings(tmp_path / "settings.json")
    settings.save_retroarch_path(retroarch)
    dialog = QtManagerSettingsDialog(settings, lambda: tmp_path / "fallback.cfg")
    qtbot.addWidget(dialog)

    assert dialog.retroarch_path.text() == str(retroarch.resolve())
    assert dialog.network_enabled.isChecked()
    assert str(retroarch / "retroarch.cfg") in dialog.config_status.text()


def test_path_controls_have_contextual_accessible_names(qtbot, tmp_path: Path) -> None:
    dialog = QtManagerSettingsDialog(
        LocalPluginSettings(tmp_path / "settings.json"),
        lambda: tmp_path / "fallback.cfg",
    )
    qtbot.addWidget(dialog)

    assert dialog.retroarch_path.accessibleName() == "RetroArch folder"
    assert dialog.browse_button.accessibleName() == "Browse for RetroArch folder"
    status = QAccessible.queryAccessibleInterface(dialog.config_status)
    assert status is not None
    assert status.text(QAccessible.Text.Name) == (
        "retroarch.cfg was not found in this folder"
    )
    assert status.text(QAccessible.Text.Description) == (
        "RetroArch configuration status"
    )


def test_dialog_uses_automatic_config_when_folder_is_blank(qtbot, tmp_path: Path) -> None:
    fallback = tmp_path / "retroarch.cfg"
    fallback.write_text('network_cmd_enable = "false"\n', encoding="utf-8")
    dialog = QtManagerSettingsDialog(
        LocalPluginSettings(tmp_path / "settings.json"),
        lambda: fallback,
    )
    qtbot.addWidget(dialog)

    assert dialog.selected_config() == fallback
    assert dialog.network_enabled.isEnabled()
    assert not dialog.network_enabled.isChecked()


def test_save_updates_local_path_and_network_setting(qtbot, tmp_path: Path) -> None:
    retroarch = _retroarch(tmp_path / "RetroArch")
    settings = LocalPluginSettings(tmp_path / "settings.json")
    dialog = QtManagerSettingsDialog(settings, lambda: tmp_path / "fallback.cfg")
    qtbot.addWidget(dialog)
    dialog.retroarch_path.setText(str(retroarch))
    dialog.network_enabled.setChecked(True)

    dialog.save()

    assert LocalPluginSettings(settings.path).retroarch_path() == retroarch.resolve()
    assert network_commands_enabled(retroarch / "retroarch.cfg")
    assert dialog.result_status.text() == "Saved settings; restart RetroArch"
    assert dialog.result() == dialog.DialogCode.Accepted


def test_invalid_folder_reports_error_without_closing(qtbot, tmp_path: Path) -> None:
    dialog = QtManagerSettingsDialog(
        LocalPluginSettings(tmp_path / "settings.json"),
        lambda: tmp_path / "fallback.cfg",
    )
    qtbot.addWidget(dialog)
    dialog.retroarch_path.setText(str(tmp_path / "missing"))

    dialog.save()

    assert "does not exist" in dialog.result_status.text()
    assert dialog.result() == 0


def test_browse_updates_folder(qtbot, tmp_path: Path) -> None:
    retroarch = _retroarch(tmp_path / "RetroArch")
    dialog = QtManagerSettingsDialog(
        LocalPluginSettings(tmp_path / "settings.json"),
        lambda: tmp_path / "fallback.cfg",
    )
    qtbot.addWidget(dialog)

    with patch(
        "retroarch_overlay.presentation.qt.manager_settings_dialog.QFileDialog.getExistingDirectory",
        return_value=str(retroarch),
    ):
        dialog.browse()

    assert dialog.retroarch_path.text() == str(retroarch)