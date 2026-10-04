from __future__ import annotations

from collections.abc import Callable
import re

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPaintEvent, QPainter, QResizeEvent, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.models import OverlaySnapshot, PanelNumberInput
from ..theme import THEME_PALETTES
from .flow_layout import FlowLayout
from .panel_document import (
    ActionIdentity,
    PanelActionView,
    PanelDocumentState,
    PanelDocumentUpdate,
    PanelSectionView,
    SectionIdentity,
)
from .panel_view import PanelRowListView
from .theme import apply_qt_theme, qt_palette


class ElidingPushButton(QPushButton):
    """Paints its label elided when narrower than its size hint; text() stays whole."""

    def setText(self, text: str) -> None:
        if text != self.text():
            super().setText(text)
            self._sync_tool_tip()

    def displayed_text(self) -> str:
        self.ensurePolished()
        option = QStyleOptionButton()
        self.initStyleOption(option)
        return self._elided_text(option)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_tool_tip()

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self._elided_text(option)
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.end()

    def _elided_text(self, option: QStyleOptionButton) -> str:
        if self.width() >= self.sizeHint().width():
            return option.text
        available = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self).width()
        return option.fontMetrics.elidedText(
            option.text, Qt.TextElideMode.ElideRight, max(0, available), Qt.TextFlag.TextShowMnemonic,
        )

    def _sync_tool_tip(self) -> None:
        self.setToolTip(self.text() if self.displayed_text() != self.text() else "")


class PanelActionWidget(QWidget):
    content_height_changed = Signal(int)

    def __init__(
        self,
        identity: ActionIdentity,
        on_toggle: Callable[[ActionIdentity], None],
        on_filter: Callable[[ActionIdentity, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.identity = identity
        self.instant = False
        self._on_toggle = on_toggle
        self._on_filter = on_filter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle_button = ElidingPushButton(self)
        self.toggle_button.setCheckable(True)
        self.toggle_button.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_button)
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter details")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._filter_changed)
        layout.addWidget(self.filter_edit)
        self.row_view = PanelRowListView(parent=self)
        self.row_view.content_height_changed.connect(self.schedule_fit_to_contents)
        layout.addWidget(self.row_view)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_contents)

    def set_view(self, view: PanelActionView) -> None:
        self.identity = view.identity
        self.instant = bool(view.action.map_layer_key or view.action.command or view.action.document_anchor)
        with QSignalBlocker(self.toggle_button):
            self.toggle_button.setCheckable(not self.instant)
            self.toggle_button.setChecked(view.expanded)
        arrow = "▾" if view.expanded else "▸"
        self.toggle_button.setText(view.action.label if self.instant else f"{arrow} {view.action.label}")
        self.toggle_button.setAccessibleName(
            f"{view.action.label}; " + ("run command" if view.action.command else "open map" if view.action.map_layer_key else
                                       "jump in guide" if view.action.document_anchor else "expanded" if view.expanded else "collapsed")
        )
        with QSignalBlocker(self.filter_edit):
            if self.filter_edit.text() != view.filter_text:
                self.filter_edit.setText(view.filter_text)
        self.filter_edit.setAccessibleName(f"Filter {view.action.title}")
        self.filter_edit.setVisible(view.expanded and view.filterable)
        self.row_view.setAccessibleName(view.action.title)
        self.row_view.set_rows(view.rows)
        self.row_view.setVisible(view.expanded)
        _fit_row_view(self.row_view)
        self.fit_to_contents()

    def set_theme(self, preference: str) -> str:
        name, palette = qt_palette(preference)
        self.setPalette(palette)
        self.row_view.set_theme(name)
        self.schedule_fit_to_contents()
        return name

    def schedule_fit_to_contents(self) -> None:
        if not self._fit_timer.isActive():
            self._fit_timer.start(0)

    def fit_to_contents(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        target = layout.sizeHint().height()
        changed = self.minimumHeight() != target or self.maximumHeight() != target
        self.setFixedHeight(target)
        if changed:
            self.content_height_changed.emit(target)

    def _toggle(self) -> None:
        self._on_toggle(self.identity)

    def _filter_changed(self, text: str) -> None:
        self._on_filter(self.identity, text)


class PanelSectionWidget(QFrame):
    input_failed = Signal(str)

    def __init__(
        self,
        identity: SectionIdentity,
        on_toggle_section: Callable[[SectionIdentity], None],
        on_toggle_action: Callable[[ActionIdentity], None],
        on_filter_action: Callable[[ActionIdentity, str], None],
        parent: QWidget | None = None,
        on_toggle_open: Callable[[SectionIdentity], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.identity = identity
        self._on_toggle_section = on_toggle_section
        self._on_toggle_action = on_toggle_action
        self._on_filter_action = on_filter_action
        self._on_toggle_open = on_toggle_open
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(4)
        self.header_button = QPushButton(self)
        self.header_button.setObjectName("panelSectionHeader")
        self.header_button.setCheckable(True)
        self.header_button.setFlat(True)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self._toggle_open)
        self._layout.addWidget(self.header_button)
        self.row_view = PanelRowListView(parent=self)
        self.row_view.content_height_changed.connect(self.schedule_fit_to_contents)
        self._layout.addWidget(self.row_view)
        self.columns_host = QWidget(self)
        self._columns_layout = QHBoxLayout(self.columns_host)
        self._columns_layout.setContentsMargins(0, 0, 0, 0)
        self._columns_layout.setSpacing(8)
        self._column_widgets: dict[str, tuple[QWidget, QLabel, PanelRowListView]] = {}
        self._layout.addWidget(self.columns_host)
        self.document_tools = QWidget(self)
        tools_layout = QVBoxLayout(self.document_tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(4)
        self.document_contents = QComboBox(self.document_tools)
        self.document_contents.setMinimumWidth(0)
        self.document_contents.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.document_contents.setAccessibleName("Guide contents")
        self.document_contents.activated.connect(self._select_document_heading)
        tools_layout.addWidget(self.document_contents)
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.document_search = QLineEdit(self.document_tools)
        self.document_search.setMinimumWidth(0)
        self.document_search.setPlaceholderText("Search guide")
        self.document_search.setAccessibleName("Search guide")
        self.document_search.setClearButtonEnabled(True)
        self.document_search.textChanged.connect(self._search_document)
        self.document_search.returnPressed.connect(lambda: self._step_document_match(1))
        search_layout.addWidget(self.document_search, 1)
        self.document_match_count = QLabel(self.document_tools)
        self.document_match_count.setFixedWidth(72)
        search_layout.addWidget(self.document_match_count)
        self.document_previous = QToolButton(self.document_tools)
        self.document_next = QToolButton(self.document_tools)
        for button, icon, label, step in (
            (self.document_previous, QStyle.StandardPixmap.SP_ArrowBack, "Previous match", -1),
            (self.document_next, QStyle.StandardPixmap.SP_ArrowForward, "Next match", 1),
        ):
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, step=step: self._step_document_match(step))
            search_layout.addWidget(button)
        tools_layout.addLayout(search_layout)
        self._layout.addWidget(self.document_tools)
        self.document_browser = QTextBrowser(self)
        self.document_browser.setPalette(qt_palette("light")[1])
        self.document_browser.setOpenExternalLinks(False)
        self.document_browser.setOpenLinks(False)
        self.document_browser.setMinimumHeight(420)
        self.document_browser.setMaximumHeight(560)
        self.document_browser.setAccessibleName("Guide document")
        self.document_browser.anchorClicked.connect(self._open_document_anchor)
        self._markdown = ""
        self._document_matches: list[QTextCursor] = []
        self._document_match_index = -1
        self._layout.addWidget(self.document_browser)
        self.preview_button = QPushButton(self)
        self.preview_button.clicked.connect(self._toggle_section)
        self._layout.addWidget(self.preview_button)
        self._inputs_host = QWidget(self)
        self._inputs_layout = QVBoxLayout(self._inputs_host)
        self._inputs_layout.setContentsMargins(0, 0, 0, 0)
        self._inputs_layout.setSpacing(4)
        self._input_widgets: dict[str, tuple[QWidget, QLabel, QSpinBox]] = {}
        self._input_fields: dict[str, PanelNumberInput] = {}
        self._layout.addWidget(self._inputs_host)
        self._actions_host = QWidget(self)
        self._actions_layout = FlowLayout(self._actions_host, spacing=4)
        self._layout.addWidget(self._actions_host)
        self._action_widgets: dict[ActionIdentity, PanelActionWidget] = {}
        self._actions_width = -1
        self._theme_name = "light"
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_contents)

    def set_view(self, view: PanelSectionView) -> None:
        self.identity = view.identity
        self.setProperty("alert", view.section.alert)
        with QSignalBlocker(self.header_button):
            self.header_button.setChecked(view.open)
        arrow = "▾" if view.open else "▸"
        self.header_button.setText(f"{arrow} {view.section.title}")
        self.header_button.setAccessibleName(
            f"{view.section.title}; {'expanded' if view.open else 'collapsed'}"
        )
        self.header_button.setVisible(not bool(view.section.columns))
        self.header_button.setEnabled(view.section.collapsible)
        self.row_view.setAccessibleName(f"{view.section.title} rows")
        self.row_view.set_rows(view.rows)
        self.row_view.setVisible(bool(view.rows))
        _fit_row_view(self.row_view)
        wanted_columns = {column.key for column in view.section.columns}
        for key in tuple(self._column_widgets):
            if key not in wanted_columns:
                host, _, _ = self._column_widgets.pop(key)
                self._columns_layout.removeWidget(host)
                host.deleteLater()
        for column in view.section.columns:
            widgets = self._column_widgets.get(column.key)
            if widgets is None:
                host = QWidget(self.columns_host)
                host.setMinimumWidth(0)
                column_layout = QVBoxLayout(host)
                column_layout.setContentsMargins(0, 0, 0, 0)
                title = QLabel(host)
                title.setWordWrap(True)
                rows = PanelRowListView(parent=host)
                rows.content_height_changed.connect(self.schedule_fit_to_contents)
                column_layout.addWidget(title)
                column_layout.addWidget(rows)
                column_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                widgets = host, title, rows
                self._column_widgets[column.key] = widgets
            host, title, rows = widgets
            title.setText(column.title)
            title.setAccessibleName(column.title)
            rows.setAccessibleName(column.title)
            rows.set_rows(column.rows)
            rows.set_theme(self._theme_name)
            _fit_row_view(rows)
            self._columns_layout.removeWidget(host)
            self._columns_layout.addWidget(host, 1)
            host.show()
        self.columns_host.setVisible(view.open and bool(view.section.columns))
        if view.section.markdown != self._markdown:
            position = self.document_browser.verticalScrollBar().value()
            self._markdown = view.section.markdown
            self.document_browser.setMarkdown(self._markdown)
            headings = _assign_document_anchors(self.document_browser)
            with QSignalBlocker(self.document_contents):
                self.document_contents.clear()
                self.document_contents.addItem("Contents", "")
                for title, anchor in headings:
                    self.document_contents.addItem(title, anchor)
            self._search_document(self.document_search.text())
            self.document_browser.verticalScrollBar().setValue(position)
        self.document_tools.setVisible(view.open and bool(view.section.markdown))
        self.document_browser.setVisible(view.open and bool(view.section.markdown))
        show_preview = view.open and (view.hidden_count > 0 or view.expanded)
        self.preview_button.setVisible(show_preview)
        if show_preview:
            text = f"Show {view.hidden_count} more" if view.hidden_count else "Show less"
            self.preview_button.setText(text)
            self.preview_button.setAccessibleName(f"{text} in {view.section.title}")
        self._inputs_host.setVisible(view.open and bool(view.section.inputs))
        self._reconcile_inputs(view.section.inputs)
        self._actions_host.setVisible(view.open and bool(view.actions))
        self._reconcile_actions(view.actions)
        self._apply_section_palette(view.section.alert)
        self.fit_to_contents()

    def set_theme(self, preference: str) -> str:
        name, palette = qt_palette(preference)
        theme_changed = self._theme_name != name
        self._theme_name = name
        self.setPalette(palette)
        self.document_browser.setPalette(palette)
        if theme_changed and self._markdown:
            _assign_document_anchors(self.document_browser)
        for button in (self.document_previous, self.document_next):
            pixmap = button.icon().pixmap(16, 16)
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), palette.color(palette.ColorRole.ButtonText))
            painter.end()
            button.setIcon(QIcon(pixmap))
        self.row_view.set_theme(name)
        for _, _, rows in self._column_widgets.values():
            rows.set_theme(name)
        for widget in self._action_widgets.values():
            widget.set_theme(name)
        self._apply_section_palette(bool(self.property("alert")))
        self.schedule_fit_to_contents()
        return name

    def action_widget(self, identity: ActionIdentity) -> PanelActionWidget | None:
        return self._action_widgets.get(identity)

    def _open_document_anchor(self, url) -> None:
        if url.fragment() and not url.scheme():
            self.document_browser.scrollToAnchor(url.fragment())

    def _select_document_heading(self, index: int) -> None:
        anchor = self.document_contents.itemData(index)
        if anchor:
            self.document_browser.scrollToAnchor(anchor)

    def _search_document(self, text: str) -> None:
        self._document_matches = []
        self._document_match_index = -1
        if text:
            document = self.document_browser.document()
            cursor = document.find(text)
            while not cursor.isNull():
                self._document_matches.append(cursor)
                cursor = document.find(text, cursor.selectionEnd())
        found = bool(self._document_matches)
        self.document_previous.setEnabled(found)
        self.document_next.setEnabled(found)
        if found:
            self._step_document_match(1)
        else:
            cursor = self.document_browser.textCursor()
            cursor.clearSelection()
            self.document_browser.setTextCursor(cursor)
            self.document_match_count.setText("No matches" if text else "")

    def _step_document_match(self, step: int) -> None:
        if not self._document_matches:
            return
        self._document_match_index = (self._document_match_index + step) % len(self._document_matches)
        self.document_browser.setTextCursor(self._document_matches[self._document_match_index])
        self.document_browser.ensureCursorVisible()
        self.document_match_count.setText(f"{self._document_match_index + 1} of {len(self._document_matches)}")

    def _reconcile_inputs(self, inputs: tuple[PanelNumberInput, ...]) -> None:
        self._input_fields = {field.key or f"input-{index}": field for index, field in enumerate(inputs)}
        for key in tuple(self._input_widgets):
            if key not in self._input_fields:
                host, _, _ = self._input_widgets.pop(key)
                self._inputs_layout.removeWidget(host)
                host.deleteLater()
        for key, field in self._input_fields.items():
            widgets = self._input_widgets.get(key)
            if widgets is None:
                host = QWidget(self._inputs_host)
                layout = QHBoxLayout(host)
                layout.setContentsMargins(0, 0, 0, 0)
                label = QLabel(host)
                label.setWordWrap(True)
                spin = QSpinBox(host)
                spin.setFixedWidth(140)
                spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                spin.setKeyboardTracking(False)
                spin.setGroupSeparatorShown(True)
                label.setBuddy(spin)
                spin.valueChanged.connect(lambda value, key=key: self._change_input(key, value))
                layout.addWidget(label, 1)
                layout.addWidget(spin)
                widgets = host, label, spin
                self._input_widgets[key] = widgets
            host, label, spin = widgets
            label.setText(field.label)
            spin.setAccessibleName(field.label)
            spin.setObjectName(key)
            with QSignalBlocker(spin):
                if (spin.minimum(), spin.maximum()) != (field.minimum, field.maximum):
                    spin.setRange(field.minimum, field.maximum)
                if spin.singleStep() != field.step:
                    spin.setSingleStep(field.step)
                if not spin.hasFocus():
                    spin.setValue(field.value)
                spin.setEnabled(field.enabled and field.command is not None)
            self._inputs_layout.removeWidget(host)
            self._inputs_layout.addWidget(host)
            host.show()

    def _change_input(self, key: str, value: int) -> None:
        field = self._input_fields.get(key)
        if field is not None and field.enabled and field.command is not None:
            try:
                field.command(value)
            except Exception as error:
                self.input_failed.emit(f"{field.label}: {error}")

    def _reconcile_actions(self, actions: tuple[PanelActionView, ...]) -> None:
        wanted = {action.identity for action in actions}
        for identity in tuple(self._action_widgets):
            if identity in wanted:
                continue
            widget = self._action_widgets.pop(identity)
            self._actions_layout.removeWidget(widget)
            widget.hide()
            widget.setEnabled(False)
            widget.deleteLater()
        ordered = []
        for action in actions:
            widget = self._action_widgets.get(action.identity)
            if widget is None:
                widget = PanelActionWidget(
                    action.identity,
                    self._on_toggle_action,
                    self._on_filter_action,
                    self._actions_host,
                )
                self._action_widgets[action.identity] = widget
                widget.content_height_changed.connect(self.schedule_fit_to_contents)
            ordered.append(widget)
        if self._actions_layout.widgets() != ordered:
            for widget in ordered:
                self._actions_layout.removeWidget(widget)
                self._actions_layout.addWidget(widget)
        for widget, action in zip(ordered, actions):
            widget.set_view(action)
            widget.set_theme(self._theme_name)
            self._actions_layout.set_full_row(widget, action.expanded)
            widget.show()
        self.schedule_fit_to_contents()

    def _toggle_section(self) -> None:
        self._on_toggle_section(self.identity)

    def _toggle_open(self) -> None:
        if self._on_toggle_open is not None:
            self._on_toggle_open(self.identity)

    def schedule_fit_to_contents(self) -> None:
        if not self._fit_timer.isActive():
            self._fit_timer.start(0)

    def fit_to_contents(self) -> None:
        self._actions_width = self._available_actions_width()
        self._actions_host.setFixedHeight(self._actions_layout.heightForWidth(self._actions_width))
        self._actions_layout.activate()
        self._layout.activate()
        target = self._layout.sizeHint().height() + self.frameWidth() * 2
        self.setFixedHeight(target)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._action_widgets and self._available_actions_width() != self._actions_width:
            self.fit_to_contents()

    def _available_actions_width(self) -> int:
        margins = self._layout.contentsMargins()
        return max(0, self.contentsRect().width() - margins.left() - margins.right())

    def _apply_section_palette(self, alert: bool) -> None:
        colors = THEME_PALETTES[self._theme_name]
        palette = self.palette()
        section_background = (
            colors["alert_background"] if alert else colors["background"]
        )
        title_foreground = (
            colors["alert_foreground"] if alert else colors["accent"]
        )
        if alert:
            palette.setColor(
                palette.ColorRole.Window,
                QColor(colors["alert_background"]),
            )
            palette.setColor(
                palette.ColorRole.WindowText,
                QColor(colors["alert_foreground"]),
            )
        else:
            palette.setColor(palette.ColorRole.Window, QColor(colors["background"]))
            palette.setColor(palette.ColorRole.WindowText, QColor(colors["foreground"]))
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        self.header_button.setStyleSheet(
            "QPushButton#panelSectionHeader { text-align: left; border: 0;"
            " padding: 2px 0; font-weight: 600; background: transparent;"
            f" color: {title_foreground}; }}"
        )
        row_palette = self.row_view.palette()
        row_palette.setColor(row_palette.ColorRole.Base, QColor(section_background))
        row_palette.setColor(row_palette.ColorRole.Window, QColor(section_background))
        self.row_view.setPalette(row_palette)


class PanelDocumentView(QScrollArea):
    map_navigation_requested = Signal(str)
    action_failed = Signal(str)
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = PanelDocumentState()
        self.setWidgetResizable(True)
        self.setAccessibleName("Game information")
        self._content = QWidget(self)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.addStretch(1)
        self.setWidget(self._content)
        self._section_widgets: dict[SectionIdentity, PanelSectionWidget] = {}
        self._pending_scroll = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._apply_pending_scroll)
        self._theme_name = "light"

    def set_snapshot(
        self,
        snapshot: OverlaySnapshot,
        *,
        content_scope: str | None = None,
    ) -> PanelDocumentUpdate:
        previous_scope = self.state.content_scope
        update = self.state.set_snapshot(snapshot, content_scope=content_scope)
        scope_changed = bool(previous_scope) and previous_scope != self.state.content_scope
        self._apply_views(reset=scope_changed)
        return update

    def set_active_role(self, role: str) -> PanelDocumentUpdate:
        update = self.state.set_active_role(role)
        self._apply_views()
        return update

    def set_hide_caught(self, hide_caught: bool) -> PanelDocumentUpdate:
        update = self.state.set_hide_caught(hide_caught)
        self._apply_views()
        return update

    def section_widget(
        self, identity: SectionIdentity
    ) -> PanelSectionWidget | None:
        return self._section_widgets.get(identity)

    def set_theme(self, preference: str) -> str:
        name, palette = qt_palette(preference)
        self._theme_name = name
        apply_qt_theme(self, name)
        self._content.setPalette(palette)
        for widget in self._section_widgets.values():
            widget.set_theme(name)
        return name

    def _apply_views(self, *, reset: bool = False) -> None:
        scroll_position = 0 if reset else self.verticalScrollBar().value()
        if reset:
            self._clear_sections()
        wanted = {view.identity for view in self.state.section_views}
        for identity in tuple(self._section_widgets):
            if identity in wanted:
                continue
            widget = self._section_widgets.pop(identity)
            self._layout.removeWidget(widget)
            widget.deleteLater()
        for view in self.state.section_views:
            widget = self._section_widgets.get(view.identity)
            if widget is None:
                widget = PanelSectionWidget(
                    view.identity,
                    self._toggle_section,
                    self._toggle_action,
                    self._filter_action,
                    self._content,
                    on_toggle_open=self._toggle_section_open,
                )
                widget.input_failed.connect(self.action_failed.emit)
                self._section_widgets[view.identity] = widget
                # Start at the rail width so width-dependent heights are right before the first layout pass.
                margins = self._layout.contentsMargins()
                widget.resize(max(0, self._content.width() - margins.left() - margins.right()), widget.height())
            self._layout.removeWidget(widget)
            self._layout.insertWidget(
                self._layout.count() - 1,
                widget,
                0,
                Qt.AlignmentFlag.AlignTop,
            )
            widget.set_view(view)
            widget.set_theme(self._theme_name)
            widget.show()
        self._restore_scroll(scroll_position)

    def _clear_sections(self) -> None:
        for widget in self._section_widgets.values():
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._section_widgets.clear()

    def _restore_scroll(self, value: int) -> None:
        self._pending_scroll = value
        self.verticalScrollBar().setValue(value)
        self._scroll_timer.start(0)

    def _apply_pending_scroll(self) -> None:
        self.verticalScrollBar().setValue(self._pending_scroll)

    def _toggle_section(self, identity: SectionIdentity) -> None:
        self.state.toggle_section(identity)
        self._apply_views()

    def _toggle_section_open(self, identity: SectionIdentity) -> None:
        self.state.toggle_section_open(identity)
        self._apply_views()

    def _toggle_action(self, identity: ActionIdentity) -> None:
        action = next((action.action for section in self.state.section_views for action in section.actions
                       if action.identity == identity), None)
        if action is not None and action.map_layer_key:
            self.map_navigation_requested.emit(action.map_layer_key)
            return
        if action is not None and action.command is not None:
            try:
                action.command()
            except Exception as error:
                self.action_failed.emit(f"{action.label}: {error}")
            return
        if action is not None and action.document_anchor:
            section = self.section_widget(identity.section)
            if section is not None:
                section.document_browser.scrollToAnchor(action.document_anchor)
                self.ensureWidgetVisible(section.document_browser)
            return
        self.state.toggle_action(identity)
        self._apply_views()

    def _filter_action(self, identity: ActionIdentity, text: str) -> None:
        self.state.set_action_filter(identity, text)
        self._apply_views()


def _fit_row_view(view: PanelRowListView) -> None:
    view.fit_to_contents()


def _assign_document_anchors(browser: QTextBrowser) -> tuple[tuple[str, str], ...]:
    document = browser.document()
    block = document.begin()
    occurrences: dict[str, int] = {}
    headings: list[tuple[str, str]] = []
    while block.isValid():
        fragment_iterator = block.begin()
        while not fragment_iterator.atEnd():
            fragment = fragment_iterator.fragment()
            formatting = fragment.charFormat()
            if formatting.anchorHref():
                formatting.setForeground(browser.palette().color(browser.palette().ColorRole.Link))
                link_cursor = QTextCursor(document)
                link_cursor.setPosition(fragment.position())
                link_cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor)
                link_cursor.mergeCharFormat(formatting)
            fragment_iterator += 1
        if block.blockFormat().headingLevel():
            slug = re.sub(r"[^\w -]", "", block.text().casefold()).replace(" ", "-")
            occurrence = occurrences.get(slug, 0)
            occurrences[slug] = occurrence + 1
            anchor = f"{slug}-{occurrence}" if occurrence else slug
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            formatting = cursor.charFormat()
            formatting.setAnchor(True)
            formatting.setAnchorNames([anchor])
            cursor.mergeCharFormat(formatting)
            headings.append((block.text(), anchor))
        block = block.next()
    return tuple(headings)