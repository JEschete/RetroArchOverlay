from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ...app.tasks import TaskCoordinator


class QtTaskCoordinator(QObject):
    task_started = Signal(str)
    task_succeeded = Signal(str, object)
    task_failed = Signal(str, object)
    _dispatch = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dispatch.connect(lambda callback: callback())
        self._coordinator: TaskCoordinator[object] = TaskCoordinator(
            self._dispatch.emit
        )

    @property
    def busy(self) -> bool:
        return self._coordinator.busy

    def start(self, label: str, operation: Callable[[], object]) -> bool:
        started = self._coordinator.start(
            label,
            operation,
            lambda result: self.task_succeeded.emit(label, result),
            lambda error: self.task_failed.emit(label, error),
        )
        if started:
            self.task_started.emit(label)
        return started

    def close(self) -> None:
        self._coordinator.close()