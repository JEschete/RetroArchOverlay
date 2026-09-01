# RetroArch Overlay

Read-only Tk overlay for RetroArch memory data. The current built-in adapters target Pokémon Emerald and Dragon Warrior III.

## Development Setup

Install the package in editable mode before running the full test suite:

```powershell
python -m pip install -e .[dev]
python -m pytest
```

The test configuration also adds `src` to `PYTHONPATH`, so focused tests can run from a fresh checkout without installation when their optional runtime dependencies are not needed.

## Pokémon Emerald Data

Emerald support derives maps, encounters, flags, Feebas tiles, catch rates, and EXP yields from a local `pokeemerald` decomp checkout. By default the app expects that checkout at:

```text
RetroArchOverlay/pokeemerald
```

You can use another location with:

```powershell
retroarch-overlay --pokeemerald-root C:\path\to\pokeemerald
```

Keeping `pokeemerald` as an external ignored checkout is the least intrusive default. A git submodule is reasonable if you want every development machine to use the exact same decomp revision, but it should stay optional because the overlay can already accept `--pokeemerald-root` and not every contributor needs Emerald data locally.

When the decomp checkout is absent, decomp-backed Emerald tests are skipped and the adapter raises a clear startup error naming the missing files.

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