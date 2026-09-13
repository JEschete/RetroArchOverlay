from unittest.mock import Mock, patch

from retroarch_overlay.main import build_parser, run_overlay_ui


def test_parser_defaults_to_qt_and_retains_explicit_tk_fallback() -> None:
    assert build_parser().parse_args([]).ui == "qt"
    assert build_parser().parse_args(["--ui", "tk"]).ui == "tk"


@patch("retroarch_overlay.main.run_qt_overlay", return_value=17)
@patch("retroarch_overlay.main.OverlayWindow")
def test_qt_dispatch_does_not_construct_tk_window(
    overlay_window: Mock,
    run_qt_overlay: Mock,
) -> None:
    client = Mock()
    registry = Mock()
    settings = Mock()
    settings.theme.return_value = "dark"
    controller = Mock()

    result = run_overlay_ui(
        "qt", client, registry, 0.8, settings, controller
    )

    assert result == 17
    run_qt_overlay.assert_called_once_with(controller, 0.8, settings)
    overlay_window.assert_not_called()


@patch("retroarch_overlay.main.run_qt_overlay")
@patch("retroarch_overlay.main.OverlayWindow")
def test_tk_dispatch_preserves_existing_constructor_and_run(
    overlay_window: Mock,
    run_qt_overlay: Mock,
) -> None:
    client = Mock()
    registry = Mock()
    settings = Mock()
    controller = Mock()

    result = run_overlay_ui(
        "tk", client, registry, 1.0, settings, controller
    )

    assert result == 0
    overlay_window.assert_called_once_with(
        client,
        registry,
        1.0,
        settings,
        controller,
    )
    overlay_window.return_value.run.assert_called_once_with()
    run_qt_overlay.assert_not_called()