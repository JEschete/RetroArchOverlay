from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QDialog

from retroarch_overlay.presentation.qt import QtApiKeyDialog


def test_qt_api_key_dialog_masks_and_validates_secret(qtbot) -> None:
    dialog = QtApiKeyDialog("Player")
    qtbot.addWidget(dialog)

    assert dialog.key_edit.echoMode() == dialog.key_edit.EchoMode.Password
    dialog._save()
    assert "Enter" in dialog.error_label.text()
    assert dialog.result() == 0
    error = QAccessible.queryAccessibleInterface(dialog.error_label)
    assert error is not None
    assert error.text(QAccessible.Text.Name) == "Enter your RA Web API key"
    assert error.text(QAccessible.Text.Description) == "API key validation"

    dialog.key_edit.setText(" secret ")
    dialog._save()

    assert dialog.api_key == "secret"
    assert dialog.result() == QDialog.DialogCode.Accepted