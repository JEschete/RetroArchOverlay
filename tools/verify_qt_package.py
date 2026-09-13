from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Sequence


ENTRY_POINTS = (
    "retroarch-overlay",
    "retroarch-overlay-manager",
    "rao-plugin",
    "retroarch-overlay-cheeves",
)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Command exceeded {timeout} seconds: {' '.join(command)}"
        ) from error
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: "
            f"{' '.join(command)}\n{output[-4_000:]}"
        )
    return result


def _venv_python(environment_root: Path) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return environment_root / directory / executable


def _entry_point(environment_root: Path, name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return environment_root / directory / f"{name}{suffix}"


def _stage_source(source_root: Path, target: Path) -> None:
    target.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        source = source_root / name
        if source.is_file():
            shutil.copy2(source, target / name)
    shutil.copytree(
        source_root / "src",
        target / "src",
        ignore=shutil.ignore_patterns("*.egg-info", "__pycache__", "*.pyc"),
    )


def _verify_wheel_contents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = tuple(archive.namelist())
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
        entry_points = archive.read(entry_points_name).decode("utf-8")
    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        raise RuntimeError("Built wheel does not contain LICENSE")
    if not any(name.endswith(".dist-info/licenses/NOTICE") for name in names):
        raise RuntimeError("Built wheel does not contain NOTICE")
    requirements = Parser().parsestr(metadata).get_all("Requires-Dist", ())
    qt_requirements = tuple(
        requirement.replace("'", '"')
        for requirement in requirements
        if requirement.startswith("PySide6-Essentials")
    )
    if len(qt_requirements) != 1 or not all(
        fragment in qt_requirements[0]
        for fragment in (">=6.11", "<6.12", 'extra == "qt"')
    ):
        raise RuntimeError(
            f"Built wheel has unexpected Qt requirements: {qt_requirements}"
        )
    commands = configparser.ConfigParser()
    commands.read_string(entry_points)
    installed_commands = set(commands["console_scripts"])
    missing_commands = tuple(
        name for name in ENTRY_POINTS if name not in installed_commands
    )
    if missing_commands:
        raise RuntimeError(f"Built wheel is missing commands: {missing_commands}")


def _metadata_probe(python: Path, cwd: Path, timeout: int) -> dict[str, object]:
    code = """
import json
from importlib.metadata import PackageNotFoundError, distribution, version

required = ("retroarch-overlay", "PySide6-Essentials", "shiboken6")
for name in required:
    version(name)
for name in ("PySide6", "PySide6-Addons"):
    try:
        version(name)
    except PackageNotFoundError:
        continue
    raise SystemExit(f"Unexpected distribution installed: {name}")

def size(name):
    package = distribution(name)
    return sum(
        path.locate().stat().st_size
        for path in package.files or ()
        if path.locate().is_file()
    )

print(json.dumps({
    "retroarch-overlay": version("retroarch-overlay"),
    "PySide6-Essentials": version("PySide6-Essentials"),
    "shiboken6": version("shiboken6"),
    "installed-bytes": {
        name: size(name) for name in required
    },
}))
"""
    result = _run((str(python), "-c", code), cwd=cwd, timeout=timeout)
    return json.loads(result.stdout)


def _runtime_probe(
    python: Path,
    cwd: Path,
    timeout: int,
    environment: dict[str, str],
) -> dict[str, str]:
    code = """
import json
from PySide6 import __version__
from PySide6.QtCore import qVersion
from retroarch_overlay.presentation.qt import create_qt_application

application = create_qt_application(("retroarch-overlay-package-smoke",))
print(json.dumps({
    "platform": application.platformName(),
    "pyside": __version__,
    "qt": qVersion(),
}))
application.quit()
"""
    result = _run(
        (str(python), "-c", code),
        cwd=cwd,
        timeout=timeout,
        environment=environment,
    )
    return json.loads(result.stdout)


def _write_settings_probe(
    python: Path,
    cwd: Path,
    timeout: int,
    environment: dict[str, str],
) -> Path:
    code = """
from retroarch_overlay.local_settings import LocalPluginSettings

settings = LocalPluginSettings()
settings.save_theme("dark")
print(settings.path)
"""
    result = _run(
        (str(python), "-c", code),
        cwd=cwd,
        timeout=timeout,
        environment=environment,
    )
    return Path(result.stdout.strip())


def _assert_uninstalled(
    python: Path,
    cwd: Path,
    timeout: int,
    settings_path: Path,
) -> None:
    code = """
import importlib.util
import json
import sys
from pathlib import Path

settings = Path(sys.argv[1])
if importlib.util.find_spec("retroarch_overlay") is not None:
    raise SystemExit("retroarch_overlay remains importable after uninstall")
if json.loads(settings.read_text(encoding="utf-8")).get("theme") != "dark":
    raise SystemExit("settings were not preserved after uninstall")
"""
    _run(
        (str(python), "-c", code, str(settings_path)),
        cwd=cwd,
        timeout=timeout,
    )


def verify(source_root: Path, timeout: int) -> dict[str, object]:
    source_root = source_root.resolve()
    if not (source_root / "pyproject.toml").is_file():
        raise ValueError(f"No pyproject.toml found under {source_root}")
    with tempfile.TemporaryDirectory(prefix="rao-qt-package-") as directory:
        temporary_root = Path(directory)
        staged_source = temporary_root / "source"
        _stage_source(source_root, staged_source)
        wheel_directory = temporary_root / "wheel"
        wheel_directory.mkdir()
        _run(
            (
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(staged_source),
                "--no-deps",
                "--wheel-dir",
                str(wheel_directory),
            ),
            cwd=temporary_root,
            timeout=timeout,
        )
        wheels = tuple(wheel_directory.glob("retroarch_overlay-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one project wheel, found {len(wheels)}")
        wheel = wheels[0]
        _verify_wheel_contents(wheel)

        environment_root = temporary_root / "environment"
        _run(
            (sys.executable, "-m", "venv", str(environment_root)),
            cwd=temporary_root,
            timeout=timeout,
        )
        python = _venv_python(environment_root)
        _run(
            (str(python), "-m", "pip", "install", f"{wheel}[qt]"),
            cwd=temporary_root,
            timeout=timeout,
        )
        _run(
            (str(python), "-m", "pip", "check"),
            cwd=temporary_root,
            timeout=timeout,
        )
        metadata = _metadata_probe(python, temporary_root, timeout)

        runtime_environment = os.environ.copy()
        runtime_environment["QT_QPA_PLATFORM"] = "offscreen"
        runtime_environment["LOCALAPPDATA"] = str(temporary_root / "local-app-data")
        runtime = _runtime_probe(
            python,
            temporary_root,
            timeout,
            runtime_environment,
        )
        for name in ENTRY_POINTS:
            _run(
                (str(_entry_point(environment_root, name)), "--help"),
                cwd=temporary_root,
                timeout=timeout,
                environment=runtime_environment,
            )

        settings_path = _write_settings_probe(
            python,
            temporary_root,
            timeout,
            runtime_environment,
        )
        _run(
            (
                str(python),
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel),
            ),
            cwd=temporary_root,
            timeout=timeout,
        )
        if json.loads(settings_path.read_text(encoding="utf-8")).get("theme") != "dark":
            raise RuntimeError("Settings were not preserved across reinstall")
        _run(
            (str(python), "-m", "pip", "uninstall", "-y", "retroarch-overlay"),
            cwd=temporary_root,
            timeout=timeout,
        )
        _assert_uninstalled(
            python,
            temporary_root,
            timeout,
            settings_path,
        )

        return {
            "wheel": wheel.name,
            "metadata": metadata,
            "runtime": runtime,
            "entry-points": ENTRY_POINTS,
            "settings-preserved": True,
            "temporary-directory-removed-on-exit": True,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify the optional Qt wheel in an isolated environment"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    result = verify(args.source, args.timeout)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
