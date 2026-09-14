import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from retroarch_overlay.plugin_repository import (
    PluginRepositoryState,
    delete_plugin_repository,
    get_plugin,
    inspect_plugin_repository,
    launch_overlay,
    update_plugin_repository,
)


class PluginRepositoryManagementTests(unittest.TestCase):
    @patch("retroarch_overlay.plugin_repository.inspect_plugin_repository")
    @patch("retroarch_overlay.plugin_repository._run_git")
    def test_catalog_install_rejects_mismatched_plugin_identity(
        self,
        run_git: Mock,
        inspect: Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "RAO_game"
            run_git.side_effect = lambda _root, *_args: destination.mkdir()
            manifest = Mock(plugin_id="org.example.wrong", slug="game")
            inspect.return_value = PluginRepositoryState(
                destination,
                manifest,
                "revision",
                "main",
                False,
            )

            with self.assertRaisesRegex(ValueError, "does not match catalog"):
                get_plugin(
                    root,
                    "https://github.com/example/RAO_game.git",
                    expected_plugin_id="org.example.game",
                    expected_slug="game",
                )

            self.assertFalse(destination.exists())
            run_git.assert_called_once()

    def test_inspects_repository_before_initial_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "RAO_game"
            repository.mkdir()
            (repository / "plugin.py").write_text("", encoding="utf-8")
            (repository / "plugin.toml").write_text(
                """schema_version = 1
plugin_id = "org.example.game"
slug = "game"
name = "Game"
api_version = 1
entry = "plugin.py"
license = "MIT"

[match]
cores = []
content_hints = []
hashes = []
""",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(repository), "init", "-b", "main"],
                check=True,
                capture_output=True,
            )

            state = inspect_plugin_repository(repository)

        self.assertEqual(state.revision, "unborn")
        self.assertEqual(state.branch, "main")
        self.assertTrue(state.dirty)

    def test_get_rejects_non_plugin_repository_name_before_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("retroarch_overlay.plugin_repository.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "RAO_<game>"):
                    get_plugin(Path(directory), "https://example.test/not-a-plugin.git")

        run.assert_not_called()

    @patch("retroarch_overlay.plugin_repository.subprocess.Popen")
    def test_launch_overlay_uses_selected_plugin_root(self, popen: Mock) -> None:
        plugin_root = Path("custom plugins").resolve()

        launch_overlay(plugin_root)

        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["--plugin-dir", str(plugin_root)])
        self.assertEqual(command[1:3], ["-m", "retroarch_overlay.main"])
        self.assertNotIn("--ui", command)

    @patch("retroarch_overlay.plugin_repository.subprocess.Popen")
    def test_launch_overlay_uses_configured_retroarch_config(self, popen: Mock) -> None:
        plugin_root = Path("custom plugins").resolve()
        config = Path("RetroArch/retroarch.cfg").resolve()

        launch_overlay(plugin_root, retroarch_config=config)

        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["--retroarch-config", str(config)])

    def test_delete_rejects_path_outside_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(ValueError, "immediate child"):
                delete_plugin_repository(root / "plugins", root / "other" / "RAO_game")

    @patch("retroarch_overlay.plugin_repository.inspect_plugin_repository")
    def test_delete_requires_explicit_dirty_permission(self, inspect: Mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plugin_root = Path(directory)
            repository = plugin_root / "RAO_game"
            repository.mkdir()
            inspect.return_value = PluginRepositoryState(
                repository,
                Mock(),
                "abc123",
                "main",
                True,
            )

            with self.assertRaisesRegex(RuntimeError, "uncommitted"):
                delete_plugin_repository(plugin_root, repository)

            self.assertTrue(repository.exists())

    @patch("retroarch_overlay.plugin_repository._run_git")
    @patch("retroarch_overlay.plugin_repository.inspect_plugin_repository")
    def test_update_uses_fast_forward_and_recursive_submodules(
        self, inspect: Mock, run_git: Mock
    ) -> None:
        repository = Path("RAO_game").resolve()
        clean = PluginRepositoryState(repository, Mock(), "abc123", "main", False)
        updated = PluginRepositoryState(repository, Mock(), "def456", "main", False)
        inspect.side_effect = (clean, updated)

        result = update_plugin_repository(repository)

        self.assertIs(result, updated)
        self.assertEqual(
            run_git.call_args_list,
            [
                unittest.mock.call(repository, "pull", "--ff-only"),
                unittest.mock.call(repository, "submodule", "sync", "--recursive"),
                unittest.mock.call(
                    repository,
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()