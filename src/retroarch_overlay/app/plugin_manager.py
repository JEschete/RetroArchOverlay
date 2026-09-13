from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
import re

from ..core.contracts import PluginRepositoryManifest, PluginSourceSpec
from ..infrastructure.plugin_discovery import (
    PLUGIN_ID_PATTERN,
    SLUG_PATTERN,
    PluginDiscoveryError,
    discover_plugin_repositories,
)
from ..plugin_catalog import PluginCatalogEntry, filter_catalog_entries
from ..plugin_tools import PluginTemplateConfig, SUPPORTED_LICENSES


class PluginPathSettings(Protocol):
    def rom_path(self, plugin_id: str) -> Path | None: ...

    def save_path(self, plugin_id: str) -> Path | None: ...


@dataclass(frozen=True, slots=True)
class InstalledPluginView:
    repository_root: Path
    manifest: PluginRepositoryManifest

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin_id

    @property
    def name(self) -> str:
        return self.manifest.display_name

    @property
    def license_expression(self) -> str:
        return self.manifest.license_expression or "None"


@dataclass(frozen=True, slots=True)
class CatalogPluginView:
    entry: PluginCatalogEntry
    installed: bool

    @property
    def label(self) -> str:
        status = "Installed" if self.installed else "Available"
        return f"{self.entry.name}  |  {status}"


@dataclass(frozen=True, slots=True)
class PluginDetails:
    installed: InstalledPluginView
    rom_path: Path | None
    save_path: Path | None
    source: PluginSourceSpec | None
    raw_manifest: str

    @property
    def required_files(self) -> tuple[str, ...]:
        if self.source is None:
            return ()
        return tuple(path.as_posix() for path in self.source.required_files)


@dataclass(frozen=True, slots=True)
class PluginEditorValues:
    game_name: str = ""
    slug: str = ""
    copyright_holder: str = "JEschete"
    license_expression: str = "MIT"
    plugin_id: str = ""
    ra_game_id: str = ""
    cores: str = ""
    content_hints: str = ""
    content_hashes: str = ""
    decomp_url: str = ""
    decomp_revision: str = ""
    required_files: str = ""
    decomp_required: bool = False
    rom_path: str = ""
    save_path: str = ""

    @classmethod
    def from_details(
        cls,
        details: PluginDetails,
        *,
        copyright_holder: str = "JEschete",
    ) -> PluginEditorValues:
        manifest = details.installed.manifest
        source = details.source
        return cls(
            game_name=manifest.display_name,
            slug=manifest.slug,
            copyright_holder=copyright_holder,
            license_expression=manifest.license_expression or "MIT",
            plugin_id=manifest.plugin_id,
            ra_game_id=str(manifest.ra_game_id or ""),
            cores=", ".join(sorted(manifest.supported_cores)),
            content_hints=", ".join(manifest.content_hints),
            content_hashes=", ".join(sorted(manifest.content_hashes)),
            decomp_url=source.url if source else "",
            decomp_revision=source.revision if source else "",
            required_files="\n".join(details.required_files),
            decomp_required=source.required if source else False,
            rom_path=str(details.rom_path or ""),
            save_path=str(details.save_path or ""),
        )

    @property
    def parsed_ra_game_id(self) -> int | None:
        value = self.ra_game_id.strip()
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError as error:
            raise ValueError("RetroAchievements ID must be an integer") from error
        if parsed <= 0:
            raise ValueError("RetroAchievements ID must be positive")
        return parsed

    @property
    def parsed_cores(self) -> tuple[str, ...]:
        return _csv(self.cores)

    @property
    def parsed_content_hints(self) -> tuple[str, ...]:
        return _csv(self.content_hints)

    @property
    def parsed_content_hashes(self) -> tuple[str, ...]:
        return _csv(self.content_hashes)

    @property
    def parsed_required_files(self) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in self.required_files.splitlines()
            if value.strip()
        )

    @property
    def optional_rom_path(self) -> Path | None:
        value = self.rom_path.strip()
        return Path(value) if value else None

    @property
    def optional_save_path(self) -> Path | None:
        value = self.save_path.strip()
        return Path(value) if value else None

    def validate(self, *, creating: bool) -> None:
        if not self.game_name.strip():
            raise ValueError("Game name is required")
        slug = self.slug.strip()
        if not SLUG_PATTERN.fullmatch(slug):
            raise ValueError(
                "Slug must start with a letter and contain lowercase letters, "
                "numbers, or underscores"
            )
        if creating and not self.copyright_holder.strip():
            raise ValueError("Copyright holder is required")
        if self.license_expression not in SUPPORTED_LICENSES:
            raise ValueError(f"Unsupported license: {self.license_expression}")
        plugin_id = self.plugin_id.strip() or f"org.jeschete.retroarch-overlay.{slug}"
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise ValueError(f"Invalid plugin ID: {plugin_id}")
        self.parsed_ra_game_id
        for value in self.parsed_required_files:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Required file must be a contained relative path: {value}")
        url = self.decomp_url.strip()
        if url:
            repository_name = Path(urlparse(url).path).name.removesuffix(".git")
            if not repository_name or not re.fullmatch(
                r"[A-Za-z0-9._-]+", repository_name
            ):
                raise ValueError("Decomp URL must end in a valid repository name")
        elif self.decomp_required or self.decomp_revision.strip() or self.parsed_required_files:
            raise ValueError("Decomp URL is required for decomp settings")

    def template_config(self, output_root: Path) -> PluginTemplateConfig:
        self.validate(creating=True)
        return PluginTemplateConfig(
            game_name=self.game_name.strip(),
            slug=self.slug.strip(),
            output_root=output_root,
            copyright_holder=self.copyright_holder.strip(),
            license_expression=self.license_expression,
            plugin_id=self.plugin_id.strip(),
            ra_game_id=self.parsed_ra_game_id,
            cores=self.parsed_cores,
            content_hints=self.parsed_content_hints,
            content_hashes=self.parsed_content_hashes,
            decomp_url=self.decomp_url.strip(),
            decomp_revision=self.decomp_revision.strip(),
            decomp_required_files=self.parsed_required_files,
            decomp_required=self.decomp_required,
        )


@dataclass(frozen=True, slots=True)
class PluginManagerState:
    plugin_root: Path
    installed: tuple[InstalledPluginView, ...]
    discovery_errors: tuple[PluginDiscoveryError, ...]
    catalog_entries: tuple[PluginCatalogEntry, ...] = ()
    query: str = ""
    selected_repository: Path | None = None

    @property
    def installed_plugin_ids(self) -> frozenset[str]:
        return frozenset(item.plugin_id for item in self.installed)

    @property
    def catalog(self) -> tuple[CatalogPluginView, ...]:
        installed = self.installed_plugin_ids
        return tuple(
            CatalogPluginView(entry, entry.plugin_id in installed)
            for entry in filter_catalog_entries(self.catalog_entries, self.query)
        )

    @property
    def selected(self) -> InstalledPluginView | None:
        if self.selected_repository is None:
            return None
        selected = self.selected_repository.resolve()
        return next(
            (item for item in self.installed if item.repository_root == selected),
            None,
        )

    def with_catalog(
        self,
        entries: tuple[PluginCatalogEntry, ...],
    ) -> PluginManagerState:
        return replace(self, catalog_entries=entries)

    def with_query(self, query: str) -> PluginManagerState:
        return replace(self, query=query)

    def with_selection(self, repository: Path | None) -> PluginManagerState:
        if repository is None:
            return replace(self, selected_repository=None)
        resolved = repository.resolve()
        if resolved not in {item.repository_root for item in self.installed}:
            return replace(self, selected_repository=None)
        return replace(self, selected_repository=resolved)


def discover_manager_state(
    plugin_root: Path,
    *,
    previous: PluginManagerState | None = None,
    select: Path | None = None,
) -> PluginManagerState:
    root = plugin_root.expanduser().resolve()
    result = discover_plugin_repositories((root,))
    installed = tuple(
        InstalledPluginView(repository.repository_root, repository.manifest)
        for repository in result.repositories
    )
    state = PluginManagerState(
        root,
        installed,
        result.errors,
        previous.catalog_entries if previous is not None else (),
        previous.query if previous is not None else "",
    )
    requested = select or (
        previous.selected_repository if previous is not None else None
    )
    return state.with_selection(requested)


def plugin_details(
    installed: InstalledPluginView,
    settings: PluginPathSettings,
) -> PluginDetails:
    source = next(
        (
            item
            for item in installed.manifest.sources
            if item.kind == "git-submodule"
        ),
        None,
    )
    raw_manifest = (installed.repository_root / "plugin.toml").read_text(
        encoding="utf-8"
    )
    return PluginDetails(
        installed,
        settings.rom_path(installed.plugin_id),
        settings.save_path(installed.plugin_id),
        source,
        raw_manifest,
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())