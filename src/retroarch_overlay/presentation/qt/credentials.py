from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .application import create_qt_application


class QtApiKeyDialog(QDialog):
    def __init__(self, username: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("RetroAchievements API Key")
        self.setMinimumWidth(440)
        self._api_key = ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("RetroAchievements", self))
        layout.addWidget(QLabel(f"Account: {username}", self))
        layout.addWidget(QLabel("Enter your Web API key:", self))
        self.key_edit = QLineEdit(self)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setAccessibleName("RetroAchievements Web API key")
        layout.addWidget(self.key_edit)
        self.error_label = QLabel(self)
        self.error_label.setAccessibleDescription("API key validation")
        layout.addWidget(self.error_label)
        link = QPushButton("Open RetroAchievements settings", self)
        link.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://retroachievements.org/settings")
            )
        )
        layout.addWidget(link)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = QPushButton("Save", self)
        save.clicked.connect(self._save)
        actions.addWidget(save)
        layout.addLayout(actions)
        self.key_edit.returnPressed.connect(self._save)

    @property
    def api_key(self) -> str:
        return self._api_key

    def _save(self) -> None:
        value = self.key_edit.text().strip()
        if not value:
            self.error_label.setText("Enter your RA Web API key")
            return
        self._api_key = value
        self.accept()


def prompt_ra_api_key(username: str, parent: QWidget | None = None) -> str:
    application = create_qt_application()
    dialog = QtApiKeyDialog(username, parent)
    result = dialog.api_key if dialog.exec() == QDialog.DialogCode.Accepted else ""
    application.processEvents()
    return result