from unittest.mock import Mock, patch

import pytest

from retroarch_overlay.main import build_parser, run_qt_overlay


def test_parser_rejects_removed_ui_selector() -> None:
    assert not hasattr(build_parser().parse_args([]), "ui")
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--ui"])


def test_qt_overlay_starts_window() -> None:
    settings = Mock()
    settings.theme.return_value = "dark"
    controller = Mock()
    with patch("retroarch_overlay.presentation.qt.create_qt_application") as create:
        with patch("retroarch_overlay.presentation.qt.apply_qt_theme") as apply_theme:
            with patch("retroarch_overlay.presentation.qt.QtOverlayWindow") as window_type:
                create.return_value.exec.return_value = 17
                result = run_qt_overlay(controller, 0.8, settings)

    assert result == 17
    apply_theme.assert_called_once_with(create.return_value, "dark")
    window_type.assert_called_once_with(controller, opacity=0.8, settings=settings)
    window_type.return_value.start.assert_called_once_with()