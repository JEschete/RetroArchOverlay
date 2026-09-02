# Plugin Development Guide

RetroArch Overlay plugins are standalone Git repositories named `RAO_<game>`. The framework discovers immediate child directories containing a valid `plugin.toml`. Adding a plugin must not require a framework source change.

## Why Python

Python is a good fit for the current framework. The workload is dominated by UDP requests, small memory reads, parsing decomp data, formatting immutable view models, filesystem discovery, and desktop controls. None of those paths currently need native throughput. Python also makes independently cloned game plugins easy to inspect, test, and modify without a compiler toolchain.

The main costs are desktop packaging, Tk styling limits, runtime environment setup, and the absence of a compile-time boundary between third-party plugins and the framework. The launcher handles environment setup, strict manifests limit discovery behavior, and isolated lazy loading limits plugin import effects.

Do not rewrite the framework only to make it feel more production-oriented. Introduce a native component when measurements or product requirements justify one, such as:

- High-frequency memory scanning that consumes meaningful CPU time
- Native transparent-window or compositor behavior that Tk cannot provide
- A signed single-file desktop distribution with no managed Python runtime
- Strong plugin isolation that requires separate processes and a versioned IPC protocol

If one of those becomes necessary, keep manifests and presentation contracts language-neutral. A Rust host or helper can then communicate through versioned JSON or another explicit IPC format while existing Python game logic migrates incrementally.

## Prerequisites

- Python 3.11 or newer
- Git
- A RetroArch core that supports the network command interface and memory reads
- A legally obtained game image for local testing
- The RetroArch Overlay framework installed in editable mode

From the framework repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

ROMs, saves, states, generated ROMs, and credentials must never be committed.

## Create a Plugin

Use the GUI through `launch_gui.cmd`, or use the generator directly:

```powershell
.\.venv\Scripts\rao-plugin.exe create `
    --game-name "Example Game" `
    --slug example_game `
    --copyright-holder JEschete `
    --license MIT `
    --core example_core `
    --content-hint "example game" `
    --init-git
```

Required information:

- Game name: the display name shown by the overlay
- Slug: lowercase letters, numbers, and underscores, starting with a letter
- Output root: normally `plugins`
- Copyright holder: owner of the locally authored plugin code
- License: MIT or Apache-2.0

Optional information:

- Stable plugin ID
- RetroAchievements game ID
- Supported RetroArch core names
- Content filename hints
- Accepted game hashes
- Decomp repository URL and tested revision
- Files required from the decomp at runtime

The default plugin ID is `org.jeschete.retroarch-overlay.<slug>`.

## Generated Layout

```text
RAO_example_game/
    .gitignore
    LICENSE
    README.md
    RIGHTS_AND_PROVENANCE.md
    plugin.toml
    plugin.py
    resources/
        .gitkeep
    game/
        __init__.py
        adapter.py
    tests/
        test_plugin.py
```

The generator initializes the repository on `main` when `--init-git` is supplied. It never commits or pushes automatically.

The generated `.gitignore` ignores `resources/*` but explicitly keeps `resources/.gitkeep`. This preserves the directory in Git while requiring deliberate review and force-addition before any resource is published.

## Manifest Contract

Discovery parses `plugin.toml` without importing plugin Python. A typical manifest is:

```toml
schema_version = 1
plugin_id = "org.jeschete.retroarch-overlay.example_game"
slug = "example_game"
name = "Example Game"
api_version = 1
entry = "plugin.py"
license = "MIT"
ra_game_id = 1234

[match]
cores = ["example_core"]
content_hints = ["example game"]
hashes = ["accepted-game-hash"]
```

Rules:

- `plugin_id` must remain stable after publication.
- `slug` identifies settings and the isolated Python namespace.
- `entry` must stay inside the plugin repository.
- Match data belongs in the plugin, never in framework source.
- Hashes should identify compatible game revisions precisely.
- The license covers only locally authored plugin code.

The GUI exposes both structured manifest fields and a read-only raw TOML view. Use Save manifest to write through the validated manifest renderer.

## Adapter Contract

`plugin.py` must expose `PLUGIN` with a callable `create(context)` method. The returned adapter must provide `snapshot(memory)`.

```python
from retroarch_overlay.core.contracts import GameContext

from .game.adapter import Adapter


class Plugin:
    def create(self, context: GameContext) -> Adapter:
        return Adapter(context)


PLUGIN = Plugin()
```

Keep `plugin.py` lightweight. Do not read a decomp, import optional tooling, open files, or perform network access at import time. The framework imports plugin Python only after manifest matching selects it.

The adapter receives shared services and its repository path through `GameContext`. Game code may import framework contracts and immutable presentation models. It must not import Tk widgets, credential implementations, sockets, or another plugin.

## Add a Decomp Later

A plugin can begin without a decomp. Record or install one later without replacing adapter code:

```powershell
.\.venv\Scripts\rao-plugin.exe update .\plugins\RAO_example_game `
    --decomp-url https://github.com/example/example-decomp.git `
    --decomp-revision <tested-commit> `
    --decomp-required-file data/maps.json `
    --decomp-required `
    --install-decomp
```

Decomps live under `decomp_reference/<repository>` as Git submodules. Pin a tested commit. Do not treat a moving branch as the compatibility contract.

Without `--install-decomp`, the command records manifest metadata only. This is useful when preparing a plugin before acquiring the upstream repository.

Required source files are checked only when matching content activates the plugin. A missing required source makes that game unavailable without terminating the framework or disabling other plugins.

## Organize Game Code

As a plugin grows, use these ownership boundaries:

```text
game/
    adapter.py          coordination only
    state.py            immutable decoded state
    memory.py           addresses and byte decoding
    presenter.py        shared panel and map documents
    tracker.py          session observations and changes
    achievements.py     achievement metadata and detectors
    knowledge.py        authored game facts
    data/               larger authored data files
    assets/             maps, images, patches, and source records
```

Memory decoding should not produce display strings. Presentation code should not read raw memory. Asset paths must resolve from `GameContext.repository_root`.

## Test the Plugin

From a plugin nested under the framework `plugins` directory:

```powershell
$env:PYTHONPATH = "..\..\src;."
..\..\.venv\Scripts\python.exe -m pytest -q tests
```

Tests should cover:

- Manifest parsing without Python import
- Content matching
- Adapter construction through the production isolated loader
- Memory decoding with compact fake buffers
- Presentation from known state
- Missing or incomplete decomp behavior
- Decomp consistency after a recursive clone

Normal unit tests should not require a ROM, emulator, network, or full decomp. Keep external-data and live-emulator checks separate.

## Manage Plugins

The framework GUI loads a separately versioned trusted catalog into its Available games picker. A live, case-insensitive search filters entries by game name, slug, and plugin ID; whitespace-separated terms are combined so every term must match. Catalog loading is asynchronous, uses a bounded network request, caches the last valid document for offline use, and never runs Git. `RETROARCH_OVERLAY_CATALOG` may point to another trusted HTTPS catalog URL or local file. The framework joins catalog entries to installed manifests by plugin ID and verifies the advertised plugin ID and slug after cloning.

The framework GUI provides these explicit operations:

- Install: clones the selected catalog repository with `git clone --recurse-submodules`
- Install from URL: clones an explicitly supplied repository outside the catalog workflow
- Pull: requires a clean checkout, uses `git pull --ff-only`, then synchronizes submodules
- Delete: confirms first and warns when local changes exist
- Open: opens the checkout in the system file manager
- Start overlay: launches the overlay with the configured plugin root
- Settings: the global application-header command stores the local RetroArch folder containing `retroarch.cfg` and uses it for overlay startup and installed-core discovery independently of plugin selection
- Path to ROM: stores an exact local ROM file for content matching and plugin runtime context
- Discover RA: resolves existing ROM hashes first, asks the user to choose among ranked candidates when the title is not exact, normalizes subsets to their parent set, and refreshes supported hashes
- View notes on RA: opens the authenticated RetroAchievements code-notes page for the selected game ID
- Import saved page: converts one or more saved `codenotes_<game_id>.html` pages into plugin-owned JSON and Markdown

The manager does not commit, push, force-update, reset, merge, or silently discard changes.

The Path to ROM value is machine-local. It is stored by plugin ID in `%LOCALAPPDATA%/RetroArchOverlay/local_settings.json`, never in `plugin.toml` or another repository file. The manager references the selected file in place and never moves, copies, modifies, commits, or pushes the ROM. Clearing the field and saving removes that plugin's local path setting.

ROM patch files are also machine-local and ignored by generated plugin repositories. This includes IPS, BPS, UPS, RUP, xdelta, VCDIFF, bsdiff, PPF, patch, and diff formats. A decomp Git submodule is an independently versioned upstream repository, so files inside it remain governed by that upstream repository rather than the plugin.

## RetroAchievements Metadata and Code Notes

Every generated plugin may use `game/data/retroachievements/code_notes.json` and `code_notes.md` as machine-local research artifacts. Both are ignored by Git by default. Plugin runtime code must tolerate their absence because a fresh clone will not contain them.

The Discover RA action uses the public Web API. It hashes the machine-local Path to ROM in its background task, then considers configured hashes, an existing code-note game ID, and finally title matching. A single exact normalized title match is accepted automatically. Any inexact or ambiguous result opens a picker showing the title, console, and RA game ID. When a local patched ROM resolves to a subset, discovery follows its parent relationship and stores the authoritative hash union for that subset and parent. It also derives stable platform aliases from the RA console name and adds installed core identifiers whose `info/*.info` metadata matches that console in the RetroArch folder selected under Settings. The patch itself is not needed or tracked.

Overlay status remains responsive at two checks per second. Live game memory is sampled at most once per second, paused games are sampled once and then left idle, and RetroAchievements progress is loaded from a five-minute local cache or refreshed in the background. Switching games therefore does not wait on the RA network request.

Credential precedence is `RETROACHIEVEMENTS_API_KEY`, the RetroArch Overlay OS keyring entry, then the credentials saved by the RA_Backlog_Timer website under keyring service `RAHLTBScraper` or its existing `%LOCALAPPDATA%/RA_Backlog_Timer/.ra_credentials.json` fallback. If none is configured, the manager prompts for the Web API key. The key is never written to the plugin.

The public Web API does not provide code notes, and the emulator Connect API is private. Import notes through the permitted saved-page workflow:

1. Select View notes on RA in the manager and sign in to RetroAchievements when prompted by the browser.
2. Save the page as `codenotes_<game_id>.html`.
3. Save linked subset pages with the same naming pattern when their notes are relevant.
4. Select Import saved page and choose all saved pages.
5. Review `code_notes.json` for structured plugin data and `code_notes.md` for the complete readable report.

The Web API key cannot authenticate the website code-notes page. Direct scraping would require access to browser session cookies or the account password, so the manager deliberately imports a page saved by the already authenticated browser instead.

The saved HTML may remain outside the repository. Keep the normalized JSON and Markdown local as well, and record any general provenance constraints in `RIGHTS_AND_PROVENANCE.md` without committing the imported notes.

## Rights and Provenance

MIT is the default plugin license because it is simple and permissive. Apache-2.0 is also available when an explicit patent grant is preferred.

Neither license grants rights to:

- ROMs or save data
- Decompiled or reconstructed game content
- Game graphics, audio, maps, or text
- Binary patches from unknown sources
- Trademarks
- Content inside `decomp_reference`

Document every third-party source, author, URL, license, tested revision, and redistribution basis in `RIGHTS_AND_PROVENANCE.md`. Keep attribution records next to game-specific assets. If permission is unknown, say so and do not describe the material as licensed.

## Release Checklist

1. Run all plugin tests.
2. Clone the plugin into a temporary directory with `--recurse-submodules`.
3. Run tests from that fresh clone.
4. Check `git diff --check`.
5. Check `git status --short` and the staged file list.
6. Verify submodule URLs and pinned revisions.
7. Verify no ROMs, saves, states, generated ROMs, or credentials are tracked.
8. Review `RIGHTS_AND_PROVENANCE.md` and every binary asset.
9. Commit in the plugin repository, then push intentionally.