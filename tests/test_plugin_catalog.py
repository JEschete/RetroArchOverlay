import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retroarch_overlay.plugin_catalog import (
    filter_catalog_entries,
    load_plugin_catalog,
    parse_plugin_catalog,
)


CATALOG = b'''schema_version = 1

[[plugins]]
plugin_id = "org.example.second"
slug = "second"
name = "Second Game"
repository = "https://github.com/example/RAO_second.git"

[[plugins]]
plugin_id = "org.example.first"
slug = "first"
name = "First Game"
repository = "https://github.com/example/RAO_first.git"
web_url = "https://github.com/example/RAO_first"
'''


class PluginCatalogTests(unittest.TestCase):
    def test_filters_by_name_slug_and_plugin_id_case_insensitively(self) -> None:
        entries = parse_plugin_catalog(CATALOG)

        self.assertEqual(filter_catalog_entries(entries, "FIRST")[0].slug, "first")
        self.assertEqual(filter_catalog_entries(entries, "second")[0].slug, "second")
        self.assertEqual(filter_catalog_entries(entries, "example first")[0].slug, "first")

    def test_filter_returns_no_entries_when_query_does_not_match(self) -> None:
        entries = parse_plugin_catalog(CATALOG)

        self.assertEqual(filter_catalog_entries(entries, "missing"), ())

    def test_parses_and_sorts_catalog_entries(self) -> None:
        entries = parse_plugin_catalog(CATALOG)

        self.assertEqual(tuple(entry.name for entry in entries), ("First Game", "Second Game"))
        self.assertEqual(entries[0].slug, "first")

    def test_rejects_untrusted_repository_host(self) -> None:
        content = CATALOG.replace(b"https://github.com/example/RAO_first.git", b"https://evil.test/RAO_first.git")

        with self.assertRaisesRegex(ValueError, "HTTPS GitHub"):
            parse_plugin_catalog(content)

    def test_loads_local_catalog_and_writes_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "catalog.toml"
            cache = root / "cache" / "catalog.toml"
            source.write_bytes(CATALOG)

            entries = load_plugin_catalog(source, cache)

            self.assertEqual(len(entries), 2)
            self.assertEqual(cache.read_bytes(), CATALOG)

    def test_uses_valid_cache_when_remote_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "catalog.toml"
            cache.write_bytes(CATALOG)
            with patch("retroarch_overlay.plugin_catalog.urllib.request.urlopen", side_effect=OSError("offline")):
                entries = load_plugin_catalog("https://example.test/catalog.toml", cache)

        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
