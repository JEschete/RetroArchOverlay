from __future__ import annotations

from collections.abc import Iterable
from enum import Enum, IntEnum

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QObject, QPersistentModelIndex, Qt

from ...core.models import PanelRow


class PanelRowRole(IntEnum):
    CAUGHT = int(Qt.ItemDataRole.UserRole) + 1
    EMPHASIS = int(Qt.ItemDataRole.UserRole) + 2
    PROGRESS = int(Qt.ItemDataRole.UserRole) + 3
    PROGRESS_COLOR = int(Qt.ItemDataRole.UserRole) + 4
    ICON_PATH = int(Qt.ItemDataRole.UserRole) + 5
    CHIPS = int(Qt.ItemDataRole.UserRole) + 6
    METERS = int(Qt.ItemDataRole.UserRole) + 7
    DETAIL = int(Qt.ItemDataRole.UserRole) + 8


class PanelModelUpdate(str, Enum):
    UNCHANGED = "unchanged"
    VALUES = "values"
    STRUCTURE = "structure"


_ROLE_NAMES = {
    PanelRowRole.CAUGHT: QByteArray(b"caught"),
    PanelRowRole.EMPHASIS: QByteArray(b"emphasis"),
    PanelRowRole.PROGRESS: QByteArray(b"progress"),
    PanelRowRole.PROGRESS_COLOR: QByteArray(b"progressColor"),
    PanelRowRole.ICON_PATH: QByteArray(b"iconPath"),
    PanelRowRole.CHIPS: QByteArray(b"chips"),
    PanelRowRole.METERS: QByteArray(b"meters"),
    PanelRowRole.DETAIL: QByteArray(b"detail"),
}

_VALUE_ROLES = [
    int(Qt.ItemDataRole.DisplayRole),
    int(Qt.ItemDataRole.ToolTipRole),
    int(Qt.ItemDataRole.AccessibleTextRole),
    int(Qt.ItemDataRole.AccessibleDescriptionRole),
    *(int(role) for role in PanelRowRole),
]


class PanelRowModel(QAbstractListModel):
    def __init__(
        self,
        rows: Iterable[PanelRow] = (),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    @property
    def rows(self) -> tuple[PanelRow, ...]:
        return self._rows

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return row.text
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return row.tooltip or None
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            return _accessible_text(row)
        if role == int(Qt.ItemDataRole.AccessibleDescriptionRole):
            return row.tooltip or None
        if role == PanelRowRole.CAUGHT:
            return row.caught
        if role == PanelRowRole.EMPHASIS:
            return row.emphasis
        if role == PanelRowRole.PROGRESS:
            return row.progress
        if role == PanelRowRole.PROGRESS_COLOR:
            return row.progress_color
        if role == PanelRowRole.ICON_PATH:
            return row.icon
        if role == PanelRowRole.CHIPS:
            return row.chips
        if role == PanelRowRole.METERS:
            return row.meters
        if role == PanelRowRole.DETAIL:
            return row.detail
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        names = super().roleNames()
        names.update({int(role): name for role, name in _ROLE_NAMES.items()})
        return names

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_rows(self, rows: Iterable[PanelRow]) -> PanelModelUpdate:
        updated = tuple(rows)
        if updated == self._rows:
            return PanelModelUpdate.UNCHANGED
        if panel_rows_structure(updated) != panel_rows_structure(self._rows):
            self.beginResetModel()
            self._rows = updated
            self.endResetModel()
            return PanelModelUpdate.STRUCTURE

        changed = [
            index
            for index, (previous, current) in enumerate(zip(self._rows, updated))
            if previous != current
        ]
        self._rows = updated
        for first, last in _contiguous_ranges(changed):
            self.dataChanged.emit(self.index(first), self.index(last), _VALUE_ROLES)
        return PanelModelUpdate.VALUES


def panel_rows_structure(
    rows: tuple[PanelRow, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (bool(row.icon), len(row.chips), row.progress is not None, len(row.meters), bool(row.detail))
        for row in rows
    )


def _contiguous_ranges(values: list[int]) -> tuple[tuple[int, int], ...]:
    if not values:
        return ()
    ranges = []
    first = previous = values[0]
    for value in values[1:]:
        if value != previous + 1:
            ranges.append((first, previous))
            first = value
        previous = value
    ranges.append((first, previous))
    return tuple(ranges)


def _accessible_text(row: PanelRow) -> str:
    parts = [row.text]
    if row.detail:
        parts.append(", ".join(row.detail.splitlines()))
    if row.caught is True:
        parts.append("complete")
    elif row.caught is False:
        parts.append("not complete")
    if row.progress is not None:
        progress = round(max(0.0, min(1.0, row.progress)) * 100)
        parts.append(f"progress {progress} percent")
    if row.chips:
        parts.append("tags " + ", ".join(chip.text for chip in row.chips))
    parts.extend(f"{meter.label} unlimited" if meter.infinite else f"{meter.label} {meter.value} of {meter.maximum}"
                 for meter in row.meters)
    return "; ".join(parts)