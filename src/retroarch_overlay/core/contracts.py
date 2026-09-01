from dataclasses import dataclass, field
from typing import Mapping, Protocol

from .models import OverlaySnapshot, RetroArchStatus


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


@dataclass(frozen=True, slots=True)
class GameContext:
    settings: Mapping[str, object] = field(default_factory=dict)


class GamePlugin(Protocol):
    manifest: GameManifest
    options: tuple[GameOptionSpec, ...]

    def supports(self, status: RetroArchStatus, content_hash: str | None) -> bool: ...

    def create(self, context: GameContext) -> GameAdapter: ...