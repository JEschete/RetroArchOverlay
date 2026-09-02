import os
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/JEschete/RAO_catalog/main/catalog.toml"
)
CATALOG_TIMEOUT_SECONDS = 5


@dataclass(frozen=True, slots=True)
class PluginCatalogEntry:
    plugin_id: str
    slug: str
    name: str
    repository: str
    web_url: str = ""


def filter_catalog_entries(
    entries: tuple[PluginCatalogEntry, ...],
    query: str,
) -> tuple[PluginCatalogEntry, ...]:
    tokens = tuple(query.casefold().split())
    if not tokens:
        return entries
    return tuple(
        entry
        for entry in entries
        if all(
            token in f"{entry.name} {entry.slug} {entry.plugin_id}".casefold()
            for token in tokens
        )
    )


def default_catalog_cache_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "RetroArchOverlay" / "catalog.toml"


def default_catalog_source() -> str | Path:
    configured = os.environ.get("RETROARCH_OVERLAY_CATALOG", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else configured
    development_catalog = Path(__file__).resolve().parents[3] / "RAO_catalog" / "catalog.toml"
    return development_catalog if development_catalog.is_file() else DEFAULT_CATALOG_URL


def parse_plugin_catalog(content: bytes) -> tuple[PluginCatalogEntry, ...]:
    document = tomllib.loads(content.decode("utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Plugin catalog schema_version must be 1")
    raw_plugins = document.get("plugins")
    if not isinstance(raw_plugins, list):
        raise ValueError("Plugin catalog must contain [[plugins]] entries")
    entries = []
    identities = set()
    for raw in raw_plugins:
        if not isinstance(raw, dict):
            raise ValueError("Each plugin catalog entry must be a table")
        entry = PluginCatalogEntry(
            plugin_id=_required_string(raw, "plugin_id"),
            slug=_required_string(raw, "slug"),
            name=_required_string(raw, "name"),
            repository=_required_string(raw, "repository"),
            web_url=str(raw.get("web_url", "")).strip(),
        )
        _validate_repository_url(entry.repository)
        if entry.plugin_id in identities:
            raise ValueError(f"Duplicate catalog plugin_id: {entry.plugin_id}")
        identities.add(entry.plugin_id)
        entries.append(entry)
    return tuple(sorted(entries, key=lambda entry: entry.name.casefold()))


def load_plugin_catalog(
    source: str | Path | None = None,
    cache_path: Path | None = None,
) -> tuple[PluginCatalogEntry, ...]:
    selected_source = source or default_catalog_source()
    cache = (cache_path or default_catalog_cache_path()).resolve()
    try:
        if isinstance(selected_source, Path):
            content = selected_source.read_bytes()
        else:
            request = urllib.request.Request(selected_source, headers={"User-Agent": "RetroArchOverlay"})
            with urllib.request.urlopen(request, timeout=CATALOG_TIMEOUT_SECONDS) as response:
                content = response.read()
        entries = parse_plugin_catalog(content)
        _write_cache(cache, content)
        return entries
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
        if cache.is_file():
            return parse_plugin_catalog(cache.read_bytes())
        raise


def _required_string(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Catalog plugin {key} must be a non-empty string")
    return value.strip()


def _validate_repository_url(repository: str) -> None:
    parsed = urlparse(repository)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("Catalog repositories must use HTTPS GitHub URLs")
    if not parsed.path.rstrip("/").endswith(".git"):
        raise ValueError("Catalog repository URLs must end with .git")


def _write_cache(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
