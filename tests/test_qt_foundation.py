from __future__ import annotations

from collections.abc import Sequence

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from retroarch_overlay.presentation.qt import (
    ControllerEventBridge,
    create_qt_application,
    qimage_from_pillow,
)
from retroarch_overlay.presentation.qt.application import (
    APPLICATION_NAME,
    ORGANIZATION_NAME,
)


class StubController:
    def __init__(self, events: Sequence[object] = ()) -> None:
        self.events = list(events)
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def drain_latest(self) -> object | None:
        if not self.events:
            return None
        latest = self.events[-1]
        self.events.clear()
        return latest


def test_application_factory_reuses_qtbot_application(qapp: QApplication) -> None:
    application = create_qt_application(("retroarch-overlay-test",))

    assert application is qapp
    assert QCoreApplication.organizationName() == ORGANIZATION_NAME
    assert QCoreApplication.applicationName() == APPLICATION_NAME
    assert application.applicationDisplayName() == APPLICATION_NAME


def test_controller_bridge_delivers_latest_event_and_stops(qtbot) -> None:
    older = object()
    latest = object()
    controller = StubController((older, latest))
    bridge = ControllerEventBridge(controller, poll_interval_ms=1)

    with qtbot.waitSignal(bridge.event_ready, timeout=1_000) as emitted:
        bridge.start()

    assert emitted.args == [latest]
    assert controller.starts == 1
    assert bridge.is_running

    bridge.stop()

    assert controller.stops == 1
    assert not bridge.is_running


def test_controller_bridge_rejects_nonpositive_interval() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ControllerEventBridge(StubController(), poll_interval_ms=0)


def test_pillow_rgba_conversion_is_exact_and_detached() -> None:
    source = Image.new("RGBA", (8, 8), (12, 34, 56, 200))

    image = qimage_from_pillow(source)
    source.putpixel((0, 0), (1, 2, 3, 4))

    assert image.pixelColor(0, 0).getRgb() == (12, 34, 56, 200)
    assert (image.width(), image.height()) == (8, 8)


def test_graphics_view_displays_converted_image(qtbot) -> None:
    image = qimage_from_pillow(Image.new("RGB", (16, 12), (20, 40, 60)))
    scene = QGraphicsScene()
    item = scene.addPixmap(QPixmap.fromImage(image))
    view = QGraphicsView(scene)
    qtbot.addWidget(view)

    view.show()
    qtbot.waitUntil(view.isVisible)

    assert item.pixmap().size().toTuple() == (16, 12)
    assert scene.items() == [item]