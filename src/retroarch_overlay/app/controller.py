from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from ..core.errors import GameUnavailableError
from ..core.models import OverlaySnapshot, RetroArchStatus
from ..retroarch import RetroArchError


LOGGER = logging.getLogger(__name__)


class RetroArchSession(Protocol):
    def get_status(self) -> RetroArchStatus: ...

    def read_memory(self, address: int, size: int) -> bytes: ...

    def close(self) -> None: ...


class AdapterRegistry(Protocol):
    def find(self, status: RetroArchStatus) -> object | None: ...


class DiagnosticCode(str, Enum):
    RETROARCH_STATE = "retroarch-state"
    CONNECTION_FAILED = "connection-failed"
    NO_ADAPTER = "no-adapter"
    GAME_UNAVAILABLE = "game-unavailable"
    PLUGIN_FAILED = "plugin-failed"
    STALE_SNAPSHOT = "stale-snapshot"
    INTERNAL_ERROR = "internal-error"


@dataclass(frozen=True, slots=True)
class OverlayDiagnostic:
    code: DiagnosticCode
    title: str
    message: str
    recoverable: bool = True

    def __str__(self) -> str:
        return self.message


ControllerEvent: TypeAlias = OverlaySnapshot | OverlayDiagnostic


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    initial_seconds: float = 0.25
    maximum_seconds: float = 2.0

    def delay(self, consecutive_failures: int) -> float:
        if consecutive_failures <= 0:
            return 0.0
        return min(
            self.maximum_seconds,
            self.initial_seconds * (2 ** (consecutive_failures - 1)),
        )


@dataclass(frozen=True, slots=True)
class ControllerMetrics:
    poll_seconds: float = 0.0
    snapshot_seconds: float = 0.0
    consecutive_failures: int = 0


class SnapshotCadence:
    def __init__(self, interval_seconds: float = 0.25) -> None:
        self.interval_seconds = interval_seconds
        self._content_key: tuple[str, str, str] | None = None
        self._last_snapshot_at = 0.0

    def should_snapshot(self, status: RetroArchStatus, now: float) -> bool:
        if status.state not in {"PLAYING", "PAUSED"}:
            self._content_key = None
            return False
        content_key = _content_key(status)
        if content_key != self._content_key:
            self._content_key = content_key
            self._last_snapshot_at = now
            return True
        if status.state == "PAUSED" or now - self._last_snapshot_at < self.interval_seconds:
            return False
        self._last_snapshot_at = now
        return True


class OverlayController:
    def __init__(
        self,
        client: RetroArchSession,
        registry: AdapterRegistry,
        *,
        poll_interval_seconds: float = 0.05,
        cadence: SnapshotCadence | None = None,
        retry_policy: RetryPolicy | None = None,
        verify_content_after_snapshot: bool = True,
    ) -> None:
        self._client = client
        self._registry = registry
        self._poll_interval_seconds = poll_interval_seconds
        self._cadence = cadence or SnapshotCadence()
        self._retry_policy = retry_policy or RetryPolicy()
        self._verify_content_after_snapshot = verify_content_after_snapshot
        self._results: queue.SimpleQueue[ControllerEvent] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status: RetroArchStatus | None = None
        self._metrics = ControllerMetrics()
        self._last_snapshot_seconds = 0.0

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def last_status(self) -> RetroArchStatus | None:
        return self._last_status

    @property
    def metrics(self) -> ControllerMetrics:
        return self._metrics

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="retroarch-overlay-controller",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def drain_latest(self) -> ControllerEvent | None:
        latest: ControllerEvent | None = None
        while True:
            try:
                latest = self._results.get_nowait()
            except queue.Empty:
                return latest

    def poll_once(self, now: float | None = None) -> ControllerEvent | None:
        try:
            status = self._client.get_status()
        except (OSError, RetroArchError, ValueError) as error:
            LOGGER.warning("RetroArch status request failed: %s", error)
            return OverlayDiagnostic(
                DiagnosticCode.CONNECTION_FAILED,
                "Not connected",
                str(error),
            )
        self._last_status = status

        current_time = time.monotonic() if now is None else now
        if status.state not in {"PLAYING", "PAUSED"}:
            self._cadence.should_snapshot(status, current_time)
            return OverlayDiagnostic(
                DiagnosticCode.RETROARCH_STATE,
                "RetroArch idle",
                f"RetroArch is {status.state.lower()}",
            )
        should_snapshot = self._cadence.should_snapshot(status, current_time)

        try:
            adapter = self._registry.find(status)
        except Exception as error:
            LOGGER.exception("Adapter selection failed")
            return OverlayDiagnostic(
                DiagnosticCode.INTERNAL_ERROR,
                "Adapter lookup failed",
                str(error),
            )
        if adapter is None:
            return OverlayDiagnostic(
                DiagnosticCode.NO_ADAPTER,
                "Unsupported game",
                f"No adapter for {status.core}: {status.content}",
            )

        capture = getattr(adapter, "capture", None)
        if status.state == "PLAYING" and not should_snapshot and callable(capture):
            try:
                capture(self._client)
            except Exception as error:
                LOGGER.warning("Plugin high-frequency capture failed: %s", error)
        if not should_snapshot:
            return None

        try:
            snapshot_started = time.perf_counter()
            snapshot = adapter.snapshot(self._client)  # type: ignore[attr-defined]
            self._last_snapshot_seconds = time.perf_counter() - snapshot_started
        except GameUnavailableError as error:
            LOGGER.warning("Game plugin unavailable: %s", error)
            return OverlayDiagnostic(
                DiagnosticCode.GAME_UNAVAILABLE,
                "Game unavailable",
                str(error),
            )
        except Exception as error:
            LOGGER.exception("Game plugin snapshot failed")
            return OverlayDiagnostic(
                DiagnosticCode.PLUGIN_FAILED,
                "Plugin error",
                f"{getattr(adapter, 'name', 'Game plugin')}: {error}",
            )

        if self._verify_content_after_snapshot:
            try:
                current_status = self._client.get_status()
            except (OSError, RetroArchError, ValueError) as error:
                LOGGER.warning("Snapshot verification failed: %s", error)
                return OverlayDiagnostic(
                    DiagnosticCode.CONNECTION_FAILED,
                    "Connection interrupted",
                    str(error),
                )
            if (
                current_status.state not in {"PLAYING", "PAUSED"}
                or _content_key(current_status) != _content_key(status)
            ):
                LOGGER.info("Discarded snapshot because active content changed")
                return OverlayDiagnostic(
                    DiagnosticCode.STALE_SNAPSHOT,
                    "Game changed",
                    "Discarded an inconsistent snapshot while RetroArch changed content",
                )
        return snapshot

    def _run(self) -> None:
        consecutive_failures = 0
        retry_codes = {
            DiagnosticCode.CONNECTION_FAILED,
            DiagnosticCode.INTERNAL_ERROR,
        }
        while not self._stop.is_set():
            started_at = time.monotonic()
            try:
                result = self.poll_once(started_at)
            except Exception as error:
                LOGGER.exception("Unexpected controller failure")
                result = OverlayDiagnostic(
                    DiagnosticCode.INTERNAL_ERROR,
                    "Overlay error",
                    str(error),
                )
            if result is not None:
                self._results.put(result)
            failed = isinstance(result, OverlayDiagnostic) and result.code in retry_codes
            consecutive_failures = consecutive_failures + 1 if failed else 0
            elapsed = time.monotonic() - started_at
            self._metrics = ControllerMetrics(
                poll_seconds=elapsed,
                snapshot_seconds=self._last_snapshot_seconds,
                consecutive_failures=consecutive_failures,
            )
            LOGGER.debug(
                "Poll %.1f ms; snapshot %.1f ms; failures %d",
                elapsed * 1000,
                self._last_snapshot_seconds * 1000,
                consecutive_failures,
            )
            normal_delay = max(0.0, self._poll_interval_seconds - elapsed)
            delay = max(normal_delay, self._retry_policy.delay(consecutive_failures))
            self._stop.wait(delay)


def _content_key(status: RetroArchStatus) -> tuple[str, str, str]:
    return status.core, status.content, status.content_crc32