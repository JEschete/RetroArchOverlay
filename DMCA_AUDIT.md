# Copyright, DMCA, and Provenance Audit

Audit date: 2026-09-01

This is a technical inventory and risk assessment, not legal advice.

## Executive Summary

No tracked Game Boy Advance or NES ROM was found in the core repository. The local Pokemon Emerald ROM is ignored and was not moved into a plugin. The most significant unresolved risks are the unlicensed `pret/pokeemerald` decompilation submodule, the undocumented Professor Oak Challenge BPS patch, and the downloaded Dragon Warrior III map images.

## Core Repository

### Dragon Warrior III maps

- Local `RAO_dragonwarrior3/resources/world.png`
- Local `RAO_dragonwarrior3/resources/underworld.png`
- Credited in the local `RAO_dragonwarrior3/resources/SOURCE.md` to Rick N. Bruns, version 1.5 (2012), hosted by VGMaps.
- No redistribution license or written permission is recorded in this repository.
- The images reproduce the complete game worlds and therefore contain substantial expressive game-derived artwork.

Risk classification: **high unresolved redistribution risk**. Attribution is not a license. The files have moved out of core into the plugin's ignored local resources directory and are not present on the current plugin branch. Before publishing them, obtain permission or replace them with independently authored maps that do not copy game artwork.

### Dragon Warrior III integration data

The temporary built-in adapter contains memory addresses, item/town names, progression facts, and achievement titles. Facts, identifiers, and short names generally carry less copyright risk than copied audiovisual assets, but RetroAchievements text and authored route descriptions should retain source attribution where applicable.

Risk classification: **moderate provenance review required**.

## RAO_pokeemerald Plugin

The plugin repository contains its own `RIGHTS_AND_PROVENANCE.md` with file-level findings.

### Locally authored Python

The adapter and tests were migrated from this repository's JEschete-authored commits. Locally authored plugin code is licensed under MIT. That license does not cover third-party game content, patches, decomps, or trademarks.

### `pret/pokeemerald` submodule

- Remote: <https://github.com/pret/pokeemerald>
- Pinned commit: `5eff78649e7170a877b961ef0b3da13b81a16038`
- No upstream `LICENSE` or `COPYING` file was found at audit time.
- The upstream tree contains reconstructed source plus graphics, audio/data, and binary map/layout assets.
- The upstream instructions require a user-supplied base ROM; no base ROM is included in the plugin.

Risk classification: **high copyright/DMCA uncertainty**. A submodule preserves provenance and avoids copying the upstream tree into plugin history, but cloning it remains an acquisition of that upstream content.

### Professor Oak Challenge patch

- BPS patch size: 33 bytes.
- Introduced by JEschete in core commit `a2b5f6101165d815e5dda2f447faa21c6dea1c06`.
- The accompanying readme identifies the clean-ROM hashes but not the patch author, source URL, license, or redistribution permission.

Risk classification: **unresolved provenance**. Its tiny size limits embedded expression, but it should be replaced by an authoritative download reference or documented permission before a public release.

## Excluded Material

- `resources/Pokemon - Emerald Version (USA, Europe).gba` is local, ignored, and not tracked.
- ROMs, saves, states, generated ROM outputs, credentials, and secrets are excluded by repository ignore rules.
- The migration must never copy a user's ROM into a plugin or Git history.

## Release Gates

1. Keep Apache-2.0 limited to the locally authored core and MIT limited to locally authored plugin code.
2. Resolve or remove the Dragon Warrior III map images before public plugin publication.
3. Decide whether the legal risk of the `pret/pokeemerald` submodule is acceptable.
4. Resolve or remove the BPS patch's missing provenance.
5. Audit `git ls-files` and submodule revisions before every release.
6. Keep catalog descriptions factual and avoid suggesting Nintendo, Game Freak, Pokemon, RetroAchievements, or VGMaps endorsement.