import logging
import os
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable


LOGGER = logging.getLogger(__name__)


def configure_logging(log_path: Path, level: int = logging.INFO) -> Path:
    path = log_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("retroarch_overlay")
    logger.setLevel(level)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == path
        for handler in logger.handlers
    ):
        handler = RotatingFileHandler(
            path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s "
                "%(name)s: %(message)s"
            )
        )
        logger.addHandler(handler)
    return path


class UIHangWatchdog:
    def __init__(
        self,
        report_path: Path,
        *,
        timeout_seconds: float = 3.0,
        repeat_seconds: float = 10.0,
        check_interval_seconds: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_seconds <= 0 or repeat_seconds <= 0 or check_interval_seconds <= 0:
            raise ValueError("Hang watchdog intervals must be positive")
        self.report_path = report_path.expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.repeat_seconds = repeat_seconds
        self.check_interval_seconds = check_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heartbeat = clock()
        self._last_report = 0.0
        self._context = "Tk event loop starting"
        self._reported = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_heartbeat = self._clock()
        self._thread = threading.Thread(
            target=self._run,
            name="retroarch-overlay-hang-watchdog",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info(
            "UI hang watchdog started timeout=%.1fs report=%s",
            self.timeout_seconds,
            self.report_path,
        )

    def stop(self) -> None:
        self._stop.set()

    def heartbeat(self, context: str = "Tk event loop idle") -> None:
        now = self._clock()
        with self._lock:
            recovered = self._reported
            self._last_heartbeat = now
            self._last_report = 0.0
            self._context = context
            self._reported = False
        if recovered:
            LOGGER.warning("Tk event loop recovered after a reported stall")

    def set_context(self, context: str) -> None:
        with self._lock:
            self._context = context

    def capture_if_stalled(self, now: float | None = None) -> bool:
        checked_at = self._clock() if now is None else now
        with self._lock:
            elapsed = checked_at - self._last_heartbeat
            due = elapsed >= self.timeout_seconds and (
                not self._reported
                or checked_at - self._last_report >= self.repeat_seconds
            )
            if not due:
                return False
            context = self._context
            self._reported = True
            self._last_report = checked_at
        self._write_report(context, elapsed)
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.check_interval_seconds):
            self.capture_if_stalled()

    def _write_report(self, context: str, elapsed: float) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_report()
        report = (
            f"\n{'=' * 80}\n"
            f"UI HANG DETECTED pid={os.getpid()} stalled={elapsed:.3f}s\n"
            f"context={context}\n"
            f"{'=' * 80}\n"
            f"{self._thread_dump()}\n"
        )
        try:
            with self.report_path.open("a", encoding="utf-8") as stream:
                stream.write(report)
                stream.flush()
        except OSError:
            LOGGER.exception("Could not write UI hang report")
            return
        LOGGER.error(
            "UI event loop stalled for %.3fs during %s; thread dump written to %s",
            elapsed,
            context,
            self.report_path,
        )

    @staticmethod
    def _thread_dump() -> str:
        frames = sys._current_frames()
        sections = []
        for thread in sorted(threading.enumerate(), key=lambda item: item.name):
            frame = frames.get(thread.ident) if thread.ident is not None else None
            stack = "".join(traceback.format_stack(frame)) if frame is not None else "<no frame>\n"
            sections.append(
                f"--- thread name={thread.name!r} ident={thread.ident} "
                f"daemon={thread.daemon} ---\n{stack}"
            )
        return "\n".join(sections)

    def _rotate_report(self, maximum_bytes: int = 2 * 1024 * 1024) -> None:
        try:
            if not self.report_path.is_file() or self.report_path.stat().st_size < maximum_bytes:
                return
            oldest = self.report_path.with_suffix(self.report_path.suffix + ".2")
            previous = self.report_path.with_suffix(self.report_path.suffix + ".1")
            oldest.unlink(missing_ok=True)
            if previous.exists():
                previous.replace(oldest)
            self.report_path.replace(previous)
        except OSError:
            LOGGER.exception("Could not rotate UI hang report")