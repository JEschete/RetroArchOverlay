from __future__ import annotations

from dataclasses import dataclass

from ..core.models import OverlaySnapshot, PanelSection


@dataclass(frozen=True, slots=True)
class AlertNotification:
    title: str
    detail: str = ""


def urgent_summary(snapshot: OverlaySnapshot) -> AlertNotification | None:
    candidates = sorted(
        (
            section
            for section in snapshot.sections
            if (section.alert or section.role == "urgent") and section.rows
        ),
        key=lambda section: (not section.alert, section.priority),
    )
    if not candidates:
        return None
    section = candidates[0]
    return AlertNotification(section.title, section.rows[0].text)


class AlertTracker:
    def __init__(self) -> None:
        self._seen: dict[str, set[tuple[str, int]]] = {}

    def observe(
        self,
        snapshot: OverlaySnapshot,
        content_scope: str,
    ) -> tuple[AlertNotification, ...]:
        alerts = _alert_sections(snapshot.sections)
        current = {identity for identity, _ in alerts}
        seen = self._seen.get(content_scope)
        if seen is None:
            self._seen[content_scope] = current
            return ()
        notifications = tuple(
            AlertNotification(
                section.title,
                section.rows[0].text if section.rows else "",
            )
            for identity, section in alerts
            if identity not in seen
        )
        seen.update(current)
        return notifications

    def clear(self) -> None:
        self._seen.clear()


def _alert_sections(
    sections: tuple[PanelSection, ...],
) -> tuple[tuple[tuple[str, int], PanelSection], ...]:
    occurrences: dict[str, int] = {}
    result = []
    for section in sections:
        if not section.alert:
            continue
        key = section.key or section.title
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        result.append(((key, occurrence), section))
    return tuple(result)