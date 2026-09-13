from retroarch_overlay.core.models import (
    OverlaySnapshot,
    PanelAction,
    PanelRow,
    PanelSection,
)
from retroarch_overlay.presentation.qt import (
    PanelDocumentState,
    PanelDocumentUpdate,
)


def _snapshot(
    game: str = "Game",
    *,
    section_title: str = "Status 10",
    row_text: str = "HP 10/20",
) -> OverlaySnapshot:
    return OverlaySnapshot(
        game,
        "Area",
        (
            PanelSection(
                section_title,
                (
                    PanelRow(row_text, progress=0.5),
                    PanelRow("Completed", caught=True),
                    PanelRow("Pending", caught=False),
                ),
                preview_limit=1,
                actions=(
                    PanelAction(
                        "OPEN DETAILS",
                        "Details",
                        (PanelRow("Alpha"), PanelRow("Beta", caught=True)),
                        key="details",
                    ),
                ),
                role="area",
                key="status",
            ),
            PanelSection(
                "Urgent",
                (PanelRow("Warning"),),
                alert=True,
                priority=1,
                role="urgent",
                key="urgent",
            ),
            PanelSection(
                "Party",
                (PanelRow("Hero"),),
                role="party",
                key="party",
            ),
        ),
        supports_caught_filter=True,
    )


def test_value_snapshot_preserves_expansion_and_action_filter_by_stable_key() -> None:
    state = PanelDocumentState()
    assert state.set_snapshot(_snapshot()) is PanelDocumentUpdate.STRUCTURE
    status = next(view for view in state.section_views if view.section.key == "status")
    action = status.actions[0]
    state.toggle_section(status.identity)
    state.toggle_action(action.identity)
    state.set_action_filter(action.identity, "alpha")

    result = state.set_snapshot(
        _snapshot(section_title="Status 11", row_text="HP 11/20")
    )

    status = next(view for view in state.section_views if view.section.key == "status")
    assert result is PanelDocumentUpdate.VALUES
    assert status.expanded
    assert status.rows[0].text == "HP 11/20"
    assert status.actions[0].expanded
    assert status.actions[0].filter_text == "alpha"
    assert [row.text for row in status.actions[0].rows] == ["Alpha"]


def test_content_scope_change_resets_transient_state_for_same_game() -> None:
    state = PanelDocumentState()
    state.set_snapshot(_snapshot(), content_scope="Game:rom-one")
    status = next(view for view in state.section_views if view.section.key == "status")
    state.toggle_section(status.identity)
    state.toggle_action(status.actions[0].identity)
    state.set_action_filter(status.actions[0].identity, "alpha")

    result = state.set_snapshot(_snapshot(), content_scope="Game:rom-two")

    status = next(view for view in state.section_views if view.section.key == "status")
    assert result is PanelDocumentUpdate.CONTENT_SCOPE
    assert state.content_scope == "Game:rom-two"
    assert not status.expanded
    assert not status.actions[0].expanded
    assert status.actions[0].filter_text == ""


def test_duplicate_fallback_titles_and_labels_have_distinct_occurrences() -> None:
    state = PanelDocumentState()
    duplicate_action = PanelAction("OPEN", "Details", ())
    duplicate_section = PanelSection(
        "Repeated",
        (),
        actions=(duplicate_action, duplicate_action),
    )
    state.set_snapshot(
        OverlaySnapshot("Game", "Area", (duplicate_section, duplicate_section))
    )

    first, second = state.section_views
    assert first.identity.occurrence == 0
    assert second.identity.occurrence == 1
    assert [action.identity.occurrence for action in first.actions] == [0, 1]


def test_role_filter_keeps_urgent_and_sorts_it_first() -> None:
    state = PanelDocumentState()
    state.set_snapshot(_snapshot())

    result = state.set_active_role("party")

    assert result is PanelDocumentUpdate.STRUCTURE
    assert [view.section.key for view in state.section_views] == ["urgent", "party"]


def test_hide_caught_filters_section_and_expanded_action_rows() -> None:
    state = PanelDocumentState()
    state.set_snapshot(_snapshot())
    status = next(view for view in state.section_views if view.section.key == "status")
    state.toggle_section(status.identity)
    state.toggle_action(status.actions[0].identity)

    result = state.set_hide_caught(True)

    status = next(view for view in state.section_views if view.section.key == "status")
    assert result is PanelDocumentUpdate.STRUCTURE
    assert [row.text for row in status.rows] == ["HP 10/20", "Pending"]
    assert [row.text for row in status.actions[0].rows] == ["Alpha"]


def test_preview_toggle_exposes_hidden_rows() -> None:
    state = PanelDocumentState()
    state.set_snapshot(_snapshot())
    status = next(view for view in state.section_views if view.section.key == "status")
    assert [row.text for row in status.rows] == ["HP 10/20"]
    assert status.hidden_count == 2

    result = state.toggle_section(status.identity)

    status = next(view for view in state.section_views if view.section.key == "status")
    assert result is PanelDocumentUpdate.STRUCTURE
    assert len(status.rows) == 3
    assert status.hidden_count == 0


def test_stale_identity_actions_are_ignored() -> None:
    state = PanelDocumentState()
    state.set_snapshot(_snapshot())
    status = next(view for view in state.section_views if view.section.key == "status")
    stale_action = status.actions[0].identity
    state.set_snapshot(OverlaySnapshot("Other", "Area", ()))

    assert state.toggle_action(stale_action) is PanelDocumentUpdate.UNCHANGED
    assert state.set_action_filter(stale_action, "alpha") is PanelDocumentUpdate.UNCHANGED