import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from ..core.retroachievements import RACodeNotesPage, RAGame
from ..infrastructure.ra_code_notes import SavedCodeNotesRepository, code_notes_page_url
from ..infrastructure.retroachievements import RetroAchievementsClient


@dataclass(frozen=True, slots=True)
class CheevesExportResult:
    path: Path
    matched_game_id: int
    included_game_ids: tuple[int, ...]


def export_cheeves_by_hash(
    client: RetroAchievementsClient,
    game_hash: str,
    output_dir: Path,
    *,
    console_id: int | None = None,
    related_game_ids: Iterable[int] = (),
    code_notes: SavedCodeNotesRepository | None = None,
    generated_at: datetime | None = None,
) -> CheevesExportResult:
    reference = client.resolve_game_hash(game_hash, console_id=console_id)
    matched = client.get_game_extended(reference.game_id)
    games: dict[int, RAGame] = {matched.game_id: matched}
    pages: dict[int, RACodeNotesPage] = {}

    pending = []
    if matched.parent_game_id is not None:
        pending.append(matched.parent_game_id)
    pending.append(matched.game_id)
    pending.extend(int(game_id) for game_id in related_game_ids)

    visited: set[int] = set()
    while pending:
        game_id = pending.pop(0)
        if game_id <= 0 or game_id in visited:
            continue
        visited.add(game_id)
        if game_id not in games:
            games[game_id] = client.get_game_extended(game_id)
        if code_notes is not None:
            page = code_notes.load(game_id)
            if page is not None:
                pages[game_id] = page
                pending.extend(page.related_game_ids)

    ordered_games = sorted(
        games.values(),
        key=lambda game: (
            game.parent_game_id is not None,
            game.game_id != matched.game_id and game.parent_game_id is None,
            game.game_id,
        ),
    )
    timestamp = generated_at or datetime.now(UTC)
    markdown = render_cheeves_markdown(
        game_hash.strip().casefold(),
        matched,
        ordered_games,
        pages,
        timestamp,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_filename_slug(matched.title)}_cheeves.md"
    output_path.write_text(markdown, encoding="utf-8")
    return CheevesExportResult(
        output_path,
        matched.game_id,
        tuple(game.game_id for game in ordered_games),
    )


def render_cheeves_markdown(
    game_hash: str,
    matched: RAGame,
    games: Iterable[RAGame],
    pages: dict[int, RACodeNotesPage],
    generated_at: datetime,
) -> str:
    ordered_games = tuple(games)
    lines = [
        f"# {matched.title} Achievements and Memory Notes",
        "",
        f"Generated: {generated_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Hash Resolution",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Game hash | `{_markdown_cell(game_hash)}` |",
        f"| Matched game ID | [{matched.game_id}](https://retroachievements.org/game/{matched.game_id}) |",
        f"| Matched title | {_markdown_cell(matched.title)} |",
        f"| Console | {_markdown_cell(matched.console_name)} (`{matched.console_id}`) |",
        "",
        "## Included Sets",
        "",
        "| Game ID | Kind | Title | Achievements |",
        "| ---: | --- | --- | ---: |",
    ]
    for game in ordered_games:
        kind = "Subset" if game.parent_game_id is not None else "Core set"
        lines.append(
            f"| [{game.game_id}](https://retroachievements.org/game/{game.game_id}) "
            f"| {kind} | {_markdown_cell(game.title)} | {len(game.achievements)} |"
        )

    for game in ordered_games:
        kind = "Subset" if game.parent_game_id is not None else "Core Set"
        lines.extend(
            (
                "",
                f"## {game.title} ({kind})",
                "",
                f"- Game page: https://retroachievements.org/game/{game.game_id}",
                f"- Code notes page: {code_notes_page_url(game.game_id)}",
                "",
                "### Achievements",
                "",
            )
        )
        if game.achievements:
            lines.extend(
                (
                    "| ID | Points | Type | Title | Description | Author |",
                    "| ---: | ---: | --- | --- | --- | --- |",
                )
            )
            for achievement in game.achievements:
                lines.append(
                    f"| {achievement.achievement_id} | {achievement.points} "
                    f"| {_markdown_cell(achievement.achievement_type)} "
                    f"| {_markdown_cell(achievement.title)} "
                    f"| {_markdown_cell(achievement.description)} "
                    f"| {_markdown_cell(achievement.author)} |"
                )
        else:
            lines.append("No published achievements were returned by the public Web API.")

        lines.extend(("", "### Memory Notes", ""))
        page = pages.get(game.game_id)
        if page is None:
            lines.extend(
                (
                    "Memory notes were not imported. RetroAchievements does not expose code notes through its public Web API.",
                    "",
                    f"To include them, save the authenticated code-notes page for game `{game.game_id}` as "
                    f"`codenotes_{game.game_id}.html`, then rerun with `--code-notes-dir`.",
                )
            )
        elif not page.notes:
            lines.append("The saved code-notes page contained no visible notes.")
        else:
            lines.extend(
                (
                    "| Address | Scope | Author | Note |",
                    "| --- | --- | --- | --- |",
                )
            )
            for note in page.notes:
                lines.append(
                    f"| `{note.address}` | {_markdown_cell(note.scope)} "
                    f"| {_markdown_cell(note.author)} | {_markdown_cell(note.note)} |"
                )

    lines.extend(
        (
            "",
            "## Data Boundary",
            "",
            "Achievement metadata and hash resolution use the authenticated public RetroAchievements Web API.",
            "Achievement trigger definitions are not requested or written. Memory notes are read only from user-saved authenticated game pages.",
            "",
        )
    )
    return "\n".join(lines)


def _filename_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.casefold()).strip("_")
    return slug or "game"


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")