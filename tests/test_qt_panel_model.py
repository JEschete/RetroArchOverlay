from PySide6.QtCore import QPersistentModelIndex, Qt
from PySide6.QtTest import QSignalSpy

from reference_documents import reference_rows, reference_snapshot
from retroarch_overlay.core.models import PanelChip, PanelRow
from retroarch_overlay.presentation.qt import (
    PanelModelUpdate,
    PanelRowListView,
    PanelRowModel,
    PanelRowRole,
)


def test_reference_document_exercises_shared_panel_contract() -> None:
    snapshot = reference_snapshot()

    assert snapshot.supports_caught_filter
    assert any(section.alert for section in snapshot.sections)
    assert any(section.actions for section in snapshot.sections)
    assert any(row.icon and row.chips and row.progress for row in reference_rows())


def test_model_exposes_semantic_and_accessibility_roles() -> None:
    row = PanelRow(
        "Catch target",
        caught=False,
        tooltip="Found on Route 1",
        progress=0.375,
        chips=(PanelChip("WATER"),),
    )
    model = PanelRowModel((row,))
    index = model.index(0)

    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "Catch target"
    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == "Found on Route 1"
    assert model.data(index, PanelRowRole.CAUGHT) is False
    assert model.data(index, PanelRowRole.PROGRESS) == 0.375
    assert model.data(index, PanelRowRole.CHIPS) == row.chips
    assert model.data(index, Qt.ItemDataRole.AccessibleTextRole) == (
        "Catch target; not complete; progress 38 percent; tags WATER"
    )
    assert model.data(index, Qt.ItemDataRole.AccessibleDescriptionRole) == (
        "Found on Route 1"
    )


def test_value_update_preserves_persistent_index_and_avoids_reset() -> None:
    model = PanelRowModel((PanelRow("HP 10/20", progress=0.5),))
    persistent = QPersistentModelIndex(model.index(0))
    changed = QSignalSpy(model.dataChanged)
    reset = QSignalSpy(model.modelReset)

    result = model.set_rows((PanelRow("HP 15/20", progress=0.75),))

    assert result is PanelModelUpdate.VALUES
    assert persistent.isValid()
    assert persistent.data() == "HP 15/20"
    assert changed.count() == 1
    assert reset.count() == 0


def test_structure_update_resets_model() -> None:
    model = PanelRowModel((PanelRow("Target"),))
    persistent = QPersistentModelIndex(model.index(0))
    changed = QSignalSpy(model.dataChanged)
    reset = QSignalSpy(model.modelReset)

    result = model.set_rows(
        (PanelRow("Target", chips=(PanelChip("NEW"),)),)
    )

    assert result is PanelModelUpdate.STRUCTURE
    assert not persistent.isValid()
    assert changed.count() == 0
    assert reset.count() == 1


def test_identical_update_emits_no_model_signal() -> None:
    rows = reference_rows()
    model = PanelRowModel(rows)
    changed = QSignalSpy(model.dataChanged)
    reset = QSignalSpy(model.modelReset)

    result = model.set_rows(rows)

    assert result is PanelModelUpdate.UNCHANGED
    assert changed.count() == 0
    assert reset.count() == 0


def test_custom_role_names_are_stable() -> None:
    names = PanelRowModel().roleNames()

    assert names[int(PanelRowRole.CAUGHT)].data() == b"caught"
    assert names[int(PanelRowRole.PROGRESS)].data() == b"progress"
    assert names[int(PanelRowRole.ICON_PATH)].data() == b"iconPath"
    assert names[int(PanelRowRole.CHIPS)].data() == b"chips"


def test_list_view_value_update_preserves_focus_selection_and_scroll(qtbot) -> None:
    rows = tuple(PanelRow(f"Row {index:03}") for index in range(100))
    view = PanelRowListView(rows)
    view.resize(240, 120)
    qtbot.addWidget(view)
    view.show()
    selected = view.row_model.index(60)
    view.setCurrentIndex(selected)
    view.scrollTo(selected, view.ScrollHint.PositionAtCenter)
    view.setFocus()
    qtbot.waitUntil(view.hasFocus)
    scroll_position = view.verticalScrollBar().value()

    updated = list(rows)
    updated[60] = PanelRow("Updated row 060", tooltip="Value-only update")
    result = view.set_rows(updated)

    assert result is PanelModelUpdate.VALUES
    assert view.hasFocus()
    assert view.currentIndex().row() == 60
    assert view.currentIndex().data() == "Updated row 060"
    assert view.verticalScrollBar().value() == scroll_position
    assert view.accessibleName() == "Information rows"