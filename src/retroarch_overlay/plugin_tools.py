import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .core.contracts import PluginRepositoryManifest, PluginSourceSpec
from .infrastructure.plugin_discovery import parse_plugin_manifest
from .license_templates import render_license


SUPPORTED_LICENSES = ("MIT", "Apache-2.0")
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class PluginTemplateConfig:
    game_name: str
    slug: str
    output_root: Path
    copyright_holder: str
    license_expression: str = "MIT"
    plugin_id: str = ""
    ra_game_id: int | None = None
    cores: tuple[str, ...] = ()
    content_hints: tuple[str, ...] = ()
    content_hashes: tuple[str, ...] = ()
    decomp_url: str = ""
    decomp_revision: str = ""
    decomp_required_files: tuple[str, ...] = ()
    decomp_required: bool = False
    year: int = date.today().year

    @property
    def repository_name(self) -> str:
        return f"RAO_{self.slug}"

    @property
    def resolved_plugin_id(self) -> str:
        return self.plugin_id or f"org.jeschete.retroarch-overlay.{self.slug}"


def create_plugin(config: PluginTemplateConfig, *, initialize_git: bool = False) -> Path:
    _validate_config(config)
    repository = config.output_root.resolve() / config.repository_name
    if repository.exists() and any(repository.iterdir()):
        raise FileExistsError(f"Repository is not empty: {repository}")
    (repository / "game").mkdir(parents=True, exist_ok=True)
    (repository / "tests").mkdir(exist_ok=True)
    source = _source_from_values(
        config.decomp_url,
        config.decomp_revision,
        config.decomp_required_files,
        config.decomp_required,
    )
    manifest = PluginRepositoryManifest(
        schema_version=1,
        plugin_id=config.resolved_plugin_id,
        slug=config.slug,
        display_name=config.game_name,
        api_version=1,
        entry=Path("plugin.py"),
        license_expression=config.license_expression,
        ra_game_id=config.ra_game_id,
        supported_cores=frozenset(config.cores),
        content_hints=config.content_hints or (config.slug.replace("_", " "),),
        content_hashes=frozenset(value.casefold() for value in config.content_hashes),
        sources=(source,) if source else (),
    )
    files = _template_files(manifest, config.copyright_holder, config.year)
    for relative_path, content in files.items():
        destination = repository / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
    if initialize_git:
        _run_git(repository, "init", "-b", "main")
    return repository


def update_plugin(
    repository: Path,
    *,
    game_name: str | None = None,
    plugin_id: str | None = None,
    ra_game_id: int | None = None,
    update_ra_game_id: bool = False,
    cores: tuple[str, ...] | None = None,
    content_hints: tuple[str, ...] | None = None,
    content_hashes: tuple[str, ...] | None = None,
    decomp_url: str | None = None,
    decomp_revision: str | None = None,
    decomp_required_files: tuple[str, ...] | None = None,
    decomp_required: bool | None = None,
    license_expression: str | None = None,
    copyright_holder: str | None = None,
    year: int | None = None,
    install_decomp: bool = False,
) -> PluginRepositoryManifest:
    root = repository.resolve()
    manifest = parse_plugin_manifest(root)
    sources = list(manifest.sources)
    source_index = next(
        (
            index
            for index, source in enumerate(sources)
            if source.kind == "git-submodule"
            and (source.path.parts[0] in {"decomp_reference", "vendor"})
        ),
        None,
    )
    existing = sources[source_index] if source_index is not None else None
    resolved_url = decomp_url if decomp_url is not None else (existing.url if existing else "")
    if resolved_url:
        source = _source_from_values(
            resolved_url,
            decomp_revision if decomp_revision is not None else (existing.revision if existing else ""),
            decomp_required_files
            if decomp_required_files is not None
            else tuple(str(path).replace("\\", "/") for path in existing.required_files)
            if existing
            else (),
            decomp_required
            if decomp_required is not None
            else existing.required
            if existing
            else False,
        )
        if existing is None:
            sources.append(source)
        else:
            sources[source_index] = source
    resolved_license = license_expression or manifest.license_expression or "MIT"
    if resolved_license not in SUPPORTED_LICENSES:
        raise ValueError(f"Unsupported license: {resolved_license}")
    updated = PluginRepositoryManifest(
        schema_version=manifest.schema_version,
        plugin_id=plugin_id or manifest.plugin_id,
        slug=manifest.slug,
        display_name=game_name or manifest.display_name,
        api_version=manifest.api_version,
        entry=manifest.entry,
        license_expression=resolved_license,
        ra_game_id=ra_game_id if update_ra_game_id else manifest.ra_game_id,
        supported_cores=frozenset(cores) if cores is not None else manifest.supported_cores,
        content_hints=content_hints if content_hints is not None else manifest.content_hints,
        content_hashes=frozenset(value.casefold() for value in content_hashes)
        if content_hashes is not None
        else manifest.content_hashes,
        options=manifest.options,
        sources=tuple(sources),
    )
    (root / "plugin.toml").write_text(_render_manifest(updated), encoding="utf-8", newline="\n")
    if copyright_holder:
        (root / "LICENSE").write_text(
            render_license(resolved_license, year or date.today().year, copyright_holder),
            encoding="utf-8",
            newline="\n",
        )
        notice = root / "NOTICE"
        if resolved_license == "Apache-2.0":
            notice.write_text(
                _apache_notice(updated.display_name, year or date.today().year, copyright_holder),
                encoding="utf-8",
                newline="\n",
            )
        elif notice.exists():
            notice.unlink()
    if install_decomp and resolved_url:
        source = sources[source_index if source_index is not None else -1]
        target = root / source.path
        if not target.exists():
            _run_git(root, "submodule", "add", resolved_url, source.path.as_posix())
        if source.revision:
            _run_git(target, "checkout", source.revision)
    return parse_plugin_manifest(root)


def _validate_config(config: PluginTemplateConfig) -> None:
    if not config.game_name.strip():
        raise ValueError("Game name is required")
    if not SLUG_PATTERN.fullmatch(config.slug):
        raise ValueError("Slug must start with a letter and contain lowercase letters, numbers, or underscores")
    if not config.copyright_holder.strip():
        raise ValueError("Copyright holder is required")
    if config.license_expression not in SUPPORTED_LICENSES:
        raise ValueError(f"Unsupported license: {config.license_expression}")


def _source_from_values(
    url: str,
    revision: str,
    required_files: tuple[str, ...],
    required: bool,
) -> PluginSourceSpec | None:
    if not url:
        return None
    name = Path(urlparse(url).path).name.removesuffix(".git")
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError("Decomp URL must end in a valid repository name")
    return PluginSourceSpec(
        source_id=name.casefold().replace("-", "_"),
        kind="git-submodule",
        path=Path("decomp_reference") / name,
        required=required,
        required_files=tuple(Path(value) for value in required_files if value),
        url=url,
        revision=revision,
    )


def _template_files(
    manifest: PluginRepositoryManifest, holder: str, year: int
) -> dict[Path, str]:
    slug = manifest.slug
    files = {
        Path("plugin.toml"): _render_manifest(manifest),
        Path("plugin.py"): (
            "from retroarch_overlay.core.contracts import GameContext\n\n"
            "from .game.adapter import Adapter\n\n\n"
            "class Plugin:\n"
            "    def create(self, context: GameContext) -> Adapter:\n"
            "        return Adapter(context)\n\n\n"
            "PLUGIN = Plugin()\n"
        ),
        Path("game/__init__.py"): "",
        Path("resources/.gitkeep"): "",
        Path("game/data/retroachievements/code_notes.json"): (
            '{\n  "schema_version": 1,\n'
            '  "source": "RetroAchievements authenticated code-notes page",\n'
            '  "pages": []\n}\n'
        ),
        Path("game/adapter.py"): (
            "from retroarch_overlay.core.contracts import GameContext\n\n\n"
            "class Adapter:\n"
            f"    name = {manifest.display_name!r}\n\n"
            "    def __init__(self, context: GameContext) -> None:\n"
            "        self.context = context\n\n"
            "    def snapshot(self, memory: object) -> object:\n"
            f"        raise NotImplementedError(\"Implement the {slug} snapshot adapter\")\n"
        ),
        Path("tests/test_plugin.py"): (
            "from pathlib import Path\n\n"
            "from retroarch_overlay.infrastructure.plugin_discovery import parse_plugin_manifest\n\n\n"
            "def test_manifest() -> None:\n"
            "    manifest = parse_plugin_manifest(Path(__file__).parents[1])\n"
            f"    assert manifest.slug == {slug!r}\n"
        ),
        Path("README.md"): (
            f"# RAO {slug} Plugin\n\n"
            f"{manifest.display_name} integration for RetroArch Overlay.\n\n"
            "## Development\n\n"
            "Implement game behavior in `game/adapter.py`. Redistributable game-specific assets "
            "belong under `game/assets`. The tracked `resources` directory is local-only by "
            "default, and its contents are ignored until deliberately reviewed and added. "
            "Decompilation repositories belong under `decomp_reference` as Git submodules and "
            "are governed by their own terms.\n"
        ),
        Path("RIGHTS_AND_PROVENANCE.md"): (
            "# Rights and Provenance\n\n"
            f"Locally authored plugin code is offered under {manifest.license_expression}. "
            "That license does not cover ROMs, game assets, patches, trademarks, or content "
            "inside `decomp_reference`. Document every third-party source and its terms here.\n"
        ),
        Path("LICENSE"): render_license(manifest.license_expression, year, holder),
        Path(".gitignore"): (
            "__pycache__/\n*.py[cod]\n.pytest_cache/\n.coverage\n"
            "resources/*\n!resources/.gitkeep\n"
            "game/data/retroachievements/code_notes.*\n"
            "game/assets/patches/\n"
            "*.ips\n*.ips32\n*.bps\n*.ups\n*.rup\n*.xdelta\n*.xdelta3\n*.vcdiff\n"
            "*.bsdiff\n*.bspatch\n*.ppf\n*.pchtxt\n*.patch\n*.diff\n"
            "*.gba\n*.gb\n*.gbc\n*.nds\n*.nes\n*.sav\n*.srm\n*.state*\n"
            "decomp_reference/**/baserom.*\ndecomp_reference/**/*.gba\n"
            "decomp_reference/**/*.gb\ndecomp_reference/**/*.gbc\n"
            "decomp_reference/**/*.nds\ndecomp_reference/**/*.nes\n"
        ),
    }
    if manifest.license_expression == "Apache-2.0":
        files[Path("NOTICE")] = _apache_notice(manifest.display_name, year, holder)
    return files


def _apache_notice(name: str, year: int, holder: str) -> str:
    return f"{name}\nCopyright {year} {holder}\n"


def _render_manifest(manifest: PluginRepositoryManifest) -> str:
    lines = [
        f"schema_version = {manifest.schema_version}",
        f"plugin_id = {_toml_string(manifest.plugin_id)}",
        f"slug = {_toml_string(manifest.slug)}",
        f"name = {_toml_string(manifest.display_name)}",
        f"api_version = {manifest.api_version}",
        f"entry = {_toml_string(manifest.entry.as_posix())}",
        f"license = {_toml_string(manifest.license_expression)}",
    ]
    if manifest.ra_game_id is not None:
        lines.append(f"ra_game_id = {manifest.ra_game_id}")
    lines.extend(
        [
            "",
            "[match]",
            f"cores = {_toml_list(sorted(manifest.supported_cores))}",
            f"content_hints = {_toml_list(manifest.content_hints)}",
            f"hashes = {_toml_list(sorted(manifest.content_hashes))}",
        ]
    )
    for option in manifest.options:
        lines.extend(
            [
                "",
                "[[options]]",
                f"key = {_toml_string(option.key)}",
                f"flag = {_toml_string(option.flags[0])}",
                f"type = {_toml_string(option.value_type)}",
                f"required = {str(option.required).lower()}",
            ]
        )
        if option.help:
            lines.append(f"help = {_toml_string(option.help)}")
    for source in manifest.sources:
        lines.extend(
            [
                "",
                "[[sources]]",
                f"id = {_toml_string(source.source_id)}",
                f"kind = {_toml_string(source.kind)}",
                f"path = {_toml_string(source.path.as_posix())}",
                f"required = {str(source.required).lower()}",
            ]
        )
        if source.url:
            lines.append(f"url = {_toml_string(source.url)}")
        if source.revision:
            lines.append(f"revision = {_toml_string(source.revision)}")
        lines.append(
            f"required_files = {_toml_list(path.as_posix() for path in source.required_files)}"
        )
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _toml_list(values: Iterable[object]) -> str:
    rendered = [_toml_string(str(value)) for value in values]
    compact = "[" + ", ".join(rendered) + "]"
    if len(compact) <= 88:
        return compact
    return "[\n" + "".join(f"    {value},\n" for value in rendered) + "]"


def _run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(repository), *arguments], check=True)