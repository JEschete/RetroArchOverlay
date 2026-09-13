from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar


Result = TypeVar("Result")
Dispatch = Callable[[Callable[[], None]], None]


class TaskCoordinator(Generic[Result]):
    def __init__(self, dispatch: Dispatch) -> None:
        self._dispatch = dispatch
        self._lock = threading.Lock()
        self._busy = False
        self._closed = False
        self._label = ""

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def label(self) -> str:
        with self._lock:
            return self._label

    def start(
        self,
        label: str,
        operation: Callable[[], Result],
        on_success: Callable[[Result], None],
        on_failure: Callable[[Exception], None],
    ) -> bool:
        with self._lock:
            if self._closed or self._busy:
                return False
            self._busy = True
            self._label = label

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                callback = lambda error=error: self._finish_failure(error, on_failure)
            else:
                callback = lambda result=result: self._finish_success(result, on_success)
            try:
                self._dispatch(callback)
            except Exception:
                self._finish()
                raise

        threading.Thread(
            target=worker,
            name="retroarch-overlay-task",
            daemon=True,
        ).start()
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _finish_success(
        self,
        result: Result,
        callback: Callable[[Result], None],
    ) -> None:
        deliver = self._finish()
        if deliver:
            callback(result)

    def _finish_failure(
        self,
        error: Exception,
        callback: Callable[[Exception], None],
    ) -> None:
        deliver = self._finish()
        if deliver:
            callback(error)

    def _finish(self) -> bool:
        with self._lock:
            self._busy = False
            self._label = ""
            return not self._closed