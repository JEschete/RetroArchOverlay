import hashlib
import zlib
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

from ..models import OverlaySnapshot, RetroArchStatus
from ..retroarch import MemoryReader


class GameAdapter(Protocol):
    name: str

    def supports(self, status: RetroArchStatus, content_hash: str | None = None) -> bool: ...

    def snapshot(self, memory: MemoryReader) -> OverlaySnapshot: ...


class ContentHashResolver:
    def __init__(self, roots: tuple[Path, ...] = ()):
        self._roots = roots
        self._cache: dict[tuple[str, str], str | None] = {}

    def resolve(self, status: RetroArchStatus) -> str | None:
        key = (status.content, status.content_crc32)
        if key not in self._cache:
            self._cache[key] = self._resolve_uncached(status)
        return self._cache[key]

    def _resolve_uncached(self, status: RetroArchStatus) -> str | None:
        content_path = Path(status.content)
        candidates = [content_path] if content_path.is_file() else []
        target_name = content_path.name.casefold()
        for root in self._roots:
            if root.is_dir():
                candidates.extend(
                    path
                    for path in root.rglob("*")
                    if path.is_file()
                    and (path.name.casefold() == target_name or path.stem.casefold() == target_name)
                )
        for candidate in candidates:
            for content_hash, crc32 in self._hash_variants(candidate):
                if not status.content_crc32 or crc32 == status.content_crc32:
                    return content_hash
        return None

    @classmethod
    def _hash_variants(cls, path: Path) -> tuple[tuple[str, str], ...]:
        raw = cls._hash_file(path)
        if path.suffix.casefold() != ".nes":
            return (raw,)
        data = path.read_bytes()
        if len(data) < 16 or data[:4] != b"NES\x1a":
            return (raw,)
        digest = hashlib.md5(data[16:], usedforsecurity=False).hexdigest()
        checksum = f"{zlib.crc32(data[16:]):08x}"
        return ((digest, checksum), (digest, raw[1]))

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, str]:
        digest = hashlib.md5(usedforsecurity=False)
        checksum = 0
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
                checksum = zlib.crc32(chunk, checksum)
        return digest.hexdigest(), f"{checksum:08x}"


class AdapterRegistry:
    def __init__(
        self,
        adapters: list[GameAdapter] | None = None,
        hash_resolver: ContentHashResolver | None = None,
    ):
        self._adapters = list(adapters or [])
        self._hash_resolver = hash_resolver or ContentHashResolver()

    def register(self, adapter: GameAdapter) -> None:
        self._adapters.append(adapter)

    def discover(self) -> None:
        for entry_point in entry_points(group="retroarch_overlay.adapters"):
            self.register(entry_point.load()())

    def find(self, status: RetroArchStatus) -> GameAdapter | None:
        content_hash = self._hash_resolver.resolve(status)
        return next(
            (adapter for adapter in self._adapters if adapter.supports(status, content_hash)),
            None,
        )
