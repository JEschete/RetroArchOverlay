from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from retroarch_overlay.core.models import LayoutProfile
from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.presentation.qt import (
    QtOverlaySettingsDialog,
    QtOverlayWindow,
)


class StubController:
    content_key = None
    last_status = None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def drain_latest(self) -> None:
        return None


def _select(combo, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_dialog_round_trips_all_preferences_and_bounds_values(qtbot) -> None:
    original = LayoutProfile(
        mode="rail",
        rail_side="left",
        rail_width=420,
        density="normal",
        game_scaling="integer",
        manage_retroarch_window=False,
    )
    saved = []
    dialog = QtOverlaySettingsDialog(
        original,
        "high-contrast",
        0.75,
        lambda *values: saved.append(values),
    )
    qtbot.addWidget(dialog)

    assert dialog.values() == (original, "high-contrast", 0.75)

    dialog.rail_width.setValue(1_000)
    dialog.opacity.setValue(1)
    dialog.save()

    profile, theme, opacity = saved[0]
    assert profile.rail_width == 640
    assert theme == "high-contrast"
    assert opacity == 0.3
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_dialog_keeps_persistence_errors_visible(qtbot) -> None:
    def fail(*_values) -> None:
        raise OSError("disk unavailable")

    dialog = QtOverlaySettingsDialog(LayoutProfile(), "light", 1.0, fail)
    qtbot.addWidget(dialog)

    dialog.save()

    assert dialog.result() == 0
    assert dialog.status_label.text() == (
        "Unable to save overlay settings: disk unavailable"
    )


def test_overlay_settings_apply_live_and_persist_together(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    settings.save_overlay_preferences(LayoutProfile(), "light", 1.0)
    window = QtOverlayWindow(StubController(), settings=settings)
    qtbot.addWidget(window)
    window.show()

    window.settings_button.click()
    dialog = window._settings_dialog
    assert dialog is not None and dialog.isVisible()
    _select(dialog.mode, "overlay")
    _select(dialog.side, "left")
    _select(dialog.density, "normal")
    _select(dialog.scaling, "fit")
    _select(dialog.theme, "dark")
    dialog.rail_width.setValue(440)
    dialog.opacity.setValue(70)
    dialog.manage_window.setChecked(False)

    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    assert save is not None
    save.click()

    expected = LayoutProfile(
        mode="overlay",
        rail_side="left",
        rail_width=440,
        density="normal",
        game_scaling="fit",
        manage_retroarch_window=False,
    )
    reloaded = LocalPluginSettings(settings.path)
    assert reloaded.layout_profile() == expected
    assert reloaded.theme() == "dark"
    assert reloaded.overlay_opacity() == 0.7
    assert window._layout_manager.profile == expected
    assert window.theme_name == "dark"
    assert window.windowOpacity() == pytest.approx(0.7, abs=1 / 255)
    assert not dialog.isVisible()


def test_owner_close_retires_open_settings_dialog(qtbot) -> None:
    window = QtOverlayWindow(StubController())
    qtbot.addWidget(window)
    window.show()
    window.settings_button.click()
    dialog = window._settings_dialog
    assert dialog is not None and dialog.isVisible()

    window.close()

    assert not dialog.isVisible()
    assert window._settings_dialog is None