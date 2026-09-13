from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow

from retroarch_overlay.presentation.qt import WindowPresentation, apply_window_presentation


NATIVE_WINDOWS_ENABLED = (
    sys.platform == "win32"
    and os.environ.get("RAO_RUN_NATIVE_QT_TESTS") == "1"
    and os.environ.get("QT_QPA_PLATFORM", "windows").lower() == "windows"
)

pytestmark = pytest.mark.skipif(
    not NATIVE_WINDOWS_ENABLED,
    reason="set RAO_RUN_NATIVE_QT_TESTS=1 with the native Windows Qt platform",
)

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000


@pytest.mark.parametrize(
    ("presentation", "caption", "topmost", "tool", "layered"),
    (
        (WindowPresentation(), True, False, False, False),
        (
            WindowPresentation(opacity=0.82, always_on_top=True),
            True,
            True,
            False,
            True,
        ),
        (
            WindowPresentation(
                always_on_top=True,
                frameless=True,
                show_in_taskbar=False,
            ),
            False,
            True,
            True,
            False,
        ),
    ),
    ids=("normal", "topmost-translucent", "frameless-tool"),
)
def test_native_window_presentation_and_lifecycle(
    qtbot,
    presentation: WindowPresentation,
    caption: bool,
    topmost: bool,
    tool: bool,
    layered: bool,
) -> None:
    assert QApplication.platformName() == "windows"
    window = QMainWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    editor = QLineEdit(window)
    window.setCentralWidget(editor)
    window.resize(360, 220)
    qtbot.addWidget(window)

    apply_window_presentation(window, presentation)
    window.show()

    assert QTest.qWaitForWindowExposed(window, 1_000)
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 1_000)
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(editor.hasFocus, timeout=1_000)

    style, extended_style = _native_styles(int(window.winId()))
    assert bool(style & WS_CAPTION) is caption
    assert bool(extended_style & WS_EX_TOPMOST) is topmost
    assert bool(extended_style & WS_EX_TOOLWINDOW) is tool
    assert bool(extended_style & WS_EX_LAYERED) is layered
    assert window.windowOpacity() == pytest.approx(presentation.opacity, abs=1 / 255)

    with qtbot.waitSignal(window.destroyed, timeout=1_000):
        window.close()


def test_live_window_moves_across_every_attached_screen(qtbot) -> None:
    screens = tuple(QGuiApplication.screens())
    if len(screens) < 2:
        pytest.skip("native multi-monitor validation requires at least two screens")
    window = QMainWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.resize(360, 220)
    qtbot.addWidget(window)
    window.show()
    assert QTest.qWaitForWindowExposed(window, 1_000)
    handle = window.windowHandle()
    assert handle is not None

    observed = []
    handle.screenChanged.connect(lambda screen: observed.append(screen.name()))
    for screen in screens:
        available = screen.availableGeometry()
        window.move(
            available.left() + max(0, (available.width() - window.width()) // 2),
            available.top() + max(0, (available.height() - window.height()) // 2),
        )
        qtbot.waitUntil(lambda screen=screen: window.screen() is screen, timeout=1_000)
        assert QGuiApplication.screenAt(window.frameGeometry().center()) is screen
        assert available.contains(window.frameGeometry().center())

    assert set(observed) >= {screen.name() for screen in screens[1:]}
    with qtbot.waitSignal(window.destroyed, timeout=1_000):
        window.close()


def test_live_presentation_round_trip_preserves_native_window_state(qtbot) -> None:
    window = QMainWindow()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    editor = QLineEdit(window)
    window.setCentralWidget(editor)
    window.setGeometry(120, 140, 420, 300)
    qtbot.addWidget(window)
    window.show()
    assert QTest.qWaitForWindowExposed(window, 1_000)
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 1_000)
    editor.setFocus(Qt.FocusReason.OtherFocusReason)
    original_geometry = window.geometry().getRect()

    presentation = WindowPresentation(
        opacity=0.8,
        always_on_top=True,
        frameless=True,
        show_in_taskbar=False,
    )
    apply_window_presentation(window, presentation)
    assert QTest.qWaitForWindowActive(window, 1_000)
    qtbot.waitUntil(editor.hasFocus, timeout=1_000)
    style, extended_style = _native_styles(int(window.winId()))

    assert window.isVisible()
    assert window.geometry().getRect() == original_geometry
    assert not style & WS_CAPTION
    assert extended_style & WS_EX_TOPMOST
    assert extended_style & WS_EX_TOOLWINDOW
    assert extended_style & WS_EX_LAYERED

    apply_window_presentation(window, WindowPresentation())
    assert QTest.qWaitForWindowActive(window, 1_000)
    qtbot.waitUntil(editor.hasFocus, timeout=1_000)
    style, extended_style = _native_styles(int(window.winId()))

    assert window.isVisible()
    assert window.geometry().getRect() == original_geometry
    assert style & WS_CAPTION
    assert not extended_style & WS_EX_TOPMOST
    assert not extended_style & WS_EX_TOOLWINDOW
    assert not extended_style & WS_EX_LAYERED
    with qtbot.waitSignal(window.destroyed, timeout=1_000):
        window.close()


def test_repeated_native_application_startup_and_shutdown() -> None:
    source_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(source_root / "src"), environment.get("PYTHONPATH", "")),
        )
    )
    program = """
import json
from PySide6.QtCore import QTimer
from retroarch_overlay.presentation.qt import QtOverlayWindow, create_qt_application

class Controller:
    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.content_key = None
        self.last_status = None

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def drain_latest(self):
        return None

application = create_qt_application(("rao-native-lifecycle",))
controller = Controller()
window = QtOverlayWindow(controller, bridge_interval_ms=5)
window.start()
QTimer.singleShot(20, window.close)
exit_code = application.exec()
print(json.dumps({
    "exit_code": exit_code,
    "starts": controller.starts,
    "stops": controller.stops,
    "visible": window.isVisible(),
    "bridge_running": window.bridge.is_running,
}))
"""

    for iteration in range(5):
        result = subprocess.run(
            (sys.executable, "-c", program),
            cwd=source_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, (
            f"native lifecycle iteration {iteration} failed:\n{result.stderr}"
        )
        output = json.loads(result.stdout.splitlines()[-1])
        assert output == {
            "exit_code": 0,
            "starts": 1,
            "stops": 1,
            "visible": False,
            "bridge_running": False,
        }


def _native_styles(handle: int) -> tuple[int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_window_long = user32.GetWindowLongW
    get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
    get_window_long.restype = ctypes.c_long
    style = get_window_long(handle, GWL_STYLE) & 0xFFFFFFFF
    extended_style = get_window_long(handle, GWL_EXSTYLE) & 0xFFFFFFFF
    return style, extended_style