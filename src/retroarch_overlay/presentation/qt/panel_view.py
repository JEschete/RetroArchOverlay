from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QAbstractItemView, QListView, QWidget

from ...core.models import PanelRow
from .panel_delegate import PanelRowDelegate
from .panel_model import PanelModelUpdate, PanelRowModel
from .theme import qt_palette


class PanelRowListView(QListView):
    content_height_changed = Signal(int)

    def __init__(
        self,
        rows: Iterable[PanelRow] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_model = PanelRowModel(rows, self)
        self._delegate = PanelRowDelegate(parent=self)
        self.setModel(self._row_model)
        self.setItemDelegate(self._delegate)
        self.setAccessibleName("Information rows")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrap(True)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_contents)
        self.fit_to_contents()

    @property
    def row_model(self) -> PanelRowModel:
        return self._row_model

    @property
    def row_delegate(self) -> PanelRowDelegate:
        return self._delegate

    def set_rows(self, rows: Iterable[PanelRow]) -> PanelModelUpdate:
        result = self._row_model.set_rows(rows)
        self.schedule_fit_to_contents()
        return result

    def set_theme(self, preference: str) -> str:
        name, palette = qt_palette(preference)
        self.setPalette(palette)
        self._delegate.set_theme(name)
        self.viewport().update()
        self.schedule_fit_to_contents()
        return name

    def schedule_fit_to_contents(self) -> None:
        if not self._fit_timer.isActive():
            self._fit_timer.start(0)

    def fit_to_contents(self) -> None:
        count = self._row_model.rowCount()
        if count <= 0:
            target = 0
        else:
            fallback = self.fontMetrics().height() + 8
            content_height = sum(
                max(fallback, self.sizeHintForRow(row)) for row in range(count)
            )
            content_height += max(0, count - 1) * self.spacing()
            target = content_height + self.frameWidth() * 2
        changed = self.minimumHeight() != target or self.maximumHeight() != target
        self.setFixedHeight(target)
        if changed:
            self.content_height_changed.emit(target)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.schedule_fit_to_contents()