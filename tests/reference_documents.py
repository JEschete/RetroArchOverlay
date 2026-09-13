from retroarch_overlay.core.models import (
    OverlaySnapshot,
    PanelAction,
    PanelChip,
    PanelRow,
    PanelSection,
)


def reference_rows() -> tuple[PanelRow, ...]:
    return (
        PanelRow("Plain row"),
        PanelRow("Completed row", caught=True, tooltip="Recorded by the game"),
        PanelRow("Incomplete row", caught=False),
        PanelRow("Heading row", emphasis="heading"),
        PanelRow("Muted row", emphasis="muted"),
        PanelRow("Warning row", emphasis="warning"),
        PanelRow("Danger row", emphasis="danger"),
        PanelRow("Progress row", progress=0.375),
        PanelRow(
            "Structured row",
            progress=0.75,
            progress_color="#123456",
            icon="icons/reference.png",
            chips=(
                PanelChip("TYPE", "#334455", "#ffffff"),
                PanelChip("LIVE", "#ddeeff", "#111111"),
            ),
        ),
    )


def reference_snapshot() -> OverlaySnapshot:
    action = PanelAction(
        "OPEN DETAILS",
        "Reference Details",
        (
            PanelRow("Alpha detail"),
            PanelRow("Beta detail", caught=True),
        ),
    )
    return OverlaySnapshot(
        "Reference Game",
        "Reference Area",
        (
            PanelSection(
                "Reference",
                reference_rows(),
                preview_limit=5,
                actions=(action,),
                priority=10,
                role="area",
                compact_rows=(PanelRow("9 reference rows"),),
            ),
            PanelSection(
                "Urgent",
                (PanelRow("Immediate warning", emphasis="danger"),),
                alert=True,
                priority=1,
                role="urgent",
            ),
        ),
        supports_caught_filter=True,
    )