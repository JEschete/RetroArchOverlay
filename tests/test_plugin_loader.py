import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from retroarch_overlay.core.contracts import GameContext
from retroarch_overlay.core.errors import GameUnavailableError
from retroarch_overlay.core.models import RetroArchStatus
from retroarch_overlay.infrastructure.plugin_discovery import (
    discover_plugin_repositories,
)
from retroarch_overlay.infrastructure.plugin_loader import RepositoryAdapter


def write_repository(
    root: Path,
    *,
    required_source: bool = False,
    source_revision: str = "",
) -> Path:
    repository = root / "plugin"
    (repository / "game").mkdir(parents=True)
    source = '''
[[sources]]
id = "data"
kind = "git-submodule"
path = "decomp_reference/data"
required = true
required_files = ["required.txt"]
revision = "{source_revision}"
''' if required_source else ""
    (repository / "plugin.toml").write_text(
        f'''schema_version = 1
plugin_id = "org.example.lazy"
slug = "lazy"
name = "Lazy Plugin"
api_version = 1
entry = "plugin.py"

[match]
cores = ["test_core"]
content_hints = ["lazy game"]
hashes = ["accepted"]
{source}
''',
        encoding="utf-8",
    )
    (repository / "plugin.py").write_text(
        "from .game.adapter import Adapter\n"
        "class Plugin:\n"
        "    def create(self, context):\n"
        "        return Adapter(context.repository_root)\n"
        "PLUGIN = Plugin()\n",
        encoding="utf-8",
    )
    (repository / "game" / "adapter.py").write_text(
        "class Adapter:\n"
        "    def __init__(self, root): self.root = root\n"
        "    def snapshot(self, memory): return ('snapshot', self.root)\n",
        encoding="utf-8",
    )
    return repository


class RepositoryAdapterTests(unittest.TestCase):
    def test_matches_manifest_without_importing_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = write_repository(root)
            repository = discover_plugin_repositories((root,)).repositories[0]
            adapter = RepositoryAdapter(
                repository, GameContext(repository_root=repository_root)
            )
            modules_before = frozenset(sys.modules)

            supported = adapter.supports(
                RetroArchStatus("PLAYING", "test_core", "Lazy Game")
            )

            self.assertTrue(supported)
            self.assertEqual(frozenset(sys.modules), modules_before)

    def test_loads_relative_import_once_and_caches_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = write_repository(root)
            repository = discover_plugin_repositories((root,)).repositories[0]
            adapter = RepositoryAdapter(
                repository,
                GameContext(
                    repository_root=repository_root / ".." / repository_root.name
                ),
            )

            first = adapter._load_adapter()
            second = adapter._load_adapter()

            self.assertIs(first, second)
            self.assertEqual(first.root, repository_root.resolve())

    def test_missing_required_source_fails_before_plugin_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = write_repository(root, required_source=True)
            repository = discover_plugin_repositories((root,)).repositories[0]
            adapter = RepositoryAdapter(
                repository, GameContext(repository_root=repository_root)
            )

            with self.assertRaisesRegex(GameUnavailableError, "submodule update"):
                adapter._load_adapter()

    def test_older_required_source_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = write_repository(
                root,
                required_source=True,
                source_revision="a" * 40,
            )
            source = repository_root / "decomp_reference" / "data"
            source.mkdir(parents=True)
            (source / "required.txt").write_text("data", encoding="utf-8")
            (source / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            repository = discover_plugin_repositories((root,)).repositories[0]
            adapter = RepositoryAdapter(
                repository, GameContext(repository_root=repository_root)
            )

            with (
                patch(
                    "retroarch_overlay.infrastructure.plugin_loader.subprocess.run",
                    side_effect=[
                        Mock(returncode=0, stdout="d" * 40 + "\n"),
                        Mock(returncode=1),
                    ],
                ),
                self.assertRaisesRegex(GameUnavailableError, "expected at least"),
            ):
                adapter._load_adapter()

    def test_newer_required_source_revision_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = write_repository(
                root,
                required_source=True,
                source_revision="a" * 40,
            )
            source = repository_root / "decomp_reference" / "data"
            source.mkdir(parents=True)
            (source / "required.txt").write_text("data", encoding="utf-8")
            (source / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
            repository = discover_plugin_repositories((root,)).repositories[0]
            adapter = RepositoryAdapter(
                repository, GameContext(repository_root=repository_root)
            )

            with patch(
                "retroarch_overlay.infrastructure.plugin_loader.subprocess.run",
                side_effect=[
                    Mock(returncode=0, stdout="c" * 40 + "\n"),
                    Mock(returncode=0),
                ],
            ) as run_mock:
                adapter._load_adapter()

            first_call = run_mock.call_args_list[0].args[0]
            self.assertIn("safe.directory=*", first_call)


if __name__ == "__main__":
    unittest.main()