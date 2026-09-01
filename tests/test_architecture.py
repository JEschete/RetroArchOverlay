import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "retroarch_overlay"
GAME_ROOTS = (
    SOURCE_ROOT / "adapters" / "dragon_warrior_3",
    SOURCE_ROOT / "adapters" / "emerald",
    SOURCE_ROOT / "games",
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


def imported_modules(path: Path) -> tuple[tuple[str, int], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append((node.module or "", node.level))
    return tuple(modules)


class ArchitectureBoundaryTests(unittest.TestCase):
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
        for root in GAME_ROOTS[:2]:
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