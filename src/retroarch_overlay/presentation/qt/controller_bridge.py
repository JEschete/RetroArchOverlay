from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class ControllerEventSource(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def drain_latest(self) -> object | None: ...


class ControllerEventBridge(QObject):
    event_ready = Signal(object)

    def __init__(
        self,
        source: ControllerEventSource,
        *,
        poll_interval_ms: int = 100,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if poll_interval_ms <= 0:
            raise ValueError("Qt controller poll interval must be positive")
        self._source = source
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self.drain_latest)

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    @Slot()
    def start(self) -> None:
        if self._timer.isActive():
            return
        self._source.start()
        self._timer.start()

    @Slot()
    def stop(self) -> None:
        self._timer.stop()
        self._source.stop()

    @Slot()
    def drain_latest(self) -> None:
        event = self._source.drain_latest()
        if event is not None:
            self.event_ready.emit(event)