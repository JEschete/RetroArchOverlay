from retroarch_overlay.app.notifications import AlertNotification, AlertTracker, urgent_summary
from retroarch_overlay.core.models import OverlaySnapshot, PanelRow, PanelSection


def test_urgent_summary_prefers_alert_then_priority() -> None:
    snapshot = OverlaySnapshot(
        "Game",
        "Area",
        (
            PanelSection(
                "Urgent role",
                (PanelRow("Role detail"),),
                priority=1,
                role="urgent",
            ),
            PanelSection(
                "Alert",
                (PanelRow("Alert detail"),),
                alert=True,
                priority=20,
            ),
        ),
    )

    assert urgent_summary(snapshot) == AlertNotification("Alert", "Alert detail")


def test_urgent_summary_ignores_empty_and_context_sections() -> None:
    snapshot = OverlaySnapshot(
        "Game",
        "Area",
        (
            PanelSection("Empty", (), alert=True),
            PanelSection("Context", (PanelRow("Normal"),)),
        ),
    )

    assert urgent_summary(snapshot) is None


def test_tracker_suppresses_first_snapshot_backlog_and_reports_new_alerts() -> None:
    tracker = AlertTracker()
    first = OverlaySnapshot(
        "Game",
        "Area",
        (PanelSection("Existing", (PanelRow("Old"),), alert=True, key="existing"),),
    )
    second = OverlaySnapshot(
        "Game",
        "Area",
        (
            first.sections[0],
            PanelSection("New", (PanelRow("Now"),), alert=True, key="new"),
        ),
    )

    assert tracker.observe(first, "scope") == ()
    assert tracker.observe(second, "scope") == (AlertNotification("New", "Now"),)
    assert tracker.observe(second, "scope") == ()


def test_tracker_scopes_same_game_content_and_disambiguates_duplicate_titles() -> None:
    tracker = AlertTracker()
    one = PanelSection("Warning", (PanelRow("One"),), alert=True)
    two = PanelSection("Warning", (PanelRow("Two"),), alert=True)
    first = OverlaySnapshot("Game", "Area", (one,))
    duplicate = OverlaySnapshot("Game", "Area", (one, two))

    assert tracker.observe(first, "rom-one") == ()
    assert tracker.observe(duplicate, "rom-one") == (
        AlertNotification("Warning", "Two"),
    )
    assert tracker.observe(duplicate, "rom-two") == ()