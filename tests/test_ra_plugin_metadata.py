import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from retroarch_overlay.core.retroachievements import RAGame, RAGameReference
from retroarch_overlay.infrastructure.plugin_discovery import parse_plugin_manifest
from retroarch_overlay.infrastructure.retroachievements import RAGameTitleMatch
from retroarch_overlay.plugin_tools import PluginTemplateConfig, create_plugin
from retroarch_overlay.ra_plugin_metadata import (
    RAGameSelectionRequired,
    discover_plugin_ra_metadata,
    import_code_notes_pages,
)


class FakeRAClient:
    def __init__(self) -> None:
        self.title_queries: list[str] = []
        self.hash_game_ids: list[int] = []

    def resolve_game_hash(self, game_hash: str, *, console_id: int | None = None) -> RAGameReference:
        return RAGameReference(24186, "Example Subset", 5, "Game Boy Advance")

    def find_game_titles(
        self, title: str, *, console_id: int | None = None
    ) -> tuple[RAGameTitleMatch, ...]:
        self.title_queries.append(title)
        return (
            RAGameTitleMatch(
                RAGameReference(668, "Example Game", 5, "Game Boy Advance"),
                1.0,
                True,
            ),
        )

    def get_game_extended(self, game_id: int) -> RAGame:
        if game_id == 24186:
            return RAGame(24186, "Example Subset", 5, "Game Boy Advance", 668, ())
        return RAGame(668, "Example Game", 5, "Game Boy Advance", None, ())

    def get_game_hashes(self, game_id: int) -> tuple[str, ...]:
        self.hash_game_ids.append(game_id)
        if game_id == 24186:
            return ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
        return ("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",)


class ConflictingRAClient(FakeRAClient):
    def resolve_game_hash(self, game_hash: str, *, console_id: int | None = None) -> RAGameReference:
        game_id = 668 if game_hash.startswith("a") else 777
        return RAGameReference(game_id, f"Game {game_id}", 5, "Game Boy Advance")

    def get_game_extended(self, game_id: int) -> RAGame:
        return RAGame(game_id, f"Game {game_id}", 5, "Game Boy Advance", None, ())


class InexactRAClient(FakeRAClient):
    def find_game_titles(
        self, title: str, *, console_id: int | None = None
    ) -> tuple[RAGameTitleMatch, ...]:
        self.title_queries.append(title)
        return (
            RAGameTitleMatch(
                RAGameReference(668, "Example Quest", 5, "Game Boy Advance"),
                0.8,
                False,
            ),
            RAGameTitleMatch(
                RAGameReference(777, "Example Adventure", 5, "Game Boy Advance"),
                0.7,
                False,
            ),
        )


class RAPluginMetadataTests(unittest.TestCase):
    def _create_plugin(self, root: Path, *, hashes: tuple[str, ...] = ()) -> Path:
        return create_plugin(
            PluginTemplateConfig(
                game_name="Example Game",
                slug="example_game",
                output_root=root,
                copyright_holder="Example Author",
                content_hashes=hashes,
            )
        )

    def test_discovers_by_title_when_manifest_has_no_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(Path(directory))
            client = FakeRAClient()

            result = discover_plugin_ra_metadata(
                client, repository, parse_plugin_manifest(repository)
            )
            manifest = parse_plugin_manifest(repository)
            notes = json.loads(
                (repository / "game/data/retroachievements/code_notes.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(client.title_queries, ["Example Game"])
        self.assertEqual(result.game.game_id, 668)
        self.assertEqual(manifest.ra_game_id, 668)
        self.assertEqual(manifest.supported_cores, frozenset({"game_boy_advance", "gba"}))
        self.assertIn("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", manifest.content_hashes)
        self.assertEqual(notes["expected_game_id"], 668)
        self.assertIn("codenotes.php?g=668", notes["source_url"])

    def test_subset_hash_normalizes_to_parent_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(
                Path(directory), hashes=("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
            )
            client = FakeRAClient()

            result = discover_plugin_ra_metadata(
                client, repository, parse_plugin_manifest(repository)
            )
            hashes = parse_plugin_manifest(repository).content_hashes

        self.assertEqual(result.game.game_id, 668)
        self.assertEqual(client.hash_game_ids, [668, 24186])
        self.assertEqual(
            hashes,
            frozenset(
                {
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                }
            ),
        )

    def test_local_patched_rom_hash_discovers_subset_without_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(Path(directory))
            client = FakeRAClient()

            result = discover_plugin_ra_metadata(
                client,
                repository,
                parse_plugin_manifest(repository),
                additional_hashes=("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
            )
            hashes = parse_plugin_manifest(repository).content_hashes

        self.assertEqual(result.game.game_id, 668)
        self.assertEqual(
            hashes,
            frozenset(
                {
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                }
            ),
        )

    def test_populates_installed_core_from_ra_console(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._create_plugin(root)
            retroarch = root / "RetroArch"
            info = retroarch / "info"
            info.mkdir(parents=True)
            (info / "mgba_libretro.info").write_text(
                'display_name = "mGBA"\n'
                'systemname = "Nintendo - Game Boy Advance"\n',
                encoding="utf-8",
            )

            result = discover_plugin_ra_metadata(
                FakeRAClient(),
                repository,
                parse_plugin_manifest(repository),
                retroarch_root=retroarch,
            )
            cores = parse_plugin_manifest(repository).supported_cores

        self.assertIn("game_boy_advance", result.cores)
        self.assertIn("gba", cores)
        self.assertIn("mgba", cores)

    def test_inexact_title_requires_selection_then_populates_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(Path(directory))
            client = InexactRAClient()

            with self.assertRaises(RAGameSelectionRequired) as raised:
                discover_plugin_ra_metadata(
                    client, repository, parse_plugin_manifest(repository)
                )
            result = discover_plugin_ra_metadata(
                client,
                repository,
                parse_plugin_manifest(repository),
                selected_game_id=raised.exception.matches[0].game.game_id,
            )
            manifest = parse_plugin_manifest(repository)

        self.assertEqual(result.game.game_id, 668)
        self.assertEqual(manifest.ra_game_id, 668)
        self.assertEqual(
            manifest.content_hashes,
            frozenset({"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}),
        )

    def test_uses_code_note_game_id_before_title_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(Path(directory))
            notes_path = repository / "game/data/retroachievements/code_notes.json"
            notes = json.loads(notes_path.read_text(encoding="utf-8"))
            notes["expected_game_id"] = 668
            notes_path.write_text(json.dumps(notes), encoding="utf-8")
            client = FakeRAClient()

            result = discover_plugin_ra_metadata(
                client, repository, parse_plugin_manifest(repository)
            )

        self.assertEqual(result.game.game_id, 668)
        self.assertEqual(client.title_queries, [])

    def test_rejects_hashes_from_different_primary_games(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._create_plugin(
                Path(directory),
                hashes=(
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                ),
            )

            with self.assertRaisesRegex(RuntimeError, "conflicting RA game IDs"):
                discover_plugin_ra_metadata(
                    ConflictingRAClient(), repository, parse_plugin_manifest(repository)
                )

    def test_imports_saved_code_notes_into_plugin_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._create_plugin(root)
            saved = root / "codenotes_668.html"
            saved.write_text(
                '<tr class="note-row"><td data-address="0x20" '
                'data-current-author="CoreDev"></td>'
                '<td class="note-display">Map group and number</td></tr>',
                encoding="utf-8",
            )

            target = import_code_notes_pages(
                repository,
                (saved,),
                default_game_id=668,
                imported_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
            document = json.loads(target.read_text(encoding="utf-8"))
            markdown = target.with_suffix(".md").read_text(encoding="utf-8")

        self.assertEqual(document["pages"][0]["game_id"], 668)
        self.assertEqual(document["pages"][0]["notes"][0]["address"], "0x000020")
        self.assertEqual(document["pages"][0]["notes"][0]["author"], "CoreDev")
        self.assertIn("codenotes.php?g=668", document["pages"][0]["source_url"])
        self.assertIn("# RetroAchievements Code Notes", markdown)
        self.assertIn("## RA Game 668", markdown)
        self.assertIn("| `0x000020` | set | CoreDev | Map group and number |", markdown)


if __name__ == "__main__":
    unittest.main()