import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .adapters import ContentHashResolver
from .cheeves import default_cache_dir, default_retroarch_config
from .core.contracts import PluginRepositoryManifest
from .infrastructure.credentials import KeyringCredentialStore, load_backlog_timer_credentials
from .infrastructure.plugin_discovery import discover_plugin_repositories, parse_plugin_manifest
from .infrastructure.ra_code_notes import code_notes_page_url
from .infrastructure.retroachievements import RetroAchievementsClient, retroarch_setting
from .local_settings import LocalPluginSettings
from .plugin_catalog import PluginCatalogEntry, filter_catalog_entries, load_plugin_catalog
from .plugin_repository import (
    delete_plugin_repository,
    get_plugin,
    inspect_plugin_repository,
    launch_overlay,
    update_plugin_repository,
)
from .plugin_tools import PluginTemplateConfig, SUPPORTED_LICENSES, create_plugin, update_plugin
from .presentation.tk.credentials import prompt_ra_api_key
from .ra_plugin_metadata import (
    RAGameSelectionRequired,
    discover_plugin_ra_metadata,
    import_code_notes_pages,
)
from .retroarch_installation import (
    network_commands_enabled,
    set_network_commands_enabled,
)


COLORS = {
    "canvas": "#f3f6f4",
    "surface": "#ffffff",
    "ink": "#172421",
    "muted": "#66736f",
    "line": "#d7dedb",
    "accent": "#0b6b57",
    "accent_hover": "#085646",
    "sidebar": "#173b35",
    "sidebar_ink": "#f4faf7",
    "danger": "#a33a32",
}


class PluginManagerWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("RetroArch Overlay")
        self.root.geometry("1180x880")
        self.root.minsize(960, 760)
        self.root.configure(background=COLORS["canvas"])
        self.plugin_root = tk.StringVar(
            value=str(Path(__file__).resolve().parents[2] / "plugins")
        )
        self.catalog_selection = tk.StringVar(value="Loading catalog...")
        self.catalog_query = tk.StringVar()
        self.catalog_result_status = tk.StringVar()
        self.status = tk.StringVar(value="Ready")
        self.plugin_title = tk.StringVar(value="No plugin selected")
        self.plugin_meta = tk.StringVar(value="Select a plugin to view its manifest")
        self.rom_path = tk.StringVar()
        self.save_path = tk.StringVar()
        self.local_settings = LocalPluginSettings()
        configured_retroarch = self.local_settings.retroarch_path()
        self.retroarch_path = tk.StringVar(
            value=str(configured_retroarch) if configured_retroarch is not None else ""
        )
        self.retroarch_config_status = tk.StringVar()
        self.network_commands_enabled = tk.BooleanVar(value=False)
        self.fields = {
            "game_name": tk.StringVar(),
            "slug": tk.StringVar(),
            "holder": tk.StringVar(value="JEschete"),
            "license": tk.StringVar(value="MIT"),
            "plugin_id": tk.StringVar(),
            "ra_game_id": tk.StringVar(),
            "cores": tk.StringVar(),
            "hints": tk.StringVar(),
            "hashes": tk.StringVar(),
            "decomp_url": tk.StringVar(),
            "decomp_revision": tk.StringVar(),
        }
        self.required = tk.BooleanVar(value=False)
        self.selected_repository: Path | None = None
        self._manifests: dict[Path, PluginRepositoryManifest] = {}
        self._catalog_entries: tuple[PluginCatalogEntry, ...] = ()
        self._catalog_by_label: dict[str, PluginCatalogEntry] = {}
        self._busy = False
        self._configure_style()
        self._build()
        self.refresh()
        self._refresh_catalog()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=COLORS["canvas"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Canvas.TFrame", background=COLORS["canvas"])
        style.configure(
            "Title.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            font=("Segoe UI Semibold", 20),
        )
        style.configure(
            "Meta.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "Section.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="white",
            borderwidth=0,
            padding=(16, 9),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"])])
        style.configure("Quiet.TButton", padding=(12, 8))
        style.configure(
            "Danger.TButton",
            foreground=COLORS["danger"],
            padding=(12, 8),
        )
        style.configure("Treeview", rowheight=38, borderwidth=0, fieldbackground=COLORS["surface"])
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), padding=(8, 8))
        style.map("Treeview", background=[("selected", "#d9eee8")], foreground=[("selected", COLORS["ink"])])
        style.configure("TNotebook", background=COLORS["surface"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 9), font=("Segoe UI Semibold", 9))

    def _build(self) -> None:
        header = tk.Frame(self.root, background=COLORS["sidebar"], height=84)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, background=COLORS["sidebar"])
        brand.pack(side="left", padx=28, pady=16)
        tk.Label(
            brand,
            text="RETROARCH OVERLAY",
            background=COLORS["sidebar"],
            foreground=COLORS["sidebar_ink"],
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="Plugin workspace",
            background=COLORS["sidebar"],
            foreground="#b8d0c9",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        header_actions = tk.Frame(header, background=COLORS["sidebar"])
        header_actions.pack(side="right", padx=28, pady=22)
        ttk.Button(
            header_actions,
            text="Start overlay",
            style="Accent.TButton",
            command=self._launch_overlay,
        ).pack(side="right")
        ttk.Button(
            header_actions,
            text="Settings",
            style="Quiet.TButton",
            command=self._open_settings,
        ).pack(side="right", padx=(0, 8))

        install = ttk.Frame(self.root, style="Surface.TFrame", padding=(24, 14))
        install.pack(fill="x", padx=22, pady=(18, 10))
        ttk.Label(install, text="Available games", style="Section.TLabel").grid(
            row=0, column=0, rowspan=2, sticky="nw", padx=(0, 14), pady=(5, 0)
        )
        search = ttk.Entry(install, textvariable=self.catalog_query)
        search.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        search.bind("<KeyRelease>", self._filter_catalog)
        self.catalog_picker = ttk.Combobox(
            install,
            textvariable=self.catalog_selection,
            state="readonly",
        )
        self.catalog_picker.grid(row=1, column=1, sticky="ew")
        ttk.Label(install, textvariable=self.catalog_result_status, style="Meta.TLabel").grid(
            row=0, column=2, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            install,
            text="Clear",
            style="Quiet.TButton",
            command=self._clear_catalog_filter,
        ).grid(row=1, column=2, padx=(8, 0))
        ttk.Button(
            install,
            text="Install",
            style="Accent.TButton",
            command=self._install_catalog_plugin,
        ).grid(row=0, column=3, rowspan=2, padx=(14, 0))
        ttk.Button(
            install,
            text="Refresh catalog",
            style="Quiet.TButton",
            command=self._refresh_catalog,
        ).grid(row=0, column=4, rowspan=2, padx=(8, 0))
        ttk.Button(
            install,
            text="Install from URL",
            style="Quiet.TButton",
            command=self._install_from_url,
        ).grid(row=0, column=5, rowspan=2, padx=(8, 0))
        install.columnconfigure(1, weight=1)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        sidebar = ttk.Frame(body, style="Surface.TFrame", padding=16)
        content = ttk.Frame(body, style="Surface.TFrame", padding=22)
        body.add(sidebar, weight=2)
        body.add(content, weight=5)
        self._build_sidebar(sidebar)
        self._build_content(content)

        footer = ttk.Frame(self.root, style="Canvas.TFrame", padding=(24, 0, 24, 12))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status, foreground=COLORS["muted"]).pack(side="left")
        ttk.Button(footer, text="Plugin folder", style="Quiet.TButton", command=self._browse_root).pack(side="right")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        title = ttk.Frame(parent, style="Surface.TFrame")
        title.pack(fill="x", pady=(0, 12))
        ttk.Label(title, text="Installed", style="Section.TLabel").pack(side="left")
        ttk.Button(title, text="Refresh", style="Quiet.TButton", command=self.refresh).pack(side="right")
        self.tree = ttk.Treeview(parent, columns=("license",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Plugin")
        self.tree.heading("license", text="License")
        self.tree.column("#0", width=210, minwidth=150)
        self.tree.column("license", width=90, anchor="center", stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._select_plugin)
        ttk.Button(parent, text="New plugin", style="Accent.TButton", command=self._clear).pack(
            fill="x", pady=(14, 0)
        )

    def _build_content(self, parent: ttk.Frame) -> None:
        heading = ttk.Frame(parent, style="Surface.TFrame")
        heading.pack(fill="x")
        labels = ttk.Frame(heading, style="Surface.TFrame")
        labels.pack(side="left", fill="x", expand=True)
        ttk.Label(labels, textvariable=self.plugin_title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(labels, textvariable=self.plugin_meta, style="Meta.TLabel").pack(anchor="w", pady=(3, 0))
        repo_actions = ttk.Frame(heading, style="Surface.TFrame")
        repo_actions.pack(side="right")
        ttk.Button(repo_actions, text="Open", style="Quiet.TButton", command=self._open_repository).pack(side="left")
        ttk.Button(repo_actions, text="Pull", style="Quiet.TButton", command=self._pull_plugin).pack(side="left", padx=6)
        ttk.Button(repo_actions, text="Delete", style="Danger.TButton", command=self._delete_plugin).pack(side="left")

        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True, pady=(18, 0))
        details = ttk.Frame(notebook, style="Surface.TFrame", padding=(4, 14))
        manifest_tab = ttk.Frame(notebook, style="Surface.TFrame", padding=(4, 14))
        notebook.add(details, text="Manifest fields")
        notebook.add(manifest_tab, text="Raw manifest")
        self._build_manifest_form(details)
        self.manifest_text = tk.Text(
            manifest_tab,
            wrap="none",
            borderwidth=1,
            relief="solid",
            background="#f8faf9",
            foreground=COLORS["ink"],
            font=("Cascadia Mono", 9),
            padx=12,
            pady=12,
        )
        self.manifest_text.pack(fill="both", expand=True)
        self.manifest_text.configure(state="disabled")

    def _open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("RetroArch Overlay Settings")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        dialog.configure(background=COLORS["canvas"])
        frame = ttk.Frame(dialog, style="Surface.TFrame", padding=22)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(frame, text="Workspace settings", style="Title.TLabel").pack(
            anchor="w", pady=(0, 12)
        )
        self._build_settings(frame)
        ttk.Button(frame, text="Close", style="Quiet.TButton", command=dialog.destroy).pack(
            anchor="e", pady=(18, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()

    def _build_settings(self, parent: ttk.Frame) -> None:
        form = ttk.Frame(parent, style="Surface.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="RetroArch folder", style="Meta.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=8
        )
        ttk.Entry(form, textvariable=self.retroarch_path).grid(row=0, column=1, sticky="ew", pady=8)
        ttk.Button(form, text="Browse", style="Quiet.TButton", command=self._browse_retroarch).grid(
            row=0, column=2, padx=(8, 0), pady=8
        )
        ttk.Label(form, textvariable=self.retroarch_config_status, style="Meta.TLabel").grid(
            row=1, column=1, sticky="w", pady=(0, 12)
        )
        self.network_commands_toggle = ttk.Checkbutton(
            form,
            text="Enable RetroArch network commands",
            variable=self.network_commands_enabled,
        )
        self.network_commands_toggle.grid(row=2, column=1, sticky="w", pady=(0, 12))
        ttk.Button(form, text="Save settings", style="Accent.TButton", command=self._save_settings).grid(
            row=3, column=1, sticky="w"
        )
        form.columnconfigure(1, weight=1)
        self._sync_retroarch_status()

    def _build_manifest_form(self, parent: ttk.Frame) -> None:
        rows = (
            (("Game name", "game_name"), ("Supported cores", "cores")),
            (("Slug", "slug"), ("Content hints", "hints")),
            (("Plugin ID", "plugin_id"), ("Content hashes", "hashes")),
            (("Copyright holder", "holder"), ("Decomp Git URL", "decomp_url")),
            (("License", "license"), ("Decomp revision", "decomp_revision")),
            (("RetroAchievements ID", "ra_game_id"), None),
        )
        form = ttk.Frame(parent, style="Surface.TFrame")
        form.pack(fill="both", expand=True)
        for row, groups in enumerate(rows):
            for group, field in enumerate(groups):
                if field is None:
                    continue
                label, key = field
                base_column = group * 2
                ttk.Label(form, text=label, style="Meta.TLabel").grid(
                    row=row, column=base_column, sticky="w", padx=(0, 8), pady=6
                )
                if key == "license":
                    widget = ttk.Combobox(
                        form,
                        textvariable=self.fields[key],
                        values=SUPPORTED_LICENSES,
                        state="readonly",
                    )
                else:
                    widget = ttk.Entry(form, textvariable=self.fields[key])
                widget.grid(
                    row=row,
                    column=base_column + 1,
                    sticky="ew",
                    padx=(0, 22) if group == 0 else (0, 0),
                    pady=6,
                )
        ttk.Label(form, text="Path to ROM", style="Meta.TLabel").grid(
            row=6, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.rom_path).grid(
            row=6, column=1, columnspan=2, sticky="ew", pady=6
        )
        ttk.Button(form, text="Browse", style="Quiet.TButton", command=self._browse_rom).grid(
            row=6, column=3, sticky="e", padx=(8, 0), pady=6
        )
        ttk.Label(form, text="Path to save file", style="Meta.TLabel").grid(
            row=7, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(form, textvariable=self.save_path).grid(
            row=7, column=1, columnspan=2, sticky="ew", pady=6
        )
        ttk.Button(form, text="Browse", style="Quiet.TButton", command=self._browse_save).grid(
            row=7, column=3, sticky="e", padx=(8, 0), pady=6
        )
        self.required_files = tk.Text(
            form,
            height=4,
            wrap="none",
            borderwidth=1,
            relief="solid",
            font=("Cascadia Mono", 9),
            padx=8,
            pady=6,
        )
        self.required_files.grid(row=8, column=1, columnspan=3, sticky="nsew", pady=6)
        ttk.Label(form, text="Required decomp files", style="Meta.TLabel").grid(
            row=8, column=0, sticky="nw", pady=6
        )
        options = ttk.Frame(form, style="Surface.TFrame")
        options.grid(row=9, column=0, columnspan=4, sticky="w", pady=(10, 6))
        ttk.Checkbutton(options, text="Decomp required at runtime", variable=self.required).pack(side="left")
        ttk.Button(
            options,
            text="Install submodule",
            style="Quiet.TButton",
            command=self._install_submodule,
        ).pack(side="left", padx=18)
        actions = ttk.Frame(form, style="Surface.TFrame")
        actions.grid(row=10, column=0, columnspan=4, sticky="e", pady=(6, 0))
        ttk.Button(actions, text="Discover RA", style="Quiet.TButton", command=self._discover_ra).pack(side="left")
        ttk.Button(actions, text="View notes on RA", style="Quiet.TButton", command=self._open_code_notes).pack(
            side="left", padx=6
        )
        ttk.Button(actions, text="Import saved page", style="Quiet.TButton", command=self._import_code_notes).pack(
            side="left", padx=(0, 12)
        )
        ttk.Button(actions, text="Save manifest", style="Accent.TButton", command=self._save_or_create).pack(side="left")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=1)
        form.columnconfigure(3, weight=1)
        form.rowconfigure(8, weight=1)

    def refresh(self, select: Path | None = None) -> None:
        self._manifests.clear()
        self.tree.delete(*self.tree.get_children())
        result = discover_plugin_repositories((Path(self.plugin_root.get()),))
        for repository in result.repositories:
            self._manifests[repository.repository_root.resolve()] = repository.manifest
            self.tree.insert(
                "",
                "end",
                iid=str(repository.repository_root),
                text=repository.manifest.display_name,
                values=(repository.manifest.license_expression or "None",),
            )
        self.status.set(f"{len(result.repositories)} installed, {len(result.errors)} manifest errors")
        self._render_catalog()
        if select is not None and self.tree.exists(str(select.resolve())):
            self.tree.selection_set(str(select.resolve()))
            self.tree.focus(str(select.resolve()))
            self._select_plugin()

    def _select_plugin(self, _event: object = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.selected_repository = Path(selection[0])
        try:
            manifest = self._repository_manifest(self.selected_repository)
            source = next((item for item in manifest.sources if item.kind == "git-submodule"), None)
            values = {
                "game_name": manifest.display_name,
                "slug": manifest.slug,
                "plugin_id": manifest.plugin_id,
                "license": manifest.license_expression or "MIT",
                "ra_game_id": str(manifest.ra_game_id or ""),
                "cores": ", ".join(sorted(manifest.supported_cores)),
                "hints": ", ".join(manifest.content_hints),
                "hashes": ", ".join(sorted(manifest.content_hashes)),
                "decomp_url": source.url if source else "",
                "decomp_revision": source.revision if source else "",
            }
            for key, value in values.items():
                self.fields[key].set(value)
            rom_path = self.local_settings.rom_path(manifest.plugin_id)
            self.rom_path.set(str(rom_path) if rom_path is not None else "")
            save_path = self.local_settings.save_path(manifest.plugin_id)
            self.save_path.set(str(save_path) if save_path is not None else "")
            self.required.set(source.required if source else False)
            self.required_files.delete("1.0", "end")
            if source:
                self.required_files.insert("1.0", "\n".join(path.as_posix() for path in source.required_files))
            self.plugin_title.set(manifest.display_name)
            self.plugin_meta.set(f"{self.selected_repository.name}  |  installed locally")
            self._show_manifest(self.selected_repository / "plugin.toml")
        except Exception as error:
            self._show_error("Unable to inspect plugin", error)

    def _repository_manifest(self, repository: Path) -> PluginRepositoryManifest:
        resolved = repository.resolve()
        manifest = self._manifests.get(resolved)
        if manifest is None:
            manifest = parse_plugin_manifest(resolved)
            self._manifests[resolved] = manifest
        return manifest

    def _save_or_create(self) -> None:
        if self.selected_repository is None:
            self._create_plugin()
        else:
            self._save_manifest()

    def _create_plugin(self) -> None:
        try:
            rom_path = self._rom_path_value()
            config = PluginTemplateConfig(
                game_name=self.fields["game_name"].get().strip(),
                slug=self.fields["slug"].get().strip(),
                output_root=Path(self.plugin_root.get()),
                copyright_holder=self.fields["holder"].get().strip(),
                license_expression=self.fields["license"].get(),
                plugin_id=self.fields["plugin_id"].get().strip(),
                ra_game_id=self._optional_int(self.fields["ra_game_id"].get()),
                cores=self._csv("cores"),
                content_hints=self._csv("hints"),
                content_hashes=self._csv("hashes"),
                decomp_url=self.fields["decomp_url"].get().strip(),
                decomp_revision=self.fields["decomp_revision"].get().strip(),
                decomp_required_files=self._required_file_values(),
                decomp_required=self.required.get(),
            )
            repository = create_plugin(config, initialize_git=True)
            self.local_settings.save_rom_path(config.resolved_plugin_id, rom_path)
            self.local_settings.save_save_path(config.resolved_plugin_id, self._save_path_value())
            self.refresh(repository)
            self.status.set(f"Created {repository.name}")
        except Exception as error:
            self._show_error("Unable to create plugin", error)

    def _save_manifest(self) -> None:
        assert self.selected_repository is not None
        try:
            plugin_id = self.fields["plugin_id"].get().strip()
            rom_path = self._rom_path_value()
            update_plugin(
                self.selected_repository,
                game_name=self.fields["game_name"].get().strip(),
                plugin_id=self.fields["plugin_id"].get().strip(),
                ra_game_id=self._optional_int(self.fields["ra_game_id"].get()),
                update_ra_game_id=True,
                cores=self._csv("cores"),
                content_hints=self._csv("hints"),
                content_hashes=self._csv("hashes"),
                decomp_url=self.fields["decomp_url"].get().strip() or None,
                decomp_revision=self.fields["decomp_revision"].get().strip() or None,
                decomp_required_files=self._required_file_values(),
                decomp_required=self.required.get(),
                license_expression=self.fields["license"].get(),
                copyright_holder=self.fields["holder"].get().strip() or None,
            )
            self.local_settings.save_rom_path(plugin_id, rom_path)
            self.local_settings.save_save_path(plugin_id, self._save_path_value())
            self.refresh(self.selected_repository)
            self.status.set(f"Saved {self.selected_repository.name}")
        except Exception as error:
            self._show_error("Unable to save manifest", error)

    def _install_catalog_plugin(self) -> None:
        entry = self._catalog_by_label.get(self.catalog_selection.get())
        if entry is None:
            messagebox.showinfo(
                "Select a game",
                "Select an available game from the catalog first.",
                parent=self.root,
            )
            return
        if entry.plugin_id in {manifest.plugin_id for manifest in self._manifests.values()}:
            messagebox.showinfo(
                "Already installed",
                f"{entry.name} is already installed.",
                parent=self.root,
            )
            return
        self._install_repository(entry.repository, catalog_entry=entry)

    def _install_from_url(self) -> None:
        url = simpledialog.askstring(
            "Install plugin from URL",
            "HTTPS Git repository URL",
            parent=self.root,
        )
        if url:
            self._install_repository(url.strip())

    def _install_repository(
        self,
        url: str,
        *,
        catalog_entry: PluginCatalogEntry | None = None,
    ) -> None:
        url = url.strip()
        if not url:
            messagebox.showinfo("Repository URL required", "Enter a Git repository URL first.", parent=self.root)
            return
        self._run_task(
            "Cloning plugin...",
            lambda: get_plugin(
                Path(self.plugin_root.get()),
                url,
                expected_plugin_id=catalog_entry.plugin_id if catalog_entry else None,
                expected_slug=catalog_entry.slug if catalog_entry else None,
            ),
            lambda state: self._task_complete(f"Installed {state.path.name}", state.path),
        )

    def _refresh_catalog(self) -> None:
        self.catalog_selection.set("Loading catalog...")
        self.catalog_picker.configure(values=())

        def worker() -> None:
            try:
                entries = load_plugin_catalog()
            except Exception as error:
                self.root.after(0, lambda error=error: self._catalog_failed(error))
            else:
                self.root.after(0, lambda: self._catalog_loaded(entries))

        threading.Thread(target=worker, daemon=True).start()

    def _catalog_loaded(self, entries: tuple[PluginCatalogEntry, ...]) -> None:
        self._catalog_entries = entries
        self._render_catalog()
        self.status.set(f"Catalog loaded with {len(entries)} available games")

    def _catalog_failed(self, error: Exception) -> None:
        self._catalog_entries = ()
        self._catalog_by_label = {}
        self.catalog_picker.configure(values=())
        self.catalog_selection.set("Catalog unavailable")
        self.status.set(f"Catalog unavailable: {error}")

    def _render_catalog(self) -> None:
        if not hasattr(self, "catalog_picker") or not self._catalog_entries:
            return
        installed = {manifest.plugin_id for manifest in self._manifests.values()}
        query = self.catalog_query.get() if hasattr(self, "catalog_query") else ""
        entries = filter_catalog_entries(self._catalog_entries, query)
        labels = tuple(
            f"{entry.name}  |  {'Installed' if entry.plugin_id in installed else 'Available'}"
            for entry in entries
        )
        self._catalog_by_label = dict(zip(labels, entries))
        picker_values = labels or ("No matching games",)
        self.catalog_picker.configure(values=picker_values)
        if hasattr(self, "catalog_result_status"):
            self.catalog_result_status.set(
                f"{len(entries)} match{'es' if len(entries) != 1 else ''}"
            )
        current = self.catalog_selection.get()
        self.catalog_selection.set(
            current if current in self._catalog_by_label else picker_values[0]
        )

    def _filter_catalog(self, _event: object = None) -> None:
        self._render_catalog()

    def _clear_catalog_filter(self) -> None:
        self.catalog_query.set("")
        self._render_catalog()

    def _pull_plugin(self) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        repository = self.selected_repository
        self._run_task(
            "Updating plugin...",
            lambda: update_plugin_repository(repository),
            lambda state: self._task_complete(f"Updated to {state.revision}", state.path),
        )

    def _install_submodule(self) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        try:
            self._validate_install_request()
        except Exception as error:
            self._show_error("Unable to install submodule", error)
            return
        repository = self.selected_repository
        self._run_task(
            "Installing decomp submodule...",
            lambda: update_plugin(
                repository,
                decomp_url=self.fields["decomp_url"].get().strip(),
                decomp_revision=self.fields["decomp_revision"].get().strip() or None,
                decomp_required_files=self._required_file_values(),
                decomp_required=self.required.get(),
                install_decomp=True,
            ),
            lambda _manifest: self._task_complete("Installed decomp submodule", repository),
        )

    def _delete_plugin(self) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        repository = self.selected_repository
        try:
            state = inspect_plugin_repository(repository)
        except Exception as error:
            self._show_error("Unable to inspect plugin", error)
            return
        warning = f"Delete {state.manifest.display_name} from this computer?"
        if state.dirty:
            warning += "\n\nThis checkout has uncommitted changes."
        if not messagebox.askyesno("Delete plugin", warning, icon="warning", parent=self.root):
            return
        self._run_task(
            "Deleting plugin...",
            lambda: delete_plugin_repository(Path(self.plugin_root.get()), repository, allow_dirty=state.dirty),
            lambda _result: self._after_delete(repository),
        )

    def _launch_overlay(self) -> None:
        try:
            process = launch_overlay(
                Path(self.plugin_root.get()),
                retroarch_config=self.local_settings.retroarch_config(),
            )
            self.status.set(f"Overlay started with process {process.pid}")
        except Exception as error:
            self._show_error("Unable to start overlay", error)

    def _discover_ra(self, selected_game_id: int | None = None) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        try:
            client = self._ra_client()
            manifest = self._repository_manifest(self.selected_repository)
        except Exception as error:
            self._show_error("RetroAchievements setup failed", error)
            return
        repository = self.selected_repository
        rom_path = self._rom_path_value()

        def discover() -> object:
            local_hashes = ContentHashResolver.hashes_for_file(rom_path) if rom_path else ()
            return discover_plugin_ra_metadata(
                client,
                repository,
                manifest,
                selected_game_id=selected_game_id,
                additional_hashes=local_hashes,
                retroarch_root=self.local_settings.retroarch_path(),
            )

        self._run_task(
            "Discovering RetroAchievements metadata...",
            discover,
            lambda result: self._ra_discovery_complete(
                repository,
                result.game.game_id,
                len(result.hashes),
                len(result.cores),
            ),
        )

    def _open_code_notes(self) -> None:
        try:
            game_id = self._selected_ra_game_id()
        except Exception as error:
            self._show_error("RetroAchievements game ID required", error)
            return
        webbrowser.open(code_notes_page_url(game_id))
        self.status.set(f"Opened authenticated code-notes page for game {game_id}")

    def _import_code_notes(self) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        try:
            game_id = self._selected_ra_game_id()
        except Exception as error:
            self._show_error("RetroAchievements game ID required", error)
            return
        selected = filedialog.askopenfilenames(
            parent=self.root,
            title="Select saved RetroAchievements code-notes pages",
            filetypes=(("HTML pages", "*.html;*.htm"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            path = import_code_notes_pages(
                self.selected_repository,
                tuple(Path(value) for value in selected),
                default_game_id=game_id,
            )
            markdown_path = path.with_suffix(".md")
            self.status.set(
                f"Imported code notes into {path.relative_to(self.selected_repository)} "
                f"and {markdown_path.relative_to(self.selected_repository)}"
            )
        except Exception as error:
            self._show_error("Unable to import code notes", error)

    def _open_repository(self) -> None:
        if self.selected_repository is None:
            self._selection_required()
            return
        os.startfile(self.selected_repository)

    def _ra_client(self) -> RetroAchievementsClient:
        config_path = self.local_settings.retroarch_config() or default_retroarch_config()
        username = retroarch_setting(config_path, "cheevos_username")
        api_key = os.environ.get("RETROACHIEVEMENTS_API_KEY", "")
        store = KeyringCredentialStore()
        if not api_key and username:
            api_key = store.get(username)
        if not api_key:
            backlog_credentials = load_backlog_timer_credentials()
            if backlog_credentials is not None:
                username = backlog_credentials.username
                api_key = backlog_credentials.api_key
        if not username:
            raise RuntimeError(
                "Configure RetroAchievements in RetroArch or the RA Backlog Timer website first"
            )
        if not api_key:
            api_key = prompt_ra_api_key(username).strip()
            if api_key and store.available:
                store.set(username, api_key)
        if not api_key:
            raise RuntimeError("A RetroAchievements Web API key is required")
        return RetroAchievementsClient(username, api_key, cache_dir=default_cache_dir())

    def _selected_ra_game_id(self) -> int:
        value = self.fields["ra_game_id"].get().strip()
        if not value:
            raise ValueError("Discover or enter the RetroAchievements game ID first")
        return int(value)

    def _ra_discovery_complete(self, repository: Path, game_id: int, hash_count: int, core_count: int) -> None:
        self._busy = False
        self.refresh(repository)
        self.status.set(
            f"RA game {game_id} discovered with {hash_count} hashes and {core_count} core identifiers"
        )

    def _clear(self) -> None:
        self.selected_repository = None
        for key, field in self.fields.items():
            field.set("MIT" if key == "license" else "JEschete" if key == "holder" else "")
        self.required.set(False)
        self.rom_path.set("")
        self.save_path.set("")
        self.required_files.delete("1.0", "end")
        self.tree.selection_remove(self.tree.selection())
        self.plugin_title.set("Create a plugin")
        self.plugin_meta.set("A new RAO_<game> repository will be initialized on main")
        self._set_manifest_text("Complete the fields, then select Save manifest.")

    def _browse_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.plugin_root.get(), parent=self.root)
        if selected:
            self.plugin_root.set(selected)
            self._clear()
            self.refresh()

    def _browse_rom(self) -> None:
        current = Path(self.rom_path.get()).expanduser()
        initial_directory = current.parent if current.is_file() else Path.home()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select ROM file",
            initialdir=initial_directory,
            filetypes=(("All files", "*.*"),),
        )
        if selected:
            self.rom_path.set(selected)

    def _browse_save(self) -> None:
        current = Path(self.save_path.get()).expanduser()
        initial_directory = current.parent if current.is_file() else Path.home()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select save file",
            initialdir=initial_directory,
            filetypes=(("Save files", "*.srm *.sav"), ("All files", "*.*")),
        )
        if selected:
            self.save_path.set(selected)

    def _browse_retroarch(self) -> None:
        current = Path(self.retroarch_path.get()).expanduser()
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Select RetroArch folder",
            initialdir=current if current.is_dir() else Path.home(),
        )
        if selected:
            self.retroarch_path.set(selected)
            self._sync_retroarch_status()

    def _save_settings(self) -> None:
        value = self.retroarch_path.get().strip()
        try:
            self.local_settings.save_retroarch_path(Path(value) if value else None)
            network_changed = False
            config = (
                Path(value).expanduser() / "retroarch.cfg"
                if value
                else default_retroarch_config()
            )
            if hasattr(self, "network_commands_enabled") and config.is_file():
                network_changed = set_network_commands_enabled(
                    config, self.network_commands_enabled.get()
                )
            self._sync_retroarch_status()
            self.status.set(
                "Saved settings; restart RetroArch"
                if network_changed
                else "Saved local settings"
            )
        except Exception as error:
            self._show_error("Unable to save settings", error)

    def _sync_retroarch_status(self) -> None:
        value = self.retroarch_path.get().strip()
        if not value:
            self.retroarch_config_status.set("Using automatic RetroArch config discovery")
            config = default_retroarch_config()
        else:
            config = Path(value).expanduser() / "retroarch.cfg"
        self.retroarch_config_status.set(
            f"Config: {config}" if config.is_file() else "retroarch.cfg was not found in this folder"
        )
        if hasattr(self, "network_commands_enabled"):
            self.network_commands_enabled.set(network_commands_enabled(config))
        toggle = getattr(self, "network_commands_toggle", None)
        if toggle is not None:
            toggle.configure(state="normal" if config.is_file() else "disabled")

    def _show_manifest(self, path: Path) -> None:
        self._set_manifest_text(path.read_text(encoding="utf-8"))

    def _set_manifest_text(self, content: str) -> None:
        self.manifest_text.configure(state="normal")
        self.manifest_text.delete("1.0", "end")
        self.manifest_text.insert("1.0", content)
        self.manifest_text.configure(state="disabled")

    def _run_task(self, label: str, operation: object, on_success: object) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.set(label)

        def worker() -> None:
            try:
                result = operation()  # type: ignore[operator]
            except Exception as error:
                self.root.after(0, lambda: self._task_failed(error))
            else:
                self.root.after(0, lambda: on_success(result))  # type: ignore[operator]

        threading.Thread(target=worker, daemon=True).start()

    def _task_complete(self, message: str, repository: Path) -> None:
        self._busy = False
        self.refresh(repository)
        self.status.set(message)

    def _task_failed(self, error: Exception) -> None:
        self._busy = False
        if isinstance(error, RAGameSelectionRequired):
            selected_game_id = self._choose_ra_game(error)
            if selected_game_id is not None:
                self._discover_ra(selected_game_id)
            else:
                self.status.set("RetroAchievements discovery canceled")
            return
        self._show_error("Plugin operation failed", error)

    def _choose_ra_game(self, selection: RAGameSelectionRequired) -> int | None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Select RetroAchievements Game")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.configure(background=COLORS["canvas"])
        frame = ttk.Frame(dialog, padding=18, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"Matches for {selection.title}",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(0, 10))
        games = tk.Listbox(
            frame,
            width=76,
            height=min(12, max(4, len(selection.matches))),
            exportselection=False,
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            selectbackground=COLORS["accent"],
            selectforeground="white",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 10),
        )
        for match in selection.matches:
            game = match.game
            games.insert("end", f"{game.title}  |  {game.console_name}  |  RA {game.game_id}")
        games.pack(fill="both", expand=True)
        games.selection_set(0)
        result: dict[str, int | None] = {"game_id": None}

        def accept() -> None:
            selected = games.curselection()
            if selected:
                result["game_id"] = selection.matches[selected[0]].game.game_id
                dialog.destroy()

        buttons = ttk.Frame(frame, style="Surface.TFrame")
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Use selected game", style="Accent.TButton", command=accept).pack(
            side="right", padx=(0, 8)
        )
        games.bind("<Double-Button-1>", lambda _event: accept())
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        games.focus_set()
        self.root.wait_window(dialog)
        return result["game_id"]

    def _after_delete(self, repository: Path) -> None:
        self._busy = False
        self._clear()
        self.refresh()
        self.status.set(f"Deleted {repository.name}")

    def _validate_install_request(self) -> None:
        if not self.fields["decomp_url"].get().strip():
            raise ValueError("Installing a decomp requires a decomp Git URL")

    def _selection_required(self) -> None:
        messagebox.showinfo("Select a plugin", "Select an installed plugin first.", parent=self.root)

    def _show_error(self, title: str, error: Exception) -> None:
        self.status.set(str(error))
        messagebox.showerror(title, str(error), parent=self.root)

    def _csv(self, key: str) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.fields[key].get().split(",") if value.strip())

    def _required_file_values(self) -> tuple[str, ...]:
        return tuple(line.strip() for line in self.required_files.get("1.0", "end").splitlines() if line.strip())

    def _rom_path_value(self) -> Path | None:
        value = self.rom_path.get().strip()
        return Path(value) if value else None

    def _save_path_value(self) -> Path | None:
        value = self.save_path.get().strip()
        return Path(value) if value else None

    @staticmethod
    def _optional_int(value: str) -> int | None:
        return int(value) if value.strip() else None


def main() -> None:
    root = tk.Tk()
    PluginManagerWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()