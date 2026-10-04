from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QStyle, QWidget, QWidgetItem


class FlowLayout(QLayout):
    """Wrapping left-to-right layout whose height depends on its width.

    Items keep insertion order. A flowing item takes its size-hint width, capped
    at the row width; a full-row item starts a new line and spans it.
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._full_rows: set[QWidget] = set()
        self._heights: dict[int, int] = {}
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def set_full_row(self, widget: QWidget, full_row: bool) -> None:
        if (widget in self._full_rows) == full_row:
            return
        if full_row:
            self._full_rows.add(widget)
        else:
            self._full_rows.discard(widget)
        self.invalidate()

    def is_full_row(self, widget: QWidget) -> bool:
        return widget in self._full_rows

    def widgets(self) -> list[QWidget]:
        return [item.widget() for item in self._items]

    def addWidget(self, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self._full_rows.discard(item.widget())
        self._heights.clear()
        return item

    def invalidate(self) -> None:
        self._heights.clear()
        super().invalidate()

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        height = self._heights.get(width)
        if height is None:
            height = self._heights[width] = self._do_layout(QRect(0, 0, width, 0), apply=False)
        return height

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        width = height = 0
        for item in self._items:
            if item.isEmpty():
                continue
            minimum = item.minimumSize()
            if item.widget() in self._full_rows:
                width = max(width, minimum.width())
            height = max(height, minimum.height())
        margins = self.contentsMargins()
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        width = max(0, area.width())
        spacing = max(0, self.spacing())
        parent = self.parentWidget()
        direction = parent.layoutDirection() if parent is not None else Qt.LayoutDirection.LeftToRight
        x = y = line_height = bottom = 0
        line_open = False
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if item.widget() in self._full_rows:
                if line_open:
                    y += line_height + spacing
                item_width = width
                item_height = item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
                item_x, item_y = 0, y
                y += item_height + spacing
                x = line_height = 0
                line_open = False
            else:
                item_width, item_height = min(hint.width(), width), hint.height()
                if line_open and x + item_width > width:
                    y += line_height + spacing
                    x = line_height = 0
                item_x, item_y = x, y
                x += item_width + spacing
                line_height = max(line_height, item_height)
                line_open = True
            bottom = max(bottom, item_y + item_height)
            if apply:
                item.setGeometry(QStyle.visualRect(direction, area, QRect(
                    area.x() + item_x, area.y() + item_y, item_width, item_height,
                )))
        return bottom + margins.top() + margins.bottom()
