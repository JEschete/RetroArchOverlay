import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "retroarch_overlay"
PLUGIN_ROOT = PROJECT_ROOT / "plugins"
GAME_ROOTS = (
    PLUGIN_ROOT / "RAO_dragonwarrior3" / "game",
    PLUGIN_ROOT / "RAO_pokeemerald" / "game",
)
FORBIDDEN_GAME_IMPORTS = frozenset(
    {
        "keyring",
        "PIL",
        "requests",
        "socket",
        "tkinter",
        "urllib",
    }
)
FORBIDDEN_PLUGIN_GUI_IMPORTS = frozenset({"PyQt6", "PySide6", "tkinter"})
TEMPORARY_PLUGIN_GUI_EXCEPTIONS = frozenset(
    {
        Path("plugins/RAO_vagrantstory/dashboard.py"),
    }
)


def imported_modules(path: Path) -> tuple[tuple[str, int], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append((node.module or "", node.level))
    return tuple(modules)


def plugin_runtime_paths(repository: Path) -> tuple[Path, ...]:
    game_root = repository / "game"
    return tuple(repository.glob("*.py")) + (
        tuple(game_root.rglob("*.py")) if game_root.is_dir() else ()
    )


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_plugin_runtime_code_is_toolkit_neutral_except_temporary_dashboards(
        self,
    ) -> None:
        violations = []
        for repository in PLUGIN_ROOT.glob("RAO_*"):
            if not repository.is_dir():
                continue
            for path in plugin_runtime_paths(repository):
                relative_path = path.relative_to(PROJECT_ROOT)
                if relative_path in TEMPORARY_PLUGIN_GUI_EXCEPTIONS:
                    continue
                for module, _ in imported_modules(path):
                    if module.partition(".")[0] in FORBIDDEN_PLUGIN_GUI_IMPORTS:
                        violations.append(f"{relative_path} imports {module}")
        self.assertEqual(violations, [])

    def test_core_production_source_contains_no_dragon_plugin_knowledge(self) -> None:
        violations = []
        forbidden = (
            "DragonWarrior3Adapter",
            "dragon_warrior_3",
            "Dragon Warrior III",
            "Dragon Quest III",
        )
        for path in SOURCE_ROOT.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                if value in content:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} contains {value}")
        self.assertEqual(violations, [])

    def test_core_production_source_contains_no_emerald_plugin_knowledge(self) -> None:
        violations = []
        forbidden = ("EmeraldAdapter", "adapters.emerald", "pokeemerald-root")
        for path in SOURCE_ROOT.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                if value in content:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} contains {value}")
        self.assertEqual(violations, [])

    def test_core_production_source_contains_no_dragon_warrior_4_knowledge(self) -> None:
        violations = []
        forbidden = (
            "Dragon Warrior IV",
            "Dragon Quest IV",
            "dragonwarrior4",
            "dragon_warrior_4",
        )
        for path in SOURCE_ROOT.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                if value in content:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)} contains {value}")
        self.assertEqual(violations, [])

    def test_game_modules_do_not_import_external_io_or_ui_implementations(self) -> None:
        violations = []
        for root in GAME_ROOTS:
            for path in root.rglob("*.py"):
                if "tests" in path.parts:
                    continue
                for module, _ in imported_modules(path):
                    if module.partition(".")[0] in FORBIDDEN_GAME_IMPORTS:
                        violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")
        self.assertEqual(violations, [])

    def test_adapters_use_core_ra_model_instead_of_compatibility_facade(self) -> None:
        violations = []
        for root in GAME_ROOTS:
            for path in root.rglob("*.py"):
                for module, level in imported_modules(path):
                    if level and module == "retroachievements":
                        violations.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(violations, [])

    def test_core_does_not_import_outer_application_layers(self) -> None:
        violations = []
        for path in (SOURCE_ROOT / "core").rglob("*.py"):
            for module, level in imported_modules(path):
                if level > 1:
                    violations.append(f"{path.name}: relative level {level} import {module}")
                if module.partition(".")[0] in {
                    "app",
                    "games",
                    "infrastructure",
                    "presentation",
                }:
                    violations.append(f"{path.name}: imports {module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()