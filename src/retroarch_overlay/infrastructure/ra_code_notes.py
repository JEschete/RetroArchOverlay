import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..core.retroachievements import RACodeNotesPage, RAMemoryNote


CODE_NOTES_PAGE_URL = "https://retroachievements.org/codenotes.php?g={game_id}"


class _CodeNotesHTMLParser(HTMLParser):
    def __init__(self, game_id: int) -> None:
        super().__init__(convert_charrefs=True)
        self.game_id = game_id
        self.notes: list[RAMemoryNote] = []
        self.related_game_ids: set[int] = set()
        self._row: dict[str, str] | None = None
        self._capture_scope: str | None = None
        self._capture_depth = 0
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {name: value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "a":
            self._capture_related_game_id(attributes.get("href", ""))
        if tag == "tr" and "note-row" in classes:
            self._row = {"address": "", "author": "", "set": "", "subset": ""}
            return
        if self._row is None:
            return
        if attributes.get("data-address"):
            self._row["address"] = attributes["data-address"]
        if attributes.get("data-current-author"):
            self._row["author"] = attributes["data-current-author"]
        if self._capture_scope is not None:
            if tag == "br":
                self._text.append("\n")
            else:
                self._capture_depth += 1
            return
        if "subset-note-display" in classes:
            self._begin_capture("subset")
        elif "note-display" in classes:
            self._begin_capture("set")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._capture_scope is not None and tag == "br":
            self._text.append("\n")
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_scope is not None:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                assert self._row is not None
                self._row[self._capture_scope] = _normalize_note_text("".join(self._text))
                self._capture_scope = None
                self._text = []
            return
        if tag == "tr" and self._row is not None:
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._capture_scope is not None:
            self._text.append(data)

    def _begin_capture(self, scope: str) -> None:
        self._capture_scope = scope
        self._capture_depth = 1
        self._text = []

    def _capture_related_game_id(self, href: str) -> None:
        parsed = urlparse(href)
        if not parsed.path.endswith("codenotes.php"):
            return
        values = parse_qs(parsed.query).get("g", ())
        for value in values:
            if value.isdigit() and int(value) != self.game_id:
                self.related_game_ids.add(int(value))

    def _finish_row(self) -> None:
        assert self._row is not None
        address = _normalize_address(self._row["address"])
        if address:
            for scope in ("set", "subset"):
                note = self._row[scope]
                if note:
                    self.notes.append(
                        RAMemoryNote(
                            self.game_id,
                            address,
                            note,
                            self._row["author"] if scope == "set" else "",
                            scope,
                        )
                    )
        self._row = None


def parse_code_notes_html(html: str, game_id: int) -> RACodeNotesPage:
    if game_id <= 0:
        raise ValueError("Game ID must be positive")
    parser = _CodeNotesHTMLParser(game_id)
    parser.feed(html)
    parser.close()
    notes = tuple(sorted(parser.notes, key=lambda note: (int(note.address, 16), note.scope)))
    return RACodeNotesPage(game_id, notes, tuple(sorted(parser.related_game_ids)))


class SavedCodeNotesRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self, game_id: int) -> RACodeNotesPage | None:
        for path in self._candidate_paths(game_id):
            if path.is_file():
                return parse_code_notes_html(
                    path.read_text(encoding="utf-8", errors="replace"),
                    game_id,
                )
        return None

    def _candidate_paths(self, game_id: int) -> tuple[Path, ...]:
        return (
            self.directory / f"codenotes_{game_id}.html",
            self.directory / f"{game_id}_codenotes.html",
            self.directory / f"{game_id}.html",
        )


def code_notes_page_url(game_id: int) -> str:
    if game_id <= 0:
        raise ValueError("Game ID must be positive")
    return CODE_NOTES_PAGE_URL.format(game_id=game_id)


def _normalize_address(value: str) -> str:
    match = re.search(r"(?:0x)?([0-9a-fA-F]+)", value.strip())
    return f"0x{int(match.group(1), 16):06X}" if match else ""


def _normalize_note_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(line for line in lines if line)