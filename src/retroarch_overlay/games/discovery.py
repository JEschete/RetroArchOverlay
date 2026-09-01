import re
from dataclasses import dataclass
from importlib import import_module
from pkgutil import iter_modules
from types import ModuleType
from typing import Callable, Iterable

from ..core.contracts import GameManifest, GameOptionSpec, GamePlugin


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class GameDiscoveryResult:
    plugins: tuple[GamePlugin, ...]
    errors: tuple[str, ...]


def discover_game_plugins(
    package_name: str = "retroarch_overlay.games",
    *,
    importer: Callable[[str], ModuleType] = import_module,
    module_iterator: Callable[[Iterable[str]], Iterable[object]] = iter_modules,
) -> GameDiscoveryResult:
    package = importer(package_name)
    package_paths = getattr(package, "__path__", None)
    if package_paths is None:
        return GameDiscoveryResult((), (f"{package_name} is not a package",))

    plugins: list[GamePlugin] = []
    errors = []
    slugs: set[str] = set()
    for module_info in module_iterator(package_paths):
        name = str(getattr(module_info, "name", ""))
        if not name or name.startswith("_") or not getattr(module_info, "ispkg", False):
            continue
        try:
            module = importer(f"{package_name}.{name}.plugin")
            plugin = getattr(module, "PLUGIN")
            _validate_plugin(plugin, name)
            if plugin.manifest.slug in slugs:
                raise ValueError(f"duplicate game slug {plugin.manifest.slug!r}")
            slugs.add(plugin.manifest.slug)
            plugins.append(plugin)
        except Exception as error:
            errors.append(f"{name}: {error}")
    plugins.sort(key=lambda plugin: plugin.manifest.slug)
    return GameDiscoveryResult(tuple(plugins), tuple(errors))


def _validate_plugin(plugin: object, package_slug: str) -> None:
    manifest = getattr(plugin, "manifest", None)
    if not isinstance(manifest, GameManifest):
        raise TypeError("PLUGIN.manifest must be a GameManifest")
    if not SLUG_PATTERN.fullmatch(manifest.slug):
        raise ValueError(f"invalid game slug {manifest.slug!r}")
    if manifest.slug != package_slug:
        raise ValueError(
            f"manifest slug {manifest.slug!r} does not match package {package_slug!r}"
        )
    if not manifest.display_name.strip():
        raise ValueError("manifest display name is required")
    options = getattr(plugin, "options", None)
    if not isinstance(options, tuple) or not all(
        isinstance(option, GameOptionSpec) for option in options
    ):
        raise TypeError("PLUGIN.options must be a tuple of GameOptionSpec values")
    for option in options:
        if not option.key.startswith(f"{manifest.slug}."):
            raise ValueError(f"option key {option.key!r} is not namespaced by game slug")
    if not callable(getattr(plugin, "supports", None)):
        raise TypeError("PLUGIN.supports must be callable")
    if not callable(getattr(plugin, "create", None)):
        raise TypeError("PLUGIN.create must be callable")