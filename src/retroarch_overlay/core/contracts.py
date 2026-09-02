from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .models import OverlaySnapshot, RetroArchStatus
from .retroachievements import RAProgress


class MemoryReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...


class GameAdapter(Protocol):
    name: str

    def supports(self, status: RetroArchStatus, content_hash: str | None = None) -> bool: ...

    def snapshot(self, memory: MemoryReader) -> OverlaySnapshot: ...


@dataclass(frozen=True, slots=True)
class GameManifest:
    slug: str
    display_name: str
    ra_game_id: int | None = None
    supported_cores: frozenset[str] = frozenset()
    content_hints: tuple[str, ...] = ()
    content_hashes: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GameOptionSpec:
    key: str
    flags: tuple[str, ...]
    help: str = ""
    value_type: str = "str"
    required: bool = False


@dataclass(frozen=True, slots=True)
class PluginSourceSpec:
    source_id: str
    kind: str
    path: Path
    required: bool = False
    required_files: tuple[Path, ...] = ()
    url: str = ""
    revision: str = ""


@dataclass(frozen=True, slots=True)
class PluginRepositoryManifest:
    schema_version: int
    plugin_id: str
    slug: str
    display_name: str
    api_version: int
    entry: Path
    license_expression: str = ""
    ra_game_id: int | None = None
    supported_cores: frozenset[str] = frozenset()
    content_hints: tuple[str, ...] = ()
    content_hashes: frozenset[str] = frozenset()
    options: tuple[GameOptionSpec, ...] = ()
    sources: tuple[PluginSourceSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class GameContext:
    settings: Mapping[str, object] = field(default_factory=dict)
    repository_root: Path | None = None
    state_directory: Path | None = None
    ra_progress_provider: Callable[[int], RAProgress | None] | None = None


class GamePlugin(Protocol):
    manifest: GameManifest
    options: tuple[GameOptionSpec, ...]

    def supports(self, status: RetroArchStatus, content_hash: str | None) -> bool: ...

    def create(self, context: GameContext) -> GameAdapter: ...