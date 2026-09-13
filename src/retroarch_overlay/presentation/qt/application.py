from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo
from PySide6.QtWidgets import QApplication

from .deployment import missing_qt_plugins


APPLICATION_NAME = "RetroArch Overlay"
ORGANIZATION_NAME = "RetroArchOverlay"
LOGGER = logging.getLogger(__name__)


def validate_qt_runtime(
    *,
    plugin_root: Path | None = None,
    platform_name: str | None = None,
) -> None:
    selected_platform = platform_name or os.environ.get("QT_QPA_PLATFORM", "")
    selected_platform = selected_platform.partition(":")[0].lower()
    if not selected_platform and sys.platform == "win32":
        selected_platform = "windows"
    if selected_platform != "windows":
        return
    root = plugin_root or Path(
        QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    )
    missing = missing_qt_plugins(root)
    if not missing:
        return
    message = (
        f"The Qt runtime under {root} is incomplete; missing: "
        f"{', '.join(missing)}. Reinstall with: python -m pip install "
        '--force-reinstall "PySide6-Essentials>=6.11,<6.12"'
    )
    LOGGER.error(message)
    raise RuntimeError(message)


def create_qt_application(argv: Sequence[str] | None = None) -> QApplication:
    instance = QCoreApplication.instance()
    if instance is None:
        validate_qt_runtime()
        application = QApplication(list(sys.argv if argv is None else argv))
    elif isinstance(instance, QApplication):
        application = instance
    else:
        raise RuntimeError("A non-GUI QCoreApplication already exists")

    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setApplicationName(APPLICATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    return application