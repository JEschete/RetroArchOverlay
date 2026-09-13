from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from ...app.plugin_manager import CatalogPluginView, InstalledPluginView


class InstalledPluginRole(IntEnum):
    REPOSITORY = int(Qt.ItemDataRole.UserRole) + 1
    PLUGIN_ID = int(Qt.ItemDataRole.UserRole) + 2
    MANIFEST = int(Qt.ItemDataRole.UserRole) + 3


class CatalogPluginRole(IntEnum):
    ENTRY = int(Qt.ItemDataRole.UserRole) + 1
    PLUGIN_ID = int(Qt.ItemDataRole.UserRole) + 2
    INSTALLED = int(Qt.ItemDataRole.UserRole) + 3
    SEARCH_TEXT = int(Qt.ItemDataRole.UserRole) + 4


class InstalledPluginModel(QAbstractTableModel):
    HEADERS = ("Game", "License")

    def __init__(
        self,
        rows: tuple[InstalledPluginView, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows = rows

    @property
    def rows(self) -> tuple[InstalledPluginView, ...]:
        return self._rows

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return (row.name, row.license_expression)[index.column()]
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            return (
                f"{row.name}; repository {row.repository_root.name}; "
                f"license {row.license_expression}"
            )
        if role == InstalledPluginRole.REPOSITORY:
            return row.repository_root
        if role == InstalledPluginRole.PLUGIN_ID:
            return row.plugin_id
        if role == InstalledPluginRole.MANIFEST:
            return row.manifest
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == int(Qt.ItemDataRole.DisplayRole)
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def roleNames(self) -> dict[int, QByteArray]:
        names = super().roleNames()
        names.update(
            {
                int(InstalledPluginRole.REPOSITORY): QByteArray(b"repository"),
                int(InstalledPluginRole.PLUGIN_ID): QByteArray(b"pluginId"),
                int(InstalledPluginRole.MANIFEST): QByteArray(b"manifest"),
            }
        )
        return names

    def set_rows(self, rows: tuple[InstalledPluginView, ...]) -> None:
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class CatalogPluginModel(QAbstractTableModel):
    HEADERS = ("Game", "Status", "Repository")

    def __init__(
        self,
        rows: tuple[CatalogPluginView, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows = rows

    @property
    def rows(self) -> tuple[CatalogPluginView, ...]:
        return self._rows

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return (
                row.entry.name,
                "Installed" if row.installed else "Available",
                row.entry.repository,
            )[index.column()]
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            status = "installed" if row.installed else "available"
            return f"{row.entry.name}; {status}; {row.entry.plugin_id}"
        if role == CatalogPluginRole.ENTRY:
            return row.entry
        if role == CatalogPluginRole.PLUGIN_ID:
            return row.entry.plugin_id
        if role == CatalogPluginRole.INSTALLED:
            return row.installed
        if role == CatalogPluginRole.SEARCH_TEXT:
            return f"{row.entry.name} {row.entry.slug} {row.entry.plugin_id}"
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == int(Qt.ItemDataRole.DisplayRole)
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def roleNames(self) -> dict[int, QByteArray]:
        names = super().roleNames()
        names.update(
            {
                int(CatalogPluginRole.ENTRY): QByteArray(b"entry"),
                int(CatalogPluginRole.PLUGIN_ID): QByteArray(b"pluginId"),
                int(CatalogPluginRole.INSTALLED): QByteArray(b"installed"),
                int(CatalogPluginRole.SEARCH_TEXT): QByteArray(b"searchText"),
            }
        )
        return names

    def set_rows(self, rows: tuple[CatalogPluginView, ...]) -> None:
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class PluginCatalogFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tokens: tuple[str, ...] = ()
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_query(self, query: str) -> None:
        tokens = tuple(query.casefold().split())
        if tokens == self._tokens:
            return
        self.beginFilterChange()
        self._tokens = tokens
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._tokens:
            return True
        model = self.sourceModel()
        if model is None:
            return False
        text = model.index(source_row, 0, source_parent).data(
            CatalogPluginRole.SEARCH_TEXT
        )
        normalized = str(text or "").casefold()
        return all(token in normalized for token in self._tokens)