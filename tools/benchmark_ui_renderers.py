from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence


PROCESS_STARTED = time.perf_counter()


class BenchmarkController:
    def __init__(self) -> None:
        self.content_key = ("benchmark", "dense-fixture", "00000000")
        self.last_status = None
        self.metrics = SimpleNamespace(snapshot_seconds=0.001)
        self.stopped = True

    def start(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def drain_latest(self) -> None:
        return None


def _snapshot(revision: int, *, extra_section: bool = False):
    from retroarch_overlay.core.models import (
        OverlaySnapshot,
        PanelAction,
        PanelChip,
        PanelRow,
        PanelSection,
    )

    sections = []
    roles = ("area", "party", "goals", "context")
    for section_index in range(10 + int(extra_section)):
        rows = tuple(
            PanelRow(
                f"Entry {section_index:02d}-{row_index:02d} value {revision}",
                caught=(row_index % 3 == 0),
                tooltip=f"Detail for row {row_index}",
                emphasis=("", "muted", "success", "warning")[row_index % 4],
                progress=((row_index + revision) % 20) / 20,
                chips=(PanelChip(f"C{row_index % 5}", "#334455", "#ffffff"),),
            )
            for row_index in range(24)
        )
        actions = (
            PanelAction(
                "DETAILS",
                f"Section {section_index} details",
                tuple(PanelRow(f"Detail {index}") for index in range(16)),
                key=f"details-{section_index}",
            ),
        )
        sections.append(
            PanelSection(
                f"Section {section_index}",
                rows,
                preview_limit=24,
                alert=section_index == 0,
                actions=actions,
                priority=section_index,
                role="urgent" if section_index == 0 else roles[section_index % 4],
                key=f"section-{section_index}",
            )
        )
    return OverlaySnapshot("Benchmark Game", "Dense Fixture", tuple(sections))


def _timings(iterations: int, operation: Callable[[int], None]) -> dict[str, float]:
    operation(-1)
    samples = []
    for index in range(iterations):
        started = time.perf_counter()
        operation(index)
        samples.append((time.perf_counter() - started) * 1_000)
    ordered = sorted(samples)
    percentile_index = round(0.95 * (len(ordered) - 1))
    return {
        "mean_ms": statistics.fmean(samples),
        "p95_ms": ordered[percentile_index],
        "maximum_ms": ordered[-1],
    }


def _memory_bytes() -> dict[str, int]:
    if sys.platform != "win32":
        raise RuntimeError("Native memory measurement currently supports Windows only")

    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        )

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "working_set": int(counters.WorkingSetSize),
        "private": int(counters.PrivateUsage),
        "peak_working_set": int(counters.PeakWorkingSetSize),
    }


def _idle_metrics(run_loop: Callable[[int], None], idle_ms: int) -> dict[str, float]:
    process_started = time.process_time()
    wall_started = time.perf_counter()
    run_loop(idle_ms)
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - process_started
    return {
        "wall_ms": wall_seconds * 1_000,
        "cpu_ms": cpu_seconds * 1_000,
        "cpu_percent_one_core": (cpu_seconds / wall_seconds) * 100,
    }


def _lifecycle_metrics(
    iterations: int,
    create_and_close: Callable[[], None],
) -> dict[str, object]:
    before = _memory_bytes()
    started = time.perf_counter()
    for _index in range(iterations):
        create_and_close()
    gc.collect()
    after = _memory_bytes()
    return {
        "iterations": iterations,
        "total_ms": (time.perf_counter() - started) * 1_000,
        "before_bytes": before,
        "after_bytes": after,
        "private_growth_bytes": after["private"] - before["private"],
        "working_set_growth_bytes": after["working_set"] - before["working_set"],
    }


def _run_tk(
    iterations: int,
    structural_iterations: int,
    idle_ms: int,
    lifecycle_iterations: int,
):
    ui_started = time.perf_counter()
    from retroarch_overlay.ui import OverlayWindow

    controller = BenchmarkController()
    window = OverlayWindow(object(), object(), controller=controller)
    window.root.update()
    startup_ms = (time.perf_counter() - ui_started) * 1_000
    process_to_ready_ms = (time.perf_counter() - PROCESS_STARTED) * 1_000
    memory_startup = _memory_bytes()
    base = _snapshot(0)
    values = (_snapshot(1), _snapshot(2))
    structural = (base, _snapshot(0, extra_section=True))

    first_started = time.perf_counter()
    window._render(base)
    window.root.update()
    first_render_ms = (time.perf_counter() - first_started) * 1_000
    unchanged = _timings(
        iterations,
        lambda _index: (window._render(base), window.root.update()),
    )
    value_updates = _timings(
        iterations,
        lambda index: (window._render(values[index % 2]), window.root.update()),
    )
    structural_updates = _timings(
        structural_iterations,
        lambda index: (window._render(structural[index % 2]), window.root.update()),
    )
    memory_updated = _memory_bytes()

    def idle(duration_ms: int) -> None:
        window.root.after(duration_ms, window.root.quit)
        window.run()

    idle_result = _idle_metrics(idle, idle_ms)
    window.close()

    def create_and_close() -> None:
        candidate = OverlayWindow(
            object(),
            object(),
            controller=BenchmarkController(),
        )
        candidate.root.after(1, candidate.root.quit)
        candidate.run()
        candidate.close()

    lifecycle = _lifecycle_metrics(lifecycle_iterations, create_and_close)
    return {
        "toolkit": "tk",
        "startup_ms": startup_ms,
        "process_to_ready_ms": process_to_ready_ms,
        "first_render_ms": first_render_ms,
        "unchanged": unchanged,
        "value_updates": value_updates,
        "structural_updates": structural_updates,
        "memory_startup_bytes": memory_startup,
        "memory_updated_bytes": memory_updated,
        "idle": idle_result,
        "lifecycle": lifecycle,
    }


def _run_qt(
    iterations: int,
    structural_iterations: int,
    idle_ms: int,
    lifecycle_iterations: int,
):
    ui_started = time.perf_counter()
    from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt

    from retroarch_overlay.presentation.qt import QtOverlayWindow, create_qt_application

    application = create_qt_application(("rao-ui-benchmark",))
    controller = BenchmarkController()
    window = QtOverlayWindow(controller, animate_map_objectives=False)
    window.show()
    application.processEvents()
    startup_ms = (time.perf_counter() - ui_started) * 1_000
    process_to_ready_ms = (time.perf_counter() - PROCESS_STARTED) * 1_000
    memory_startup = _memory_bytes()
    base = _snapshot(0)
    values = (_snapshot(1), _snapshot(2))
    structural = (base, _snapshot(0, extra_section=True))

    def render(snapshot) -> None:
        window.render_event(snapshot)
        application.processEvents()

    first_started = time.perf_counter()
    render(base)
    first_render_ms = (time.perf_counter() - first_started) * 1_000
    unchanged = _timings(iterations, lambda _index: render(base))
    value_updates = _timings(
        iterations,
        lambda index: render(values[index % 2]),
    )
    structural_updates = _timings(
        structural_iterations,
        lambda index: render(structural[index % 2]),
    )
    memory_updated = _memory_bytes()

    def idle(duration_ms: int) -> None:
        window.start()
        loop = QEventLoop()
        QTimer.singleShot(duration_ms, loop.quit)
        loop.exec()

    idle_result = _idle_metrics(idle, idle_ms)
    window.close()
    window.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()

    def create_and_close() -> None:
        candidate = QtOverlayWindow(
            BenchmarkController(),
            animate_map_objectives=False,
        )
        candidate.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        candidate.start()
        application.processEvents()
        candidate.close()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()

    lifecycle = _lifecycle_metrics(lifecycle_iterations, create_and_close)
    return {
        "toolkit": "qt",
        "startup_ms": startup_ms,
        "process_to_ready_ms": process_to_ready_ms,
        "first_render_ms": first_render_ms,
        "unchanged": unchanged,
        "value_updates": value_updates,
        "structural_updates": structural_updates,
        "memory_startup_bytes": memory_startup,
        "memory_updated_bytes": memory_updated,
        "idle": idle_result,
        "lifecycle": lifecycle,
    }


def _worker(
    toolkit: str,
    iterations: int,
    structural: int,
    idle_ms: int,
    lifecycle_iterations: int,
) -> int:
    runner = _run_tk if toolkit == "tk" else _run_qt
    result = runner(iterations, structural, idle_ms, lifecycle_iterations)
    print(json.dumps(result, separators=(",", ":")))
    return 0


def _run_child(
    toolkit: str,
    source_root: Path,
    iterations: int,
    structural: int,
    idle_ms: int,
    lifecycle_iterations: int,
    timeout: int,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(source_root / "src"), environment.get("PYTHONPATH", "")),
        )
    )
    if toolkit == "qt":
        environment["QT_QPA_PLATFORM"] = "windows"
    command = (
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        toolkit,
        "--iterations",
        str(iterations),
        "--structural-iterations",
        str(structural),
        "--idle-ms",
        str(idle_ms),
        "--lifecycle-iterations",
        str(lifecycle_iterations),
    )
    try:
        result = subprocess.run(
            command,
            cwd=source_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{toolkit} benchmark exceeded {timeout} seconds") from error
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(
            f"{toolkit} benchmark failed with exit code {result.returncode}\n"
            f"{output[-4_000:]}"
        )
    lines = tuple(line for line in result.stdout.splitlines() if line.strip())
    return json.loads(lines[-1])


def _ratio(qt: float, tk: float) -> float | None:
    return qt / tk if tk > 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare native Tk and Qt base-overlay rendering"
    )
    parser.add_argument("--worker", choices=("tk", "qt"))
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--structural-iterations", type=int, default=20)
    parser.add_argument("--idle-ms", type=int, default=1_000)
    parser.add_argument("--lifecycle-iterations", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("native renderer comparison currently supports Windows only")
    if min(
        args.iterations,
        args.structural_iterations,
        args.idle_ms,
        args.lifecycle_iterations,
        args.timeout,
    ) <= 0:
        parser.error("all numeric options must be positive")
    if args.worker is not None:
        return _worker(
            args.worker,
            args.iterations,
            args.structural_iterations,
            args.idle_ms,
            args.lifecycle_iterations,
        )

    source_root = Path(__file__).resolve().parents[1]
    results = {
        toolkit: _run_child(
            toolkit,
            source_root,
            args.iterations,
            args.structural_iterations,
            args.idle_ms,
            args.lifecycle_iterations,
            args.timeout,
        )
        for toolkit in ("tk", "qt")
    }
    results["workload"] = {
        "sections": 10,
        "rows_per_section": 24,
        "value_iterations": args.iterations,
        "structural_iterations": args.structural_iterations,
        "idle_ms": args.idle_ms,
        "lifecycle_iterations": args.lifecycle_iterations,
    }
    tk_result = results["tk"]
    qt_result = results["qt"]
    results["qt_to_tk_ratio"] = {
        "startup": _ratio(qt_result["startup_ms"], tk_result["startup_ms"]),
        "process_to_ready": _ratio(
            qt_result["process_to_ready_ms"], tk_result["process_to_ready_ms"]
        ),
        "first_render": _ratio(
            qt_result["first_render_ms"], tk_result["first_render_ms"]
        ),
        "unchanged_mean": _ratio(
            qt_result["unchanged"]["mean_ms"],
            tk_result["unchanged"]["mean_ms"],
        ),
        "value_update_mean": _ratio(
            qt_result["value_updates"]["mean_ms"],
            tk_result["value_updates"]["mean_ms"],
        ),
        "structural_update_mean": _ratio(
            qt_result["structural_updates"]["mean_ms"],
            tk_result["structural_updates"]["mean_ms"],
        ),
        "updated_private_memory": _ratio(
            qt_result["memory_updated_bytes"]["private"],
            tk_result["memory_updated_bytes"]["private"],
        ),
        "idle_cpu": _ratio(
            qt_result["idle"]["cpu_percent_one_core"],
            tk_result["idle"]["cpu_percent_one_core"],
        ),
    }
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())