import unittest
from pkgutil import ModuleInfo
from types import ModuleType

from retroarch_overlay.core.contracts import GameContext, GameManifest, GameOptionSpec
from retroarch_overlay.games.discovery import discover_game_plugins


class FakePlugin:
    def __init__(self, slug: str, options: tuple[GameOptionSpec, ...] = ()) -> None:
        self.manifest = GameManifest(slug, slug.replace("_", " ").title())
        self.options = options

    def supports(self, *_args: object) -> bool:
        return True

    def create(self, _context: GameContext) -> object:
        return object()


class GameDiscoveryTests(unittest.TestCase):
    def test_discovers_valid_sibling_game_without_a_central_list(self) -> None:
        package = ModuleType("example.games")
        package.__path__ = ["virtual"]
        plugin_module = ModuleType("example.games.alpha.plugin")
        plugin_module.PLUGIN = FakePlugin(
            "alpha",
            (GameOptionSpec("alpha.data_root", ("--alpha-data-root",)),),
        )

        def importer(name: str) -> ModuleType:
            return package if name == "example.games" else plugin_module

        result = discover_game_plugins(
            "example.games",
            importer=importer,
            module_iterator=lambda _: (ModuleInfo(None, "alpha", True),),
        )

        self.assertEqual(tuple(plugin.manifest.slug for plugin in result.plugins), ("alpha",))
        self.assertEqual(result.errors, ())

    def test_broken_game_does_not_hide_valid_sibling(self) -> None:
        package = ModuleType("example.games")
        package.__path__ = ["virtual"]
        valid_module = ModuleType("example.games.alpha.plugin")
        valid_module.PLUGIN = FakePlugin("alpha")

        def importer(name: str) -> ModuleType:
            if name == "example.games":
                return package
            if name.endswith("alpha.plugin"):
                return valid_module
            raise ImportError("optional game dependency missing")

        result = discover_game_plugins(
            "example.games",
            importer=importer,
            module_iterator=lambda _: (
                ModuleInfo(None, "alpha", True),
                ModuleInfo(None, "broken", True),
            ),
        )

        self.assertEqual(tuple(plugin.manifest.slug for plugin in result.plugins), ("alpha",))
        self.assertEqual(result.errors, ("broken: optional game dependency missing",))

    def test_rejects_non_namespaced_game_option(self) -> None:
        package = ModuleType("example.games")
        package.__path__ = ["virtual"]
        plugin_module = ModuleType("example.games.alpha.plugin")
        plugin_module.PLUGIN = FakePlugin(
            "alpha",
            (GameOptionSpec("shared_root", ("--shared-root",)),),
        )

        result = discover_game_plugins(
            "example.games",
            importer=lambda name: package if name == "example.games" else plugin_module,
            module_iterator=lambda _: (ModuleInfo(None, "alpha", True),),
        )

        self.assertEqual(result.plugins, ())
        self.assertIn("not namespaced by game slug", result.errors[0])


if __name__ == "__main__":
    unittest.main()