import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retroarch_overlay.infrastructure.logging_config import UIHangWatchdog


class UIHangWatchdogTests(unittest.TestCase):
    def test_writes_context_and_stack_after_timeout(self) -> None:
        clock = [10.0]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "hang.log"
            watchdog = UIHangWatchdog(
                report,
                timeout_seconds=3.0,
                repeat_seconds=10.0,
                clock=lambda: clock[0],
            )
            watchdog.heartbeat("UI event loop idle")
            watchdog.set_context("map=world stage=full-redraw")
            clock[0] = 13.1

            with patch.object(watchdog, "_thread_dump", return_value="thread stack"):
                captured = watchdog.capture_if_stalled()

            self.assertTrue(captured)
            text = report.read_text(encoding="utf-8")
            self.assertIn("UI HANG DETECTED", text)
            self.assertIn("map=world stage=full-redraw", text)
            self.assertIn("thread stack", text)

    def test_heartbeat_rearms_watchdog_after_report(self) -> None:
        clock = [20.0]
        with tempfile.TemporaryDirectory() as directory:
            watchdog = UIHangWatchdog(
                Path(directory) / "hang.log",
                timeout_seconds=3.0,
                repeat_seconds=10.0,
                clock=lambda: clock[0],
            )
            with patch.object(watchdog, "_write_report") as write_report:
                clock[0] = 23.1
                self.assertTrue(watchdog.capture_if_stalled())
                clock[0] = 24.0
                self.assertFalse(watchdog.capture_if_stalled())
                watchdog.heartbeat()
                clock[0] = 27.1
                self.assertTrue(watchdog.capture_if_stalled())

            self.assertEqual(write_report.call_count, 2)


if __name__ == "__main__":
    unittest.main()