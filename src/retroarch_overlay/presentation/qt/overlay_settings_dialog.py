from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.models import LayoutProfile
from ..theme import THEME_CHOICES
from .theme import apply_qt_theme


class QtOverlaySettingsDialog(QDialog):
    def __init__(
        self,
        profile: LayoutProfile,
        theme: str,
        opacity: float,
        on_save: Callable[[LayoutProfile, str, float], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self.setWindowTitle("Overlay Settings")
        self.setMinimumWidth(420)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = _choice(
            (
                ("Auto", "auto"),
                ("Rail", "rail"),
                ("Dual strips", "dual-strips"),
                ("Overlay", "overlay"),
            ),
            profile.mode,
            "Overlay layout mode",
            self,
        )
        form.addRow("Mode", self.mode)
        self.side = _choice(
            (("Left", "left"), ("Right", "right")),
            profile.rail_side,
            "Rail side",
            self,
        )
        form.addRow("Side", self.side)
        self.density = _choice(
            (("Compact", "compact"), ("Normal", "normal")),
            profile.density,
            "Information density",
            self,
        )
        form.addRow("Density", self.density)
        self.scaling = _choice(
            (("Auto", "auto"), ("Integer", "integer"), ("Fit", "fit")),
            profile.game_scaling,
            "Game scaling",
            self,
        )
        form.addRow("Game scale", self.scaling)
        self.theme = _choice(
            tuple(
                (value.replace("-", " ").title(), value)
                for value in THEME_CHOICES
            ),
            theme,
            "Overlay theme",
            self,
        )
        form.addRow("Theme", self.theme)

        self.rail_width = QSpinBox(self)
        self.rail_width.setRange(280, 640)
        self.rail_width.setSingleStep(20)
        self.rail_width.setValue(profile.rail_width)
        self.rail_width.setSuffix(" px")
        self.rail_width.setAccessibleName("Rail width")
        form.addRow("Rail width", self.rail_width)

        self.opacity = QSpinBox(self)
        self.opacity.setRange(30, 100)
        self.opacity.setSingleStep(5)
        self.opacity.setValue(round(opacity * 100))
        self.opacity.setSuffix(" %")
        self.opacity.setAccessibleName("Overlay opacity")
        form.addRow("Opacity", self.opacity)

        self.manage_window = QCheckBox("Resize windowed RetroArch", self)
        self.manage_window.setChecked(profile.manage_retroarch_window)
        form.addRow("RetroArch", self.manage_window)
        layout.addLayout(form)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleDescription("Overlay settings result")
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        apply_qt_theme(self, theme)

    def values(self) -> tuple[LayoutProfile, str, float]:
        profile = LayoutProfile(
            mode=str(self.mode.currentData()),
            rail_side=str(self.side.currentData()),
            rail_width=self.rail_width.value(),
            density=str(self.density.currentData()),
            game_scaling=str(self.scaling.currentData()),
            manage_retroarch_window=self.manage_window.isChecked(),
        )
        return profile, str(self.theme.currentData()), self.opacity.value() / 100

    def save(self) -> None:
        profile, theme, opacity = self.values()
        try:
            self._on_save(profile, theme, opacity)
        except (OSError, ValueError) as error:
            self.status_label.setText(f"Unable to save overlay settings: {error}")
            return
        self.accept()


def _choice(
    values: tuple[tuple[str, str], ...],
    selected: str,
    accessible_name: str,
    parent: QWidget,
) -> QComboBox:
    combo = QComboBox(parent)
    combo.setAccessibleName(accessible_name)
    for label, value in values:
        combo.addItem(label, value)
    index = combo.findData(selected)
    combo.setCurrentIndex(max(0, index))
    return combo