from __future__ import annotations

from pathlib import Path


QT_RUNTIME_DISTRIBUTION = "PySide6-Essentials"
QT_RUNTIME_MODULES = ("QtCore", "QtGui", "QtWidgets")
QT_TEST_ONLY_MODULES = ("QtTest",)
WINDOWS_QT_PLUGIN_ALLOWLIST = (
    "platforms/qwindows.dll",
    "styles/qmodernwindowsstyle.dll",
    "imageformats/qgif.dll",
    "imageformats/qico.dll",
    "imageformats/qjpeg.dll",
)


def missing_qt_plugins(
    plugin_root: Path,
    required: tuple[str, ...] = WINDOWS_QT_PLUGIN_ALLOWLIST,
) -> tuple[str, ...]:
    return tuple(
        relative for relative in required if not (plugin_root / relative).is_file()
    )