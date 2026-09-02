import subprocess
import tempfile
import unittest
from pathlib import Path

from retroarch_overlay.infrastructure.plugin_discovery import parse_plugin_manifest
from retroarch_overlay.plugin_tools import PluginTemplateConfig, create_plugin, update_plugin


class PluginGeneratorTests(unittest.TestCase):
    def test_creates_uniform_plugin_without_decomp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = create_plugin(
                PluginTemplateConfig(
                    game_name="Example Game",
                    slug="example_game",
                    output_root=Path(directory),
                    copyright_holder="Example Author",
                    cores=("example_core",),
                ),
                initialize_git=True,
            )
            manifest = parse_plugin_manifest(repository)

            self.assertEqual(repository.name, "RAO_example_game")
            self.assertEqual(manifest.license_expression, "MIT")
            self.assertEqual(manifest.sources, ())
            self.assertTrue((repository / "LICENSE").is_file())
            self.assertTrue((repository / "game" / "adapter.py").is_file())
            self.assertTrue((repository / "resources" / ".gitkeep").is_file())
            gitignore = (repository / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("resources/*\n", gitignore)
            self.assertIn("!resources/.gitkeep\n", gitignore)
            local_resource = repository / "resources" / "local.bin"
            local_resource.write_bytes(b"local research")
            ignored = subprocess.run(
                ["git", "-C", str(repository), "check-ignore", "--quiet", str(local_resource)],
                check=False,
            )
            keep_ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "check-ignore",
                    "--quiet",
                    str(repository / "resources" / ".gitkeep"),
                ],
                check=False,
            )
            self.assertEqual(ignored.returncode, 0)
            self.assertNotEqual(keep_ignored.returncode, 0)
            self.assertTrue(
                (repository / "game" / "data" / "retroachievements" / "code_notes.json").is_file()
            )
            notes_ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "check-ignore",
                    "--quiet",
                    str(repository / "game/data/retroachievements/code_notes.json"),
                ],
                check=False,
            )
            self.assertEqual(notes_ignored.returncode, 0)
            patch = repository / "subset.bps"
            patch.write_bytes(b"local patch")
            patch_ignored = subprocess.run(
                ["git", "-C", str(repository), "check-ignore", "--quiet", str(patch)],
                check=False,
            )
            self.assertEqual(patch_ignored.returncode, 0)
            unknown_patch = repository / "game" / "assets" / "patches" / "subset.custom"
            unknown_patch.parent.mkdir(parents=True)
            unknown_patch.write_bytes(b"unknown local patch format")
            directory_ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "check-ignore",
                    "--quiet",
                    str(unknown_patch),
                ],
                check=False,
            )
            self.assertEqual(directory_ignored.returncode, 0)

    def test_adds_decomp_metadata_later_without_replacing_plugin_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = create_plugin(
                PluginTemplateConfig(
                    game_name="Example Game",
                    slug="example_game",
                    output_root=Path(directory),
                    copyright_holder="Example Author",
                )
            )
            adapter = repository / "game" / "adapter.py"
            adapter.write_text("user implementation\n", encoding="utf-8")

            manifest = update_plugin(
                repository,
                decomp_url="https://github.com/example/example-decomp.git",
                decomp_revision="abc123",
                decomp_required_files=("data/maps.json",),
                decomp_required=True,
            )

            self.assertEqual(adapter.read_text(encoding="utf-8"), "user implementation\n")
            self.assertEqual(manifest.sources[0].path, Path("decomp_reference/example-decomp"))
            self.assertEqual(manifest.sources[0].revision, "abc123")
            self.assertEqual(manifest.sources[0].required_files, (Path("data/maps.json"),))

    def test_generates_apache_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = create_plugin(
                PluginTemplateConfig(
                    game_name="Example Game",
                    slug="example_game",
                    output_root=Path(directory),
                    copyright_holder="Example Author",
                    license_expression="Apache-2.0",
                )
            )

            self.assertIn("Apache License", (repository / "LICENSE").read_text(encoding="utf-8"))
            self.assertIn("Example Author", (repository / "NOTICE").read_text(encoding="utf-8"))

    def test_updates_manifest_metadata_without_replacing_plugin_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = create_plugin(
                PluginTemplateConfig(
                    game_name="Example Game",
                    slug="example_game",
                    output_root=Path(directory),
                    copyright_holder="Example Author",
                )
            )
            entry = repository / "plugin.py"
            original_entry = entry.read_text(encoding="utf-8")

            manifest = update_plugin(
                repository,
                game_name="Updated Game",
                plugin_id="org.example.updated",
                ra_game_id=42,
                update_ra_game_id=True,
                cores=("core_a", "core_b"),
                content_hints=("updated",),
                content_hashes=("ABCDEF",),
            )

            self.assertEqual(manifest.display_name, "Updated Game")
            self.assertEqual(manifest.plugin_id, "org.example.updated")
            self.assertEqual(manifest.ra_game_id, 42)
            self.assertEqual(manifest.supported_cores, frozenset({"core_a", "core_b"}))
            self.assertEqual(manifest.content_hashes, frozenset({"abcdef"}))
            self.assertEqual(entry.read_text(encoding="utf-8"), original_entry)


if __name__ == "__main__":
    unittest.main()