from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...core.layout import sections_for_role
from ...core.models import OverlaySnapshot, PanelAction, PanelRow, PanelSection
from ...core.presentation import (
    filter_caught_sections,
    filter_detail_rows,
    preview_section_rows,
)
from .panel_model import panel_rows_structure


DETAIL_FILTER_THRESHOLD = 13


@dataclass(frozen=True, slots=True)
class SectionIdentity:
    content_scope: str
    key: str
    occurrence: int = 0


@dataclass(frozen=True, slots=True)
class ActionIdentity:
    section: SectionIdentity
    key: str
    occurrence: int = 0


@dataclass(frozen=True, slots=True)
class PanelActionView:
    identity: ActionIdentity
    action: PanelAction
    expanded: bool
    filter_text: str
    rows: tuple[PanelRow, ...]
    filterable: bool


@dataclass(frozen=True, slots=True)
class PanelSectionView:
    identity: SectionIdentity
    section: PanelSection
    expanded: bool
    rows: tuple[PanelRow, ...]
    hidden_count: int
    actions: tuple[PanelActionView, ...]
    # Closed sections render only their header and a one-row summary.
    open: bool = True


class PanelDocumentUpdate(str, Enum):
    UNCHANGED = "unchanged"
    VALUES = "values"
    STRUCTURE = "structure"
    CONTENT_SCOPE = "content-scope"


class PanelDocumentState:
    def __init__(self) -> None:
        self._snapshot: OverlaySnapshot | None = None
        self._content_scope = ""
        self._active_role = "all"
        self._hide_caught = False
        self._expanded_sections: set[SectionIdentity] = set()
        self._open_sections: dict[SectionIdentity, bool] = {}
        self._expanded_actions: set[ActionIdentity] = set()
        self._detail_filters: dict[ActionIdentity, str] = {}
        self._section_views: tuple[PanelSectionView, ...] = ()

    @property
    def content_scope(self) -> str:
        return self._content_scope

    @property
    def active_role(self) -> str:
        return self._active_role

    @property
    def hide_caught(self) -> bool:
        return self._hide_caught

    @property
    def section_views(self) -> tuple[PanelSectionView, ...]:
        return self._section_views

    def set_snapshot(
        self,
        snapshot: OverlaySnapshot,
        *,
        content_scope: str | None = None,
    ) -> PanelDocumentUpdate:
        resolved_scope = (content_scope or snapshot.game).strip() or snapshot.game
        previous_scope = self._content_scope
        scope_changed = bool(previous_scope) and resolved_scope != previous_scope
        if resolved_scope != previous_scope:
            self._expanded_sections.clear()
            self._open_sections.clear()
            self._expanded_actions.clear()
            self._detail_filters.clear()
        # Interaction state is keyed by stable section/action identity and is
        # kept while a section is absent, so battles and map changes that hide
        # sections do not reset what the player opened.
        self._snapshot = snapshot
        self._content_scope = resolved_scope
        update = self._refresh()
        return PanelDocumentUpdate.CONTENT_SCOPE if scope_changed else update

    def set_active_role(self, role: str) -> PanelDocumentUpdate:
        role = role.strip().casefold() or "all"
        if role == self._active_role:
            return PanelDocumentUpdate.UNCHANGED
        self._active_role = role
        return self._refresh()

    def set_hide_caught(self, hide_caught: bool) -> PanelDocumentUpdate:
        hide_caught = bool(hide_caught)
        if hide_caught == self._hide_caught:
            return PanelDocumentUpdate.UNCHANGED
        self._hide_caught = hide_caught
        return self._refresh()

    def toggle_section(self, identity: SectionIdentity) -> PanelDocumentUpdate:
        if identity not in {view.identity for view in self._section_views}:
            return PanelDocumentUpdate.UNCHANGED
        if identity in self._expanded_sections:
            self._expanded_sections.remove(identity)
        else:
            self._expanded_sections.add(identity)
        return self._refresh()

    def toggle_section_open(self, identity: SectionIdentity) -> PanelDocumentUpdate:
        view = next(
            (view for view in self._section_views if view.identity == identity),
            None,
        )
        if view is None:
            return PanelDocumentUpdate.UNCHANGED
        self._open_sections[identity] = not view.open
        return self._refresh()

    def toggle_action(self, identity: ActionIdentity) -> PanelDocumentUpdate:
        if identity not in {
            action.identity
            for section in self._section_views
            for action in section.actions
        }:
            return PanelDocumentUpdate.UNCHANGED
        if identity in self._expanded_actions:
            self._expanded_actions.remove(identity)
        else:
            self._expanded_actions.add(identity)
        return self._refresh()

    def set_action_filter(
        self, identity: ActionIdentity, filter_text: str
    ) -> PanelDocumentUpdate:
        valid_actions = {
            action.identity
            for section in self._section_views
            for action in section.actions
        }
        if identity not in valid_actions:
            return PanelDocumentUpdate.UNCHANGED
        if self._detail_filters.get(identity, "") == filter_text:
            return PanelDocumentUpdate.UNCHANGED
        if filter_text:
            self._detail_filters[identity] = filter_text
        else:
            self._detail_filters.pop(identity, None)
        return self._refresh()

    def _refresh(self) -> PanelDocumentUpdate:
        previous = self._section_views
        current = self._build_views()
        self._section_views = current
        if current == previous:
            return PanelDocumentUpdate.UNCHANGED
        if _document_structure(current) != _document_structure(previous):
            return PanelDocumentUpdate.STRUCTURE
        return PanelDocumentUpdate.VALUES

    def _build_views(self) -> tuple[PanelSectionView, ...]:
        snapshot = self._snapshot
        if snapshot is None:
            return ()
        entries = _section_entries(snapshot, self._content_scope)
        accepted = {
            id(section)
            for section in sections_for_role(snapshot.sections, self._active_role)
        }
        views = []
        hide_caught = self._hide_caught and snapshot.supports_caught_filter
        for identity, original in entries:
            if id(original) not in accepted:
                continue
            filtered = filter_caught_sections((original,), hide_caught)
            if not filtered:
                continue
            section = filtered[0]
            expanded = identity in self._expanded_sections
            is_open = self._open_sections.get(identity, _opens_by_default(section))
            if is_open:
                rows, hidden_count = preview_section_rows(section, expanded)
            else:
                rows, hidden_count = section.compact_rows or section.rows[:1], 0
            actions = tuple(
                self._action_view(action_identity, action, hide_caught)
                for action_identity, action in _action_entries(original, identity)
            )
            views.append(
                PanelSectionView(
                    identity,
                    section,
                    expanded,
                    rows,
                    hidden_count,
                    actions,
                    is_open,
                )
            )
        views.sort(key=lambda view: (not view.section.alert, view.section.priority))
        return tuple(views)

    def _action_view(
        self,
        identity: ActionIdentity,
        action: PanelAction,
        hide_caught: bool,
    ) -> PanelActionView:
        rows = action.rows
        if hide_caught:
            rows = tuple(row for row in rows if row.caught is not True)
        filter_text = self._detail_filters.get(identity, "")
        return PanelActionView(
            identity,
            action,
            identity in self._expanded_actions,
            filter_text,
            filter_detail_rows(rows, filter_text),
            len(rows) > DETAIL_FILTER_THRESHOLD or bool(filter_text),
        )


def _opens_by_default(section: PanelSection) -> bool:
    return section.alert or section.role == "urgent"


def _section_entries(
    snapshot: OverlaySnapshot, content_scope: str
) -> tuple[tuple[SectionIdentity, PanelSection], ...]:
    occurrences: dict[str, int] = {}
    entries = []
    for section in snapshot.sections:
        key = section.key.strip() or section.title
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        entries.append((SectionIdentity(content_scope, key, occurrence), section))
    return tuple(entries)


def _action_entries(
    section: PanelSection, section_identity: SectionIdentity
) -> tuple[tuple[ActionIdentity, PanelAction], ...]:
    occurrences: dict[str, int] = {}
    entries = []
    for action in section.actions:
        key = action.key.strip() or action.label
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        entries.append((ActionIdentity(section_identity, key, occurrence), action))
    return tuple(entries)


def _document_structure(
    sections: tuple[PanelSectionView, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            section.identity,
            section.section.alert,
            section.open,
            section.expanded,
            panel_rows_structure(section.rows),
            section.hidden_count > 0,
            tuple(
                (
                    action.identity,
                    action.expanded,
                    action.filterable,
                    panel_rows_structure(action.rows) if action.expanded else (),
                )
                for action in section.actions
            ),
        )
        for section in sections
    )