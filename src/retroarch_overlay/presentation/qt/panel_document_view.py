from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.models import OverlaySnapshot
from ..theme import THEME_PALETTES
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
        self._on_toggle = on_toggle
        self._on_filter = on_filter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle_button = QPushButton(self)
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
        with QSignalBlocker(self.toggle_button):
            self.toggle_button.setChecked(view.expanded)
        arrow = "▾" if view.expanded else "▸"
        self.toggle_button.setText(f"{arrow} {view.action.label}")
        self.toggle_button.setAccessibleName(
            f"{view.action.label}; {'expanded' if view.expanded else 'collapsed'}"
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
        self.preview_button = QPushButton(self)
        self.preview_button.clicked.connect(self._toggle_section)
        self._layout.addWidget(self.preview_button)
        self._actions_host = QWidget(self)
        self._actions_layout = QVBoxLayout(self._actions_host)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(4)
        self._layout.addWidget(self._actions_host)
        self._action_widgets: dict[ActionIdentity, PanelActionWidget] = {}
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
        self.row_view.setAccessibleName(f"{view.section.title} rows")
        self.row_view.set_rows(view.rows)
        self.row_view.setVisible(bool(view.rows))
        _fit_row_view(self.row_view)
        show_preview = view.open and (view.hidden_count > 0 or view.expanded)
        self.preview_button.setVisible(show_preview)
        if show_preview:
            text = f"Show {view.hidden_count} more" if view.hidden_count else "Show less"
            self.preview_button.setText(text)
            self.preview_button.setAccessibleName(f"{text} in {view.section.title}")
        self._actions_host.setVisible(view.open and bool(view.actions))
        self._reconcile_actions(view.actions)
        self._apply_section_palette(view.section.alert)
        self.fit_to_contents()

    def set_theme(self, preference: str) -> str:
        name, palette = qt_palette(preference)
        self._theme_name = name
        self.setPalette(palette)
        self.row_view.set_theme(name)
        for widget in self._action_widgets.values():
            widget.set_theme(name)
        self._apply_section_palette(bool(self.property("alert")))
        self.schedule_fit_to_contents()
        return name

    def action_widget(self, identity: ActionIdentity) -> PanelActionWidget | None:
        return self._action_widgets.get(identity)

    def _reconcile_actions(self, actions: tuple[PanelActionView, ...]) -> None:
        wanted = {action.identity for action in actions}
        for identity in tuple(self._action_widgets):
            if identity in wanted:
                continue
            widget = self._action_widgets.pop(identity)
            self._actions_layout.removeWidget(widget)
            widget.deleteLater()
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
            self._actions_layout.removeWidget(widget)
            self._actions_layout.addWidget(widget)
            widget.set_view(action)
            widget.set_theme(self._theme_name)
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
        self._actions_layout.activate()
        self._layout.activate()
        target = self._layout.sizeHint().height() + self.frameWidth() * 2
        self.setFixedHeight(target)

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
                self._section_widgets[view.identity] = widget
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
        self.state.toggle_action(identity)
        self._apply_views()

    def _filter_action(self, identity: ActionIdentity, text: str) -> None:
        self.state.set_action_filter(identity, text)
        self._apply_views()


def _fit_row_view(view: PanelRowListView) -> None:
    view.fit_to_contents()