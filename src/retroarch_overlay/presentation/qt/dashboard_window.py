from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...app.dashboard import DashboardChoiceControl, DashboardStore
from ...core.models import MapDocument, MapLayer, MapOverlay, MapPosition, MapWaypoint
from .map_view import QtMapView
from .theme import apply_qt_theme


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _clear_layout(layout: QVBoxLayout | QGridLayout | QHBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)  # type: ignore[arg-type]


class _DashboardWorkspace(QWidget):
    def update_document(self, document: dict[str, Any]) -> None:
        raise NotImplementedError

    def ui_state(self) -> dict[str, Any]:
        return {}


class QtDashboardOverviewView(_DashboardWorkspace):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page = QWidget(scroll)
        self.layout = QVBoxLayout(self.page)
        self.layout.setContentsMargins(22, 18, 22, 22)
        self.layout.setSpacing(12)
        scroll.setWidget(self.page)
        root.addWidget(scroll)
        self._signature: tuple[object, ...] = ()
        self._heading: QLabel | None = None
        self._subtitle: QLabel | None = None
        self._metric_values: dict[str, QLabel] = {}
        self._row_values: dict[tuple[str, str], QLabel] = {}
        self._progress: QProgressBar | None = None

    def update_document(self, document: dict[str, Any]) -> None:
        metrics = _mappings(document.get("metrics"))
        sections = _mappings(document.get("sections"))
        progress = _mapping(document.get("progress"))
        signature = (
            tuple(str(metric.get("label", "")) for metric in metrics),
            tuple(
                (
                    str(section.get("key", index)),
                    tuple(
                        str(row.get("label", ""))
                        for row in _mappings(section.get("rows"))
                    ),
                )
                for index, section in enumerate(sections)
            ),
            bool(progress),
        )
        if signature != self._signature:
            self._build(document, metrics, sections, progress)
            self._signature = signature
        self._update_values(document, metrics, sections, progress)

    def _build(
        self,
        document: dict[str, Any],
        metrics: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        progress: dict[str, Any],
    ) -> None:
        _clear_layout(self.layout)
        self._metric_values = {}
        self._row_values = {}
        self._heading = QLabel(self.page)
        self._heading.setObjectName("dashboardHeading")
        self.layout.addWidget(self._heading)
        self._subtitle = QLabel(self.page)
        self._subtitle.setObjectName("dashboardSubtitle")
        self._subtitle.setWordWrap(True)
        self.layout.addWidget(self._subtitle)
        if progress:
            self._progress = QProgressBar(self.page)
            self._progress.setTextVisible(True)
            self.layout.addWidget(self._progress)
        else:
            self._progress = None
        if metrics:
            metric_host = QWidget(self.page)
            metric_layout = QGridLayout(metric_host)
            metric_layout.setContentsMargins(0, 0, 0, 0)
            for index, metric in enumerate(metrics):
                panel = QFrame(metric_host)
                panel.setObjectName("dashboardPanel")
                panel_layout = QVBoxLayout(panel)
                label = QLabel(str(metric.get("label", "Metric")), panel)
                label.setObjectName("dashboardEyebrow")
                value = QLabel(panel)
                value.setObjectName("dashboardMetric")
                panel_layout.addWidget(label)
                panel_layout.addWidget(value)
                metric_layout.addWidget(panel, index // 4, index % 4)
                self._metric_values[str(metric.get("label", index))] = value
            self.layout.addWidget(metric_host)
        for section_index, section in enumerate(sections):
            section_key = str(section.get("key", section_index))
            group = QGroupBox(str(section.get("title", "Details")), self.page)
            group.setObjectName("dashboardPanel")
            group_layout = QGridLayout(group)
            subtitle = str(section.get("subtitle", "")).strip()
            row_offset = 0
            if subtitle:
                subtitle_label = QLabel(subtitle, group)
                subtitle_label.setObjectName("dashboardSectionSubtitle")
                subtitle_label.setWordWrap(True)
                group_layout.addWidget(subtitle_label, 0, 0, 1, 3)
                row_offset = 1
            for row_index, row in enumerate(_mappings(section.get("rows"))):
                label_text = str(row.get("label", ""))
                label = QLabel(label_text, group)
                label.setObjectName("dashboardRowLabel")
                label.setAlignment(Qt.AlignmentFlag.AlignTop)
                value = QLabel(group)
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                group_layout.addWidget(label, row_index + row_offset, 0)
                group_layout.addWidget(value, row_index + row_offset, 1)
                url = str(row.get("url", "")).strip()
                if url:
                    button = QToolButton(group)
                    button.setIcon(
                        self.style().standardIcon(
                            QStyle.StandardPixmap.SP_DirLinkIcon
                        )
                    )
                    button.setToolTip(f"Open {label_text}")
                    button.setAccessibleName(f"Open {label_text}")
                    button.clicked.connect(
                        lambda _checked=False, target=url: QDesktopServices.openUrl(
                            QUrl(target)
                        )
                    )
                    group_layout.addWidget(button, row_index + row_offset, 2)
                self._row_values[(section_key, label_text)] = value
            group_layout.setColumnStretch(1, 1)
            self.layout.addWidget(group)
        self.layout.addStretch(1)

    def _update_values(
        self,
        document: dict[str, Any],
        metrics: list[dict[str, Any]],
        sections: list[dict[str, Any]],
        progress: dict[str, Any],
    ) -> None:
        if self._heading is not None:
            heading = str(document.get("heading", "Dashboard"))
            self._heading.setText(heading)
            self._heading.setVisible(bool(heading))
        if self._subtitle is not None:
            subtitle = str(document.get("subtitle", ""))
            self._subtitle.setText(subtitle)
            self._subtitle.setVisible(bool(subtitle))
        for metric in metrics:
            widget = self._metric_values.get(str(metric.get("label", "")))
            if widget is not None:
                widget.setText(str(metric.get("value", "")))
        for section_index, section in enumerate(sections):
            section_key = str(section.get("key", section_index))
            for row in _mappings(section.get("rows")):
                widget = self._row_values.get(
                    (section_key, str(row.get("label", "")))
                )
                if widget is not None:
                    detail = str(row.get("detail", "")).strip()
                    text = str(row.get("value", ""))
                    widget.setText(f"{text}\n{detail}" if detail else text)
                    widget.setToolTip(detail)
        if self._progress is not None:
            maximum = max(1, int(progress.get("maximum", 1)))
            value = max(0, min(maximum, int(progress.get("value", 0))))
            self._progress.setRange(0, maximum)
            self._progress.setValue(value)
            labels = progress.get("labels", [])
            label = (
                str(labels[value - 1])
                if value and isinstance(labels, list) and value <= len(labels)
                else f"{value}/{maximum}"
            )
            self._progress.setFormat(label)


class QtDashboardCardsView(_DashboardWorkspace):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page = QWidget(scroll)
        self.layout = QGridLayout(self.page)
        self.layout.setContentsMargins(22, 18, 22, 22)
        self.layout.setSpacing(12)
        scroll.setWidget(self.page)
        root.addWidget(scroll)
        self._signature: tuple[object, ...] = ()
        self._labels: dict[tuple[str, str], QLabel] = {}
        self._bars: dict[tuple[str, str], QProgressBar] = {}
        self._heading: QLabel | None = None
        self._subtitle: QLabel | None = None

    def update_document(self, document: dict[str, Any]) -> None:
        cards = _mappings(document.get("cards"))
        signature = tuple(
            (
                str(card.get("key", "")),
                str(card.get("title", "")),
                tuple(str(metric.get("label", "")) for metric in _mappings(card.get("metrics"))),
                tuple(str(row.get("label", "")) for row in _mappings(card.get("rows"))),
            )
            for card in cards
        )
        if signature != self._signature:
            self._build(document, cards)
            self._signature = signature
        self._update_values(document, cards)

    def _build(self, document: dict[str, Any], cards: list[dict[str, Any]]) -> None:
        _clear_layout(self.layout)
        self._labels = {}
        self._bars = {}
        self._heading = QLabel(str(document.get("heading", "Party")), self.page)
        self._heading.setObjectName("dashboardHeading")
        self.layout.addWidget(self._heading, 0, 0, 1, 2)
        self._subtitle = QLabel(str(document.get("subtitle", "")), self.page)
        self._subtitle.setObjectName("dashboardSubtitle")
        self.layout.addWidget(self._subtitle, 1, 0, 1, 2)
        for index, card in enumerate(cards):
            key = str(card.get("key", index))
            group = QGroupBox(str(card.get("title", "Item")), self.page)
            group.setObjectName("dashboardPanel")
            content = QVBoxLayout(group)
            subtitle_label = QLabel(group)
            subtitle_label.setObjectName("dashboardSectionSubtitle")
            content.addWidget(subtitle_label)
            self._labels[(key, "subtitle")] = subtitle_label
            status = QLabel(group)
            status.setObjectName("dashboardStatus")
            content.addWidget(status)
            self._labels[(key, "status")] = status
            for metric in _mappings(card.get("metrics")):
                metric_key = str(metric.get("label", "Metric"))
                value = QLabel(group)
                content.addWidget(value)
                bar = QProgressBar(group)
                bar.setRange(0, 1000)
                bar.setTextVisible(False)
                content.addWidget(bar)
                self._labels[(key, metric_key)] = value
                self._bars[(key, metric_key)] = bar
            for row in _mappings(card.get("rows")):
                row_key = str(row.get("label", ""))
                value = QLabel(group)
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                content.addWidget(value)
                self._labels[(key, row_key)] = value
            self.layout.addWidget(group, 2 + index // 2, index % 2)
        self.layout.setRowStretch(2 + (len(cards) + 1) // 2, 1)

    def _update_values(
        self,
        document: dict[str, Any],
        cards: list[dict[str, Any]],
    ) -> None:
        if self._heading is not None:
            self._heading.setText(str(document.get("heading", "Party")))
        if self._subtitle is not None:
            self._subtitle.setText(str(document.get("subtitle", "")))
        for card in cards:
            key = str(card.get("key", ""))
            subtitle = self._labels.get((key, "subtitle"))
            status = self._labels.get((key, "status"))
            if subtitle is not None:
                subtitle.setText(str(card.get("subtitle", "")))
            if status is not None:
                status.setText(str(card.get("status", "")))
            for metric in _mappings(card.get("metrics")):
                metric_key = str(metric.get("label", "Metric"))
                label = self._labels.get((key, metric_key))
                bar = self._bars.get((key, metric_key))
                if label is not None:
                    label.setText(f"{metric_key}  {metric.get('value', '')}")
                if bar is not None:
                    bar.setValue(round(max(0.0, min(1.0, float(metric.get("progress", 0)))) * 1000))
            for row in _mappings(card.get("rows")):
                row_key = str(row.get("label", ""))
                label = self._labels.get((key, row_key))
                if label is not None:
                    label.setText(f"{row_key}: {row.get('value', '')}")


class QtDashboardRecordsView(_DashboardWorkspace):
    def __init__(
        self,
        store: DashboardStore,
        workspace_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.workspace_key = workspace_key
        self._records: dict[str, dict[str, Any]] = {}
        self._source_keys: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 22)
        self.heading = QLabel(self)
        self.heading.setObjectName("dashboardHeading")
        root.addWidget(self.heading)
        self.subtitle = QLabel(self)
        self.subtitle.setObjectName("dashboardSubtitle")
        root.addWidget(self.subtitle)
        self.summary = QtDashboardOverviewView(self)
        self.summary.setMaximumHeight(250)
        root.addWidget(self.summary)
        tools = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search dashboard records")
        self.search.textChanged.connect(self._apply_filter)
        tools.addWidget(self.search, 1)
        self.sort = QComboBox(self)
        self.sort.setAccessibleName("Sort dashboard records")
        self.sort.addItem("Newest first", "source")
        self.sort.addItem("Oldest first", "reverse")
        self.sort.addItem("Title A-Z", "title")
        self.sort.currentIndexChanged.connect(self._refresh_list)
        tools.addWidget(self.sort)
        root.addLayout(tools)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.list = QListWidget(self.splitter)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        detail = QWidget(self.splitter)
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel(detail)
        self.detail_title.setObjectName("dashboardSectionTitle")
        self.detail_title.setWordWrap(True)
        self.detail_meta = QLabel(detail)
        self.detail_meta.setObjectName("dashboardSubtitle")
        self.detail_meta.setWordWrap(True)
        self.detail = QPlainTextEdit(detail)
        self.detail.setReadOnly(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_meta)
        detail_layout.addWidget(self.detail, 1)
        self.splitter.addWidget(self.list)
        self.splitter.addWidget(detail)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        root.addWidget(self.splitter, 1)
        state = store.ui_state(workspace_key)
        self.search.setText(str(state.get("query", "")))
        sort_index = self.sort.findData(str(state.get("sort", "source")))
        self.sort.setCurrentIndex(sort_index if sort_index >= 0 else 0)
        splitter_state = str(state.get("splitter", ""))
        if splitter_state:
            self.splitter.restoreState(
                QByteArray.fromBase64(splitter_state.encode("ascii"))
            )

    @property
    def record_count(self) -> int:
        return self.list.count()

    def update_document(self, document: dict[str, Any]) -> None:
        self.heading.setText(str(document.get("heading", "Records")))
        self.subtitle.setText(str(document.get("subtitle", "")))
        self.search.setPlaceholderText(str(document.get("search_placeholder", "Search")))
        self.summary.setVisible(bool(document.get("sections")))
        if document.get("sections"):
            self.summary.update_document(
                {
                    "heading": "",
                    "subtitle": "",
                    "sections": document.get("sections", []),
                }
            )
        selected = self.current_key
        records = _mappings(document.get("records"))
        self._records = {str(record.get("key", "")): record for record in records}
        self._source_keys = [str(record.get("key", "")) for record in records]
        self._refresh_list()
        if selected in self._records:
            self._select_key(selected)
        elif self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.detail_title.setText(str(document.get("empty", "No records")))
            self.detail_meta.clear()
            self.detail.clear()

    def ui_state(self) -> dict[str, Any]:
        return {
            "query": self.search.text(),
            "sort": str(self.sort.currentData()),
            "splitter": bytes(self.splitter.saveState().toBase64()).decode("ascii"),
        }

    @property
    def current_key(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _select_key(self, key: str) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentItem(item)
                return

    def _apply_filter(self, query: str) -> None:
        needle = query.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            record = self._records.get(
                str(item.data(Qt.ItemDataRole.UserRole)),
                {},
            )
            haystack = str(record.get("search", item.text())).casefold()
            item.setHidden(bool(needle and needle not in haystack))

    def _refresh_list(self) -> None:
        selected = self.current_key
        mode = str(self.sort.currentData())
        keys = list(self._source_keys)
        if mode == "reverse":
            keys.reverse()
        elif mode == "title":
            keys.sort(key=lambda key: str(self._records[key].get("title", "")).casefold())
        existing = [
            str(self.list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.list.count())
        ]
        if existing != keys:
            self.list.clear()
            for key in keys:
                item = QListWidgetItem(self.list)
                item.setData(Qt.ItemDataRole.UserRole, key)
        for index, key in enumerate(keys):
            record = self._records[key]
            item = self.list.item(index)
            item.setText(f"{record.get('title', 'Record')}\n{record.get('subtitle', '')}")
            item.setToolTip(str(record.get("detail", "")))
        self._apply_filter(self.search.text())
        if selected in self._records:
            self._select_key(selected)

    def _selection_changed(self) -> None:
        record = self._records.get(self.current_key)
        if record is None:
            return
        self.detail_title.setText(str(record.get("title", "Record")))
        self.detail_meta.setText(str(record.get("meta", "")))
        text = str(record.get("detail", ""))
        path = str(record.get("detail_path", "")).strip()
        if path:
            try:
                value = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            else:
                text = f"{text}\n\n{json.dumps(value, ensure_ascii=False, indent=2)}"
        self.detail.setPlainText(text)


class QtDashboardMapDialog(QDialog):
    def __init__(self, document: MapDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(document.title)
        self.resize(900, 720)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        zoom_out = QPushButton("-", self)
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self.view.change_zoom(-1))
        zoom_in = QPushButton("+", self)
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(lambda: self.view.change_zoom(1))
        recenter = QPushButton("Center", self)
        recenter.clicked.connect(self.view_recenter)
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(recenter)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.view = QtMapView(document, parent=self)
        layout.addWidget(self.view, 1)

    def view_recenter(self) -> None:
        self.view.recenter()

    def update_map(
        self,
        position: MapPosition,
        overlays: tuple[MapOverlay, ...],
        kinds: set[str],
    ) -> None:
        self.view.update_map(position, overlays)
        for kind in kinds:
            self.view.set_overlay_visible(kind, True)


class QtDashboardMapView(_DashboardWorkspace):
    def __init__(
        self,
        store: DashboardStore,
        workspace_key: str,
        controls: tuple[DashboardChoiceControl, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.workspace_key = workspace_key
        self.document = _map_document(store.static)
        self._items: dict[str, dict[str, Any]] = {}
        self._position: MapPosition | None = None
        self._overlays: tuple[MapOverlay, ...] = ()
        self._popout: QtDashboardMapDialog | None = None
        self._kind_visibility = {
            str(key): bool(value)
            for key, value in _mapping(
                store.ui_state(workspace_key).get("layers")
            ).items()
        }
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 22)
        self.heading = QLabel(self)
        self.heading.setObjectName("dashboardHeading")
        root.addWidget(self.heading)
        self.subtitle = QLabel(self)
        self.subtitle.setObjectName("dashboardSubtitle")
        root.addWidget(self.subtitle)
        toolbar = QHBoxLayout()
        self.choice_boxes: dict[str, QComboBox] = {}
        for control in controls:
            label = QLabel(control.label, self)
            combo = QComboBox(self)
            for choice in control.choices:
                combo.addItem(choice.label, choice.value)
            current = str(store.controls.get(control.key, control.default))
            selected = combo.findData(current)
            combo.setCurrentIndex(selected if selected >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _index, key=control.key, widget=combo: self.store.set_choice(
                    key,
                    str(widget.currentData()),
                )
            )
            toolbar.addWidget(label)
            toolbar.addWidget(combo)
            self.choice_boxes[control.key] = combo
        toolbar.addStretch(1)
        zoom_out = QPushButton("-", self)
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self.map_view and self.map_view.change_zoom(-1))
        zoom_in = QPushButton("+", self)
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(lambda: self.map_view and self.map_view.change_zoom(1))
        self.popout_button = QToolButton(self)
        self.popout_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
        )
        self.popout_button.setToolTip("Open map in a separate window")
        self.popout_button.setAccessibleName("Open map in a separate window")
        self.popout_button.clicked.connect(self.open_popout)
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(self.popout_button)
        root.addLayout(toolbar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.map_stack = QStackedWidget(self.splitter)
        self.map_view = (
            QtMapView(self.document, parent=self.map_stack) if self.document else None
        )
        if self.map_view is not None:
            self.map_stack.addWidget(self.map_view)
        self.map_error = QLabel("Map assets are unavailable", self.map_stack)
        self.map_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_error.setWordWrap(True)
        self.map_stack.addWidget(self.map_error)
        self.map_stack.setCurrentWidget(
            self.map_view if self.map_view is not None else self.map_error
        )
        self.splitter.addWidget(self.map_stack)
        rail = QWidget(self.splitter)
        rail_layout = QVBoxLayout(rail)
        self.coordinates = QLabel(rail)
        self.coordinates.setObjectName("dashboardMetric")
        rail_layout.addWidget(self.coordinates)
        self.context = QtDashboardOverviewView(rail)
        self.context.setMaximumHeight(240)
        rail_layout.addWidget(self.context)
        self.layers = QGroupBox("Layers", rail)
        self.layers_layout = QGridLayout(self.layers)
        self._kind_checks: dict[str, QCheckBox] = {}
        rail_layout.addWidget(self.layers)
        self.features = QListWidget(rail)
        self.features.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.features.itemChanged.connect(self._item_changed)
        self.features.itemSelectionChanged.connect(self._selection_changed)
        rail_layout.addWidget(self.features, 1)
        self.detail_title = QLabel("Select a map feature", rail)
        self.detail_title.setObjectName("dashboardSectionTitle")
        self.detail_title.setWordWrap(True)
        self.detail = QLabel(rail)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rail_layout.addWidget(self.detail_title)
        rail_layout.addWidget(self.detail)
        self.splitter.addWidget(rail)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter, 1)
        state = store.ui_state(workspace_key)
        if self.map_view is not None:
            zoom = int(state.get("zoom", 1))
            if zoom in self.map_view.ZOOM_LEVELS:
                self.map_view.set_zoom(zoom)
        splitter_state = str(state.get("splitter", ""))
        if splitter_state:
            self.splitter.restoreState(
                QByteArray.fromBase64(splitter_state.encode("ascii"))
            )

    @property
    def feature_count(self) -> int:
        return self.features.count()

    def update_document(self, document: dict[str, Any]) -> None:
        self.heading.setText(str(document.get("heading", "Map")))
        self.subtitle.setText(str(document.get("subtitle", "")))
        map_value = _mapping(document.get("map"))
        self.coordinates.setText(
            f"X {int(map_value.get('x', 0))} / Y {int(map_value.get('y', 0))}"
        )
        sections = _mappings(document.get("sections"))
        self.context.setVisible(bool(sections))
        if sections:
            self.context.update_document(
                {"heading": "", "subtitle": "", "sections": sections}
            )
        scope = str(self.store.live.get("playthrough", ""))
        completed = self.store.completed_ids(scope)
        items = _mappings(document.get("items"))
        self._items = {str(item.get("key", "")): item for item in items}
        kinds = {
            *(self.document.overlay_kinds if self.document is not None else ()),
            *(str(item.get("kind", "point")) for item in items),
        }
        self._sync_kind_controls(kinds)
        selected = self.current_feature_key
        self.features.blockSignals(True)
        existing_keys = [
            str(self.features.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.features.count())
        ]
        new_keys = [str(item.get("key", "")) for item in items]
        if existing_keys != new_keys:
            self.features.clear()
            for item in items:
                widget = QListWidgetItem(self.features)
                widget.setData(Qt.ItemDataRole.UserRole, str(item.get("key", "")))
        waypoints = []
        for index, item in enumerate(items):
            key = str(item.get("key", ""))
            game_completed = bool(item.get("game_completed"))
            is_completed = game_completed or key in completed
            status = (
                "LOOTED IN GAME"
                if game_completed
                else "MARKED COMPLETE"
                if key in completed
                else "AVAILABLE"
            )
            widget = self.features.item(index)
            widget.setText(f"{item.get('title', 'Feature')}\n{item.get('subtitle', '')}")
            widget.setToolTip(
                f"{item.get('title', 'Feature')}\n{status}\n{item.get('detail', '')}"
            )
            flags = widget.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
            if item.get("can_complete"):
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                widget.setCheckState(
                    Qt.CheckState.Checked if is_completed else Qt.CheckState.Unchecked
                )
            widget.setFlags(flags)
            if game_completed:
                widget.setFlags(widget.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            kind = str(item.get("kind", "point"))
            widget.setHidden(not self._kind_visibility.get(kind, True))
            waypoints.append(
                MapWaypoint(
                    int(item.get("x", 0)),
                    int(item.get("y", 0)),
                    str(item.get("title", "Feature")),
                    str(item.get("detail", "")),
                    kind,
                    is_completed,
                    str(item.get("marker", "")),
                )
            )
        self.features.blockSignals(False)
        if selected in self._items:
            self._select_feature(selected)
        elif self.features.count():
            self.features.setCurrentRow(0)
        else:
            self.detail_title.setText("No documented map features")
            self.detail.clear()
        if self.document is None or self.map_view is None:
            self.map_error.setText("Map assets are unavailable")
            self.map_stack.setCurrentWidget(self.map_error)
            return
        layer_key = str(map_value.get("key", ""))
        layer = next(
            (candidate for candidate in self.document.layers if candidate.key == layer_key),
            None,
        )
        if layer is None:
            self.map_error.setText("The current map layer is unavailable")
            self.map_stack.setCurrentWidget(self.map_error)
            return
        map_id = map_value.get("map_id")
        self._position = MapPosition(
            str(map_value.get("area", layer.area)),
            int(map_id) if isinstance(map_id, int) else 0,
            int(map_value.get("x", 0)),
            int(map_value.get("y", 0)),
            bool(map_value.get("is_world")),
        )
        self._overlays = (MapOverlay(layer_key, tuple(waypoints)),)
        try:
            self.map_view.update_map(self._position, self._overlays)
        except ValueError as error:
            self.map_error.setText(str(error))
            self.map_stack.setCurrentWidget(self.map_error)
            return
        self.map_stack.setCurrentWidget(self.map_view)
        for kind in kinds:
            self.map_view.set_overlay_visible(
                kind,
                self._kind_visibility.get(kind, True),
            )
        if self._popout is not None:
            self._popout.update_map(self._position, self._overlays, kinds)

    @property
    def current_feature_key(self) -> str:
        item = self.features.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _select_feature(self, key: str) -> None:
        for index in range(self.features.count()):
            item = self.features.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.features.setCurrentItem(item)
                return

    def _selection_changed(self) -> None:
        feature = self._items.get(self.current_feature_key)
        if feature is None:
            return
        self.detail_title.setText(str(feature.get("title", "Feature")))
        scope = str(self.store.live.get("playthrough", ""))
        completed = self.store.completed_ids(scope)
        key = str(feature.get("key", ""))
        status = (
            "LOOTED IN GAME"
            if feature.get("game_completed")
            else "MARKED COMPLETE"
            if key in completed
            else "AVAILABLE"
        )
        self.detail.setText(f"{status}\n\n{feature.get('detail', '')}")
        if self.map_view is not None:
            waypoint = next(
                (
                    point
                    for overlay in self._overlays
                    for point in overlay.waypoints
                    if point.title == str(feature.get("title", ""))
                    and point.x == int(feature.get("x", 0))
                    and point.y == int(feature.get("y", 0))
                ),
                None,
            )
            if waypoint is not None:
                self.map_view.center_on_waypoint(waypoint)

    def _item_changed(self, item: QListWidgetItem) -> None:
        key = str(item.data(Qt.ItemDataRole.UserRole))
        feature = self._items.get(key)
        if feature is None:
            return
        scope = str(self.store.live.get("playthrough", ""))
        changed = self.store.set_completed(
            key,
            scope,
            item.checkState() == Qt.CheckState.Checked,
            allowed=bool(feature.get("can_complete")),
            game_completed=bool(feature.get("game_completed")),
        )
        if changed:
            self.update_document(
                _mapping(
                    _mapping(self.store.live.get("presentation")).get("workspaces")
                ).get(self.workspace_key, {})
            )

    def _sync_kind_controls(self, kinds: set[str]) -> None:
        if set(self._kind_checks) == kinds:
            return
        _clear_layout(self.layers_layout)
        self._kind_checks = {}
        for index, kind in enumerate(sorted(kinds)):
            control = QCheckBox(kind.replace("_", " ").title(), self.layers)
            control.setChecked(self._kind_visibility.get(kind, True))
            control.toggled.connect(
                lambda visible, selected=kind: self._set_kind_visible(
                    selected,
                    visible,
                )
            )
            self.layers_layout.addWidget(control, index // 2, index % 2)
            self._kind_checks[kind] = control
        self.layers.setVisible(bool(kinds))

    def _set_kind_visible(self, kind: str, visible: bool) -> None:
        self._kind_visibility[kind] = bool(visible)
        for index in range(self.features.count()):
            widget = self.features.item(index)
            feature = self._items.get(
                str(widget.data(Qt.ItemDataRole.UserRole)),
                {},
            )
            if str(feature.get("kind", "point")) == kind:
                widget.setHidden(not visible)
        if self.map_view is not None:
            self.map_view.set_overlay_visible(kind, visible)
        if self._popout is not None:
            self._popout.view.set_overlay_visible(kind, visible)

    def open_popout(self) -> None:
        if self.document is None or self._position is None:
            return
        if self._popout is None:
            self._popout = QtDashboardMapDialog(self.document, self)
        kinds = {str(item.get("kind", "point")) for item in self._items.values()}
        self._popout.update_map(self._position, self._overlays, kinds)
        self._popout.show()
        self._popout.raise_()

    def ui_state(self) -> dict[str, Any]:
        return {
            "zoom": self.map_view.zoom if self.map_view is not None else 1,
            "splitter": bytes(self.splitter.saveState().toBase64()).decode("ascii"),
            "layers": dict(sorted(self._kind_visibility.items())),
        }


class QtDashboardWindow(QMainWindow):
    POLL_INTERVAL_MS = 250

    def __init__(
        self,
        store: DashboardStore,
        *,
        theme: str = "dark",
        poll_interval_ms: int = POLL_INTERVAL_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._workspace_signature: tuple[object, ...] = ()
        self._workspace_widgets: dict[str, _DashboardWorkspace] = {}
        self._workspace_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("RetroArch Overlay Companion")
        self.resize(1260, 790)
        self.setMinimumSize(960, 620)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame(central)
        header.setObjectName("dashboardHeader")
        header_layout = QHBoxLayout(header)
        brand = QVBoxLayout()
        self.title_label = QLabel("Companion", header)
        self.title_label.setObjectName("dashboardBrand")
        self.subtitle_label = QLabel(header)
        self.subtitle_label.setObjectName("dashboardSubtitle")
        brand.addWidget(self.title_label)
        brand.addWidget(self.subtitle_label)
        header_layout.addLayout(brand)
        header_layout.addStretch(1)
        status = QVBoxLayout()
        self.status_title = QLabel("Waiting for game", header)
        self.status_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status_detail = QLabel(header)
        self.status_detail.setObjectName("dashboardSubtitle")
        self.status_detail.setAlignment(Qt.AlignmentFlag.AlignRight)
        status.addWidget(self.status_title)
        status.addWidget(self.status_detail)
        header_layout.addLayout(status)
        root.addWidget(header)
        self.content_stack = QStackedWidget(central)
        body = QSplitter(Qt.Orientation.Horizontal, self.content_stack)
        self.sidebar = QWidget(body)
        self.sidebar.setObjectName("dashboardSidebar")
        self.sidebar.setMinimumWidth(170)
        self.sidebar.setMaximumWidth(230)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(12, 18, 12, 18)
        self.sidebar_layout.setSpacing(6)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.stack = QStackedWidget(body)
        body.addWidget(self.sidebar)
        body.addWidget(self.stack)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        self.content_stack.addWidget(body)
        waiting = QWidget(self.content_stack)
        waiting_layout = QVBoxLayout(waiting)
        waiting_layout.addStretch(1)
        self.waiting_title = QLabel("Waiting for game", waiting)
        self.waiting_title.setObjectName("dashboardHeading")
        self.waiting_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waiting_detail = QLabel(waiting)
        self.waiting_detail.setObjectName("dashboardSubtitle")
        self.waiting_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.waiting_detail.setWordWrap(True)
        waiting_layout.addWidget(self.waiting_title)
        waiting_layout.addWidget(self.waiting_detail)
        waiting_layout.addStretch(1)
        self.content_stack.addWidget(waiting)
        root.addWidget(self.content_stack, 1)
        self.setCentralWidget(central)
        apply_qt_theme(self, theme)
        self.setStyleSheet(self.styleSheet() + _DASHBOARD_STYLE)
        self.store.open()
        self._render()
        window_state = self.store.ui_state("window")
        width = window_state.get("width")
        height = window_state.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            self.resize(max(self.minimumWidth(), width), max(self.minimumHeight(), height))
        self._timer = QTimer(self)
        self._timer.setInterval(max(25, poll_interval_ms))
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    @property
    def workspace_keys(self) -> tuple[str, ...]:
        return tuple(self._workspace_widgets)

    @property
    def active_workspace(self) -> str:
        current = self.stack.currentWidget()
        return next(
            (key for key, widget in self._workspace_widgets.items() if widget is current),
            "",
        )

    def workspace_widget(self, key: str) -> _DashboardWorkspace | None:
        return self._workspace_widgets.get(key)

    def select_workspace(self, key: str) -> bool:
        widget = self._workspace_widgets.get(key)
        if widget is None:
            return False
        self.stack.setCurrentWidget(widget)
        button = self._workspace_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.store.select_workspace(key)
        return True

    def poll(self) -> None:
        if self.store.refresh():
            self._render()

    def _render(self) -> None:
        presentation = _mapping(self.store.static.get("presentation"))
        self.title_label.setText(str(presentation.get("title", "Companion")))
        self.subtitle_label.setText(str(presentation.get("subtitle", "")))
        specs = self.store.workspaces
        signature = tuple((item.key, item.title, item.kind) for item in specs)
        if signature != self._workspace_signature:
            self._rebuild_workspaces()
            self._workspace_signature = signature
        live_presentation = _mapping(self.store.live.get("presentation"))
        status = _mapping(live_presentation.get("status"))
        self.status_title.setText(str(status.get("title", "Waiting for game")))
        self.status_detail.setText(
            f"{status.get('mode', 'WAITING')} · {status.get('detail', '')}"
        )
        waiting = (
            not self.store.live
            or not self._workspace_widgets
            or self.store.live.get("mode") == "waiting"
        )
        self.content_stack.setCurrentIndex(1 if waiting else 0)
        if waiting:
            self.waiting_title.setText(str(status.get("title", "Waiting for game")))
            detail = str(status.get("detail", "")).strip()
            if not detail and self.store.errors:
                detail = " · ".join(self.store.errors.values())
            self.waiting_detail.setText(detail)
        documents = _mapping(live_presentation.get("workspaces"))
        for key, widget in self._workspace_widgets.items():
            widget.update_document(_mapping(documents.get(key)))
        requested = str(self.store.controls.get("workspace", ""))
        if requested not in self._workspace_widgets and specs:
            requested = specs[0].key
        if requested:
            self.select_workspace(requested)

    def _rebuild_workspaces(self) -> None:
        for button in self._workspace_buttons.values():
            self.button_group.removeButton(button)
        self._workspace_buttons = {}
        _clear_layout(self.sidebar_layout)
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self._workspace_widgets = {}
        controls = self.store.choice_controls
        for workspace in self.store.workspaces:
            button = QPushButton(workspace.title, self.sidebar)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, key=workspace.key: self.select_workspace(key)
            )
            self.button_group.addButton(button)
            self.sidebar_layout.addWidget(button)
            self._workspace_buttons[workspace.key] = button
            if workspace.kind == "map":
                widget: _DashboardWorkspace = QtDashboardMapView(
                    self.store,
                    workspace.key,
                    tuple(control for control in controls if control.workspace == workspace.key),
                    self.stack,
                )
            elif workspace.kind == "cards":
                widget = QtDashboardCardsView(self.stack)
            elif workspace.kind == "records":
                widget = QtDashboardRecordsView(
                    self.store,
                    workspace.key,
                    self.stack,
                )
            else:
                widget = QtDashboardOverviewView(self.stack)
            self.stack.addWidget(widget)
            self._workspace_widgets[workspace.key] = widget
        self.sidebar_layout.addStretch(1)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        states = {
            key: widget.ui_state()
            for key, widget in self._workspace_widgets.items()
            if widget.ui_state()
        }
        states["window"] = {
            "width": self.width(),
            "height": self.height(),
        }
        self.store.save_ui_states(states)
        for widget in self._workspace_widgets.values():
            if isinstance(widget, QtDashboardMapView) and widget._popout is not None:
                widget._popout.close()
        self.store.close()
        super().closeEvent(event)


def _map_document(static: dict[str, Any]) -> MapDocument | None:
    layers = []
    for value in _mappings(static.get("maps")):
        key = str(value.get("key", "")).strip()
        path = str(value.get("path", "")).strip()
        if not key or not path:
            continue
        map_id = value.get("map_id")
        layers.append(
            MapLayer(
                key,
                str(value.get("title", key)),
                str(value.get("area", "")),
                Path(path),
                str(value.get("source_url", "")),
                str(value.get("credit", "")),
                max(1, int(value.get("tile_width", 16))),
                max(1, int(value.get("tile_height", 16))),
                int(value.get("offset_x", 0)),
                int(value.get("offset_y", 0)),
                int(value.get("anchor_x", 0)),
                int(value.get("anchor_y", 0)),
                max(1, int(value.get("width", 1))),
                max(1, int(value.get("height", 1))),
                int(map_id) if isinstance(map_id, int) else None,
                wraps=bool(value.get("wraps")),
            )
        )
    presentation = _mapping(static.get("presentation"))
    overlay_kinds = tuple(
        value
        for value in presentation.get("map_overlay_kinds", [])
        if isinstance(value, str) and value
    )
    return (
        MapDocument(
            str(static.get("game", "Companion map")),
            tuple(layers),
            overlay_kinds,
        )
        if layers
        else None
    )


_DASHBOARD_STYLE = """
    QMainWindow, QWidget { font-family: "Bahnschrift"; }
    QFrame#dashboardHeader { padding: 10px 14px; }
    QWidget#dashboardSidebar { border-right: 1px solid palette(mid); }
    QLabel#dashboardBrand { font-family: "Palatino Linotype"; font-size: 22px; font-weight: 700; }
    QLabel#dashboardHeading { font-family: "Palatino Linotype"; font-size: 20px; font-weight: 700; }
    QLabel#dashboardMetric { font-size: 18px; font-weight: 600; }
    QLabel#dashboardSectionTitle { font-size: 15px; font-weight: 600; }
    QLabel#dashboardSubtitle, QLabel#dashboardEyebrow, QLabel#dashboardRowLabel { color: palette(mid); }
    QFrame#dashboardPanel, QGroupBox#dashboardPanel { border: 1px solid palette(mid); border-radius: 4px; margin-top: 8px; padding: 8px; }
    QGroupBox#dashboardPanel::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; font-weight: 600; }
    QListWidget { border: 1px solid palette(mid); }
    QListWidget::item { padding: 7px; }
    QProgressBar { min-height: 8px; max-height: 14px; border: 1px solid palette(mid); }
    QProgressBar::chunk { background: palette(highlight); }
"""