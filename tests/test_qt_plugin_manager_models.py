from pathlib import Path

from PySide6.QtCore import Qt

from retroarch_overlay.app.plugin_manager import (
    CatalogPluginView,
    InstalledPluginView,
)
from retroarch_overlay.core.contracts import PluginRepositoryManifest
from retroarch_overlay.plugin_catalog import PluginCatalogEntry
from retroarch_overlay.presentation.qt import (
    CatalogPluginModel,
    CatalogPluginRole,
    InstalledPluginModel,
    InstalledPluginRole,
    PluginCatalogFilterModel,
)


def _manifest(plugin_id: str, name: str, slug: str) -> PluginRepositoryManifest:
    return PluginRepositoryManifest(
        1,
        plugin_id,
        slug,
        name,
        1,
        Path("plugin.py"),
        "MIT",
    )


def test_installed_model_exposes_columns_identity_and_accessible_text() -> None:
    row = InstalledPluginView(
        Path("C:/plugins/RAO_alpha"),
        _manifest("org.example.alpha", "Alpha", "alpha"),
    )
    model = InstalledPluginModel((row,))

    assert model.rowCount() == 1
    assert model.columnCount() == 2
    assert model.index(0, 0).data() == "Alpha"
    assert model.index(0, 1).data() == "MIT"
    assert model.index(0, 0).data(InstalledPluginRole.REPOSITORY) == row.repository_root
    assert model.index(0, 0).data(InstalledPluginRole.PLUGIN_ID) == "org.example.alpha"
    assert "license MIT" in model.index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole)


def test_catalog_model_exposes_installation_and_entry_identity() -> None:
    entry = PluginCatalogEntry(
        "org.example.alpha",
        "alpha",
        "Alpha",
        "https://github.com/example/RAO_alpha.git",
    )
    row = CatalogPluginView(entry, True)
    model = CatalogPluginModel((row,))

    assert model.index(0, 0).data() == "Alpha"
    assert model.index(0, 1).data() == "Installed"
    assert model.index(0, 0).data(CatalogPluginRole.ENTRY) is entry
    assert model.index(0, 0).data(CatalogPluginRole.INSTALLED) is True
    assert "installed" in model.index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole)


def test_catalog_proxy_filters_all_tokens_across_name_slug_and_id() -> None:
    rows = tuple(
        CatalogPluginView(
            PluginCatalogEntry(
                f"org.example.{slug}",
                slug,
                name,
                f"https://github.com/example/RAO_{slug}.git",
            ),
            False,
        )
        for slug, name in (("alpha", "Alpha Quest"), ("beta", "Beta Story"))
    )
    source = CatalogPluginModel(rows)
    proxy = PluginCatalogFilterModel()
    proxy.setSourceModel(source)

    proxy.set_query("beta org.example")

    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data() == "Beta Story"


def test_models_do_not_reset_for_identical_rows() -> None:
    installed_rows = (
        InstalledPluginView(
            Path("C:/plugins/RAO_alpha"),
            _manifest("org.example.alpha", "Alpha", "alpha"),
        ),
    )
    catalog_rows = (
        CatalogPluginView(
            PluginCatalogEntry(
                "org.example.alpha",
                "alpha",
                "Alpha",
                "https://github.com/example/RAO_alpha.git",
            ),
            True,
        ),
    )
    installed = InstalledPluginModel(installed_rows)
    catalog = CatalogPluginModel(catalog_rows)
    installed_resets = []
    catalog_resets = []
    installed.modelReset.connect(lambda: installed_resets.append(True))
    catalog.modelReset.connect(lambda: catalog_resets.append(True))

    installed.set_rows(installed_rows)
    catalog.set_rows(catalog_rows)

    assert installed_resets == []
    assert catalog_resets == []