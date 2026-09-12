# RetroArch Overlay

Read-only Tk overlay for RetroArch memory data. Game behavior is loaded from standalone plugin repositories, including Dragon Warrior III and Pokemon Emerald.

## Smart Layouts

Installed plugins declare their native display geometry. On Windows, the overlay locates the RetroArch client area and selected monitor work area, then applies an aspect-aware companion layout:

- Windowed, resizable RetroArch uses a side rail and restores the original emulator window geometry when the overlay exits.
- Borderless or exclusive-fullscreen content uses existing pillarbox space as compact side strips when those strips are wide enough.
- Narrow displays fall back to a movable overlay instead of producing unusable strips.
- Pausing in Auto mode opens the larger pause-drawer layout.
- Game Boy Advance defaults to integer-perfect `240x160` scaling, preferring `6x` (`1440x960`) on a 1080p display.
- 4:3 content remains aspect-correct and uses the wider side space available on 16:9 monitors.

Use the gear button in the overlay header to choose Auto, Rail, Dual Strips, or Overlay mode; rail side and width; compact or normal density; integer or fit scaling; emulator-window management; the theme; and rail opacity. Themes are Auto, Light, Dark, or High Contrast; Auto follows the Windows app theme and is overridden by the system high-contrast setting. The rail is fully opaque by default; lowering opacity makes it see-through while idle and it lifts toward legible on hover. Layout, theme, opacity, the active rail tab per game, and main/map window geometry are saved under `%LOCALAPPDATA%/RetroArchOverlay/local_settings.json`.

The rail tabs are All, Area, Party, and Goals. All is the default and shows every section in one scroll; the others narrow it to that role, with urgent sections always kept visible.

Panel rows carry optional structure that plugins may supply: a progress bar, coloured chips, a small icon, and an emphasis colour. Section detail views expand inline within the rail, and lists longer than a dozen rows gain a type-to-filter box.

Keyboard access includes `Tab`/`Shift+Tab` for controls, `1`-`4` to switch rail tabs, `Escape` to collapse or expand, `Alt+M` for the map, `Alt+N` for the minimap, and `Page Up`/`Page Down` for scrolling.

Runtime diagnostics are written to `%LOCALAPPDATA%/RetroArchOverlay/logs/retroarch-overlay.log` with bounded rotation. `--log-level`, `--retroarch-timeout`, and `--snapshot-interval` tune diagnostics and polling without source changes.

The project is migrating to a blank core harness with each game maintained as a standalone Git plugin repository. See [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) for the filesystem discovery, repository ownership, and decomp-submodule design.

The parent framework is licensed under Apache-2.0 for its explicit patent grant. MIT is the recommended default for locally authored plugin code. Plugin licenses do not cover ROMs, third-party assets, patches, trademarks, or repositories under `decomp_reference`; each plugin must document those separately.

## Development Setup

Install the package in editable mode before running the full test suite:

```powershell
python -m pip install -e .[dev]
python -m pytest
```

The test configuration also adds `src` to `PYTHONPATH`, so focused tests can run from a fresh checkout without installation when their optional runtime dependencies are not needed.

## Pokemon Emerald Plugin

Clone the Emerald plugin and its pinned `pret/pokeemerald` submodule into the default discovery root:

```powershell
git clone --recurse-submodules `
	https://github.com/JEschete/RAO_pokeemerald.git `
	.\plugins\RAO_pokeemerald
```

The core discovers immediate child repositories containing `plugin.toml`. An additional root can be supplied with a repeatable option:

```powershell
retroarch-overlay --plugin-dir D:\RetroArchOverlayPlugins
```

Plugin Python is imported only after its manifest matches active content. If the submodule is missing, the plugin reports the exact `git submodule update --init --recursive` recovery command without preventing the core harness from running.

Review [DMCA_AUDIT.md](DMCA_AUDIT.md) and each plugin's rights/provenance report before public redistribution.

## Plugin Manager and Generator

Run `launch_gui.cmd` to create its virtual environment when needed, install missing runtime dependencies, and open the manager. The Available games picker loads the trusted `JEschete/RAO_catalog` manifest, marks installed games, and clones a selected game only after Install is pressed. Its live search filters case-insensitively across game names, slugs, and plugin IDs, supports multiple search terms, and can be cleared to restore the full catalog. The last valid catalog is cached under `%LOCALAPPDATA%/RetroArchOverlay` for offline use. `RETROARCH_OVERLAY_CATALOG` may select another trusted HTTPS catalog URL or local catalog file, and Install from URL remains available for an explicitly supplied third-party repository. Catalog installs verify the cloned plugin ID and slug before accepting the checkout.

The manager can inspect and edit manifests, retain a machine-local path to each ROM without copying it into a repository, apply clean fast-forward updates, synchronize submodules, delete plugins with confirmation, discover public RetroAchievements game metadata and supported hashes, import saved authenticated code-note pages, open repositories, and start the overlay. The global Settings command in the application header accepts the local RetroArch installation folder containing `retroarch.cfg`; it is independent of plugin selection. Settings also has an **Enable RetroArch network commands** checkbox. Save the setting and restart RetroArch after changing it. Discovery uses the RetroAchievements console name to populate stable platform aliases and enriches them with matching installed cores found under the selected installation's `info` folder. Local ROM and RetroArch paths are stored outside Git in `%LOCALAPPDATA%/RetroArchOverlay/local_settings.json`. The same template operations are available without Tk:

```powershell
rao-plugin create `
	--game-name "Example Game" `
	--slug example_game `
	--copyright-holder JEschete `
	--core example_core `
	--init-git

rao-plugin update .\plugins\RAO_example_game `
	--decomp-url https://github.com/example/example-decomp.git `
	--decomp-revision <tested-commit> `
	--decomp-required
```

Creation requires the game name, lowercase slug, output root, copyright holder, and a license choice. Plugin ID defaults to `org.jeschete.retroarch-overlay.<slug>`. RetroAchievements ID, core names, content hints/hashes, and decomp metadata are optional. Add `--install-decomp` to either command only when the recorded repository should also be installed as a Git submodule; create mode initializes Git automatically in that case.

See [docs/PLUGIN_DEVELOPMENT.md](docs/PLUGIN_DEVELOPMENT.md) for the repository contract, adapter boundaries, decomp workflow, tests, management operations, and release checklist.

## Achievement Research Export

The `retroarch-overlay-cheeves` command resolves a RetroAchievements MD5 game hash with the authenticated public Web API and writes `<game_name>_cheeves.md`. It includes the matched achievement set, its parent core set when the match is a subset, and any explicitly supplied or saved-page-linked related sets.

Set your own Web API key through `RETROACHIEVEMENTS_API_KEY` or the shared OS keyring. Do not put the key on the command line.

```powershell
retroarch-overlay-cheeves 31446456df04356cb9f2145bada42ed2 `
	--console-id 5 `
	--output-dir .\research
```

`--console-id` is optional, but supplying it avoids downloading every active system catalog. Catalog responses are cached for seven days because the RA API documentation recommends aggressive caching for game lists with hashes.

Extended game and achievement metadata is cached as well. If RA is blocked or temporarily unavailable, the exporter will use an existing stale cache rather than fail. A machine with access can populate the cache once and copy that cache directory to the blocked machine.

RetroAchievements does not expose memory/code notes through its public Web API. The emulator Connect API does expose them, but its terms explicitly prohibit using it for third-party tools. To include memory notes without using that endpoint:

1. Sign in to RetroAchievements in a browser.
2. Open `https://retroachievements.org/codenotes.php?g=<game_id>` for each core set or subset.
3. Save each page as `codenotes_<game_id>.html` in one directory.
4. Pass that directory with `--code-notes-dir`.

Imported `game/data/retroachievements/code_notes.json` and `code_notes.md` files are machine-local research artifacts and are ignored by plugin repositories by default.

ROM patch artifacts are also ignored by generated plugins. Select the resulting local ROM in the manager instead; Discover RA hashes it in the background, identifies a subset through the public RA metadata, follows its parent set, and records authoritative hashes for both sets without storing the patch or ROM in Git.

```powershell
retroarch-overlay-cheeves 31446456df04356cb9f2145bada42ed2 `
	--console-id 5 `
	--code-notes-dir .\saved-ra-pages `
	--related-game-id 668 `
	--output-dir .\research
```

The exporter discovers subset links present in saved code-note pages. It never requests or writes achievement trigger definitions.