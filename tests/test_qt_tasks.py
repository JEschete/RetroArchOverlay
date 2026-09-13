from retroarch_overlay.presentation.qt import QtTaskCoordinator


def test_qt_task_success_returns_to_gui_thread(qtbot) -> None:
    coordinator = QtTaskCoordinator()
    started = []
    coordinator.task_started.connect(started.append)

    with qtbot.waitSignal(coordinator.task_succeeded, timeout=1_000) as signal:
        assert coordinator.start("Load", lambda: 42)

    assert started == ["Load"]
    assert signal.args == ["Load", 42]
    assert not coordinator.busy


def test_qt_task_failure_emits_exception(qtbot) -> None:
    coordinator = QtTaskCoordinator()

    def fail() -> object:
        raise RuntimeError("offline")

    with qtbot.waitSignal(coordinator.task_failed, timeout=1_000) as signal:
        assert coordinator.start("Load", fail)

    assert signal.args[0] == "Load"
    assert isinstance(signal.args[1], RuntimeError)
    assert str(signal.args[1]) == "offline"