import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .core.contracts import PluginRepositoryManifest
from .core.errors import RetroAchievementsError
from .core.retroachievements import RACodeNotesPage, RAGameReference
from .infrastructure.ra_code_notes import code_notes_page_url, parse_code_notes_html
from .infrastructure.retroachievements import RAGameTitleMatch, RetroAchievementsClient
from .plugin_tools import update_plugin
from .retroarch_installation import supported_cores_for_console


CODE_NOTES_PATH = Path("game/data/retroachievements/code_notes.json")
CODE_NOTES_MARKDOWN_PATH = Path("game/data/retroachievements/code_notes.md")


@dataclass(frozen=True, slots=True)
class RAPluginDiscoveryResult:
    game: RAGameReference
    hashes: tuple[str, ...]
    cores: tuple[str, ...]


class RAGameSelectionRequired(RetroAchievementsError):
    def __init__(self, title: str, matches: tuple[RAGameTitleMatch, ...]) -> None:
        super().__init__(f"Select the RetroAchievements game for {title!r}")
        self.title = title
        self.matches = matches


def discover_plugin_ra_metadata(
    client: RetroAchievementsClient,
    repository: Path,
    manifest: PluginRepositoryManifest,
    *,
    console_id: int | None = None,
    selected_game_id: int | None = None,
    additional_hashes: tuple[str, ...] = (),
    retroarch_root: Path | None = None,
) -> RAPluginDiscoveryResult:
    references: list[RAGameReference] = []
    discovered_set_ids: set[int] = set()
    candidate_hashes = manifest.content_hashes | frozenset(additional_hashes)
    for game_hash in sorted(candidate_hashes):
        try:
            references.append(client.resolve_game_hash(game_hash, console_id=console_id))
        except (RetroAchievementsError, ValueError):
            continue
    resolved_ids = {_primary_game_id(client, reference.game_id) for reference in references}
    if len(resolved_ids) > 1:
        choices = ", ".join(str(game_id) for game_id in sorted(resolved_ids))
        raise RetroAchievementsError(f"Plugin hashes resolve to conflicting RA game IDs: {choices}")
    known_game_id = selected_game_id or manifest.ra_game_id or _code_notes_game_id(repository)
    if known_game_id is not None:
        game = client.get_game_extended(known_game_id)
        discovered_set_ids.add(game.game_id)
        configured_id = game.parent_game_id or game.game_id
        if resolved_ids and configured_id not in resolved_ids:
            raise RetroAchievementsError(
                f"Configured RA game ID {configured_id} conflicts with plugin hashes"
            )
        reference = RAGameReference(game.game_id, game.title, game.console_id, game.console_name)
    elif references:
        reference = references[0]
    else:
        title_matches = client.find_game_titles(manifest.display_name, console_id=console_id)
        exact_matches = [match.game for match in title_matches if match.exact]
        if len(exact_matches) == 1:
            reference = exact_matches[0]
        elif title_matches:
            raise RAGameSelectionRequired(manifest.display_name, title_matches)
        else:
            raise RetroAchievementsError(
                f"No RetroAchievements game matched title {manifest.display_name!r}"
            )
    details = client.get_game_extended(reference.game_id)
    discovered_set_ids.update(item.game_id for item in references)
    discovered_set_ids.add(details.game_id)
    if details.parent_game_id is not None:
        parent = client.get_game_extended(details.parent_game_id)
        reference = RAGameReference(parent.game_id, parent.title, parent.console_id, parent.console_name)
    else:
        reference = RAGameReference(details.game_id, details.title, details.console_id, details.console_name)
    discovered_set_ids.add(reference.game_id)
    hashes = tuple(
        sorted(
            frozenset(
                game_hash
                for game_id in sorted(discovered_set_ids)
                for game_hash in client.get_game_hashes(game_id)
            )
        )
    )
    if not hashes:
        raise RetroAchievementsError(
            f"RetroAchievements returned no supported hashes for game {reference.game_id}"
        )
    cores = supported_cores_for_console(reference.console_name, retroarch_root)
    update_plugin(
        repository,
        ra_game_id=reference.game_id,
        update_ra_game_id=True,
        content_hashes=hashes,
        cores=cores,
    )
    ensure_code_notes_file(repository, reference.game_id)
    return RAPluginDiscoveryResult(reference, hashes, cores)


def ensure_code_notes_file(repository: Path, game_id: int | None = None) -> Path:
    path = repository.resolve() / CODE_NOTES_PATH
    if path.is_file():
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("pages"), list):
            raise ValueError(f"Invalid code-note document: {path}")
        if game_id is not None:
            document["expected_game_id"] = game_id
            document["source_url"] = code_notes_page_url(game_id)
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path
    document = {
        "schema_version": 1,
        "source": "RetroAchievements authenticated code-notes page",
        "pages": [],
    }
    if game_id is not None:
        document["expected_game_id"] = game_id
        document["source_url"] = code_notes_page_url(game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def import_code_notes_pages(
    repository: Path,
    saved_pages: tuple[Path, ...],
    *,
    default_game_id: int | None = None,
    imported_at: datetime | None = None,
) -> Path:
    target = ensure_code_notes_file(repository, default_game_id)
    document = json.loads(target.read_text(encoding="utf-8"))
    pages = {
        int(page["game_id"]): page
        for page in document.get("pages", [])
        if isinstance(page, dict) and isinstance(page.get("game_id"), int)
    }
    for saved_page in saved_pages:
        game_id = _game_id_from_filename(saved_page) or default_game_id
        if game_id is None:
            raise ValueError(f"Could not determine game ID from {saved_page.name}")
        parsed = parse_code_notes_html(
            saved_page.read_text(encoding="utf-8", errors="replace"),
            game_id,
        )
        pages[game_id] = _serialize_page(parsed)
    timestamp = imported_at or datetime.now(UTC)
    document["imported_at"] = timestamp.astimezone(UTC).isoformat()
    document["pages"] = [pages[game_id] for game_id in sorted(pages)]
    target.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    markdown_path = repository.resolve() / CODE_NOTES_MARKDOWN_PATH
    markdown_path.write_text(render_code_notes_markdown(document), encoding="utf-8")
    return target


def render_code_notes_markdown(document: dict[str, object]) -> str:
    lines = [
        "# RetroAchievements Code Notes",
        "",
        "Imported from authenticated RetroAchievements code-notes pages.",
    ]
    imported_at = document.get("imported_at")
    if imported_at:
        lines.extend(("", f"Imported: {imported_at}"))
    pages = document.get("pages", [])
    if not isinstance(pages, list) or not pages:
        lines.extend(("", "No code-note pages have been imported.", ""))
        return "\n".join(lines)
    for page in pages:
        if not isinstance(page, dict):
            continue
        game_id = page.get("game_id", "Unknown")
        source_url = page.get("source_url", "")
        lines.extend(("", f"## RA Game {game_id}", ""))
        if source_url:
            lines.extend((f"Source: {source_url}", ""))
        related = page.get("related_game_ids", [])
        if isinstance(related, list) and related:
            lines.extend((f"Related game IDs: {', '.join(str(value) for value in related)}", ""))
        notes = page.get("notes", [])
        if not isinstance(notes, list) or not notes:
            lines.append("No visible code notes were found on this page.")
            continue
        lines.extend(
            (
                "| Address | Scope | Author | Note |",
                "| --- | --- | --- | --- |",
            )
        )
        for note in notes:
            if not isinstance(note, dict):
                continue
            lines.append(
                f"| `{_markdown_cell(note.get('address', ''))}` "
                f"| {_markdown_cell(note.get('scope', ''))} "
                f"| {_markdown_cell(note.get('author', ''))} "
                f"| {_markdown_cell(note.get('note', ''))} |"
            )
    lines.append("")
    return "\n".join(lines)


def _serialize_page(page: RACodeNotesPage) -> dict[str, object]:
    return {
        "game_id": page.game_id,
        "source_url": code_notes_page_url(page.game_id),
        "related_game_ids": list(page.related_game_ids),
        "notes": [
            {
                "address": note.address,
                "scope": note.scope,
                "author": note.author,
                "note": note.note,
            }
            for note in page.notes
        ],
    }


def _game_id_from_filename(path: Path) -> int | None:
    values = [int(value) for value in re.findall(r"\d+", path.stem)]
    return values[-1] if values else None


def _primary_game_id(client: RetroAchievementsClient, game_id: int) -> int:
    details = client.get_game_extended(game_id)
    return details.parent_game_id or details.game_id


def _code_notes_game_id(repository: Path) -> int | None:
    path = repository.resolve() / CODE_NOTES_PATH
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    game_id = document.get("expected_game_id") if isinstance(document, dict) else None
    return game_id if isinstance(game_id, int) and game_id > 0 else None


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")