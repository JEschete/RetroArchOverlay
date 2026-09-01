# RetroArch Overlay

Read-only Tk overlay for RetroArch memory data. Dragon Warrior III remains a temporary built-in adapter while Pokemon Emerald is loaded from a standalone plugin repository.

The project is migrating to a blank core harness with each game maintained as a standalone Git plugin repository. See [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) for the filesystem discovery, repository ownership, and decomp-submodule design.

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

```powershell
retroarch-overlay-cheeves 31446456df04356cb9f2145bada42ed2 `
	--console-id 5 `
	--code-notes-dir .\saved-ra-pages `
	--related-game-id 668 `
	--output-dir .\research
```

The exporter discovers subset links present in saved code-note pages. It never requests or writes achievement trigger definitions.