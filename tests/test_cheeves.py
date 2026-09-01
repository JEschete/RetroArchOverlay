import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from retroarch_overlay.app.cheeves import export_cheeves_by_hash
from retroarch_overlay.infrastructure.credentials import KeyringCredentialStore
from retroarch_overlay.infrastructure.ra_code_notes import (
    SavedCodeNotesRepository,
    parse_code_notes_html,
)
from retroarch_overlay.infrastructure.retroachievements import RetroAchievementsClient


GAME_HASH = "31446456df04356cb9f2145bada42ed2"


class JsonResponse(BytesIO):
    def __enter__(self) -> "JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeRAOpener:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: object, **_kwargs: object) -> JsonResponse:
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        endpoint = Path(parsed.path).name
        game_or_console_id = query.get("i", [""])[0]
        self.calls.append((endpoint, game_or_console_id))
        if endpoint == "API_GetGameList.php":
            document = [
                {
                    "ID": 24186,
                    "Title": "Pokemon Emerald [Subset - Professor Oak Challenge]",
                    "ConsoleID": 5,
                    "ConsoleName": "Game Boy Advance",
                    "Hashes": [GAME_HASH],
                }
            ]
        elif endpoint == "API_GetGameExtended.php" and game_or_console_id == "24186":
            document = {
                "ID": 24186,
                "Title": "Pokemon Emerald [Subset - Professor Oak Challenge]",
                "ConsoleID": 5,
                "ConsoleName": "Game Boy Advance",
                "ParentGameID": 668,
                "Achievements": {
                    "57265": {
                        "ID": 57265,
                        "Title": "One Tile Away from Beauty",
                        "Description": "Fish on a Feebas tile.",
                        "Points": 5,
                        "type": "missable",
                        "Author": "SubsetDev",
                        "DisplayOrder": 1,
                        "MemAddr": "logic-hash-only",
                    }
                },
            }
        elif endpoint == "API_GetGameExtended.php" and game_or_console_id == "668":
            document = {
                "ID": 668,
                "Title": "Pokemon Emerald",
                "ConsoleID": 5,
                "ConsoleName": "Game Boy Advance",
                "ParentGameID": None,
                "Achievements": {
                    "27592": {
                        "ID": 27592,
                        "Title": "Let's Have a Quick Battle!",
                        "Description": "Defeat the rival.",
                        "Points": 2,
                        "type": "progression",
                        "Author": "CoreDev",
                        "DisplayOrder": 0,
                    }
                },
            }
        else:
            raise AssertionError(f"Unexpected RA request: {endpoint}, {game_or_console_id}")
        return JsonResponse(json.dumps(document).encode("utf-8"))


class FakeKeyringBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, secret: str) -> None:
        self.values[(service, account)] = secret

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class CredentialBoundaryTests(unittest.TestCase):
    def test_keyring_store_is_shared_and_injectable(self) -> None:
        backend = FakeKeyringBackend()
        store = KeyringCredentialStore(backend=backend)

        store.set("PlayerOne", "secret")
        self.assertEqual(store.get("PlayerOne"), "secret")
        store.delete("PlayerOne")
        self.assertEqual(store.get("PlayerOne"), "")


class CodeNotesPageTests(unittest.TestCase):
    def test_parses_base_subset_notes_and_related_page_links(self) -> None:
        page = parse_code_notes_html(
            """
            <a href="codenotes.php?g=24186">Professor Oak subset</a>
            <table><tr class="note-row" id="row-0">
              <td data-address="0x1234" data-current-author="CoreDev">0x1234</td>
              <td><span class="note-display">Player level<br>one byte</span>
              <span class="subset-note-display">Subset counter</span></td>
            </tr></table>
            """,
            668,
        )

        self.assertEqual(page.related_game_ids, (24186,))
        self.assertEqual(len(page.notes), 2)
        self.assertEqual(page.notes[0].address, "0x001234")
        self.assertEqual(page.notes[0].note, "Player level\none byte")
        self.assertEqual(page.notes[0].author, "CoreDev")
        self.assertEqual(page.notes[1].scope, "subset")


class RetroAchievementsResearchTests(unittest.TestCase):
    def test_hash_lookup_uses_public_game_catalog_and_cache(self) -> None:
        opener = FakeRAOpener()
        with tempfile.TemporaryDirectory() as directory:
            client = RetroAchievementsClient(
                "PlayerOne",
                "api-key",
                opener=opener,
                cache_dir=Path(directory),
            )
            first = client.resolve_game_hash(GAME_HASH, console_id=5)
            second = client.resolve_game_hash(GAME_HASH, console_id=5)

        self.assertEqual(first.game_id, 24186)
        self.assertEqual(second, first)
        self.assertEqual(opener.calls, [("API_GetGameList.php", "5")])

    def test_uses_stale_game_cache_when_ra_is_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            cache_path = cache_dir / "game-668-extended.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "ID": 668,
                        "Title": "Pokemon Emerald",
                        "ConsoleID": 5,
                        "ConsoleName": "Game Boy Advance",
                        "ParentGameID": None,
                        "Achievements": {},
                    }
                ),
                encoding="utf-8",
            )
            old = time.time() - 30 * 24 * 60 * 60
            os.utime(cache_path, (old, old))

            def blocked(*_args: object, **_kwargs: object) -> object:
                raise OSError("site blocked")

            client = RetroAchievementsClient(
                "PlayerOne",
                "api-key",
                opener=blocked,
                cache_dir=cache_dir,
            )
            game = client.get_game_extended(668)

        self.assertEqual(game.game_id, 668)
        self.assertEqual(game.title, "Pokemon Emerald")

    def test_exports_parent_subset_achievements_and_saved_memory_notes(self) -> None:
        opener = FakeRAOpener()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes_dir = root / "notes"
            notes_dir.mkdir()
            (notes_dir / "codenotes_668.html").write_text(
                """
                <a href="codenotes.php?g=24186">Professor Oak subset</a>
                <tr class="note-row"><td data-address="0x20" data-current-author="CoreDev"></td>
                <td class="note-display">Map group and number</td></tr>
                """,
                encoding="utf-8",
            )
            (notes_dir / "codenotes_24186.html").write_text(
                """
                <tr class="note-row"><td data-address="0x30"></td>
                <td class="subset-note-display">POC caught count</td></tr>
                """,
                encoding="utf-8",
            )
            client = RetroAchievementsClient(
                "PlayerOne",
                "api-key",
                opener=opener,
                cache_dir=root / "cache",
            )

            result = export_cheeves_by_hash(
                client,
                GAME_HASH,
                root / "output",
                console_id=5,
                code_notes=SavedCodeNotesRepository(notes_dir),
            )
            markdown = result.path.read_text(encoding="utf-8")

        self.assertEqual(result.matched_game_id, 24186)
        self.assertEqual(result.included_game_ids, (668, 24186))
        self.assertEqual(
            result.path.name,
            "pokemon_emerald_subset_professor_oak_challenge_cheeves.md",
        )
        self.assertIn("Let's Have a Quick Battle!", markdown)
        self.assertIn("One Tile Away from Beauty", markdown)
        self.assertIn("Map group and number", markdown)
        self.assertIn("POC caught count", markdown)
        self.assertIn("codenotes.php?g=24186", markdown)


if __name__ == "__main__":
    unittest.main()