import queue
import threading

from retroarch_overlay.app.tasks import TaskCoordinator


def _queued_dispatch():
    callbacks: queue.Queue[object] = queue.Queue()
    dispatched = threading.Event()

    def dispatch(callback) -> None:
        callbacks.put(callback)
        dispatched.set()

    return dispatch, callbacks, dispatched


def test_task_success_stays_busy_until_dispatched_callback_runs() -> None:
    dispatch, callbacks, dispatched = _queued_dispatch()
    coordinator = TaskCoordinator[int](dispatch)
    results = []

    assert coordinator.start("Work", lambda: 42, results.append, lambda _: None)
    assert dispatched.wait(1)
    assert coordinator.busy
    assert coordinator.label == "Work"

    callbacks.get_nowait()()

    assert results == [42]
    assert not coordinator.busy
    assert coordinator.label == ""


def test_task_failure_is_dispatched_and_overlapping_task_is_rejected() -> None:
    dispatch, callbacks, dispatched = _queued_dispatch()
    release = threading.Event()
    coordinator = TaskCoordinator[object](dispatch)
    errors = []

    def fail() -> object:
        release.wait(1)
        raise ValueError("broken")

    assert coordinator.start("Fail", fail, lambda _: None, errors.append)
    assert not coordinator.start("Overlap", lambda: None, lambda _: None, errors.append)
    release.set()
    assert dispatched.wait(1)
    callbacks.get_nowait()()

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "broken"
    assert not coordinator.busy


def test_close_suppresses_pending_callback() -> None:
    dispatch, callbacks, dispatched = _queued_dispatch()
    coordinator = TaskCoordinator[int](dispatch)
    results = []

    assert coordinator.start("Work", lambda: 42, results.append, lambda _: None)
    assert dispatched.wait(1)
    coordinator.close()
    callbacks.get_nowait()()

    assert results == []
    assert not coordinator.busy