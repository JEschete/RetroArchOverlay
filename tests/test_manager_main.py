from unittest.mock import Mock, patch
from pathlib import Path

from retroarch_overlay.manager_gui import build_manager_parser, run_manager_ui


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_manager_parser_defaults_to_qt_and_retains_explicit_tk_fallback() -> None:
    assert build_manager_parser().parse_args([]).ui == "qt"
    assert build_manager_parser().parse_args(["--ui", "tk"]).ui == "tk"


def test_windows_launcher_installs_and_selects_qt() -> None:
    launcher = (PROJECT_ROOT / "launch_gui.cmd").read_text(encoding="utf-8")

    assert 'pip install -e ".[qt]"' in launcher
    assert "retroarch_overlay.manager_gui --ui qt" in launcher


@patch("retroarch_overlay.manager_gui.run_qt_manager", return_value=19)
@patch("retroarch_overlay.manager_gui.PluginManagerWindow")
@patch("retroarch_overlay.manager_gui.tk.Tk")
def test_qt_manager_dispatch_does_not_construct_tk(
    tk_root: Mock,
    manager_window: Mock,
    run_qt: Mock,
) -> None:
    result = run_manager_ui("qt")

    assert result == 19
    run_qt.assert_called_once_with()
    tk_root.assert_not_called()
    manager_window.assert_not_called()


@patch("retroarch_overlay.manager_gui.run_qt_manager")
@patch("retroarch_overlay.manager_gui.PluginManagerWindow")
@patch("retroarch_overlay.manager_gui.tk.Tk")
def test_tk_manager_dispatch_preserves_existing_lifecycle(
    tk_root: Mock,
    manager_window: Mock,
    run_qt: Mock,
) -> None:
    result = run_manager_ui("tk")

    assert result == 0
    manager_window.assert_called_once_with(tk_root.return_value)
    tk_root.return_value.mainloop.assert_called_once_with()
    run_qt.assert_not_called()