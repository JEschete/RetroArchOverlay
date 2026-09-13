from pathlib import Path

from retroarch_overlay.app.plugin_manager import (
    PluginEditorValues,
    discover_manager_state,
    plugin_details,
)
from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.plugin_catalog import PluginCatalogEntry


def _write_plugin(root: Path, name: str, plugin_id: str, slug: str) -> Path:
    repository = root / f"RAO_{slug}"
    repository.mkdir()
    (repository / "plugin.py").write_text("PLUGIN = object()\n", encoding="utf-8")
    (repository / "plugin.toml").write_text(
        f'''schema_version = 1
plugin_id = "{plugin_id}"
slug = "{slug}"
name = "{name}"
api_version = 1
entry = "plugin.py"
license = "MIT"

[match]
cores = ["test"]
content_hints = ["{slug}"]
hashes = []
''',
        encoding="utf-8",
    )
    return repository


def test_discovery_builds_installed_rows_and_isolates_manifest_errors(
    tmp_path: Path,
) -> None:
    valid = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    broken = tmp_path / "RAO_broken"
    broken.mkdir()
    (broken / "plugin.toml").write_text("not toml = [", encoding="utf-8")

    state = discover_manager_state(tmp_path)

    assert [item.name for item in state.installed] == ["Alpha"]
    assert state.installed[0].repository_root == valid.resolve()
    assert len(state.discovery_errors) == 1


def test_catalog_rows_report_installation_and_filter_without_losing_state(
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    state = discover_manager_state(tmp_path, select=repository).with_catalog(
        (
            PluginCatalogEntry(
                "org.example.alpha",
                "alpha",
                "Alpha",
                "https://github.com/example/RAO_alpha.git",
            ),
            PluginCatalogEntry(
                "org.example.beta",
                "beta",
                "Beta Game",
                "https://github.com/example/RAO_beta.git",
            ),
        )
    )

    filtered = state.with_query("beta game")

    assert state.selected is not None
    assert [row.label for row in state.catalog] == [
        "Alpha  |  Installed",
        "Beta Game  |  Available",
    ]
    assert [row.entry.plugin_id for row in filtered.catalog] == ["org.example.beta"]
    assert filtered.selected == state.selected


def test_refresh_preserves_selection_only_while_repository_remains_installed(
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    selected = discover_manager_state(tmp_path, select=repository)

    refreshed = discover_manager_state(tmp_path, previous=selected)
    (repository / "plugin.toml").unlink()
    removed = discover_manager_state(tmp_path, previous=refreshed)

    assert refreshed.selected_repository == repository.resolve()
    assert removed.selected_repository is None


def test_details_use_discovered_manifest_without_git_inspection(
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    rom = tmp_path / "game.rom"
    save = tmp_path / "game.sav"
    rom.write_bytes(b"rom")
    save.write_bytes(b"save")
    settings = LocalPluginSettings(tmp_path / "local_settings.json")
    settings.save_rom_path("org.example.alpha", rom)
    settings.save_save_path("org.example.alpha", save)
    state = discover_manager_state(tmp_path, select=repository)
    assert state.selected is not None

    details = plugin_details(state.selected, settings)

    assert details.installed.manifest is state.selected.manifest
    assert details.rom_path == rom.resolve()
    assert details.save_path == save.resolve()
    assert "org.example.alpha" in details.raw_manifest
    assert details.source is None


def test_editor_values_validate_and_build_template_config(tmp_path: Path) -> None:
    values = PluginEditorValues(
        game_name="Example Game",
        slug="example_game",
        copyright_holder="Example Author",
        cores="nes, mesen",
        content_hints="Example, Example Game",
        content_hashes="ABC, def",
        ra_game_id="123",
        decomp_url="https://github.com/example/decomp.git",
        decomp_revision="abc123",
        required_files="src/data.json\ninclude/constants.h",
        decomp_required=True,
    )

    config = values.template_config(tmp_path)

    assert config.resolved_plugin_id == "org.jeschete.retroarch-overlay.example_game"
    assert config.ra_game_id == 123
    assert config.cores == ("nes", "mesen")
    assert config.content_hashes == ("ABC", "def")
    assert config.decomp_required_files == (
        "src/data.json",
        "include/constants.h",
    )


def test_editor_values_reject_invalid_values_before_repository_write() -> None:
    invalid_values = (
        (PluginEditorValues(game_name="", slug="game"), "Game name"),
        (PluginEditorValues(game_name="Game", slug="Bad Slug"), "Slug"),
        (
            PluginEditorValues(
                game_name="Game",
                slug="game",
                plugin_id="invalid",
            ),
            "Invalid plugin ID",
        ),
        (
            PluginEditorValues(game_name="Game", slug="game", ra_game_id="zero"),
            "must be an integer",
        ),
        (
            PluginEditorValues(
                game_name="Game",
                slug="game",
                required_files="../escape.txt",
                decomp_url="https://github.com/example/decomp.git",
            ),
            "contained relative path",
        ),
        (
            PluginEditorValues(
                game_name="Game",
                slug="game",
                decomp_required=True,
            ),
            "Decomp URL is required",
        ),
    )
    for values, message in invalid_values:
        try:
            values.validate(creating=True)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError(f"Expected invalid editor values: {values}")