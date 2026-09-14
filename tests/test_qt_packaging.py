from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

from retroarch_overlay.presentation.qt.application import validate_qt_runtime
from retroarch_overlay.presentation.qt.deployment import (
    QT_RUNTIME_DISTRIBUTION,
    QT_RUNTIME_MODULES,
    QT_TEST_ONLY_MODULES,
    WINDOWS_QT_PLUGIN_ALLOWLIST,
    missing_qt_plugins,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QT_SOURCE_ROOT = PROJECT_ROOT / "src" / "retroarch_overlay" / "presentation" / "qt"
EXPECTED_ENTRY_POINTS = {
    "rao-plugin",
    "retroarch-overlay",
    "retroarch-overlay-cheeves",
    "retroarch-overlay-manager",
}


def _project_config() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)


def _pyside_modules(paths: tuple[Path, ...]) -> set[str]:
    modules: set[str] = set()
    for root in paths:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: tuple[str, ...]
                if isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = (node.module,)
                else:
                    continue
                for name in names:
                    if name.startswith("PySide6."):
                        modules.add(name.split(".", 2)[1])
    return modules


def test_runtime_uses_only_the_tested_essentials_minor() -> None:
    config = _project_config()

    assert "PySide6-Essentials>=6.11,<6.12" in config["project"]["dependencies"]
    assert "qt" not in config["project"]["optional-dependencies"]
    policy = config["tool"]["retroarch-overlay"]["qt-deployment"]
    assert policy["runtime-distribution"] == QT_RUNTIME_DISTRIBUTION
    assert tuple(policy["runtime-modules"]) == QT_RUNTIME_MODULES
    assert tuple(policy["test-only-modules"]) == QT_TEST_ONLY_MODULES
    assert tuple(policy["windows-plugins"]) == WINDOWS_QT_PLUGIN_ALLOWLIST


def test_production_qt_imports_match_the_module_allowlist() -> None:
    config = _project_config()
    policy = config["tool"]["retroarch-overlay"]["qt-deployment"]

    assert _pyside_modules((QT_SOURCE_ROOT,)) == set(policy["runtime-modules"])


def test_tests_use_only_runtime_and_declared_test_modules() -> None:
    config = _project_config()
    policy = config["tool"]["retroarch-overlay"]["qt-deployment"]
    allowed = set(policy["runtime-modules"]) | set(policy["test-only-modules"])

    assert _pyside_modules((PROJECT_ROOT / "tests",)) <= allowed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows deployment policy")
def test_windows_plugin_allowlist_exists_in_candidate_runtime() -> None:
    from PySide6.QtCore import QLibraryInfo

    config = _project_config()
    policy = config["tool"]["retroarch-overlay"]["qt-deployment"]
    plugin_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))

    missing = [
        relative
        for relative in policy["windows-plugins"]
        if not (plugin_root / relative).is_file()
    ]
    assert missing == []


def test_missing_plugin_check_preserves_allowlist_order(tmp_path: Path) -> None:
    present = tmp_path / WINDOWS_QT_PLUGIN_ALLOWLIST[1]
    present.parent.mkdir(parents=True)
    present.write_bytes(b"plugin")

    assert missing_qt_plugins(tmp_path) == (
        WINDOWS_QT_PLUGIN_ALLOWLIST[0],
        *WINDOWS_QT_PLUGIN_ALLOWLIST[2:],
    )


def test_windows_runtime_preflight_reports_recovery_command(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError) as raised:
        validate_qt_runtime(plugin_root=tmp_path, platform_name="windows")

    message = str(raised.value)
    assert "platforms/qwindows.dll" in message
    assert "PySide6-Essentials>=6.11,<6.12" in message


def test_non_windows_runtime_does_not_require_windows_plugins(tmp_path: Path) -> None:
    validate_qt_runtime(plugin_root=tmp_path, platform_name="offscreen")


def test_distribution_metadata_preserves_commands_and_notices() -> None:
    config = _project_config()

    assert set(config["project"]["scripts"]) == EXPECTED_ENTRY_POINTS
    assert config["project"]["urls"]["Repository"] == (
        "https://github.com/JEschete/RetroArchOverlay"
    )
    assert (PROJECT_ROOT / "LICENSE").is_file()
    assert (PROJECT_ROOT / "NOTICE").is_file()