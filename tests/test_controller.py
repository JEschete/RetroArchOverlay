import unittest
from unittest.mock import Mock

from retroarch_overlay.app.controller import (
    DiagnosticCode,
    OverlayController,
    OverlayDiagnostic,
    RetryPolicy,
    SnapshotCadence,
)
from retroarch_overlay.models import OverlaySnapshot, RetroArchStatus


class OverlayControllerTests(unittest.TestCase):
    def test_returns_snapshot_when_content_remains_stable(self) -> None:
        status = RetroArchStatus("PLAYING", "core", "Game", "12345678")
        client = Mock()
        client.get_status.side_effect = (status, status)
        adapter = Mock()
        snapshot = OverlaySnapshot("Game", "Location", ())
        adapter.snapshot.return_value = snapshot
        registry = Mock()
        registry.find.return_value = adapter
        controller = OverlayController(client, registry)

        result = controller.poll_once(10.0)

        self.assertIs(result, snapshot)
        self.assertIs(controller.last_status, status)
        adapter.snapshot.assert_called_once_with(client)

    def test_discards_snapshot_if_content_changes_during_reads(self) -> None:
        first = RetroArchStatus("PLAYING", "core", "First", "11111111")
        second = RetroArchStatus("PLAYING", "core", "Second", "22222222")
        client = Mock()
        client.get_status.side_effect = (first, second)
        adapter = Mock()
        adapter.snapshot.return_value = OverlaySnapshot("First", "Location", ())
        registry = Mock()
        registry.find.return_value = adapter
        controller = OverlayController(client, registry)

        result = controller.poll_once(10.0)

        self.assertIsInstance(result, OverlayDiagnostic)
        self.assertEqual(result.code, DiagnosticCode.STALE_SNAPSHOT)

    def test_unexpected_plugin_exception_becomes_recoverable_diagnostic(self) -> None:
        status = RetroArchStatus("PLAYING", "core", "Game", "12345678")
        client = Mock()
        client.get_status.return_value = status
        adapter = Mock(name="Broken game")
        adapter.name = "Broken game"
        adapter.snapshot.side_effect = KeyError("missing state")
        registry = Mock()
        registry.find.return_value = adapter
        controller = OverlayController(client, registry)

        result = controller.poll_once(10.0)

        self.assertIsInstance(result, OverlayDiagnostic)
        self.assertEqual(result.code, DiagnosticCode.PLUGIN_FAILED)
        self.assertIn("Broken game", result.message)

    def test_connection_failure_is_typed(self) -> None:
        client = Mock()
        client.get_status.side_effect = OSError("offline")
        controller = OverlayController(client, Mock())

        result = controller.poll_once(10.0)

        self.assertIsInstance(result, OverlayDiagnostic)
        self.assertEqual(result.code, DiagnosticCode.CONNECTION_FAILED)

    def test_runs_capture_hook_between_full_snapshots(self) -> None:
        status = RetroArchStatus("PLAYING", "core", "Game", "12345678")
        client = Mock()
        client.get_status.side_effect = (status, status, status)
        adapter = Mock()
        adapter.snapshot.return_value = OverlaySnapshot("Game", "Location", ())
        registry = Mock()
        registry.find.return_value = adapter
        controller = OverlayController(
            client,
            registry,
            cadence=SnapshotCadence(0.25),
        )

        controller.poll_once(10.0)
        result = controller.poll_once(10.05)

        self.assertIsNone(result)
        adapter.capture.assert_called_once_with(client)
        adapter.snapshot.assert_called_once_with(client)

    def test_capture_failure_does_not_block_full_snapshot(self) -> None:
        status = RetroArchStatus("PLAYING", "core", "Game", "12345678")
        client = Mock()
        client.get_status.side_effect = (status, status)
        adapter = Mock()
        adapter.capture.side_effect = RuntimeError("capture unavailable")
        snapshot = OverlaySnapshot("Game", "Location", ())
        adapter.snapshot.return_value = snapshot
        registry = Mock()
        registry.find.return_value = adapter
        controller = OverlayController(client, registry)

        result = controller.poll_once(10.0)

        self.assertIs(result, snapshot)

    def test_retry_policy_is_exponential_and_bounded(self) -> None:
        policy = RetryPolicy(initial_seconds=0.25, maximum_seconds=1.0)

        self.assertEqual(
            tuple(policy.delay(value) for value in range(1, 6)),
            (0.25, 0.5, 1.0, 1.0, 1.0),
        )


if __name__ == "__main__":
    unittest.main()