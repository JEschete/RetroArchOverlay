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
            self._expanded_actions.clear()
            self._detail_filters.clear()
        self._snapshot = snapshot
        self._content_scope = resolved_scope
        self._prune_transient_state()
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
            rows, hidden_count = preview_section_rows(section, expanded)
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

    def _prune_transient_state(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        sections = _section_entries(snapshot, self._content_scope)
        valid_sections = {identity for identity, _ in sections}
        valid_actions = {
            action_identity
            for section_identity, section in sections
            for action_identity, _ in _action_entries(section, section_identity)
        }
        self._expanded_sections.intersection_update(valid_sections)
        self._expanded_actions.intersection_update(valid_actions)
        self._detail_filters = {
            identity: value
            for identity, value in self._detail_filters.items()
            if identity in valid_actions
        }


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