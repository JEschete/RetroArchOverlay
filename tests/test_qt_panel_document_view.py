from PySide6.QtCore import Qt, QUrl
from unittest.mock import Mock
import pytest

from retroarch_overlay.core.models import OverlaySnapshot, PanelAction, PanelColumn, PanelMeter, PanelNumberInput, PanelRow, PanelSection
from retroarch_overlay.presentation.qt import PanelDocumentUpdate, PanelDocumentView


def test_command_action_invokes_once_without_disclosure_and_contains_failure(qtbot) -> None:
    command = Mock()
    view = PanelDocumentView()
    qtbot.addWidget(view)
    view.set_snapshot(OverlaySnapshot("Game", "Area", (
        PanelSection("Tools", (), actions=(PanelAction("Reset", "Reset", (), key="reset", command=command),), key="tools"),
    )))
    section = view.state.section_views[0]
    widget = view.section_widget(section.identity)
    button = widget.action_widget(section.actions[0].identity).toggle_button
    assert not button.isCheckable()
    button.click()
    command.assert_called_once_with()
    assert not view.state.section_views[0].actions[0].expanded
    errors = []
    view.action_failed.connect(errors.append)
    command.side_effect = ValueError("Scoped reset failed")
    button.click()
    assert errors == ["Reset: Scoped reset failed"]


@pytest.mark.parametrize("width", (360, 760))
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_number_input_is_keyed_preserves_typing_and_contains_callback_errors(qtbot, width, theme) -> None:
    from PySide6.QtWidgets import QSpinBox
    from dataclasses import replace

    command = Mock()
    field = PanelNumberInput("Simulations", 100, minimum=1, maximum=100_000,
                             key="simulations", command=command)
    section = PanelSection("Arena", (), key="arena", role="urgent", inputs=(field,))
    view = PanelDocumentView()
    qtbot.addWidget(view)
    view.resize(width, 700)
    view.set_theme(theme)
    view.show()
    view.set_snapshot(OverlaySnapshot("Game", "Area", (section,)))
    spin = view.findChild(QSpinBox, "simulations")
    qtbot.waitUntil(spin.isVisible)
    assert spin.value() == 100 and spin.accessibleName() == "Simulations"
    spin.setValue(250)
    command.assert_called_once_with(250)
    section = replace(section, inputs=(replace(field, value=250),))
    spin.setFocus()
    qtbot.waitUntil(spin.hasFocus)
    spin.lineEdit().setText("1200")
    view.set_snapshot(OverlaySnapshot("Game", "Area", (section,)))
    assert view.findChild(QSpinBox, "simulations") is spin
    assert spin.lineEdit().text() == "1200"
    spin.interpretText()
    command.assert_called_with(1200)
    errors = []
    view.action_failed.connect(errors.append)
    command.side_effect = ValueError("Invalid count")
    spin.setValue(500)
    assert errors == ["Simulations: Invalid count"]
    calls = command.call_count
    view.set_snapshot(OverlaySnapshot("Game", "Area", (
        replace(section, inputs=(replace(field, value=250, enabled=False),)),)))
    assert not spin.isEnabled() and command.call_count == calls
    widget = view.section_widget(view.state.section_views[0].identity)
    host, label, _ = widget._input_widgets["simulations"]
    assert not label.geometry().intersects(spin.geometry())
    assert spin.geometry().right() < host.width()


@pytest.mark.parametrize("width", (360, 760))
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_replacing_command_buttons_hides_old_widgets_before_deferred_delete(qtbot, tmp_path, width, theme) -> None:
    from PySide6.QtWidgets import QPushButton

    view = PanelDocumentView()
    qtbot.addWidget(view)
    view.resize(width, 700)
    view.set_theme(theme)
    view.show()
    previous = None
    for index in range(8):
        running = bool(index % 2)
        label = "Cancel" if running else "Estimate win chances"
        action = PanelAction(label, label, (), key="cancel" if running else "estimate", command=Mock())
        section = PanelSection("Arena", (PanelRow("Simulating 36/100", progress=0.36),),
                               role="urgent", key="arena", actions=(action,), inputs=(
                                   PanelNumberInput("Simulations", 100, key="simulations", command=Mock(), enabled=not running),))
        view.set_snapshot(OverlaySnapshot("Game", "Arena", (section,)))
        widget = view.section_widget(view.state.section_views[0].identity)
        current = widget.action_widget(view.state.section_views[0].actions[0].identity)
        if previous is not None:
            assert previous.isHidden() and not previous.isEnabled()
        assert widget._actions_layout.widgets() == [current]
        assert [button.text() for button in widget._actions_host.findChildren(QPushButton)
                if button.isVisible()] == [label]
        previous = current
    screenshot = tmp_path / f"action-swap-{width}-{theme}.png"
    assert view.grab().toImage().save(str(screenshot))
    print(f"Action swap screenshot: {screenshot}")


@pytest.mark.parametrize("width", (360, 760))
def test_collapsed_details_wrap_and_expansion_owns_a_row(qtbot, width) -> None:
    view = PanelDocumentView()
    view.resize(width, 700)
    qtbot.addWidget(view)
    view.show()
    actions = tuple(PanelAction(label, label, (PanelRow("Detail"),), key=label)
                    for label in ("Bestiary", "Knowledge", "Equipment"))
    view.set_snapshot(OverlaySnapshot("Game", "Area", (
        PanelSection("Tools", (), key="tools", actions=actions, collapsible=False),
        PanelSection("Next", (PanelRow("Following section"),), key="next"),
    )))
    section = view.state.section_views[0]
    widget = view.section_widget(section.identity)
    buttons = [widget.action_widget(action.identity) for action in section.actions]
    qtbot.waitUntil(lambda: widget._actions_host.width() > 0)
    assert all(not widget._actions_layout.is_full_row(button) for button in buttons)
    assert buttons[0].y() == buttons[1].y()
    buttons[1].toggle_button.click()
    qtbot.waitUntil(lambda: buttons[1].row_view.isVisible())
    assert widget._actions_layout.is_full_row(buttons[1])
    qtbot.waitUntil(lambda: buttons[1].width() == widget._actions_host.width())
    for index, button in enumerate(buttons):
        assert all(not button.geometry().intersects(other.geometry()) for other in buttons[index + 1:])
    following = view.section_widget(view.state.section_views[1].identity)
    assert not widget.geometry().intersects(following.geometry())


def test_guide_shortcut_scrolls_without_expanding_details(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(440, 700)
    qtbot.addWidget(view)
    view.show()
    markdown = "# Guide\n\n" + "\n\n".join(f"## Chapter {index}\n\nText" for index in range(60))
    view.set_snapshot(OverlaySnapshot("Game", "Area", (
        PanelSection("Guide", (), key="guide", markdown=markdown, collapsible=False,
                     actions=(PanelAction("Last chapter", "Last chapter", (), key="last", document_anchor="chapter-59"),)),
    )))
    section = view.state.section_views[0]
    widget = view.section_widget(section.identity)
    qtbot.waitUntil(lambda: widget.document_browser.verticalScrollBar().maximum() > 0)
    widget.action_widget(section.actions[0].identity).toggle_button.click()
    assert widget.document_browser.verticalScrollBar().value() > 0
    assert not view.state.section_views[0].actions[0].expanded


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


def test_columns_show_labeled_meters_and_remain_open(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(360, 500)
    qtbot.addWidget(view)
    view.show()
    rows = (PanelRow("Hero", meters=(PanelMeter("HP", 25, 50), PanelMeter("MP", 6, 12))),)
    section = PanelSection("Combatants", (), key="combatants", columns=(
        PanelColumn("party", "Party", rows), PanelColumn("enemies", "Enemies"),
    ), collapsible=False)
    view.set_snapshot(OverlaySnapshot("Game", "World", (section,)))
    state = view.state.section_views[0]
    widget = view.section_widget(state.identity)
    assert widget is not None
    assert state.open
    assert widget.columns_host.isVisible()
    assert not widget.header_button.isVisible()
    party = widget._column_widgets["party"][2]
    assert party.row_model.rows[0].meters[0].value == 25
    accessible = party.row_model.index(0).data(Qt.ItemDataRole.AccessibleTextRole)
    assert "HP 25 of 50" in accessible
    assert "MP 6 of 12" in accessible
    assert view.state.toggle_section_open(state.identity) is PanelDocumentUpdate.UNCHANGED


def test_markdown_document_preserves_its_scroll_on_live_updates(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(440, 700)
    qtbot.addWidget(view)
    view.show()
    markdown = "# Guide\n\n" + "\n\n".join(f"## Chapter {index}\n\nText" for index in range(60))
    section = PanelSection("Guide", (), key="guide", markdown=markdown, collapsible=False)
    view.set_snapshot(OverlaySnapshot("Game", "World", (section,)))
    state = view.state.section_views[0]
    widget = view.section_widget(state.identity)
    assert widget is not None
    browser = widget.document_browser
    qtbot.waitUntil(lambda: browser.verticalScrollBar().maximum() > 0)
    browser.verticalScrollBar().setValue(120)
    view.set_snapshot(OverlaySnapshot("Game", "Town", (section,)))
    assert widget.document_browser is browser
    assert browser.verticalScrollBar().value() == 120
    assert "Chapter 59" in browser.toPlainText()


@pytest.mark.parametrize("width", (360, 760))
def test_guide_search_contents_and_live_reading_state(qtbot, width) -> None:
    view = PanelDocumentView()
    view.resize(width, 700)
    qtbot.addWidget(view)
    view.show()
    markdown = "# Guide\n\n" + "\n\n".join(f"## Town\n\nTreasure {index}" for index in range(60))
    section = PanelSection("Guide", (), key="guide", markdown=markdown, collapsible=False)
    view.set_snapshot(OverlaySnapshot("Game", "Town", (section,)))
    widget = view.section_widget(view.state.section_views[0].identity)
    qtbot.waitUntil(lambda: widget.document_browser.verticalScrollBar().maximum() > 0)
    assert widget.document_contents.itemData(61) == "town-59"
    widget.document_contents.activated.emit(61)
    assert widget.document_browser.verticalScrollBar().value() > 0
    widget.document_search.setText("Treasure")
    assert widget.document_match_count.text() == "1 of 60"
    widget.document_next.click()
    assert widget.document_match_count.text() == "2 of 60"
    widget.document_previous.click()
    widget.document_previous.click()
    assert widget.document_match_count.text() == "60 of 60"
    position = widget.document_browser.verticalScrollBar().value()
    view.set_snapshot(OverlaySnapshot("Game", "Cave", (section,)))
    assert widget.document_match_count.text() == "60 of 60"
    assert widget.document_browser.verticalScrollBar().value() == position
    widget.document_search.setText("does not exist")
    assert widget.document_match_count.text() == "No matches"
    assert not widget.document_next.isEnabled()
    assert not widget.document_browser.textCursor().hasSelection()
    widget.document_search.clear()
    assert widget.document_match_count.text() == ""


def test_guide_contents_links_navigate_to_heading_anchors(qtbot) -> None:
    view = PanelDocumentView()
    view.resize(440, 700)
    qtbot.addWidget(view)
    view.show()
    markdown = "# Guide\n\n[Last chapter](#chapter-59)\n\n" + "\n\n".join(
        f"## Chapter {index}\n\nText" for index in range(60)
    )
    view.set_snapshot(OverlaySnapshot("Game", "World", (
        PanelSection("Guide", (), key="guide", markdown=markdown, collapsible=False),
    )))
    widget = view.section_widget(view.state.section_views[0].identity)
    assert widget is not None
    qtbot.waitUntil(lambda: widget.document_browser.verticalScrollBar().maximum() > 0)
    assert 'name="chapter-59"' in widget.document_browser.toHtml()
    widget._open_document_anchor(QUrl("#chapter-59"))
    assert widget.document_browser.verticalScrollBar().value() > 0