import hashlib
import importlib.util
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from ..core.contracts import GameAdapter, GameContext
from ..core.errors import GameUnavailableError
from ..core.models import OverlaySnapshot, RetroArchStatus
from .plugin_discovery import DiscoveredPluginRepository


class RepositoryAdapter:
    def __init__(
        self,
        repository: DiscoveredPluginRepository,
        context: GameContext,
    ) -> None:
        self.name = repository.manifest.display_name
        self._repository = repository
        self._context = replace(
            context,
            repository_root=(
                context.repository_root.resolve()
                if context.repository_root is not None
                else None
            ),
        )
        self._adapter: GameAdapter | None = None

    def supports(
        self, status: RetroArchStatus, content_hash: str | None = None
    ) -> bool:
        manifest = self._repository.manifest
        core = status.core.casefold().replace(" ", "_")
        supported_cores = {
            value.casefold().replace(" ", "_") for value in manifest.supported_cores
        }
        if supported_cores and core not in supported_cores:
            return False
        if content_hash is not None and manifest.content_hashes:
            return content_hash.casefold() in manifest.content_hashes
        content = status.content.casefold()
        return any(hint.casefold() in content for hint in manifest.content_hints)

    def snapshot(self, memory: object) -> OverlaySnapshot:
        return self._load_adapter().snapshot(memory)  # type: ignore[arg-type]

    def capture(self, memory: object) -> None:
        capture = getattr(self._load_adapter(), "capture", None)
        if callable(capture):
            capture(memory)

    def _load_adapter(self) -> GameAdapter:
        if self._adapter is not None:
            return self._adapter
        manifest = self._repository.manifest
        try:
            _preflight_sources(self._repository)
            module = _load_plugin_module(
                manifest.plugin_id,
                self._repository.repository_root,
                manifest.entry,
            )
            plugin = getattr(module, "PLUGIN")
            create = getattr(plugin, "create", None)
            if not callable(create):
                raise TypeError("PLUGIN.create must be callable")
            adapter = create(self._context)
            if not callable(getattr(adapter, "snapshot", None)):
                raise TypeError("created adapter must provide snapshot")
            self._adapter = adapter
            return adapter
        except Exception as error:
            raise GameUnavailableError(f"{manifest.display_name}: {error}") from error


def _load_plugin_module(plugin_id: str, repository_root: Path, entry: Path) -> ModuleType:
    root = repository_root.resolve()
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    safe_id = re.sub(r"[^a-z0-9_]", "_", plugin_id.casefold())
    package_name = f"_retroarch_overlay_plugin_{safe_id}_{identity}"
    module_name = f"{package_name}.entry"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    package = ModuleType(package_name)
    package.__path__ = [str(root)]  # type: ignore[attr-defined]
    package.__package__ = package_name
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(module_name, root / entry)
    if spec is None or spec.loader is None:
        sys.modules.pop(package_name, None)
        raise ImportError(f"cannot load plugin entry {entry}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        sys.modules.pop(package_name, None)
        raise
    return module


def _run_git_check(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-c", "safe.directory=*", "-C", str(repo_path), *args),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _preflight_sources(repository: DiscoveredPluginRepository) -> None:
    root = repository.repository_root
    for source in repository.manifest.sources:
        if not source.required:
            continue
        source_root = root / source.path
        missing = [path for path in source.required_files if not (source_root / path).exists()]
        if not source_root.is_dir() or missing:
            command = f"git -C {root} submodule update --init --recursive"
            details = ", ".join(str(path).replace("\\", "/") for path in missing[:4])
            raise GameUnavailableError(
                f"required source {source.source_id!r} is incomplete"
                f"{f': {details}' if details else ''}; run: {command}"
            )
        if source.revision and (source_root / ".git").exists():
            try:
                head_result = _run_git_check(source_root, "rev-parse", "HEAD")
            except (OSError, subprocess.TimeoutExpired) as error:
                raise GameUnavailableError(
                    f"could not verify required source {source.source_id!r}: {error}"
                ) from error
            revision = head_result.stdout.strip().casefold()
            if head_result.returncode:
                raise GameUnavailableError(
                    f"required source {source.source_id!r} is at "
                    f"{revision or 'an unknown revision'}; expected at least {source.revision}; "
                    f"run: git -C {root} submodule update --init --recursive"
                )
            minimum_revision = source.revision.casefold()
            try:
                ancestor_result = _run_git_check(
                    source_root,
                    "merge-base",
                    "--is-ancestor",
                    minimum_revision,
                    "HEAD",
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise GameUnavailableError(
                    f"could not verify required source {source.source_id!r}: {error}"
                ) from error
            if ancestor_result.returncode != 0:
                raise GameUnavailableError(
                    f"required source {source.source_id!r} is at "
                    f"{revision}; expected at least {source.revision}; "
                    f"run: git -C {root} submodule update --init --recursive"
                )