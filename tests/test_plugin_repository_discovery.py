import tempfile
import unittest
from pathlib import Path

from retroarch_overlay.core.errors import PluginManifestError
from retroarch_overlay.infrastructure.plugin_discovery import (
    discover_plugin_repositories,
    parse_plugin_manifest,
)


def write_plugin(
    root: Path,
    name: str,
    *,
    plugin_id: str | None = None,
    slug: str | None = None,
    entry: str = "plugin.py",
    extra: str = "",
) -> Path:
    repository = root / name
    repository.mkdir(parents=True)
    resolved_slug = slug or name.casefold().replace("-", "_")
    resolved_id = plugin_id or f"org.example.{resolved_slug}"
    (repository / "plugin.toml").write_text(
        f'''schema_version = 1
plugin_id = "{resolved_id}"
slug = "{resolved_slug}"
name = "{name}"
api_version = 1
entry = "{entry}"

[match]
cores = ["test_core"]
content_hints = ["{resolved_slug}"]
hashes = ["ABCDEF"]
{extra}
''',
        encoding="utf-8",
    )
    entry_path = repository / entry
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text("raise AssertionError('discovery imported plugin Python')\n", encoding="utf-8")
    return repository


class PluginManifestTests(unittest.TestCase):
    def test_parses_manifest_without_importing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = write_plugin(Path(directory), "alpha")

            manifest = parse_plugin_manifest(repository)

        self.assertEqual(manifest.plugin_id, "org.example.alpha")
        self.assertEqual(manifest.content_hashes, frozenset({"abcdef"}))
        self.assertEqual(manifest.entry, Path("plugin.py"))

    def test_rejects_entry_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = write_plugin(root, "alpha")
            manifest_path = repository / "plugin.toml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    'entry = "plugin.py"', 'entry = "../outside.py"'
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PluginManifestError, "escapes repository root"):
                parse_plugin_manifest(repository)

    def test_rejects_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = write_plugin(Path(directory), "alpha")
            manifest_path = repository / "plugin.toml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    "schema_version = 1", "schema_version = 2"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PluginManifestError, "unsupported schema_version 2"):
                parse_plugin_manifest(repository)


class PluginRepositoryDiscoveryTests(unittest.TestCase):
    def test_absent_and_empty_roots_are_normal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = discover_plugin_repositories((root / "missing", root))

        self.assertEqual(result.repositories, ())
        self.assertEqual(result.errors, ())

    def test_scans_only_immediate_repository_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plugin(root, "alpha")
            write_plugin(root / "group", "nested")

            result = discover_plugin_repositories((root,))

        self.assertEqual(
            tuple(item.manifest.slug for item in result.repositories), ("alpha",)
        )

    def test_broken_repository_does_not_hide_valid_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = write_plugin(root, "broken")
            (broken / "plugin.toml").write_text("not valid toml = [", encoding="utf-8")
            write_plugin(root, "valid")

            result = discover_plugin_repositories((root,))

        self.assertEqual(
            tuple(item.manifest.slug for item in result.repositories), ("valid",)
        )
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].path.name, "broken")

    def test_duplicate_slug_is_reported_without_poisoning_later_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plugin(root, "a", plugin_id="org.example.first", slug="shared")
            write_plugin(root, "b", plugin_id="org.example.reusable", slug="shared")
            write_plugin(root, "c", plugin_id="org.example.reusable", slug="unique")

            result = discover_plugin_repositories((root,))

        self.assertEqual(
            tuple(item.manifest.slug for item in result.repositories),
            ("shared", "unique"),
        )
        self.assertEqual(len(result.errors), 1)
        self.assertIn("duplicate slug", result.errors[0].message)


if __name__ == "__main__":
    unittest.main()