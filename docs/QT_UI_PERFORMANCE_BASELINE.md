# Base UI Performance Baseline

Status: first native comparison captured. These measurements establish direction
and expose regressions; they are not final release budgets.

## Environment

- Windows 11 Pro 10.0.26200, 64-bit
- AMD Ryzen 9 9950X3D, 16 cores and 32 logical processors
- 66,197,573,632 bytes physical memory
- CPython 3.14.3, 64-bit
- PySide6 6.11.2 and Qt 6.11.2
- Native `windows` Qt platform
- Four attached displays, all reporting 144 logical DPI and device-pixel ratio 1.0

The displays had logical geometries of 3840x2160, 1100x3840, 2160x3840, and
3840x2160. Because every display reported the same logical DPI, this machine does
not provide mixed-DPI evidence.

## Workload

Both toolkits run in separate fresh Python processes. They receive the same
immutable synthetic document:

- 10 sections;
- 24 visible rows per section, for 240 visible rows;
- stable section/action keys;
- completion state, tooltips, emphasis, progress, and colored chips;
- one collapsed 16-row action per section; and
- one alert/urgent section.

The captured run used 50 no-change updates, 50 alternating value-only updates,
10 structural updates that add/remove one 24-row section, a 5-second live idle
window, and 10 full window/controller start-close cycles. Each operation class
receives one untimed warm-up so deferred first-paint work is not mislabeled as
steady state.

Run it from the repository root:

```powershell
python tools/benchmark_ui_renderers.py `
    --iterations 50 `
    --structural-iterations 10 `
    --idle-ms 5000 `
    --lifecycle-iterations 10 `
    --timeout 90
```

Every child process has a hard timeout. The harness uses native Tk and Qt windows,
process-isolated imports, `time.perf_counter()`, Windows process memory counters,
and each toolkit's event loop.

## Results

| Metric | Tk | Qt | Qt relative to Tk |
| --- | ---: | ---: | ---: |
| UI startup | 187.54 ms | 413.91 ms | 2.21x slower |
| Process to ready | 202.47 ms | 428.59 ms | 2.12x slower |
| First dense render | 1301.18 ms | 218.09 ms | 83.2% faster |
| Unchanged update mean | 0.0057 ms | 0.0213 ms | both below 0.1 ms |
| Unchanged update p95 | 0.0235 ms | 0.0780 ms | both below 0.1 ms |
| Value update mean | 202.51 ms | 48.66 ms | 76.0% faster |
| Value update p95 | 227.22 ms | 63.65 ms | 72.0% faster |
| Structural update mean | 1620.32 ms | 52.53 ms | 96.8% faster |
| Structural update p95 | 1710.72 ms | 57.80 ms | 96.6% faster |
| Private memory after updates | 45.81 MiB | 80.14 MiB | 1.75x higher |
| Ten start-close cycles | 869.14 ms | 192.75 ms | 77.8% faster |
| Lifecycle private-memory delta | +0.21 MiB | -1.99 MiB | no Qt growth in this sample |
| Lifecycle working-set delta | +0.59 MiB | -1.20 MiB | no Qt growth in this sample |

Both idle intervals recorded less CPU time than the Windows process-time clock
resolved during five seconds. That result means "below this probe's resolution,"
not literal zero CPU consumption.

## Finding and Repair

The first calibration found that Qt spent about 40.8 ms reconciling a snapshot
that was byte-for-byte unchanged. `QtOverlayWindow` now exits early only when both
the immutable snapshot and exact controller content scope match. This preserves
same-title ROM isolation while reducing the stabilized unchanged path to 0.0213 ms
mean and 0.0780 ms p95 in the final run.

## Interpretation

The candidate has a measurable startup and memory cost. It has a much stronger
dense-render/update path and showed no retained-memory signal across ten base
window cycles. This supports continuing with PySide6, but does not set or pass a
final startup or memory budget.

Still required:

- repeat the run across supported Python/Windows versions and representative lower-end hardware;
- use maximum-density immutable documents captured from every plugin;
- measure map and both dashboard workloads through the same runner;
- measure disconnected, idle, playing, and paused controller states with longer CPU sampling;
- run a longer lifecycle soak and inspect native handles as well as memory; and
- set acceptance budgets from the collected distributions, then obtain explicit approval for any regression.