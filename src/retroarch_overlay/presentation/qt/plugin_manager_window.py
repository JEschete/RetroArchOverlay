from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QInputDialog,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QGridLayout,
    QHeaderView,
)

from ...app.plugin_manager import (
    PluginEditorValues,
    PluginDetails,
    PluginManagerState,
    discover_manager_state,
    plugin_details,
)
from ...app.ra_credentials import create_ra_client
from ...adapters import ContentHashResolver
from ...local_settings import LocalPluginSettings
from ...plugin_catalog import load_plugin_catalog
from ...plugin_repository import (
    PluginRepositoryState,
    delete_plugin_repository,
    get_plugin,
    inspect_plugin_repository,
    launch_overlay,
    update_plugin_repository,
)
from ...plugin_tools import SUPPORTED_LICENSES, create_plugin, update_plugin
from ...cheeves import default_cache_dir, default_retroarch_config
from ...infrastructure.ra_code_notes import code_notes_page_url
from ...ra_plugin_metadata import (
    RAPluginDiscoveryResult,
    RAGameSelectionRequired,
    discover_plugin_ra_metadata,
    import_code_notes_pages,
)
from .credentials import prompt_ra_api_key
from .plugin_manager_models import (
    CatalogPluginModel,
    CatalogPluginRole,
    InstalledPluginModel,
    InstalledPluginRole,
    PluginCatalogFilterModel,
)
from .manager_settings_dialog import QtManagerSettingsDialog
from .tasks import QtTaskCoordinator
from .theme import apply_qt_theme, qt_palette


class QtPluginManagerWindow(QMainWindow):
    def __init__(
        self,
        *,
        plugin_root: Path | None = None,
        settings: LocalPluginSettings | None = None,
        theme: str | None = None,
        auto_load_catalog: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or LocalPluginSettings()
        self.plugin_root = (
            plugin_root or Path(__file__).resolve().parents[4] / "plugins"
        ).resolve()
        self.state = discover_manager_state(self.plugin_root)
        self._details: PluginDetails | None = None
        self.setWindowTitle("RetroArch Overlay Plugin Manager")
        self.resize(1180, 880)
        self.setMinimumSize(960, 700)

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 10)
        self.setCentralWidget(central)

        catalog_bar = QHBoxLayout()
        catalog_bar.addWidget(QLabel("Available games", central))
        self.catalog_search = QLineEdit(central)
        self.catalog_search.setPlaceholderText("Search catalog")
        self.catalog_search.setAccessibleName("Search available games")
        self.catalog_search.setClearButtonEnabled(True)
        self.catalog_search.textChanged.connect(self._catalog_query_changed)
        catalog_bar.addWidget(self.catalog_search, 1)
        self.refresh_catalog_button = QPushButton("Refresh catalog", central)
        self.refresh_catalog_button.clicked.connect(self.refresh_catalog)
        catalog_bar.addWidget(self.refresh_catalog_button)
        self.install_url_button = QPushButton("Install from URL", central)
        self.install_url_button.clicked.connect(self.install_from_url)
        catalog_bar.addWidget(self.install_url_button)
        self.install_button = QPushButton("Install", central)
        self.install_button.clicked.connect(self.install_selected_catalog)
        catalog_bar.addWidget(self.install_button)
        root_layout.addLayout(catalog_bar)

        self.catalog_model = CatalogPluginModel(parent=self)
        self.catalog_proxy = PluginCatalogFilterModel(self)
        self.catalog_proxy.setSourceModel(self.catalog_model)
        self.catalog_table = QTableView(central)
        self.catalog_table.setAccessibleName("Available plugins")
        self.catalog_table.setModel(self.catalog_proxy)
        self.catalog_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.catalog_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.catalog_table.selectionModel().selectionChanged.connect(
            lambda: self._update_action_state()
        )
        self.catalog_table.horizontalHeader().setStretchLastSection(True)
        root_layout.addWidget(self.catalog_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.installed_model = InstalledPluginModel(parent=self)
        self.installed_table = QTableView(splitter)
        self.installed_table.setAccessibleName("Installed plugins")
        self.installed_table.setModel(self.installed_model)
        self.installed_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.installed_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.installed_table.setMinimumWidth(300)
        self.installed_table.selectionModel().selectionChanged.connect(
            self._installed_selection_changed
        )
        self.installed_table.horizontalHeader().setStretchLastSection(True)
        self.installed_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.installed_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        splitter.addWidget(self.installed_table)

        details = QWidget(splitter)
        details_layout = QVBoxLayout(details)
        self.plugin_title = QLabel("No plugin selected", details)
        self.plugin_meta = QLabel("Select an installed plugin", details)
        details_layout.addWidget(self.plugin_title)
        details_layout.addWidget(self.plugin_meta)
        action_bar = QHBoxLayout()
        self.open_button = QPushButton("Open", details)
        self.open_button.clicked.connect(self.open_selected_repository)
        self.update_button = QPushButton("Update", details)
        self.update_button.clicked.connect(self.update_selected_repository)
        self.delete_button = QPushButton("Delete", details)
        self.delete_button.clicked.connect(self.delete_selected_repository)
        self.new_button = QPushButton("New plugin", details)
        self.new_button.clicked.connect(self.new_plugin)
        for button in (
            self.open_button,
            self.update_button,
            self.delete_button,
            self.new_button,
        ):
            action_bar.addWidget(button)
        details_layout.addLayout(action_bar)
        tabs = QTabWidget(details)
        self.details_text = QPlainTextEdit(tabs)
        self.details_text.setReadOnly(True)
        self.details_text.setAccessibleName("Plugin details")
        self.manifest_text = QPlainTextEdit(tabs)
        self.manifest_text.setReadOnly(True)
        self.manifest_text.setAccessibleName("Raw plugin manifest")
        self.editor = QWidget()
        editor_layout = QFormLayout(self.editor)
        editor_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.editor_fields: dict[str, QLineEdit] = {}
        for label, key in (
            ("Game name", "game_name"),
            ("Slug", "slug"),
            ("Plugin ID", "plugin_id"),
            ("Copyright holder", "copyright_holder"),
            ("RetroAchievements ID", "ra_game_id"),
            ("Supported cores", "cores"),
            ("Content hints", "content_hints"),
            ("Content hashes", "content_hashes"),
            ("Decomp Git URL", "decomp_url"),
            ("Decomp revision", "decomp_revision"),
        ):
            field = QLineEdit(self.editor)
            field.setAccessibleName(label)
            self.editor_fields[key] = field
            editor_layout.addRow(label, field)
        self.license_combo = QComboBox(self.editor)
        self.license_combo.addItems(SUPPORTED_LICENSES)
        self.license_combo.setAccessibleName("License")
        editor_layout.addRow("License", self.license_combo)
        self.required_files = QPlainTextEdit(self.editor)
        self.required_files.setAccessibleName("Required decomp files")
        self.required_files.setMaximumHeight(100)
        editor_layout.addRow("Required files", self.required_files)
        self.decomp_required = QCheckBox("Required at runtime", self.editor)
        editor_layout.addRow("Decomp", self.decomp_required)
        self.rom_path = QLineEdit(self.editor)
        self.rom_path.setAccessibleName("Path to ROM")
        rom_row = QWidget(self.editor)
        rom_layout = QHBoxLayout(rom_row)
        rom_layout.setContentsMargins(0, 0, 0, 0)
        rom_layout.addWidget(self.rom_path, 1)
        self.browse_rom_button = QPushButton("Browse", rom_row)
        self.browse_rom_button.setAccessibleName("Browse for ROM file")
        self.browse_rom_button.clicked.connect(self.browse_rom)
        rom_layout.addWidget(self.browse_rom_button)
        editor_layout.addRow("ROM", rom_row)
        self.save_path = QLineEdit(self.editor)
        self.save_path.setAccessibleName("Path to save file")
        save_row = QWidget(self.editor)
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        save_layout.addWidget(self.save_path, 1)
        self.browse_save_button = QPushButton("Browse", save_row)
        self.browse_save_button.setAccessibleName("Browse for save file")
        self.browse_save_button.clicked.connect(self.browse_save)
        save_layout.addWidget(self.browse_save_button)
        editor_layout.addRow("Save", save_row)
        editor_actions = QWidget(self.editor)
        editor_actions_layout = QGridLayout(editor_actions)
        editor_actions_layout.setContentsMargins(0, 0, 0, 0)
        editor_actions_layout.setHorizontalSpacing(6)
        editor_actions_layout.setVerticalSpacing(6)
        self.install_decomp_button = QPushButton("Install decomp", editor_actions)
        self.install_decomp_button.clicked.connect(self.install_decomp)
        editor_actions_layout.addWidget(self.install_decomp_button, 0, 0)
        self.discover_ra_button = QPushButton("Discover RA", editor_actions)
        self.discover_ra_button.clicked.connect(
            lambda _checked=False: self.discover_retroachievements()
        )
        editor_actions_layout.addWidget(self.discover_ra_button, 0, 1)
        self.open_notes_button = QPushButton("Open RA notes", editor_actions)
        self.open_notes_button.clicked.connect(self.open_code_notes)
        editor_actions_layout.addWidget(self.open_notes_button, 0, 2)
        self.import_notes_button = QPushButton("Import saved page", editor_actions)
        self.import_notes_button.clicked.connect(self.import_code_notes)
        editor_actions_layout.addWidget(self.import_notes_button, 1, 0, 1, 2)
        self.save_manifest_button = QPushButton("Save manifest", editor_actions)
        self.save_manifest_button.clicked.connect(self.save_manifest)
        editor_actions_layout.addWidget(self.save_manifest_button, 1, 2)
        for column in range(3):
            editor_actions_layout.setColumnStretch(column, 1)
        editor_layout.addRow(editor_actions)
        self.editor_scroll = QScrollArea(tabs)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_scroll.setAccessibleName("Manifest fields")
        self.editor_scroll.setWidget(self.editor)
        tabs.addTab(self.editor_scroll, "Manifest fields")
        tabs.addTab(self.details_text, "Details")
        tabs.addTab(self.manifest_text, "Raw manifest")
        details_layout.addWidget(tabs, 1)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes((340, 800))
        root_layout.addWidget(splitter, 3)

        footer = QHBoxLayout()
        self.status_label = QLabel("Ready", central)
        self.status_label.setAccessibleDescription("Plugin manager status")
        footer.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton("Refresh installed", central)
        self.refresh_button.clicked.connect(self.refresh_installed)
        footer.addWidget(self.refresh_button)
        self.plugin_root_button = QPushButton("Plugin folder", central)
        self.plugin_root_button.clicked.connect(self.browse_plugin_root)
        footer.addWidget(self.plugin_root_button)
        self.launch_button = QPushButton("Start overlay", central)
        self.launch_button.clicked.connect(self.launch_overlay)
        footer.addWidget(self.launch_button)
        self.settings_button = QPushButton("Settings", central)
        self.settings_button.clicked.connect(self.open_settings)
        footer.addWidget(self.settings_button)
        root_layout.addLayout(footer)

        self.tasks = QtTaskCoordinator(self)
        self.tasks.task_started.connect(self._task_started)
        self.tasks.task_succeeded.connect(self._task_succeeded)
        self.tasks.task_failed.connect(self._task_failed)
        self._catalog_task_label = "Loading plugin catalog"
        self._pending_success: Callable[[object], None] | None = None
        resolved_theme = apply_qt_theme(self, theme or self.settings.theme())
        _, palette = qt_palette(resolved_theme)
        for surface in (
            central,
            details,
            self.editor_scroll.viewport(),
            self.editor,
        ):
            surface.setPalette(palette)
            surface.setAutoFillBackground(True)
        self._sync_models()
        self._set_editor_values(PluginEditorValues())
        self.editor_fields["ra_game_id"].textChanged.connect(
            lambda: self._update_action_state()
        )
        self._update_action_state()
        if auto_load_catalog:
            self.refresh_catalog()

    def refresh_installed(self, select: Path | None = None) -> None:
        self.state = discover_manager_state(
            self.plugin_root,
            previous=self.state,
            select=select,
        )
        self._sync_models()
        self._restore_installed_selection()
        self.status_label.setText(
            f"{len(self.state.installed)} installed, "
            f"{len(self.state.discovery_errors)} manifest errors"
        )

    def refresh_catalog(self) -> None:
        self._start_task(
            self._catalog_task_label,
            load_plugin_catalog,
            self._catalog_loaded,
        )

    def install_selected_catalog(self) -> None:
        entry = self.selected_catalog_entry()
        if entry is None:
            self.status_label.setText("Select an available catalog plugin first")
            return
        if entry.plugin_id in self.state.installed_plugin_ids:
            self.status_label.setText(f"{entry.name} is already installed")
            return
        self._install_repository(
            entry.repository,
            expected_plugin_id=entry.plugin_id,
            expected_slug=entry.slug,
        )

    def install_from_url(self) -> None:
        url, accepted = QInputDialog.getText(
            self,
            "Install plugin from URL",
            "HTTPS Git repository URL",
        )
        if accepted and url.strip():
            self._install_repository(url.strip())

    def update_selected_repository(self) -> None:
        repository = self.selected_installed_repository()
        if repository is None:
            self.status_label.setText("Select an installed plugin first")
            return
        self._start_task(
            f"Updating {repository.name}",
            lambda: update_plugin_repository(repository),
            lambda result: self._repository_task_complete("Updated", result),
        )

    def delete_selected_repository(self) -> None:
        repository = self.selected_installed_repository()
        if repository is None:
            self.status_label.setText("Select an installed plugin first")
            return
        self._start_task(
            f"Inspecting {repository.name}",
            lambda: inspect_plugin_repository(repository),
            self._confirm_delete,
        )

    def open_selected_repository(self) -> None:
        repository = self.selected_installed_repository()
        if repository is None:
            self.status_label.setText("Select an installed plugin first")
            return
        try:
            os.startfile(repository)
        except OSError as error:
            self.status_label.setText(f"Unable to open repository: {error}")

    def launch_overlay(self) -> None:
        try:
            process = launch_overlay(
                self.plugin_root,
                retroarch_config=self.settings.retroarch_config(),
            )
        except Exception as error:
            self.status_label.setText(f"Unable to start overlay: {error}")
        else:
            self.status_label.setText(f"Overlay started with process {process.pid}")

    def open_settings(self) -> None:
        dialog = QtManagerSettingsDialog(
            self.settings,
            default_retroarch_config,
            self,
        )
        dialog.exec()
        if dialog.result_status.text():
            self.status_label.setText(dialog.result_status.text())

    def new_plugin(self) -> None:
        self.installed_table.clearSelection()
        self.state = self.state.with_selection(None)
        self._details = None
        self.plugin_title.setText("Create a plugin")
        self.plugin_meta.setText("A new RAO_<game> repository will be initialized on main")
        self.details_text.clear()
        self.manifest_text.setPlainText(
            "Complete the fields, then select Save manifest."
        )
        self._set_editor_values(PluginEditorValues())
        self._update_action_state()

    def browse_plugin_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select plugin folder",
            str(self.plugin_root),
        )
        if not selected:
            return
        self.plugin_root = Path(selected).resolve()
        self.state = discover_manager_state(self.plugin_root, previous=self.state)
        self._sync_models()
        self._restore_installed_selection()

    def browse_rom(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select ROM file",
            _initial_file_directory(self.rom_path.text()),
            "All files (*.*)",
        )
        if selected:
            self.rom_path.setText(selected)

    def browse_save(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select save file",
            _initial_file_directory(self.save_path.text()),
            "Save files (*.srm *.sav);;All files (*.*)",
        )
        if selected:
            self.save_path.setText(selected)

    def save_manifest(self) -> None:
        values = self._editor_values()
        repository = self.selected_installed_repository()
        creating = repository is None
        try:
            values.validate(creating=creating)
        except ValueError as error:
            self.status_label.setText(f"Unable to save manifest: {error}")
            return
        if creating:
            config = values.template_config(self.plugin_root)

            def create() -> Path:
                created = create_plugin(config, initialize_git=True)
                self.settings.save_rom_path(
                    config.resolved_plugin_id,
                    values.optional_rom_path,
                )
                self.settings.save_save_path(
                    config.resolved_plugin_id,
                    values.optional_save_path,
                )
                return created

            self._start_task("Creating plugin", create, self._manifest_saved)
            return
        selected = self.state.selected
        assert selected is not None
        if values.slug.strip() != selected.manifest.slug:
            self.status_label.setText("Unable to save manifest: Slug cannot be changed")
            return

        def update() -> Path:
            plugin_id = values.plugin_id.strip()
            update_plugin(
                repository,
                game_name=values.game_name.strip(),
                plugin_id=plugin_id,
                ra_game_id=values.parsed_ra_game_id,
                update_ra_game_id=True,
                cores=values.parsed_cores,
                content_hints=values.parsed_content_hints,
                content_hashes=values.parsed_content_hashes,
                decomp_url=values.decomp_url.strip() or None,
                decomp_revision=values.decomp_revision.strip() or None,
                decomp_required_files=values.parsed_required_files,
                decomp_required=values.decomp_required,
                license_expression=values.license_expression,
                copyright_holder=values.copyright_holder.strip() or None,
            )
            self.settings.save_rom_path(plugin_id, values.optional_rom_path)
            self.settings.save_save_path(plugin_id, values.optional_save_path)
            return repository

        self._start_task("Saving manifest", update, self._manifest_saved)

    def install_decomp(self) -> None:
        repository = self.selected_installed_repository()
        if repository is None:
            self.status_label.setText("Select an installed plugin first")
            return
        values = self._editor_values()
        try:
            values.validate(creating=False)
        except ValueError as error:
            self.status_label.setText(f"Unable to install decomp: {error}")
            return
        if not values.decomp_url.strip():
            self.status_label.setText("Unable to install decomp: Decomp URL is required")
            return

        def install() -> Path:
            update_plugin(
                repository,
                decomp_url=values.decomp_url.strip(),
                decomp_revision=values.decomp_revision.strip() or None,
                decomp_required_files=values.parsed_required_files,
                decomp_required=values.decomp_required,
                install_decomp=True,
            )
            return repository

        self._start_task("Installing decomp submodule", install, self._manifest_saved)

    def discover_retroachievements(self, selected_game_id: int | None = None) -> None:
        repository = self.selected_installed_repository()
        selected = self.state.selected
        if repository is None or selected is None:
            self.status_label.setText("Select an installed plugin first")
            return
        try:
            client = self._ra_client()
            rom_path = self._editor_values().optional_rom_path
        except Exception as error:
            self.status_label.setText(f"RetroAchievements setup failed: {error}")
            return

        def discover() -> object:
            hashes = (
                ContentHashResolver.hashes_for_file(rom_path)
                if rom_path is not None
                else ()
            )
            return discover_plugin_ra_metadata(
                client,
                repository,
                selected.manifest,
                selected_game_id=selected_game_id,
                additional_hashes=hashes,
                retroarch_root=self.settings.retroarch_path(),
            )

        self._start_task(
            "Discovering RetroAchievements metadata",
            discover,
            self._ra_discovery_complete,
        )

    def open_code_notes(self) -> None:
        try:
            game_id = self._editor_values().parsed_ra_game_id
        except ValueError as error:
            self.status_label.setText(f"RetroAchievements game ID required: {error}")
            return
        if game_id is None:
            self.status_label.setText("RetroAchievements game ID required")
            return
        QDesktopServices.openUrl(QUrl(code_notes_page_url(game_id)))
        self.status_label.setText(
            f"Opened authenticated code-notes page for game {game_id}"
        )

    def import_code_notes(self) -> None:
        repository = self.selected_installed_repository()
        if repository is None:
            self.status_label.setText("Select an installed plugin first")
            return
        try:
            game_id = self._editor_values().parsed_ra_game_id
        except ValueError as error:
            self.status_label.setText(f"RetroAchievements game ID required: {error}")
            return
        if game_id is None:
            self.status_label.setText("RetroAchievements game ID required")
            return
        selected, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select saved RetroAchievements code-notes pages",
            str(Path.home()),
            "HTML pages (*.html *.htm);;All files (*.*)",
        )
        if not selected:
            return
        pages = tuple(Path(value) for value in selected)
        self._start_task(
            "Importing RetroAchievements code notes",
            lambda: import_code_notes_pages(
                repository,
                pages,
                default_game_id=game_id,
            ),
            self._code_notes_imported,
        )

    def _ra_client(self):
        config = self.settings.retroarch_config() or default_retroarch_config()
        return create_ra_client(
            config,
            default_cache_dir(),
            lambda username: prompt_ra_api_key(username, self),
        )

    def selected_catalog_entry(self):
        indexes = self.catalog_table.selectionModel().selectedRows(0)
        if not indexes:
            return None
        return indexes[0].data(CatalogPluginRole.ENTRY)

    def selected_installed_repository(self) -> Path | None:
        indexes = self.installed_table.selectionModel().selectedRows(0)
        if not indexes:
            return None
        value = indexes[0].data(InstalledPluginRole.REPOSITORY)
        return value if isinstance(value, Path) else None

    def closeEvent(self, event) -> None:
        self.tasks.close()
        super().closeEvent(event)

    def _sync_models(self) -> None:
        self.installed_model.set_rows(self.state.installed)
        self.catalog_model.set_rows(self.state.catalog)
        self.catalog_proxy.set_query(self.state.query)
        self.catalog_search.setText(self.state.query)

    def _catalog_query_changed(self, query: str) -> None:
        self.state = self.state.with_query(query)
        self.catalog_proxy.set_query(query)
        self._update_action_state()

    def _installed_selection_changed(self) -> None:
        repository = self.selected_installed_repository()
        self.state = self.state.with_selection(repository)
        selected = self.state.selected
        if selected is None:
            self._details = None
            self.plugin_title.setText("No plugin selected")
            self.plugin_meta.setText("Select an installed plugin")
            self.details_text.clear()
            self.manifest_text.clear()
            self._set_editor_values(PluginEditorValues())
        else:
            try:
                self._details = plugin_details(selected, self.settings)
            except (OSError, ValueError) as error:
                self._details = None
                self.status_label.setText(f"Unable to inspect plugin: {error}")
            else:
                self._render_details(self._details)
        self._update_action_state()

    def _render_details(self, details: PluginDetails) -> None:
        manifest = details.installed.manifest
        self.plugin_title.setText(manifest.display_name)
        self.plugin_meta.setText(
            f"{details.installed.repository_root.name} · installed locally"
        )
        source = details.source
        lines = (
            f"Plugin ID: {manifest.plugin_id}",
            f"Slug: {manifest.slug}",
            f"License: {manifest.license_expression or 'None'}",
            f"RetroAchievements ID: {manifest.ra_game_id or ''}",
            f"Cores: {', '.join(sorted(manifest.supported_cores))}",
            f"Content hints: {', '.join(manifest.content_hints)}",
            f"ROM: {details.rom_path or ''}",
            f"Save: {details.save_path or ''}",
            f"Source: {source.url if source else ''}",
            f"Revision: {source.revision if source else ''}",
            "Required files:",
            *(f"  {path}" for path in details.required_files),
        )
        self.details_text.setPlainText("\n".join(lines))
        self.manifest_text.setPlainText(details.raw_manifest)
        self._set_editor_values(PluginEditorValues.from_details(details))

    def _restore_installed_selection(self) -> None:
        selected = self.state.selected_repository
        if selected is None:
            self.installed_table.clearSelection()
            self._installed_selection_changed()
            return
        for row in range(self.installed_model.rowCount()):
            index = self.installed_model.index(row, 0)
            if index.data(InstalledPluginRole.REPOSITORY) == selected:
                self.installed_table.selectRow(row)
                return

    def _task_started(self, label: str) -> None:
        self.status_label.setText(label)
        self._update_action_state()

    def _task_succeeded(self, label: str, result: object) -> None:
        callback = self._pending_success
        self._pending_success = None
        if callback is None and label == self._catalog_task_label:
            callback = self._catalog_loaded
        if callback is not None:
            try:
                callback(result)
            except Exception as error:
                self.status_label.setText(f"{label} completion failed: {error}")
        else:
            self.status_label.setText(f"{label} completed")
        self._update_action_state()

    def _task_failed(self, label: str, error: object) -> None:
        self._pending_success = None
        if isinstance(error, RAGameSelectionRequired):
            selected_game_id = self._choose_ra_game(error)
            if selected_game_id is not None:
                self.discover_retroachievements(selected_game_id)
            else:
                self.status_label.setText("RetroAchievements discovery canceled")
            self._update_action_state()
            return
        self.status_label.setText(f"{label} failed: {error}")
        self._update_action_state()

    def _start_task(
        self,
        label: str,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> bool:
        if self.tasks.busy:
            return False
        self._pending_success = on_success
        if self.tasks.start(label, operation):
            return True
        self._pending_success = None
        return False

    def _catalog_loaded(self, result: object) -> None:
        if not isinstance(result, tuple):
            raise TypeError("Catalog loader returned an invalid result")
        self.state = self.state.with_catalog(result)
        self.catalog_model.set_rows(self.state.catalog)
        self.status_label.setText(
            f"Catalog loaded with {len(result)} available games"
        )

    def _install_repository(
        self,
        url: str,
        *,
        expected_plugin_id: str | None = None,
        expected_slug: str | None = None,
    ) -> None:
        self._start_task(
            "Installing plugin",
            lambda: get_plugin(
                self.plugin_root,
                url,
                expected_plugin_id=expected_plugin_id,
                expected_slug=expected_slug,
            ),
            lambda result: self._repository_task_complete("Installed", result),
        )

    def _repository_task_complete(self, verb: str, result: object) -> None:
        if not isinstance(result, PluginRepositoryState):
            raise TypeError("Repository operation returned an invalid result")
        self.refresh_installed(result.path)
        self.status_label.setText(f"{verb} {result.manifest.display_name}")

    def _manifest_saved(self, result: object) -> None:
        if not isinstance(result, Path):
            raise TypeError("Manifest operation returned an invalid result")
        self.refresh_installed(result)
        selected = self.state.selected
        self.status_label.setText(
            f"Saved {selected.name if selected is not None else result.name}"
        )

    def _ra_discovery_complete(self, result: object) -> None:
        if not isinstance(result, RAPluginDiscoveryResult):
            raise TypeError("RA discovery returned an invalid result")
        repository = self.selected_installed_repository()
        if repository is None:
            raise RuntimeError("Selected plugin changed during RA discovery")
        self.refresh_installed(repository)
        self.status_label.setText(
            f"RA game {result.game.game_id} discovered with "
            f"{len(result.hashes)} hashes and {len(result.cores)} core identifiers"
        )

    def _choose_ra_game(self, selection: RAGameSelectionRequired) -> int | None:
        labels = tuple(
            f"{match.game.title} | {match.game.console_name} | RA {match.game.game_id}"
            for match in selection.matches
        )
        selected, accepted = QInputDialog.getItem(
            self,
            "Select RetroAchievements Game",
            f"Matches for {selection.title}",
            labels,
            0,
            False,
        )
        if not accepted or selected not in labels:
            return None
        return selection.matches[labels.index(selected)].game.game_id

    def _code_notes_imported(self, result: object) -> None:
        if not isinstance(result, Path):
            raise TypeError("Code-note import returned an invalid path")
        repository = self.selected_installed_repository()
        shown = result.relative_to(repository) if repository is not None else result
        self.status_label.setText(f"Imported code notes into {shown}")

    def _confirm_delete(self, result: object) -> None:
        if not isinstance(result, PluginRepositoryState):
            raise TypeError("Repository inspection returned an invalid result")
        warning = f"Delete {result.manifest.display_name} from this computer?"
        if result.dirty:
            warning += "\n\nThis checkout has uncommitted changes."
        answer = QMessageBox.question(
            self,
            "Delete plugin",
            warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status_label.setText("Delete canceled")
            return
        repository = result.path
        self._start_task(
            f"Deleting {repository.name}",
            lambda: delete_plugin_repository(
                self.plugin_root,
                repository,
                allow_dirty=result.dirty,
            ),
            lambda _unused: self._delete_complete(result),
        )

    def _delete_complete(self, state: PluginRepositoryState) -> None:
        self.refresh_installed()
        self.status_label.setText(f"Deleted {state.manifest.display_name}")

    def _update_action_state(self) -> None:
        busy = self.tasks.busy
        selected = self.state.selected is not None
        entry = self.selected_catalog_entry()
        catalog_installable = entry is not None and entry.plugin_id not in self.state.installed_plugin_ids
        self.install_button.setEnabled(not busy and catalog_installable)
        self.open_button.setEnabled(not busy and selected)
        self.update_button.setEnabled(not busy and selected)
        self.delete_button.setEnabled(not busy and selected)
        self.refresh_button.setEnabled(not busy)
        self.refresh_catalog_button.setEnabled(not busy)
        self.install_url_button.setEnabled(not busy)
        self.launch_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        self.plugin_root_button.setEnabled(not busy)
        self.save_manifest_button.setEnabled(not busy)
        self.install_decomp_button.setEnabled(not busy and selected)
        self.discover_ra_button.setEnabled(not busy and selected)
        has_ra_id = False
        try:
            has_ra_id = self._editor_values().parsed_ra_game_id is not None
        except ValueError:
            pass
        self.open_notes_button.setEnabled(not busy and selected and has_ra_id)
        self.import_notes_button.setEnabled(not busy and selected and has_ra_id)

    def _editor_values(self) -> PluginEditorValues:
        return PluginEditorValues(
            game_name=self.editor_fields["game_name"].text(),
            slug=self.editor_fields["slug"].text(),
            copyright_holder=self.editor_fields["copyright_holder"].text(),
            license_expression=self.license_combo.currentText(),
            plugin_id=self.editor_fields["plugin_id"].text(),
            ra_game_id=self.editor_fields["ra_game_id"].text(),
            cores=self.editor_fields["cores"].text(),
            content_hints=self.editor_fields["content_hints"].text(),
            content_hashes=self.editor_fields["content_hashes"].text(),
            decomp_url=self.editor_fields["decomp_url"].text(),
            decomp_revision=self.editor_fields["decomp_revision"].text(),
            required_files=self.required_files.toPlainText(),
            decomp_required=self.decomp_required.isChecked(),
            rom_path=self.rom_path.text(),
            save_path=self.save_path.text(),
        )

    def _set_editor_values(self, values: PluginEditorValues) -> None:
        for key in self.editor_fields:
            self.editor_fields[key].setText(str(getattr(values, key)))
        index = self.license_combo.findText(values.license_expression)
        self.license_combo.setCurrentIndex(max(0, index))
        self.required_files.setPlainText(values.required_files)
        self.decomp_required.setChecked(values.decomp_required)
        self.rom_path.setText(values.rom_path)
        self.save_path.setText(values.save_path)
        self.editor_fields["slug"].setReadOnly(self.state.selected is not None)


def _initial_file_directory(value: str) -> str:
    path = Path(value).expanduser()
    if path.is_file():
        return str(path.parent)
    return str(path if path.is_dir() else Path.home())