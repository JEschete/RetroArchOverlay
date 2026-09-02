import shutil
import subprocess
import sys
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .core.contracts import PluginRepositoryManifest
from .infrastructure.plugin_discovery import parse_plugin_manifest


GIT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PluginRepositoryState:
    path: Path
    manifest: PluginRepositoryManifest
    revision: str
    branch: str
    dirty: bool


def inspect_plugin_repository(repository: Path) -> PluginRepositoryState:
    root = repository.resolve()
    manifest = parse_plugin_manifest(root)
    return PluginRepositoryState(
        path=root,
        manifest=manifest,
        revision=_git_revision(root),
        branch=_git_output(root, "branch", "--show-current") or "detached",
        dirty=bool(_git_output(root, "status", "--porcelain")),
    )


def get_plugin(
    plugin_root: Path,
    repository_url: str,
    *,
    expected_plugin_id: str | None = None,
    expected_slug: str | None = None,
) -> PluginRepositoryState:
    root = plugin_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    repository_name = _repository_name(repository_url)
    destination = _contained_plugin_path(root, root / repository_name)
    if destination.exists():
        raise FileExistsError(f"Plugin already exists: {destination}")
    _run_git(
        root,
        "clone",
        "--recurse-submodules",
        repository_url,
        str(destination),
    )
    try:
        state = inspect_plugin_repository(destination)
        if expected_plugin_id is not None and state.manifest.plugin_id != expected_plugin_id:
            raise ValueError(
                f"Cloned plugin ID {state.manifest.plugin_id!r} does not match catalog "
                f"ID {expected_plugin_id!r}"
            )
        if expected_slug is not None and state.manifest.slug != expected_slug:
            raise ValueError(
                f"Cloned plugin slug {state.manifest.slug!r} does not match catalog "
                f"slug {expected_slug!r}"
            )
        return state
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def update_plugin_repository(repository: Path) -> PluginRepositoryState:
    root = repository.resolve()
    state = inspect_plugin_repository(root)
    if state.dirty:
        raise RuntimeError("Commit or discard local changes before updating this plugin")
    _run_git(root, "pull", "--ff-only")
    _run_git(root, "submodule", "sync", "--recursive")
    _run_git(root, "submodule", "update", "--init", "--recursive")
    return inspect_plugin_repository(root)


def delete_plugin_repository(
    plugin_root: Path,
    repository: Path,
    *,
    allow_dirty: bool = False,
) -> None:
    root = plugin_root.resolve()
    target = _contained_plugin_path(root, repository.resolve())
    state = inspect_plugin_repository(target)
    if state.dirty and not allow_dirty:
        raise RuntimeError("Plugin has uncommitted changes")
    shutil.rmtree(target)


def launch_overlay(
    plugin_root: Path,
    *,
    retroarch_config: Path | None = None,
) -> subprocess.Popen[bytes]:
    framework_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "retroarch_overlay.main",
        "--plugin-dir",
        str(plugin_root.resolve()),
    ]
    if retroarch_config is not None:
        command.extend(("--retroarch-config", str(retroarch_config.resolve())))
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(command, cwd=framework_root, creationflags=creation_flags)


def _repository_name(repository_url: str) -> str:
    name = Path(urlparse(repository_url).path.rstrip("/")).name.removesuffix(".git")
    if not re.fullmatch(r"RAO_[A-Za-z0-9][A-Za-z0-9_]*", name):
        raise ValueError("Plugin repository URL must end with RAO_<game>[.git]")
    return name


def _contained_plugin_path(plugin_root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if resolved.parent != plugin_root.resolve():
        raise ValueError("Plugin must be an immediate child of the configured plugin root")
    return resolved


def _git_output(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def _git_revision(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if _git_output(repository, "rev-parse", "--is-inside-work-tree") == "true":
        return "unborn"
    result.check_returncode()
    raise RuntimeError("Unable to inspect Git revision")


def _run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )