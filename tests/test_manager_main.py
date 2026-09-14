from pathlib import Path
from unittest.mock import patch

import pytest

from retroarch_overlay.manager_gui import build_manager_parser, main, run_qt_manager


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_manager_parser_rejects_removed_ui_selector() -> None:
    assert vars(build_manager_parser().parse_args([])) == {}
    with pytest.raises(SystemExit):
        build_manager_parser().parse_args(["--ui"])


def test_windows_launcher_installs_and_selects_qt() -> None:
    launcher = (PROJECT_ROOT / "launch_gui.cmd").read_text(encoding="utf-8")

    assert 'pip install -e "."' in launcher
    assert "retroarch_overlay.manager_gui" in launcher
    assert "--ui" not in launcher


def test_qt_manager_starts_window() -> None:
    with patch("retroarch_overlay.presentation.qt.create_qt_application") as create:
        with patch(
            "retroarch_overlay.presentation.qt.QtPluginManagerWindow"
        ) as window_type:
            create.return_value.exec.return_value = 19
            result = run_qt_manager()

    assert result == 19
    window_type.assert_called_once_with()
    window_type.return_value.show.assert_called_once_with()


@patch("retroarch_overlay.manager_gui.run_qt_manager", return_value=23)
def test_main_runs_qt_manager(run_qt: object) -> None:
    assert main([]) == 23