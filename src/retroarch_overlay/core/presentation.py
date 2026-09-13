from dataclasses import replace

from .models import PanelRow, PanelSection


def filter_detail_rows(
    rows: tuple[PanelRow, ...], needle: str
) -> tuple[PanelRow, ...]:
    needle = needle.strip().casefold()
    if not needle:
        return rows
    return tuple(row for row in rows if needle in row.text.casefold())


def filter_caught_sections(
    sections: tuple[PanelSection, ...], hide_caught: bool
) -> tuple[PanelSection, ...]:
    if not hide_caught:
        return sections
    return tuple(
        replace(
            section,
            rows=tuple(row for row in section.rows if row.caught is not True),
            compact_rows=tuple(
                row for row in section.compact_rows if row.caught is not True
            ),
        )
        for section in sections
        if any(row.caught is not True for row in section.rows)
    )


def preview_section_rows(
    section: PanelSection, expanded: bool
) -> tuple[tuple[PanelRow, ...], int]:
    if expanded or section.preview_limit is None:
        return section.rows, 0
    visible = section.rows[: section.preview_limit]
    return visible, len(section.rows) - len(visible)


def compact_secondary_sections(
    sections: tuple[PanelSection, ...],
) -> tuple[PanelSection, ...]:
    projected = (
        replace(
            section,
            rows=section.compact_rows or section.rows[:1],
            preview_limit=None,
            actions=(),
        )
        for section in sections
        if section.role in {"urgent", "party", "goals"}
    )
    return tuple(
        sorted(projected, key=lambda section: (not section.alert, section.priority))
    )