import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..core.contracts import (
    GameOptionSpec,
    PluginRepositoryManifest,
    PluginSourceSpec,
)
from ..core.errors import PluginManifestError


PLUGIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_API_VERSION = 1
TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "plugin_id",
        "slug",
        "name",
        "api_version",
        "entry",
        "ra_game_id",
        "match",
        "options",
        "sources",
    }
)


@dataclass(frozen=True, slots=True)
class DiscoveredPluginRepository:
    repository_root: Path
    manifest: PluginRepositoryManifest


@dataclass(frozen=True, slots=True)
class PluginDiscoveryError:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class PluginDiscoveryResult:
    repositories: tuple[DiscoveredPluginRepository, ...]
    errors: tuple[PluginDiscoveryError, ...]


def parse_plugin_manifest(repository_root: Path) -> PluginRepositoryManifest:
    root = repository_root.resolve()
    manifest_path = root / "plugin.toml"
    try:
        document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PluginManifestError(str(error)) from error
    _reject_unknown_keys(document, TOP_LEVEL_KEYS, "plugin")
    schema_version = _required_int(document, "schema_version")
    api_version = _required_int(document, "api_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise PluginManifestError(f"unsupported schema_version {schema_version}")
    if api_version != SUPPORTED_API_VERSION:
        raise PluginManifestError(f"unsupported api_version {api_version}")
    plugin_id = _required_string(document, "plugin_id")
    slug = _required_string(document, "slug")
    if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
        raise PluginManifestError(f"invalid plugin_id {plugin_id!r}")
    if not SLUG_PATTERN.fullmatch(slug):
        raise PluginManifestError(f"invalid slug {slug!r}")
    entry = _contained_relative_path(root, _required_string(document, "entry"), "entry")
    if not (root / entry).is_file():
        raise PluginManifestError(f"entry does not exist: {entry}")
    match = _table(document, "match")
    _reject_unknown_keys(match, frozenset({"cores", "content_hints", "hashes"}), "match")
    options = tuple(_parse_option(value, slug) for value in _table_list(document, "options"))
    sources = tuple(_parse_source(root, value) for value in _table_list(document, "sources"))
    ra_game_id = document.get("ra_game_id")
    if ra_game_id is not None and (isinstance(ra_game_id, bool) or not isinstance(ra_game_id, int)):
        raise PluginManifestError("ra_game_id must be an integer")
    return PluginRepositoryManifest(
        schema_version=schema_version,
        plugin_id=plugin_id,
        slug=slug,
        display_name=_required_string(document, "name"),
        api_version=api_version,
        entry=entry,
        ra_game_id=ra_game_id,
        supported_cores=frozenset(_string_list(match, "cores")),
        content_hints=tuple(_string_list(match, "content_hints")),
        content_hashes=frozenset(value.casefold() for value in _string_list(match, "hashes")),
        options=options,
        sources=sources,
    )


def discover_plugin_repositories(roots: tuple[Path, ...]) -> PluginDiscoveryResult:
    repositories: list[DiscoveredPluginRepository] = []
    errors: list[PluginDiscoveryError] = []
    plugin_ids: dict[str, Path] = {}
    slugs: dict[str, Path] = {}
    flags: dict[str, Path] = {}
    for discovery_root in roots:
        if not discovery_root.is_dir():
            continue
        for repository_root in sorted(
            (path for path in discovery_root.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        ):
            if not (repository_root / "plugin.toml").is_file():
                continue
            try:
                manifest = parse_plugin_manifest(repository_root)
                claims = (
                    ("plugin_id", manifest.plugin_id, plugin_ids),
                    ("slug", manifest.slug, slugs),
                    *(
                        ("option flag", flag, flags)
                        for option in manifest.options
                        for flag in option.flags
                    ),
                )
                for label, value, claimed in claims:
                    _require_unique(label, value, claimed)
                for _, value, claimed in claims:
                    claimed[value] = repository_root
                repositories.append(DiscoveredPluginRepository(repository_root.resolve(), manifest))
            except PluginManifestError as error:
                errors.append(PluginDiscoveryError(repository_root.resolve(), str(error)))
    return PluginDiscoveryResult(tuple(repositories), tuple(errors))


def _parse_option(value: Mapping[str, object], slug: str) -> GameOptionSpec:
    _reject_unknown_keys(value, frozenset({"key", "flag", "type", "required", "help"}), "option")
    key = _required_string(value, "key")
    if not key.startswith(f"{slug}."):
        raise PluginManifestError(f"option key {key!r} is not namespaced by slug {slug!r}")
    flag = _required_string(value, "flag")
    if not flag.startswith("--"):
        raise PluginManifestError(f"invalid option flag {flag!r}")
    return GameOptionSpec(
        key,
        (flag,),
        _optional_string(value, "help"),
        _optional_string(value, "type", "str"),
        _optional_bool(value, "required"),
    )


def _parse_source(root: Path, value: Mapping[str, object]) -> PluginSourceSpec:
    _reject_unknown_keys(
        value,
        frozenset({"id", "kind", "path", "required", "required_files"}),
        "source",
    )
    path = _contained_relative_path(root, _required_string(value, "path"), "source path")
    required_files = tuple(
        _contained_relative_path(root / path, item, "required file")
        for item in _string_list(value, "required_files")
    )
    return PluginSourceSpec(
        _required_string(value, "id"),
        _required_string(value, "kind"),
        path,
        _optional_bool(value, "required"),
        required_files,
    )


def _contained_relative_path(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise PluginManifestError(f"{label} must be relative")
    resolved = (root / path).resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as error:
        raise PluginManifestError(f"{label} escapes repository root") from error
    return relative


def _require_unique(label: str, value: str, claimed: dict[str, Path]) -> None:
    if value in claimed:
        raise PluginManifestError(f"duplicate {label} {value!r}; first declared by {claimed[value]}")


def _reject_unknown_keys(value: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PluginManifestError(f"unknown {label} keys: {', '.join(unknown)}")


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise PluginManifestError(f"{key} must be a non-empty string")
    return result.strip()


def _optional_string(value: Mapping[str, object], key: str, default: str = "") -> str:
    result = value.get(key, default)
    if not isinstance(result, str):
        raise PluginManifestError(f"{key} must be a string")
    return result


def _required_int(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise PluginManifestError(f"{key} must be an integer")
    return result


def _optional_bool(value: Mapping[str, object], key: str) -> bool:
    result = value.get(key, False)
    if not isinstance(result, bool):
        raise PluginManifestError(f"{key} must be a boolean")
    return result


def _table(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    result = value.get(key, {})
    if not isinstance(result, dict):
        raise PluginManifestError(f"{key} must be a table")
    return result


def _table_list(value: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    result = value.get(key, [])
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise PluginManifestError(f"{key} must be an array of tables")
    return tuple(result)


def _string_list(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    result = value.get(key, [])
    if not isinstance(result, list) or not all(isinstance(item, str) and item for item in result):
        raise PluginManifestError(f"{key} must be an array of non-empty strings")
    return tuple(result)