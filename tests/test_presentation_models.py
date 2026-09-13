from retroarch_overlay.core.models import PanelAction, PanelRow, PanelSection
from retroarch_overlay.core.presentation import compact_secondary_sections


def test_legacy_panel_document_construction_keeps_empty_stable_keys() -> None:
    action = PanelAction("OPEN", "Details", (PanelRow("Detail"),), True)
    section = PanelSection(
        "Status",
        (PanelRow("Ready"),),
        1,
        False,
        (action,),
        10,
        "context",
        (PanelRow("1 row"),),
    )

    assert action.key == ""
    assert section.key == ""


def test_panel_documents_accept_explicit_stable_keys() -> None:
    action = PanelAction("OPEN", "Details", (), key="details")
    section = PanelSection("Status", (), actions=(action,), key="status")

    assert action.key == "details"
    assert section.key == "status"


def test_compact_secondary_sections_keep_semantics_without_actions() -> None:
    action = PanelAction("OPEN", "Details", (PanelRow("Detail"),))
    sections = (
        PanelSection(
            "Party",
            (PanelRow("Full party row"), PanelRow("Second")),
            actions=(action,),
            priority=20,
            role="party",
            compact_rows=(PanelRow("Compact party"),),
            key="party",
        ),
        PanelSection(
            "Alert",
            (PanelRow("Urgent row"), PanelRow("More")),
            alert=True,
            priority=1,
            role="urgent",
            key="alert",
        ),
        PanelSection("Area", (PanelRow("Area row"),), role="area"),
    )

    compact = compact_secondary_sections(sections)

    assert [section.key for section in compact] == ["alert", "party"]
    assert compact[0].rows == (PanelRow("Urgent row"),)
    assert compact[1].rows == (PanelRow("Compact party"),)
    assert all(section.actions == () for section in compact)
    assert all(section.preview_limit is None for section in compact)