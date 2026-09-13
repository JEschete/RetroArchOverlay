from pathlib import Path
import shutil
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QAccessible, QPalette

from retroarch_overlay.core.retroachievements import RAGameReference
from retroarch_overlay.infrastructure.plugin_discovery import parse_plugin_manifest
from retroarch_overlay.infrastructure.retroachievements import RAGameTitleMatch
from retroarch_overlay.local_settings import LocalPluginSettings
from retroarch_overlay.plugin_catalog import PluginCatalogEntry
from retroarch_overlay.plugin_repository import PluginRepositoryState
from retroarch_overlay.presentation.qt import QtPluginManagerWindow
from retroarch_overlay.ra_plugin_metadata import (
    RAPluginDiscoveryResult,
    RAGameSelectionRequired,
)


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


def test_window_renders_installed_details_and_raw_manifest(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    settings = LocalPluginSettings(tmp_path / "settings.json")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=settings,
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.show()

    window.installed_table.selectRow(0)

    assert window.plugin_title.text() == "Alpha"
    assert "Plugin ID: org.example.alpha" in window.details_text.toPlainText()
    assert "org.example.alpha" in window.manifest_text.toPlainText()
    assert window.selected_installed_repository() == repository.resolve()
    assert window.open_button.isEnabled()


def test_ambiguous_manager_controls_have_contextual_names_and_tab_order(
    qtbot,
    tmp_path: Path,
) -> None:
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()

    assert window.catalog_search.accessibleName() == "Search available games"
    assert window.browse_rom_button.accessibleName() == "Browse for ROM file"
    assert window.browse_save_button.accessibleName() == "Browse for save file"
    status = QAccessible.queryAccessibleInterface(window.status_label)
    assert status is not None
    assert status.text(QAccessible.Text.Name) == "Ready"
    assert status.text(QAccessible.Text.Description) == "Plugin manager status"

    window.catalog_search.setFocus()
    qtbot.keyClick(window.catalog_search, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.refresh_catalog_button


def test_catalog_search_and_install_button_follow_selection(qtbot, tmp_path: Path) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    entries = (
        PluginCatalogEntry(
            "org.example.alpha",
            "alpha",
            "Alpha",
            "https://github.com/example/RAO_alpha.git",
        ),
        PluginCatalogEntry(
            "org.example.beta",
            "beta",
            "Beta Story",
            "https://github.com/example/RAO_beta.git",
        ),
    )
    window._task_succeeded(window._catalog_task_label, entries)

    window.catalog_search.setText("beta")
    window.catalog_table.selectRow(0)

    assert window.catalog_proxy.rowCount() == 1
    assert window.selected_catalog_entry().plugin_id == "org.example.beta"
    assert window.install_button.isEnabled()

    window.catalog_search.clear()
    window.catalog_table.selectRow(0)
    assert window.selected_catalog_entry().plugin_id == "org.example.alpha"
    assert not window.install_button.isEnabled()


def test_refresh_preserves_selected_repository(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    window.refresh_installed()

    assert window.selected_installed_repository() == repository.resolve()
    assert window.plugin_title.text() == "Alpha"


def test_async_catalog_load_and_busy_state(qtbot, tmp_path: Path, monkeypatch) -> None:
    entry = PluginCatalogEntry(
        "org.example.beta",
        "beta",
        "Beta Story",
        "https://github.com/example/RAO_beta.git",
    )
    monkeypatch.setattr(
        "retroarch_overlay.presentation.qt.plugin_manager_window.load_plugin_catalog",
        lambda: (entry,),
    )
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)

    window.refresh_catalog()
    assert not window.refresh_catalog_button.isEnabled()
    qtbot.waitUntil(lambda: window.catalog_model.rowCount() == 1)

    assert window.status_label.text() == "Catalog loaded with 1 available games"
    assert window.refresh_catalog_button.isEnabled()


def _repository_state(repository: Path) -> PluginRepositoryState:
    return PluginRepositoryState(
        repository.resolve(),
        parse_plugin_manifest(repository),
        "abc123",
        "main",
        False,
    )


def test_catalog_install_uses_expected_identity_and_refreshes_selection(
    qtbot,
    tmp_path: Path,
) -> None:
    entry = PluginCatalogEntry(
        "org.example.beta",
        "beta",
        "Beta Story",
        "https://github.com/example/RAO_beta.git",
    )
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window._catalog_loaded((entry,))
    window.catalog_table.selectRow(0)

    def install(*args, **kwargs):
        repository = _write_plugin(
            tmp_path,
            "Beta Story",
            "org.example.beta",
            "beta",
        )
        assert args == (tmp_path.resolve(), entry.repository)
        assert kwargs == {
            "expected_plugin_id": entry.plugin_id,
            "expected_slug": entry.slug,
        }
        return _repository_state(repository)

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.get_plugin",
        side_effect=install,
    ):
        window.install_button.click()
        qtbot.waitUntil(lambda: window.installed_model.rowCount() == 1)

    assert window.selected_installed_repository() == (tmp_path / "RAO_beta").resolve()
    assert window.status_label.text() == "Installed Beta Story"


def test_update_selected_repository_uses_bounded_service(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    state = _repository_state(repository)
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.update_plugin_repository",
        return_value=state,
    ) as update:
        window.update_button.click()
        qtbot.waitUntil(lambda: window.status_label.text() == "Updated Alpha")

    update.assert_called_once_with(repository.resolve())
    assert window.update_button.isEnabled()


def test_delete_requires_inspection_and_explicit_confirmation(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    state = _repository_state(repository)
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    with (
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.inspect_plugin_repository",
            return_value=state,
        ) as inspect,
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.delete_plugin_repository",
            side_effect=lambda *_args, **_kwargs: shutil.rmtree(repository),
        ) as delete,
    ):
        window.delete_button.click()
        qtbot.waitUntil(lambda: window.installed_model.rowCount() == 0)

    inspect.assert_called_once_with(repository.resolve())
    delete.assert_called_once_with(
        tmp_path.resolve(),
        repository.resolve(),
        allow_dirty=False,
    )
    assert window.status_label.text() == "Deleted Alpha"


def test_open_and_launch_use_existing_services(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    settings = LocalPluginSettings(tmp_path / "settings.json")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=settings,
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    process = Mock(pid=1234)

    with (
        patch("retroarch_overlay.presentation.qt.plugin_manager_window.os.startfile") as startfile,
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.launch_overlay",
            return_value=process,
        ) as launch,
    ):
        window.open_button.click()
        window.launch_button.click()

    startfile.assert_called_once_with(repository.resolve())
    launch.assert_called_once_with(tmp_path.resolve(), retroarch_config=None)
    assert window.status_label.text() == "Overlay started with process 1234"


def test_repository_operation_failure_restores_controls(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.update_plugin_repository",
        side_effect=RuntimeError("dirty checkout"),
    ):
        window.update_button.click()
        qtbot.waitUntil(lambda: "dirty checkout" in window.status_label.text())

    assert window.update_button.isEnabled()
    assert not window.tasks.busy


def test_selected_plugin_populates_editable_manifest_fields(qtbot, tmp_path: Path) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)

    window.installed_table.selectRow(0)

    assert window.editor_fields["game_name"].text() == "Alpha"
    assert window.editor_fields["slug"].text() == "alpha"
    assert window.editor_fields["slug"].isReadOnly()
    assert window.editor_fields["plugin_id"].text() == "org.example.alpha"
    assert window.license_combo.currentText() == "MIT"


def test_invalid_editor_values_stop_before_create(qtbot, tmp_path: Path) -> None:
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.new_plugin()
    window.editor_fields["game_name"].setText("Bad Game")
    window.editor_fields["slug"].setText("Bad Slug")

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.create_plugin"
    ) as create:
        window.save_manifest_button.click()

    create.assert_not_called()
    assert "Slug must start" in window.status_label.text()


def test_create_plugin_uses_validated_values_and_generated_id_for_paths(
    qtbot,
    tmp_path: Path,
) -> None:
    settings = LocalPluginSettings(tmp_path / "settings.json")
    rom = tmp_path / "game.nes"
    save = tmp_path / "game.sav"
    rom.write_bytes(b"rom")
    save.write_bytes(b"save")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=settings,
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.new_plugin()
    window.editor_fields["game_name"].setText("Beta Story")
    window.editor_fields["slug"].setText("beta")
    window.editor_fields["copyright_holder"].setText("Example Author")
    window.editor_fields["cores"].setText("nes, mesen")
    window.editor_fields["content_hints"].setText("beta story")
    window.rom_path.setText(str(rom))
    window.save_path.setText(str(save))

    def create(config, *, initialize_git):
        assert initialize_git
        assert config.game_name == "Beta Story"
        assert config.cores == ("nes", "mesen")
        return _write_plugin(
            tmp_path,
            config.game_name,
            config.resolved_plugin_id,
            config.slug,
        )

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.create_plugin",
        side_effect=create,
    ):
        window.save_manifest_button.click()
        qtbot.waitUntil(lambda: window.installed_model.rowCount() == 1)

    plugin_id = "org.jeschete.retroarch-overlay.beta"
    assert window.selected_installed_repository() == (tmp_path / "RAO_beta").resolve()
    assert LocalPluginSettings(settings.path).rom_path(plugin_id) == rom.resolve()
    assert LocalPluginSettings(settings.path).save_path(plugin_id) == save.resolve()
    assert window.status_label.text() == "Saved Beta Story"


def test_update_plugin_passes_validated_fields_and_rejects_slug_change(
    qtbot,
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    window.editor_fields["game_name"].setText("Alpha Updated")
    window.editor_fields["cores"].setText("mesen, nestopia")
    window.editor_fields["ra_game_id"].setText("123")

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.update_plugin",
        return_value=parse_plugin_manifest(repository),
    ) as update:
        window.save_manifest_button.click()
        qtbot.waitUntil(lambda: not window.tasks.busy)

    kwargs = update.call_args.kwargs
    assert update.call_args.args == (repository.resolve(),)
    assert kwargs["game_name"] == "Alpha Updated"
    assert kwargs["cores"] == ("mesen", "nestopia")
    assert kwargs["ra_game_id"] == 123
    assert kwargs["update_ra_game_id"] is True

    window.editor_fields["slug"].setReadOnly(False)
    window.editor_fields["slug"].setText("changed")
    update.reset_mock()
    window.save_manifest_button.click()

    update.assert_not_called()
    assert "Slug cannot be changed" in window.status_label.text()


def test_install_decomp_uses_editor_source_values(qtbot, tmp_path: Path) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    window.editor_fields["decomp_url"].setText(
        "https://github.com/example/decomp.git"
    )
    window.editor_fields["decomp_revision"].setText("abc123")
    window.required_files.setPlainText("src/data.json")
    window.decomp_required.setChecked(True)

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.update_plugin",
        return_value=parse_plugin_manifest(repository),
    ) as update:
        window.install_decomp_button.click()
        qtbot.waitUntil(lambda: not window.tasks.busy)

    assert update.call_args.args == (repository.resolve(),)
    assert update.call_args.kwargs == {
        "decomp_url": "https://github.com/example/decomp.git",
        "decomp_revision": "abc123",
        "decomp_required_files": ("src/data.json",),
        "decomp_required": True,
        "install_decomp": True,
    }


def test_plugin_root_rom_and_save_browsers_update_fields(qtbot, tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    replacement = tmp_path / "other-plugins"
    replacement.mkdir()
    rom = tmp_path / "game.nes"
    save = tmp_path / "game.sav"
    rom.write_bytes(b"rom")
    save.write_bytes(b"save")
    window = QtPluginManagerWindow(
        plugin_root=root,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)

    with (
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.QFileDialog.getExistingDirectory",
            return_value=str(replacement),
        ),
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.QFileDialog.getOpenFileName",
            side_effect=((str(rom), ""), (str(save), "")),
        ),
    ):
        window.plugin_root_button.click()
        window.browse_rom()
        window.browse_save()

    assert window.plugin_root == replacement.resolve()
    assert window.rom_path.text() == str(rom)
    assert window.save_path.text() == str(save)


def test_ra_discovery_uses_local_hashes_and_refreshes_manifest(
    qtbot,
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    rom = tmp_path / "game.nes"
    rom.write_bytes(b"rom")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    window.rom_path.setText(str(rom))
    client = Mock()
    result = RAPluginDiscoveryResult(
        RAGameReference(123, "Alpha", 7, "NES/Famicom"),
        ("a" * 32,),
        ("nes",),
    )

    with (
        patch.object(window, "_ra_client", return_value=client),
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.ContentHashResolver.hashes_for_file",
            return_value=("b" * 32,),
        ) as hashes,
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.discover_plugin_ra_metadata",
            return_value=result,
        ) as discover,
    ):
        window.discover_ra_button.click()
        qtbot.waitUntil(lambda: window.status_label.text().startswith("RA game 123"))

    hashes.assert_called_once_with(rom)
    assert discover.call_args.args == (
        client,
        repository.resolve(),
        window.state.selected.manifest,
    )
    assert discover.call_args.kwargs["additional_hashes"] == ("b" * 32,)
    assert discover.call_args.kwargs["selected_game_id"] is None


def test_ambiguous_ra_failure_prompts_and_retries_selected_game(
    qtbot,
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    selection = RAGameSelectionRequired(
        "Alpha",
        (
            RAGameTitleMatch(
                RAGameReference(123, "Alpha Quest", 7, "NES/Famicom"),
                0.8,
                False,
            ),
        ),
    )

    with (
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.QInputDialog.getItem",
            return_value=("Alpha Quest | NES/Famicom | RA 123", True),
        ),
        patch.object(window, "discover_retroachievements") as retry,
    ):
        window._task_failed("Discovering RetroAchievements metadata", selection)

    retry.assert_called_once_with(123)


def test_open_code_notes_uses_validated_game_id(qtbot, tmp_path: Path) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    window.editor_fields["ra_game_id"].setText("123")

    with patch(
        "retroarch_overlay.presentation.qt.plugin_manager_window.QDesktopServices.openUrl",
        return_value=True,
    ) as open_url:
        window.open_notes_button.click()

    assert open_url.call_args.args[0].toString().endswith("codenotes.php?g=123")
    assert window.status_label.text().endswith("game 123")


def test_import_code_notes_uses_selected_pages_and_game_id(
    qtbot,
    tmp_path: Path,
) -> None:
    repository = _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    saved = tmp_path / "codenotes_123.html"
    saved.write_text("<html></html>", encoding="utf-8")
    target = repository / "game/data/retroachievements/code_notes.json"
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)
    window.editor_fields["ra_game_id"].setText("123")

    with (
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.QFileDialog.getOpenFileNames",
            return_value=([str(saved)], ""),
        ),
        patch(
            "retroarch_overlay.presentation.qt.plugin_manager_window.import_code_notes_pages",
            return_value=target,
        ) as import_pages,
    ):
        window.import_notes_button.click()
        qtbot.waitUntil(lambda: window.status_label.text().startswith("Imported code notes"))

    import_pages.assert_called_once_with(
        repository.resolve(),
        (saved,),
        default_game_id=123,
    )
    assert "game\\data\\retroachievements\\code_notes.json" in window.status_label.text()


def test_ra_note_actions_track_valid_game_id(qtbot, tmp_path: Path) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    assert not window.open_notes_button.isEnabled()
    window.editor_fields["ra_game_id"].setText("123")
    assert window.open_notes_button.isEnabled()
    assert window.import_notes_button.isEnabled()
    window.editor_fields["ra_game_id"].setText("invalid")
    assert not window.open_notes_button.isEnabled()


def test_manifest_editor_scrolls_and_action_grid_fits_at_minimum_size(
    qtbot,
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        auto_load_catalog=False,
    )
    window.resize(window.minimumSize())
    qtbot.addWidget(window)
    window.show()
    window.installed_table.selectRow(0)
    qtbot.waitUntil(window.isVisible)

    assert window.editor_scroll.widgetResizable()
    assert window.editor_scroll.verticalScrollBar().maximum() > 0
    assert window.editor_scroll.viewport().width() >= 500
    action_geometry = window.save_manifest_button.geometry()
    assert action_geometry.right() <= window.editor.width()
    assert action_geometry.bottom() <= window.editor.height()
    assert window.installed_table.width() >= 300


def test_light_theme_reaches_scrollable_editor_surfaces(qtbot, tmp_path: Path) -> None:
    _write_plugin(tmp_path, "Alpha", "org.example.alpha", "alpha")
    window = QtPluginManagerWindow(
        plugin_root=tmp_path,
        settings=LocalPluginSettings(tmp_path / "settings.json"),
        theme="light",
        auto_load_catalog=False,
    )
    qtbot.addWidget(window)
    window.installed_table.selectRow(0)

    for surface in (window.editor_scroll.viewport(), window.editor):
        assert surface.autoFillBackground()
        assert surface.palette().color(QPalette.ColorRole.Window).name() == "#f4f1e8"
        assert surface.palette().color(QPalette.ColorRole.WindowText).name() == "#20251f"