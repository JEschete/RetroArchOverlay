from retroarch_overlay.app.notifications import AlertNotification
from retroarch_overlay.presentation.qt import QtToastQueue


def test_toast_queue_shows_notifications_sequentially(qtbot) -> None:
    owner = __import__("PySide6.QtWidgets", fromlist=("QWidget",)).QWidget()
    owner.resize(500, 300)
    qtbot.addWidget(owner)
    owner.show()
    queue = QtToastQueue(owner, duration_ms=25)
    shown = []
    queue.notification_shown.connect(shown.append)
    first = AlertNotification("First", "One")
    second = AlertNotification("Second", "Two")

    queue.enqueue((first, second))

    assert queue.active == first
    assert queue.pending_count == 1
    assert queue.visible
    assert queue._frame.accessibleName() == "First: One"
    qtbot.waitUntil(lambda: len(shown) == 2, timeout=500)
    assert shown == [first, second]
    qtbot.waitUntil(lambda: not queue.visible, timeout=500)


def test_toast_repositions_and_theme_updates(qtbot) -> None:
    owner = __import__("PySide6.QtWidgets", fromlist=("QWidget",)).QWidget()
    owner.resize(480, 300)
    qtbot.addWidget(owner)
    owner.show()
    queue = QtToastQueue(owner, duration_ms=1_000)
    queue.enqueue((AlertNotification("Alert", "Details"),))

    owner.resize(620, 300)
    queue.reposition()
    name = queue.set_theme("high-contrast")

    assert name == "high-contrast"
    assert queue._frame.x() == owner.width() - queue._frame.width() - 8
    assert queue._frame.palette().window().color().name() == "#ffffff"
    assert queue._frame.palette().windowText().color().name() == "#a00000"


def test_clear_cancels_active_and_pending_notifications(qtbot) -> None:
    owner = __import__("PySide6.QtWidgets", fromlist=("QWidget",)).QWidget()
    qtbot.addWidget(owner)
    owner.show()
    queue = QtToastQueue(owner, duration_ms=1_000)
    queue.enqueue(
        (
            AlertNotification("First"),
            AlertNotification("Second"),
        )
    )

    queue.clear()

    assert queue.active is None
    assert queue.pending_count == 0
    assert not queue.visible
    assert not queue._timer.isActive()