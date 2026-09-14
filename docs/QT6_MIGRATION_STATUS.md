# Qt 6 Migration Status

Status: Complete; the base and all five plugins are Qt-only and the final compatibility, packaging, and removal gates pass

Started: 2026-09-12

Selected binding: PySide6 for the Python source/wheel runtime. Standalone packaging, accessibility acceptance, native-validation acceptance, and performance acceptance were removed from the migration gate by explicit user decision on 2026-09-13.

## Environment

- Local selected interpreter: CPython 3.14.3, 64-bit
- CI interpreter: CPython 3.13 on `windows-latest`
- Verified local PySide6: 6.11.2
- Verified local Qt: 6.11.2
- Verified local shiboken6: 6.11.2
- Verified local pytest-qt: 4.5.0
- Automated Qt platform: `offscreen`
- Supported candidate range: `PySide6-Essentials>=6.11,<6.12`

Qt is the required and sole UI for the overlay, manager, `launch_gui.cmd`, manager-spawned overlays, credential prompts, and plugin companion dashboards.

## Verified

- `.[dev]` resolves and installs the required Qt runtime in the selected Python 3.14 environment.
- `QApplication` can be created and reused with stable application identity.
- A `QTimer` bridge can drain the existing controller's latest event and emit it on the Qt event loop.
- Stopping the bridge stops its timer before stopping the controller source.
- Pillow RGBA channels and alpha survive conversion to a detached `QImage` exactly.
- A converted image can be displayed through `QGraphicsScene` and `QGraphicsView`.
- The focused Qt foundation suite passes offscreen.
- Deterministic reference documents exercise plain, completion, tooltip, emphasis, progress, icon, chip, preview, alert, compact-row, and action states.
- `PanelRowModel` exposes stable display, tooltip, accessibility, completion, emphasis, progress, icon-path, and chip roles.
- Value-only row changes emit `dataChanged` without resetting the model or invalidating persistent indexes.
- Structural row changes perform one model reset.
- A native `QListView` retains keyboard focus, current selection, and scroll position across value-only updates.
- `PanelSection` and `PanelAction` support optional stable keys while preserving existing positional construction.
- Pure detail filtering, caught filtering, and section preview rules live in `core.presentation`.
- Section and action identities deterministically disambiguate duplicate legacy titles and labels.
- Section expansion, action expansion, detail filters, selection, focus, and scroll state survive keyed value-only snapshots.
- An exact controller content key resets transient presentation state when content changes, including same-title content.
- Native section/action controls expose accessible names and reconcile by identity instead of clearing the full scroll area.
- Qt consumes one immutable shared theme source.
- The light-theme success and warning text tokens were corrected from measured 4.25:1 and 3.79:1 contrast to AA-safe values above 5.1:1.
- Every semantic foreground/background pair in light, dark, and high-contrast themes is covered by a WCAG AA regression test.
- `PanelRowDelegate` renders completion symbols, emphasis, wrapped text, progress tracks/fills, bounded high-DPI icons, and chips from generic model roles only.
- Invalid plugin-provided chip or progress colors fall back to valid semantic colors instead of breaking paint.
- Chip foregrounds are repaired to black or white when the requested foreground does not meet 4.5:1 contrast.
- `QtIconCache` is LRU-bounded and preserves requested device-pixel ratio.
- The document owns vertical scrolling; row lists size to all delegate rows and expose no nested vertical scrollbars.
- Responsive content-height signals keep row, action, and section widgets at their exact live content height as wrapping and expansion change.
- Qt accessibility reports semantic rows as `ListItem` children with completion, progress, and chip text in the accessible name and tooltips in the description.
- Ambiguous base controls now expose task-oriented names: catalog search, ROM/save/RetroArch browsing, map recentering, map overlays, collected-marker filtering, and map opacity.
- Focus tests verify the visual first-hop tab order through overlay role controls, map controls, and manager catalog actions; editable fields retain numeric input instead of triggering role shortcuts.
- Dynamic labels expose their live game, location, connection, urgent, map, zoom, manager, settings, and credential-validation text as the accessible name while retaining semantic context in the accessible description.
- The first `QtOverlayWindow` renders typed snapshots and diagnostics, remembers role selection per game, supports hide-completed state, and stops its controller bridge once on close.
- `retroarch-overlay` and `retroarch-overlay-manager` bootstrap Qt directly and reject the removed `--ui` selector.
- Local settings and hero-path documents now use same-directory temporary files, flush plus `fsync`, atomic replacement, and failure cleanup; forced replacement failures preserve prior files byte-for-byte.
- Qt loads the existing theme, saved opacity, and per-game active role through `LocalPluginSettings`.
- The nonblocking Qt overlay settings dialog edits layout mode, side, width, density, game scaling, RetroArch-window management, theme, and opacity with validated ranges and choices.
- Saving overlay preferences writes profile, theme, and opacity in one atomic document update, then applies the Qt layout, native opacity, and resolved theme immediately; persistence failures remain visible without partially applying runtime state.
- Qt writes window geometry under `main-qt` and retains legacy geometry migration support.
- First Qt launch combines the legacy `main` position with `main-native` size, then constrains it to the nearest current monitor work area.
- Removed-monitor, negative-coordinate monitor, oversized-window, and Qt-specific geometry cases have pure regression coverage.
- Opacity, topmost, frameless chrome, and taskbar presence are independent `WindowPresentation` policies; the generic policy remains normal and framed while the production overlay explicitly defaults to topmost.
- The toolkit-neutral layout coordinator lives in `app.layout` and is consumed through the Qt geometry target.
- The shared coordinator retries failed native placements, distinguishes restarted RetroArch handles, and clears restoration baselines between management sessions.
- `QtGeometryTarget` and `QtResponsiveLayoutManager` translate the shared layout result into Qt work-area queries and `setGeometry` calls.
- A toolkit-neutral compact projection retains urgent/party/goals sections, uses plugin-provided compact rows or first-row fallback, preserves stable keys, and removes actions.
- `QtSecondaryPanelWindow` renders that projection as a frameless, non-taskbar, non-activating generic tool window for dual-strip layouts.
- Automatic overlay, rail, dual-strip, and pause-drawer layout refresh is enabled in the experimental Qt path when a snapshot provides `GameDisplaySpec`.
- Entering a managed Qt mode preserves the prior unmanaged Qt rectangle; close restores the exact captured RetroArch rectangle before atomically saving `main-qt`.
- Timer-driven mode changes hide/show the secondary window and role controls coherently, and all layout timers stop before teardown.
- Toolkit-neutral map viewport, projection, calibration, wrapping, tooltip, path, marker, opacity, layer-selection, and tracked-position helpers live in `core.map`.
- `QtMapView` uses `QGraphicsScene` with lazy layer loading, a four-entry LRU pixmap cache, calibrated player/waypoint/region coordinates, static tooltips, and dynamic overlay items.
- Wrapping layers reuse one implicitly shared pixmap across a 3x3 scene and create corresponding marker copies so edge-centered views contain the opposite side.
- Nonwrapping layers use one image and rely on scene bounds for clamped navigation.
- Same-layer player movement updates persistent graphics items in place without rebuilding static imagery.
- Discrete zoom levels `(1, 2, 4, 8, 16)`, native hand-drag mode, wheel stepping, and player recentering are implemented in the map component.
- A rendered-pixel test proves the offscreen scene contains both source-image pixels and the dynamic player marker.
- `QtMapWindow` provides generic layer, overlay, hide-completed, opacity, zoom, recenter, source-credit, and accessible marker-list controls.
- Map and minimap windows read the existing view-state schema and write separate `map-qt`/`minimap-qt` geometry keys with legacy geometry fallback.
- Map controls persist immediately, close hides for fast reopening, shutdown cancels timers and destroys owned windows, and hidden windows retain pending state without loading images.
- The Qt shell exposes map and minimap buttons plus Alt+M/Alt+N shortcuts only when a snapshot supplies a map document and position.
- The Qt shell supports Escape to collapse or restore the prior expanded geometry, keys 1-4 to switch visible role views without intercepting text entry, and Page Up/Page Down to scroll the main document.
- Incoming snapshots update hidden state without expanding a collapsed shell, managed-layout refreshes do not reopen it, and closing while collapsed persists the expanded rectangle rather than the temporary header height.
- Hero paths continue recording while map windows are closed, persist atomically through the existing settings service, update incrementally when visible, and do not materialize while their overlay is hidden.
- Generic waypoint marker shapes, symbols, completion colors, objective rings, encounter labels, tooltips, and accessible marker navigation are preserved.
- Objective emphasis stops while hidden; reduced-motion mode keeps a persistent ring with no animation timer.
- Marker rows wrap at both default and wide window sizes, retain full tooltips/accessibility text, and map controls use a responsive multi-row grid.
- Native Windows captures at 144 logical DPI verified the complete DW3 map window at 760x800 and 1000x820 without clipped controls or marker text.
- Hidden overlay kinds materialize on demand. On the real DW3 4096x4096 world, this reduced cold rendering from about 2.7 seconds and 5,076 items to 54.3 ms and 468 items; 200 position updates measured 0.170 ms mean and 0.173 ms p95.
- Enabling DW3's hidden encounter grid later materialized all 4,608 region/label items in 87.5 ms without rebuilding the base scene.
- Final real-plugin map measurements were nonblank with one static build and 200 dynamic updates: DW3 world 54.3 ms cold/0.173 ms p95, DW4 1024x1024 world 100.8 ms cold/0.004 ms p95, Emerald Hoenn 29.7 ms cold/0.004 ms p95, and Vagrant Story SCEN001 5.3 ms cold/0.004 ms p95.
- Toolkit-neutral alert semantics select the highest-priority urgent summary, suppress first-snapshot alert backlogs, disambiguate duplicate legacy titles, and isolate seen state by the controller's exact content key.
- The Qt overlay pins the current urgent fact outside the scrolling document and queues later `alert=True` sections through a parent-owned 3.5-second notification timer.
- Qt notifications expose a complete accessible name and emit `QAccessible.Event.Alert`; diagnostic and close paths clear pending work before teardown.
- `PluginManagerState` now owns immutable installed/catalog rows, isolated manifest errors, stable selection, query filtering, local ROM/save paths, and raw manifest details without Git inspection on selection.
- `PluginEditorValues` validates create/update input before repository mutation, preserves plugin identity during edits, and supplies the existing plugin generator and decomp installer without duplicating manifest logic in Qt.
- Installed and catalog Qt table models expose semantic identity/accessibility roles and multi-token filtering without unnecessary resets.
- `TaskCoordinator` provides one bounded daemon operation at a time with Qt-dispatched success/failure and callback suppression after close.
- `QtPluginManagerWindow` renders installed/catalog model views, searchable catalog state, selected manifest details, raw TOML, and asynchronous catalog loading.
- The Qt manager invokes existing bounded services for catalog/URL install, fast-forward update, inspected and explicitly confirmed delete, repository opening, and overlay launch.
- Repository operation controls disable while busy, recover after failure, refresh installed/catalog state after success, and preserve the selected repository where applicable.
- The scrollable manifest editor creates and updates validated manifests, browses plugin/ROM/save paths, persists local paths, prevents slug changes, and drives optional decomp-submodule setup.
- The Qt settings dialog persists RetroArch location and network-command state, while shared credential resolution preserves explicit, stored, and Qt-prompted RetroAchievements API-key precedence.
- RetroAchievements workflows discover metadata from local hashes, handle ambiguous game selection, open code-note pages, and import selected code-note exports through bounded tasks.
- The manager's responsive action grid and editor remain usable at its minimum window size, and explicit child palettes prevent native dark-mode colors from leaking into light-theme editor surfaces.
- `retroarch-overlay-manager` and `launch_gui.cmd` start the Qt manager, and manager-launched overlays use the sole Qt entry path.
- Production Qt imports are restricted by an AST-based gate to `QtCore`, `QtGui`, and `QtWidgets`; `QtTest` remains test-only.
- The required dependency installs `PySide6-Essentials` directly. A clean 6.11.2 environment excludes both the PySide6 meta-package and the unused 435.64 MiB Addons distribution.
- The Windows deployment allowlist contains only `qwindows`, `qmodernwindowsstyle`, and the GIF/ICO/JPEG image readers observed in a native plugin trace; PNG succeeds without a separate plugin.
- Before creating a Windows `QApplication`, the host checks that every allowlisted plugin exists and reports the missing paths plus an exact Essentials reinstall command.
- The bounded package verifier builds from a temporary staged source, inspects wheel metadata and notices, installs the wheel and its required Qt runtime into a fresh environment, starts Qt outside the checkout, exercises all four entry points, verifies reinstall/uninstall settings preservation, and removes its environment without dirtying the repository.
- The isolated 6.11.2 package run measured approximately 2.01 MiB for the application, 204.27 MiB for Essentials, and 2.96 MiB for shiboken.
- Windows CI now runs the isolated package verifier after the normal suite.
- Architecture tests scan core production modules for Tkinter and every plugin's top-level Python modules and `game/` package for GUI-toolkit imports.
- No plugin production module imports Tkinter, PySide6, or PyQt6, and no temporary GUI-toolkit exception remains.
- The final Qt-only base suite passes with 332 tests, 7 native-only skips, and no warnings in the local offscreen environment.
- The opt-in native Windows suite passes 7 tests covering normal, topmost/translucent, and frameless/tool policies, the production overlay's default topmost/frame-fit behavior, live policy round trips, four-monitor movement, and repeated full-process startup/shutdown.
- All independent plugin suites pass against the extended contracts: Pokemon Red 71, Dragon Warrior III 86, Pokemon Emerald 171 plus 61 subtests, Dragon Warrior IV 98, and Vagrant Story 73.
- Both Pokémon wild-IV comparators now rank the active wild Pokémon against the
    best same-family candidate in party and PC storage. Emerald reads all 14 live
    boxes once per encounter; Red reads all 12 checksum-valid boxes from the
    configured save and labels them as last-save data.
- The overlay is topmost by default. Frame-aware placement keeps native title
    bars and borders inside the desktop work area, and manual drag/resize undocks
    automatic placement without a later snap-back.
- The generic companion starts as a desktop-height right rail, migrates the old
    1260-pixel default, permits a 420-pixel minimum width, persists frame position,
    wraps control-heavy workspaces, and substitutes compact navigation plus
    vertical map/record panes below 720 pixels.
- Pokemon Red now supplies native Game Boy display metadata on waiting and live
    snapshots, so all five plugins participate in automatic layout.
- The native Windows suite passes 7 tests, including the actual topmost style
    and full-height frame containment; real narrow DW4 and Vagrant captures are
    nonblank at 440x700.
- Player markers blink at a shared 450 ms cadence on full maps, minimaps,
  embedded companion maps, and popouts. Hidden maps and disabled player layers
  stop the timer and reset to a visible phase before reopening.
- Dragon Warrior III now supplies stable section/action identities, semantic roles,
  content-lifecycle isolation, real overworld/battle/local-map Qt integration,
  explicit Sphere of Light routing, Dhama readiness, and atomic generated-map
  cache writes with reuse and extractor-version invalidation coverage.
- Dragon Warrior IV now publishes generic versioned dashboard presentation
    documents and launches the isolated shared Qt dashboard host. Its six
    workspaces, world selectors, local maps, player/features/popout, manual versus
    game completion precedence, playthrough migration, search/sort, lazy encounter
    details, UI-state isolation, waiting/error states, and bounded sidecar lifecycle
    pass real-document Qt tests. The plugin-owned legacy renderer and architecture
    exception have been removed.
- Pokemon Emerald now supplies stable identities for all 48 presentation
    constructors, content/title lifecycle isolation, coherent Trainer-ID rebinding
    after save-block relocation, dense real-snapshot Qt coverage, all Frontier
    facility states, account success/failure presentation, real Route 119/Hoenn
    and route/city/interior/cave/underwater Qt maps, atomic generated images,
    renderer-versioned map/icon caches, and a bounded species-icon LRU.
- Vagrant Story now publishes six generic dashboard workspaces and launches the
    shared Qt host plus an isolated voice worker. Battle radar/master-detail,
    all 31 atlases, progressive puzzles, exact Forge controls, Challenges, every
    Codex category/image/read command, voice/TTS/cues, title/memory/card/dump
    failures, atomic derived assets, bounded process shutdown, and keyed overlay
    transitions pass executable tests. Its plugin-owned legacy renderer and the final
    plugin architecture exception have been removed.
- The cross-plugin gate discovers and loads all five repositories together,
    verifies order-independent matching, module/state/workspace/control isolation,
    malformed/import/runtime failure recovery, unsupported API diagnostics,
    content-scoped transient state, and rapid lifecycle switching.

## Runtime Finding

PySide6 6.11.2 does not export `QT_VERSION_STR` from `PySide6.QtCore`. Runtime Qt version checks must use `qVersion()`.

## Native Windows Evidence

A bounded local probe using the real `windows` Qt platform verified:

- visible framed `QMainWindow` with a nonzero native handle;
- topmost enabled and disabled independently;
- requested opacity `0.82` reported as `0.82`;
- clean close;
- 360x220 logical client area and 360x265 frame area.

The probe is now an opt-in automated gate. It verifies the native `WS_CAPTION`, `WS_EX_TOPMOST`, `WS_EX_TOOLWINDOW`, and `WS_EX_LAYERED` mappings, requested opacity, editable focus after activation, and QObject destruction on close for normal, topmost/translucent, and frameless/non-taskbar profiles.

Applying a different presentation to an already-visible window now restores visibility, exact client geometry, activation, and child focus after Qt recreates native styles. Native tests verify the full frameless/tool/topmost/translucent round trip back to a normal opaque window.

A live window also moved successfully through all four attached work areas, including a negative-coordinate portrait display, and Qt reported the expected owning `QScreen` at every stop. Five separately launched native processes each entered the real event loop, started and stopped the controller exactly once, stopped the bridge, hid the overlay, and exited with code zero.

The same probe reported 144 logical DPI and a widget device-pixel ratio of 1.0. This is recorded evidence, not a passed mixed-DPI gate; monitor transitions, coordinate interpretation, rendering sharpness, and restored geometry still require dedicated tests.

A native reference-document capture at 144 logical DPI verified readable system fonts, semantic completion/emphasis colors, progress bars, chips, project-accent checked controls, exact 90/90 and 513/513 section geometry, a single outer scroll owner, and no internal empty-band expansion. The offscreen screenshot remains layout-only evidence because that backend has no bundled fonts.

Native manager captures verified readable installed/catalog tables, manifest fields, settings surfaces, and action controls at both normal and minimum supported window sizes.

## Revised Base Gate

Approved non-goals for this migration:

- no standalone Windows executable or installer; running through Python is the selected deployment model;
- no accessibility or assistive-technology acceptance program;
- no additional native Windows, shell, taskbar, mixed-DPI, or real-window acceptance program; and
- no performance acceptance, hardware matrix, or final performance budgets.

Existing work and measurements in those areas remain useful engineering evidence,
but they no longer block the base application or any game phase.

Base closure disposition:

- maximum-density documents are validated in each owning game phase;
- Vagrant Story codex image behavior is validated in the Vagrant Story phase;
- Dragon Warrior IV and Vagrant Story dashboard/sidecar fixtures are validated in their owning phases;
- the Python source/wheel model and separate Qt licensing are documented in `QT_PACKAGING.md` and `NOTICE`; and
- the final base suite passed with 380 tests, 6 native-only skips, and 32 subtests, followed by clean independent-plugin suites.

The revised base gate closed on 2026-09-13. No plugin repository was modified
before that closure.

PySide6-Essentials is a required dependency. Qt is the only production UI.

## Implemented Files

- `presentation/qt/application.py`: single-application creation and identity
- `presentation/qt/controller_bridge.py`: Qt event-loop adapter for the existing controller
- `presentation/qt/dashboard_main.py`: isolated generic dashboard process entry point
- `presentation/qt/dashboard_window.py`: data-driven map, card, overview, and record workspaces
- `presentation/qt/credentials.py`: accessible RetroAchievements API-key prompt
- `presentation/qt/deployment.py`: runtime module/plugin allowlist and missing-plugin detection
- `presentation/qt/images.py`: detached Pillow-to-Qt image conversion
- `presentation/qt/layout.py`: Qt geometry target and shared-manager adapter
- `presentation/qt/manager_settings_dialog.py`: RetroArch and network-command settings
- `presentation/qt/map_view.py`: lazy graphics scene, wrapping tiles, calibrated markers, overlays, zoom, and bounded cache
- `presentation/qt/map_window.py`: complete generic map/minimap controls, persistence, accessibility, and lifecycle
- `presentation/qt/notifications.py`: accessible parent-owned sequential alert queue
- `presentation/qt/overlay_settings_dialog.py`: nonblocking validated layout/theme/opacity settings
- `presentation/qt/plugin_manager_models.py`: installed/catalog table models and proxy filtering
- `presentation/qt/plugin_manager_window.py`: operational Qt installed/catalog manager shell
- `presentation/qt/overlay_window.py`: production shell for snapshots, diagnostics, controls, and lifecycle
- `presentation/qt/panel_document.py`: stable section/action identities and transient view state
- `presentation/qt/panel_document_view.py`: keyed native section/action components
- `presentation/qt/panel_delegate.py`: semantic row painting and bounded high-DPI icon cache
- `presentation/qt/panel_model.py`: semantic model roles and structural/value update separation
- `presentation/qt/panel_view.py`: native list harness with stable interaction state
- `presentation/qt/secondary_window.py`: generic compact dual-strip window
- `presentation/qt/tasks.py`: Qt signal adapter for shared bounded tasks
- `presentation/qt/theme.py`: Qt palette and contrast-safe native control styling
- `presentation/qt/window_state.py`: presentation policies and legacy-compatible Qt geometry persistence
- `presentation/theme.py`: immutable theme tokens and semantic color helpers
- `core/map.py`: toolkit-neutral map geometry, wrapping, tracking, and path helpers
- `app/layout.py`: toolkit-neutral layout orchestration and RetroArch restoration lifecycle
- `app/dashboard.py`: versioned dashboard document/control store and atomic UI/game-state persistence
- `app/notifications.py`: toolkit-neutral urgent-summary and scoped alert tracking
- `app/plugin_manager.py`: toolkit-neutral installed/catalog/detail/editor manager state
- `app/ra_credentials.py`: shared credential precedence and RetroAchievements client creation
- `app/tasks.py`: toolkit-neutral single-task coordination and shutdown suppression
- `tests/test_qt_foundation.py`: focused executable binding evidence
- `tests/test_dashboard_state.py`: dashboard schema, partial-file, control, completion, and UI-state evidence
- `tests/test_qt_dashboard_window.py`: generic dashboard workspace, map, record, lifecycle, and failure evidence
- `tests/reference_documents.py`: deterministic shared-contract fixtures
- `tests/test_main.py`: Qt-only bootstrap and removed-selector behavior
- `tests/test_app_layout.py`: shared layout placement/retry/restart lifecycle
- `tests/test_local_settings.py`: atomic settings and hero-path failure safety
- `tests/test_qt_layout.py`: Qt target coordinate translation
- `tests/test_qt_map_view.py`: lazy loading, cache bounds, wrapping, calibration, dynamic identity, zoom, errors, and rendered pixels
- `tests/test_qt_map_window.py`: controls, responsive layout, state/geometry persistence, marker accessibility, source credit, minimap, and lifecycle
- `tests/test_qt_native_windows.py`: opt-in native Win32 style, focus, opacity, and destruction matrix
- `tests/test_qt_packaging.py`: dependency, module, plugin, command, and notice policy gates
- `tests/test_notifications.py`: urgent selection, backlog suppression, duplicate identity, and exact content scope
- `tests/test_plugin_manager_state.py`: discovery, catalog, selection, and detail state
- `tests/test_qt_credentials.py`: masked credential-dialog behavior
- `tests/test_qt_manager_settings_dialog.py`: settings persistence, validation, and failure behavior
- `tests/test_qt_notifications.py`: sequential timing, theme, position, accessibility text, and cancellation
- `tests/test_qt_overlay_settings_dialog.py`: full field round-trip, bounds, errors, live application, persistence, and owner shutdown
- `tests/test_qt_plugin_manager_models.py`: manager model roles, filtering, and reset behavior
- `tests/test_qt_plugin_manager_window.py`: manager views, async catalog, repository operations, and failure recovery
- `tests/test_presentation_models.py`: stable-key backward compatibility
- `tests/test_qt_overlay_window.py`: shell rendering, scope, role, alerts, diagnostics, and shutdown
- `tests/test_qt_panel_document.py`: section/action state behavior
- `tests/test_qt_panel_document_view.py`: keyed native component behavior
- `tests/test_qt_panel_delegate.py`: semantic painting, accessibility, sizing, and icon-cache evidence
- `tests/test_qt_panel_model.py`: model and interaction-state evidence
- `tests/test_qt_secondary_window.py`: compact projection, secondary geometry, theme, and lifecycle
- `tests/test_qt_tasks.py`: Qt-dispatched task success and failure
- `tests/test_qt_theme.py`: shared/Qt palette and runtime-theme evidence
- `tests/test_qt_window_state.py`: legacy geometry, monitor clamping, policy independence, and Qt-specific saves
- `tests/test_ra_credentials.py`: shared credential precedence and client construction
- `tests/test_tasks.py`: task exclusion, callback dispatch, errors, and close suppression
- `tests/test_manager_main.py`: Qt-only manager dispatch
- `tests/test_architecture.py`: whole-plugin GUI-toolkit boundary check
- `tests/test_cross_plugin_compatibility.py`: five-plugin discovery, namespace, failure-isolation, and lifecycle gate
- `tools/verify_qt_package.py`: bounded clean wheel/install/reinstall/uninstall smoke harness
- `docs/QT_PACKAGING.md`: supported versions, allowlists, recovery, release checks, and licensing obligations

## Final State

All game phases and the cross-plugin compatibility gate are complete. The user
approved final Tkinter removal on 2026-09-13. The legacy overlay, manager,
credential/layout modules, selector flags, tests, benchmark, and compatibility
imports have been removed; Qt is the sole production UI. The final base suite,
all five independent plugin suites, the 15-test cross-plugin/architecture gate,
the clean-wheel verifier, knowledge generation check, and repository whitespace
checks pass.