from __future__ import annotations

import json
from pathlib import Path

import pytest

from retroarch_overlay.adapters import AdapterRegistry
from retroarch_overlay.app.controller import DiagnosticCode, OverlayController
from retroarch_overlay.app.dashboard import DashboardStore
from retroarch_overlay.core.contracts import GameContext
from retroarch_overlay.core.errors import GameUnavailableError
from retroarch_overlay.core.models import (
    OverlaySnapshot,
    PanelAction,
    PanelRow,
    PanelSection,
    RetroArchStatus,
)
from retroarch_overlay.infrastructure.plugin_discovery import (
    DiscoveredPluginRepository,
    discover_plugin_repositories,
)
from retroarch_overlay.infrastructure.plugin_loader import RepositoryAdapter
from retroarch_overlay.presentation.qt import PanelDocumentView


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins"
EXPECTED_SLUGS = {
    "dragonwarrior3",
    "dragonwarrior4",
    "pokeemerald",
    "pokered",
    "vagrantstory",
}
STATUS_BY_SLUG = {
    "dragonwarrior3": RetroArchStatus(
        "PLAYING", "mesen", "Dragon Warrior III"
    ),
    "dragonwarrior4": RetroArchStatus(
        "PLAYING", "mesen", "Dragon Warrior IV"
    ),
    "pokeemerald": RetroArchStatus(
        "PLAYING", "mgba", "Pokemon Emerald"
    ),
    "pokered": RetroArchStatus(
        "PLAYING", "gambatte", "Pokemon Red"
    ),
    "vagrantstory": RetroArchStatus(
        "PLAYING", "swanstation", "Vagrant Story"
    ),
}


def _discover_real_plugins():
    result = discover_plugin_repositories((PLUGIN_ROOT,))
    assert result.errors == ()
    assert {value.manifest.slug for value in result.repositories} == EXPECTED_SLUGS
    return result.repositories


def _context(repository: DiscoveredPluginRepository, state_root: Path) -> GameContext:
    return GameContext(
        settings={
            "dashboard": False,
            "dashboard_launch": False,
            "dump_path": state_root / "missing-retail-dump",
        },
        repository_root=repository.repository_root,
        state_directory=state_root / repository.manifest.plugin_id,
    )


def test_all_catalog_plugins_load_in_isolated_namespaces_and_state_roots(
    tmp_path: Path,
) -> None:
    repositories = _discover_real_plugins()
    loaded = []
    for repository in repositories:
        wrapper = RepositoryAdapter(
            repository,
            _context(repository, tmp_path / "plugin-state"),
        )
        adapter = wrapper._load_adapter()
        loaded.append((repository, wrapper, adapter))

    modules = [type(adapter).__module__.split(".", 1)[0] for _, _, adapter in loaded]
    state_roots = [wrapper._context.state_directory for _, wrapper, _ in loaded]
    assert len(modules) == len(set(modules)) == 5
    assert all(module.startswith("_retroarch_overlay_plugin_") for module in modules)
    assert len(state_roots) == len(set(state_roots)) == 5
    assert all(
        path is not None and path.name == repository.manifest.plugin_id
        for repository, wrapper, _ in loaded
        for path in (wrapper._context.state_directory,)
    )
    scoped_workspaces = set()
    scoped_controls = set()
    for repository, _wrapper, adapter in loaded:
        for option in repository.manifest.options:
            assert option.key.startswith(f"{repository.manifest.slug}.")
        model = getattr(adapter, "_dashboard_model", None)
        if model is None:
            continue
        static = model.static_document()
        presentation = static.get("presentation", {})
        workspaces = [
            str(value.get("key", ""))
            for value in presentation.get("workspaces", [])
        ]
        controls = [
            str(value.get("key", ""))
            for value in presentation.get("controls", [])
        ]
        assert all(workspaces) and len(workspaces) == len(set(workspaces))
        assert len(controls) == len(set(controls))
        scoped_workspaces.update(
            (repository.manifest.plugin_id, key) for key in workspaces
        )
        scoped_controls.update(
            (repository.manifest.plugin_id, key) for key in controls
        )
    assert len(scoped_workspaces) == sum(
        len(
            getattr(adapter, "_dashboard_model").static_document()["presentation"][
                "workspaces"
            ]
        )
        for _, _, adapter in loaded
        if hasattr(adapter, "_dashboard_model")
    )

    for repository, wrapper, _adapter in loaded:
        key = ("core", repository.manifest.display_name, repository.manifest.slug)
        wrapper.activate(key)
        wrapper.deactivate()
        wrapper.activate(key)
        wrapper.deactivate()


def test_real_plugin_selection_is_independent_of_registration_order(
    tmp_path: Path,
) -> None:
    repositories = _discover_real_plugins()

    def adapters(values):
        return [
            RepositoryAdapter(
                repository,
                _context(repository, tmp_path / "state"),
            )
            for repository in values
        ]

    forward = AdapterRegistry(adapters(repositories))
    reverse = AdapterRegistry(adapters(tuple(reversed(repositories))))

    for slug, status in STATUS_BY_SLUG.items():
        first = forward.find(status)
        second = reverse.find(status)
        assert first is not None and second is not None
        assert first._repository.manifest.slug == slug
        assert second._repository.manifest.slug == slug


def test_action_and_workspace_state_are_isolated_by_content_and_plugin_scope(
    qtbot,
    tmp_path: Path,
) -> None:
    action = PanelAction(
        "OPEN DETAILS",
        "Details",
        (PanelRow("Detail"),),
        key="shared-action",
    )
    first = OverlaySnapshot(
        "First Game",
        "First",
        (
            PanelSection(
                "Section",
                (PanelRow("One"),),
                actions=(action,),
                key="shared-section",
            ),
        ),
    )
    second = OverlaySnapshot(
        "Second Game",
        "Second",
        (
            PanelSection(
                "Section",
                (PanelRow("Two"),),
                actions=(action,),
                key="shared-section",
            ),
        ),
    )
    view = PanelDocumentView()
    qtbot.addWidget(view)
    view.set_snapshot(first, content_scope="plugin-one:rom-one")
    first_section = view.state.section_views[0]
    widget = view.section_widget(first_section.identity)
    assert widget is not None
    action_widget = widget.action_widget(first_section.actions[0].identity)
    assert action_widget is not None
    action_widget.toggle_button.click()
    assert view.state.section_views[0].actions[0].expanded

    view.set_snapshot(second, content_scope="plugin-two:rom-two")
    assert not view.state.section_views[0].actions[0].expanded

    static = {
        "schema_version": 1,
        "presentation": {
            "workspaces": [
                {"key": "shared", "title": "Shared", "kind": "overview"}
            ]
        },
    }
    stores = []
    for plugin_id in ("plugin-one", "plugin-two"):
        root = tmp_path / plugin_id
        root.mkdir()
        (root / "static.json").write_text(json.dumps(static), encoding="utf-8")
        (root / "live.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8"
        )
        (root / "controls.json").write_text("{}", encoding="utf-8")
        stores.append(DashboardStore(root))
    stores[0].select_workspace("shared")
    assert stores[0].controls["workspace"] == "shared"
    assert "workspace" not in stores[1].controls


def _write_synthetic_plugin(
    root: Path,
    name: str,
    *,
    content: str,
    mode: str,
    api_version: int = 1,
) -> Path:
    repository = root / name
    repository.mkdir(parents=True)
    slug = name.replace("-", "_")
    (repository / "plugin.toml").write_text(
        f'''schema_version = 1
plugin_id = "org.example.{slug}"
slug = "{slug}"
name = "{name}"
api_version = {api_version}
entry = "plugin.py"

[match]
cores = ["test_core"]
content_hints = ["{content}"]
hashes = []
''',
        encoding="utf-8",
    )
    if mode == "import-failure":
        source = "raise RuntimeError('import failed')\n"
    else:
        snapshot_line = (
            "        raise RuntimeError('snapshot failed')\n"
            if mode == "runtime-failure"
            else "        return OverlaySnapshot(self.name, 'ok', ())\n"
        )
        source = (
            "from retroarch_overlay.models import OverlaySnapshot\n"
            "class Adapter:\n"
            f"    name = '{name}'\n"
            "    def activate(self, key): self.active = key\n"
            "    def deactivate(self): self.active = None\n"
            "    def snapshot(self, memory):\n"
            + snapshot_line
            + "class Plugin:\n"
            "    def create(self, context): return Adapter()\n"
            "PLUGIN = Plugin()\n"
        )
    (repository / "plugin.py").write_text(source, encoding="utf-8")
    return repository


def test_malformed_import_and_runtime_failures_do_not_poison_healthy_plugins(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    malformed = _write_synthetic_plugin(
        root,
        "malformed",
        content="malformed",
        mode="healthy",
    )
    (malformed / "plugin.toml").write_text("invalid = [", encoding="utf-8")
    _write_synthetic_plugin(
        root,
        "import_failure",
        content="import failure",
        mode="import-failure",
    )
    _write_synthetic_plugin(
        root,
        "runtime_failure",
        content="runtime failure",
        mode="runtime-failure",
    )
    _write_synthetic_plugin(
        root,
        "healthy",
        content="healthy",
        mode="healthy",
    )
    discovery = discover_plugin_repositories((root,))

    assert len(discovery.errors) == 1
    wrappers = {
        repository.manifest.slug: RepositoryAdapter(
            repository,
            GameContext(
                repository_root=repository.repository_root,
                state_directory=tmp_path / "state" / repository.manifest.plugin_id,
            ),
        )
        for repository in discovery.repositories
    }
    with pytest.raises(GameUnavailableError, match="import failed"):
        wrappers["import_failure"]._load_adapter()
    assert wrappers["healthy"].snapshot(object()).location == "ok"

    class Client:
        def __init__(self, status: RetroArchStatus) -> None:
            self.status = status

        def get_status(self) -> RetroArchStatus:
            return self.status

        def close(self) -> None:
            return None

    registry = AdapterRegistry(tuple(wrappers.values()))
    client = Client(RetroArchStatus("PLAYING", "test_core", "runtime failure"))
    controller = OverlayController(
        client,
        registry,
        verify_content_after_snapshot=False,
    )
    failed = controller.poll_once(1.0)
    assert failed.code == DiagnosticCode.PLUGIN_FAILED
    client.status = RetroArchStatus("PLAYING", "test_core", "healthy")
    recovered = controller.poll_once(2.0)
    assert isinstance(recovered, OverlaySnapshot)
    assert recovered.game == "healthy"


def test_unsupported_plugin_api_is_reported_without_hiding_real_catalog(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    _write_synthetic_plugin(
        root,
        "future",
        content="future",
        mode="healthy",
        api_version=99,
    )

    result = discover_plugin_repositories((PLUGIN_ROOT, root))

    assert {value.manifest.slug for value in result.repositories} == EXPECTED_SLUGS
    assert len(result.errors) == 1
    assert "unsupported api_version 99" in result.errors[0].message


def test_rapid_switching_runs_lifecycle_in_order_without_stale_events() -> None:
    first_status = RetroArchStatus("PLAYING", "core", "first", "1")
    second_status = RetroArchStatus("PLAYING", "core", "second", "2")
    idle = RetroArchStatus("MENU")

    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name
            self.events = []

        def supports(self, status, _content_hash=None):
            return self.name == status.content

        def activate(self, key):
            self.events.append(("activate", key))

        def deactivate(self):
            self.events.append(("deactivate", None))

        def snapshot(self, _memory):
            self.events.append(("snapshot", None))
            return OverlaySnapshot(self.name, self.name, ())

    class Client:
        def __init__(self) -> None:
            self.status = first_status

        def get_status(self):
            return self.status

        def close(self):
            return None

    first = Adapter("first")
    second = Adapter("second")
    client = Client()
    controller = OverlayController(
        client,
        AdapterRegistry((first, second)),
        verify_content_after_snapshot=False,
    )

    results = [controller.poll_once(1.0)]
    client.status = second_status
    results.append(controller.poll_once(2.0))
    client.status = first_status
    results.append(controller.poll_once(3.0))
    client.status = idle
    results.append(controller.poll_once(4.0))

    assert [value.game for value in results[:3]] == ["first", "second", "first"]
    assert results[3].code == DiagnosticCode.RETROARCH_STATE
    assert first.events == [
        ("activate", ("core", "first", "1")),
        ("snapshot", None),
        ("deactivate", None),
        ("activate", ("core", "first", "1")),
        ("snapshot", None),
        ("deactivate", None),
    ]
    assert second.events == [
        ("activate", ("core", "second", "2")),
        ("snapshot", None),
        ("deactivate", None),
    ]
