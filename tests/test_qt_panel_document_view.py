from retroarch_overlay.core.models import OverlaySnapshot, PanelAction, PanelRow, PanelSection
from retroarch_overlay.presentation.qt import PanelDocumentUpdate, PanelDocumentView


def _view_snapshot(value: int = 10) -> OverlaySnapshot:
    primary = PanelSection(
        f"Status {value}",
        tuple(
            PanelRow(
                f"Row {index:02} value {value}",
                progress=(value + index) / 100,
            )
            for index in range(12)
        ),
        preview_limit=4,
        actions=(
            PanelAction(
                "OPEN DETAILS",
                "Status details",
                tuple(PanelRow(f"Detail {index:02} value {value}") for index in range(20)),
                key="details",
            ),
        ),
        key="status",
    )
    filler = tuple(
        PanelSection(
            f"Filler {index:02}",
            (PanelRow(f"Filler row {index:02}"),),
            key=f"filler-{index:02}",
        )
        for index in range(20)
    )
    return OverlaySnapshot("Game", "Area", (primary, *filler))


def test_native_controls_toggle_section_action_and_filter(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 500)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(_view_snapshot())
    status_state = view.state.section_views[0]
    status = view.section_widget(status_state.identity)
    assert status is not None
    assert not status.preview_button.isVisible()

    status.header_button.click()
    assert view.state.section_views[0].open
    assert status.header_button.text() == "▾ Status 10"
    status.preview_button.click()
    status_state = view.state.section_views[0]
    assert status_state.expanded
    action = status.action_widget(status_state.actions[0].identity)
    assert action is not None

    view.ensureWidgetVisible(action.toggle_button)
    qtbot.waitUntil(action.toggle_button.isVisible)
    action.toggle_button.click()
    action = status.action_widget(view.state.section_views[0].actions[0].identity)
    assert action is not None
    assert action.row_view.isVisible()
    action.filter_edit.setText("Detail 17")

    action_state = view.state.section_views[0].actions[0]
    assert action_state.filter_text == "Detail 17"
    assert [row.text for row in action_state.rows] == ["Detail 17 value 10"]
    assert action.filter_edit.accessibleName() == "Filter Status details"


def test_sections_use_content_height_instead_of_stretching(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(460, 820)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(
        OverlaySnapshot(
            "Game",
            "Area",
            (
                PanelSection("First", (PanelRow("One"),), key="first"),
                PanelSection("Second", (PanelRow("Two"),), key="second"),
            ),
        )
    )
    qtbot.waitUntil(lambda: all(widget.isVisible() for widget in view._section_widgets.values()))

    heights = [widget.height() for widget in view._section_widgets.values()]
    assert max(heights) < 160
    assert all(
        widget.height() <= widget.sizeHint().height() + 4
        for widget in view._section_widgets.values()
    )


def test_closed_sections_show_one_summary_row_until_header_is_clicked(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 500)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(_view_snapshot())
    status_state = view.state.section_views[0]
    status = view.section_widget(status_state.identity)
    assert status is not None

    assert status.header_button.text() == "▸ Status 10"
    assert status.row_view.row_model.rowCount() == 1
    assert not status._actions_host.isVisible()

    status.header_button.click()

    qtbot.waitUntil(status._actions_host.isVisible)
    assert status.row_view.row_model.rowCount() == 4


def test_outer_document_owns_vertical_scrolling(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 320)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(
        OverlaySnapshot(
            "Game",
            "Area",
            (
                PanelSection(
                    "Long section",
                    tuple(PanelRow(f"Row {index:03}") for index in range(50)),
                    role="urgent",
                    key="long",
                ),
            ),
        )
    )
    section = next(iter(view._section_widgets.values()))
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)

    assert section.row_view.verticalScrollBar().maximum() == 0
    assert view.verticalScrollBar().maximum() > 0


def test_value_snapshot_reuses_widgets_and_preserves_interaction_state(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 420)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(_view_snapshot())
    status_state = view.state.section_views[0]
    view.state.toggle_section_open(status_state.identity)
    view.state.toggle_section(status_state.identity)
    view.state.toggle_action(status_state.actions[0].identity)
    view.state.set_action_filter(status_state.actions[0].identity, "Detail 17")
    view._apply_views()
    status = view.section_widget(status_state.identity)
    assert status is not None
    action = status.action_widget(status_state.actions[0].identity)
    assert action is not None
    action.row_view.setCurrentIndex(action.row_view.row_model.index(0))
    action.filter_edit.setFocus()
    qtbot.waitUntil(action.filter_edit.hasFocus)
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() // 2)
    scroll_position = view.verticalScrollBar().value()

    result = view.set_snapshot(_view_snapshot(11))
    qtbot.wait(1)

    updated_status = view.section_widget(status_state.identity)
    assert result is PanelDocumentUpdate.VALUES
    assert updated_status is status
    assert updated_status is not None
    updated_action = updated_status.action_widget(status_state.actions[0].identity)
    assert updated_action is action
    assert updated_action is not None
    assert updated_action.filter_edit.text() == "Detail 17"
    assert updated_action.filter_edit.hasFocus()
    assert updated_action.row_view.currentIndex().row() == 0
    assert updated_action.row_view.currentIndex().data() == "Detail 17 value 11"
    assert view.verticalScrollBar().value() == scroll_position


def test_content_scope_change_rebuilds_widgets_and_resets_scroll(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 420)
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(_view_snapshot(), content_scope="Game:one")
    first_state = view.state.section_views[0]
    first_widget = view.section_widget(first_state.identity)
    assert first_widget is not None
    view.state.toggle_section_open(first_state.identity)
    view.state.toggle_section(first_state.identity)
    view.state.toggle_action(first_state.actions[0].identity)
    view.state.set_action_filter(first_state.actions[0].identity, "Detail 17")
    view._apply_views()
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())

    result = view.set_snapshot(_view_snapshot(), content_scope="Game:two")
    qtbot.wait(1)

    second_state = view.state.section_views[0]
    second_widget = view.section_widget(second_state.identity)
    assert result is PanelDocumentUpdate.CONTENT_SCOPE
    assert second_widget is not None
    assert second_widget is not first_widget
    assert not second_state.open
    assert not second_state.expanded
    assert not second_state.actions[0].expanded
    assert second_state.actions[0].filter_text == ""
    assert view.verticalScrollBar().value() == 0