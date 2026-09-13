from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...local_settings import LocalPluginSettings
from ...retroarch_installation import (
    network_commands_enabled,
    set_network_commands_enabled,
)


class QtManagerSettingsDialog(QDialog):
    def __init__(
        self,
        settings: LocalPluginSettings,
        default_config: Callable[[], Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._default_config = default_config
        self.setWindowTitle("RetroArch Overlay Settings")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.retroarch_path = QLineEdit(self)
        self.retroarch_path.setAccessibleName("RetroArch folder")
        configured = settings.retroarch_path()
        self.retroarch_path.setText(str(configured) if configured is not None else "")
        path_row = QWidget(self)
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.retroarch_path, 1)
        self.browse_button = QPushButton("Browse", path_row)
        self.browse_button.setAccessibleName("Browse for RetroArch folder")
        self.browse_button.clicked.connect(self.browse)
        path_layout.addWidget(self.browse_button)
        form.addRow("RetroArch folder", path_row)
        self.config_status = QLabel(self)
        self.config_status.setWordWrap(True)
        self.config_status.setAccessibleDescription("RetroArch configuration status")
        form.addRow("Configuration", self.config_status)
        self.network_enabled = QCheckBox(
            "Enable RetroArch network commands",
            self,
        )
        form.addRow("Network", self.network_enabled)
        layout.addLayout(form)
        self.result_status = QLabel(self)
        self.result_status.setAccessibleDescription("Settings result")
        layout.addWidget(self.result_status)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.save_button = QPushButton("Save", self)
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self.retroarch_path.textChanged.connect(self.sync_status)
        self.sync_status()

    def selected_config(self) -> Path:
        value = self.retroarch_path.text().strip()
        return Path(value).expanduser() / "retroarch.cfg" if value else self._default_config()

    def sync_status(self) -> None:
        config = self.selected_config()
        exists = config.is_file()
        self.config_status.setText(
            f"Config: {config}" if exists else "retroarch.cfg was not found in this folder"
        )
        self.network_enabled.setEnabled(exists)
        self.network_enabled.setChecked(network_commands_enabled(config) if exists else False)

    def browse(self) -> None:
        value = self.retroarch_path.text().strip()
        current = Path(value).expanduser() if value else Path.home()
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select RetroArch folder",
            str(current if current.is_dir() else Path.home()),
        )
        if selected:
            self.retroarch_path.setText(selected)

    def save(self) -> None:
        value = self.retroarch_path.text().strip()
        try:
            self.settings.save_retroarch_path(Path(value) if value else None)
            config = self.selected_config()
            changed = (
                set_network_commands_enabled(config, self.network_enabled.isChecked())
                if config.is_file()
                else False
            )
        except Exception as error:
            self.result_status.setText(f"Unable to save settings: {error}")
            return
        self.result_status.setText(
            "Saved settings; restart RetroArch"
            if changed
            else "Saved local settings"
        )
        self.accept()