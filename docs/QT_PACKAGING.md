# Qt Packaging and Distribution

Status: the Python source/wheel runtime is the selected distribution model. A
standalone Windows executable or installer is intentionally out of scope.

## Supported Runtime

- Python: 3.11 or newer; CI currently uses 3.13 and local evidence uses 3.14.
- Binding: `PySide6-Essentials>=6.11,<6.12`.
- Validated binding and Qt version: 6.11.2.
- Linkage: dynamic. Do not statically link Qt for this distribution.
- `PySide6` and `PySide6-Addons` are not runtime dependencies.

The minor-version ceiling is intentional. A later Qt minor requires correctness,
compatibility, and licensing review before the range changes.

## Module Allowlist

Production code may import only:

| Module | Accepted use |
| --- | --- |
| `QtCore` | event delivery, timers, models, geometry, and URLs |
| `QtGui` | painting, images, palettes, accessibility, shortcuts, and desktop services |
| `QtWidgets` | overlay, manager, dialogs, model views, and graphics views |

`QtTest` is test-only. `QtNetwork`, `QtSvg`, `QtOpenGL`, `QtQml`, `QtQuick`,
`QtCharts`, `QtMultimedia`, `QtTextToSpeech`, and `QtWebEngine` are not approved.
Adding a module requires a demonstrated feature need plus package-size, license,
failure-mode, and performance review.

The source import set is checked with Python's AST in
`tests/test_qt_packaging.py`; text inside comments and strings cannot satisfy or
trip the check.

## Windows Runtime Plugin Set

The required plugin set for the supported pip-installed Windows runtime is:

| Relative path | Purpose |
| --- | --- |
| `platforms/qwindows.dll` | required Windows QPA platform |
| `styles/qmodernwindowsstyle.dll` | native Windows widget style |
| `imageformats/qgif.dll` | GIF map/icon input |
| `imageformats/qico.dll` | Windows icon input |
| `imageformats/qjpeg.dll` | JPEG map/icon input |

PNG loading succeeded without a separate plugin in the validated Qt 6.11.2
runtime. A native `QT_DEBUG_PLUGINS=1` trace loaded only the five DLLs above while
the application created widgets and loaded PNG, JPEG, GIF, and ICO images.

The allowlist is duplicated deliberately in build metadata and runtime code, and
a test requires those copies to remain identical. Before `QApplication` is
created on Windows, the application checks that all five files exist. An
incomplete runtime fails with the missing relative paths and this recovery
command:

```powershell
python -m pip install --force-reinstall "PySide6-Essentials>=6.11,<6.12"
```

Do not add QML tooling, SQL drivers, virtual keyboards, TLS backends, alternate
platforms, or other image readers merely because they are present in the
Essentials wheel. Add one only after a feature and its test require it.

## Installation and Commands

Install the optional Qt UI from a published wheel with:

```powershell
python -m pip install "retroarch-overlay[qt]"
retroarch-overlay --ui qt
retroarch-overlay-manager --ui qt
```

For a source checkout:

```powershell
python -m pip install -e ".[dev,qt]"
```

Qt is the default during coexistence; `--ui tk` selects the temporary fallback.
The command roles are:

| Command | Role |
| --- | --- |
| `retroarch-overlay` | GUI; Qt default, Tk explicit fallback |
| `retroarch-overlay-manager` | GUI; Qt default, Tk explicit fallback |
| `rao-plugin` | CLI-only plugin creation and update |
| `retroarch-overlay-cheeves` | CLI-only research export |

If Qt still fails during platform initialization, run the command once with
`QT_DEBUG_PLUGINS=1`, retain the loader output, and reinstall the exact supported
Essentials range. ABI or dependent-DLL failures can occur after the file
preflight and are reported by Qt's loader before Python can recover.

## Python Runtime Verification

Run the bounded isolated verifier from the repository root:

```powershell
python tools/verify_qt_package.py --source . --timeout 300
```

The verifier:

1. builds one wheel and checks its `LICENSE`, `NOTICE`, extras, and four entry points;
2. creates a fresh temporary virtual environment;
3. installs the wheel's `qt` extra and runs `pip check`;
4. proves that Essentials and shiboken are installed while Addons and the meta-package are absent;
5. starts an offscreen `QApplication` outside the source checkout;
6. invokes all four installed commands with `--help`;
7. force-reinstalls the application wheel and verifies settings preservation;
8. uninstalls the application and verifies that settings remain while imports are removed; and
9. deletes its temporary environment.

Every subprocess has the supplied timeout. The Windows CI workflow runs this
verifier after the normal test suite.

The 6.11.2 evidence measured approximately 2.01 MiB for the installed application,
204.27 MiB for Essentials, and 2.96 MiB for shiboken. The previous `PySide6`
meta-package also installed approximately 435.64 MiB of Addons that this project
does not use.

## License and Notice Requirements

RetroArch Overlay remains Apache-2.0. The optional Qt runtime is separate and is
not covered by that license. The selected `PySide6-Essentials` and `shiboken6`
wheel metadata identifies each as available under
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, in addition to Qt's commercial
licensing path.

The RetroArch Overlay source tree and project wheel do not bundle PySide6,
shiboken, Qt DLLs, or Qt plugins. They declare an optional dependency that pip
installs as a separate distribution. The project NOTICE identifies that optional
runtime and its separate licensing.

If a future distribution contains or redistributes PySide6, shiboken, Qt DLLs,
or Qt plugins, that artifact must:

- prominently identify Qt for Python, PySide6, shiboken, and Qt and include the applicable copyright notices;
- include complete LGPL 3.0 and incorporated GPL 3.0 license texts;
- include the applicable third-party license notices for the exact shipped Qt modules and plugins;
- provide the corresponding source or a compliant written/source-download offer for the shipped LGPL components;
- permit replacement and relinking with a compatible modified library and not prohibit reverse engineering for that debugging purpose;
- preserve installation information needed to run a permitted relinked version; and
- record exact component versions and hashes in the release manifest.

Do not assume that a wheel's `.dist-info` directory alone is a complete bundled
application notice payload. Generate and review the exact third-party inventory
for the final artifact. If these obligations cannot be met, use a suitable Qt
commercial license or do not distribute the Qt bundle.

Primary references:

- [Qt for Python package details](https://doc.qt.io/qtforpython-6/package_details.html)
- [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qt for Windows deployment](https://doc.qt.io/qt-6/windows-deployment.html)
- [Qt open-source LGPL obligations](https://www.qt.io/licensing/open-source-lgpl-obligations)

This document is engineering guidance, not legal advice. Any future artifact
that redistributes Qt binaries requires review of the assembled artifact and its
terms.

## Selected Distribution Model

Users run the application through a supported Python environment, either from a
source checkout or an installed project wheel. The bounded verifier covers that
model in a fresh virtual environment. No self-contained executable, installer,
bundler configuration, or clean-machine-without-Python gate is planned. If that
distribution decision changes later, it requires a new explicit scope decision
and a fresh licensing review.