from PySide6.QtWidgets import QWidget

from retroarch_overlay.core.models import OverlaySnapshot, PanelAction, PanelRow, PanelSection, ScreenRect
from retroarch_overlay.presentation.qt import QtSecondaryPanelWindow


def _snapshot() -> OverlaySnapshot:
    return OverlaySnapshot(
        "Game",
        "Area",
        (
            PanelSection(
                "Party",
                (PanelRow("Full party"), PanelRow("Second")),
                actions=(PanelAction("OPEN", "Details", (PanelRow("Detail"),)),),
                role="party",
                compact_rows=(PanelRow("Compact party"),),
                key="party",
            ),
            PanelSection(
                "Urgent",
                (PanelRow("Warning"),),
                alert=True,
                priority=1,
                role="urgent",
                key="urgent",
            ),
            PanelSection("Area", (PanelRow("Area"),), role="area", key="area"),
        ),
    )


def test_secondary_window_renders_only_compact_generic_sections(qtbot) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtSecondaryPanelWindow(owner, theme="high-contrast")

    shown = window.update_snapshot(
        _snapshot(),
        "scope",
        ScreenRect(10, 20, 310, 620),
    )

    assert shown
    assert window.isVisible()
    assert window.geometry().getRect() == (10, 20, 300, 600)
    assert window.theme_name == "high-contrast"
    views = window.document_view.state.section_views
    assert [view.section.key for view in views] == ["urgent", "party"]
    assert views[1].rows == (PanelRow("Compact party"),)
    assert views[1].actions == ()
    assert window.windowType().name == "Tool"


def test_secondary_window_hides_when_no_compact_sections(qtbot) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    window = QtSecondaryPanelWindow(owner)
    snapshot = OverlaySnapshot(
        "Game",
        "Area",
        (PanelSection("Area", (PanelRow("Area"),), role="area"),),
    )

    assert not window.update_snapshot(snapshot, "scope", ScreenRect(0, 0, 300, 600))
    assert window.isHidden()