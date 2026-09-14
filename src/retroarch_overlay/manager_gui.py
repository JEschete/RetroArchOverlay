from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_manager_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="RetroArch Overlay plugin manager")


def run_qt_manager() -> int:
    try:
        from .presentation.qt import QtPluginManagerWindow, create_qt_application
    except ModuleNotFoundError as error:
        if error.name and error.name.partition(".")[0] == "PySide6":
            raise RuntimeError(
                'The Qt manager requires PySide6-Essentials: pip install "."'
            ) from error
        raise
    application = create_qt_application()
    window = QtPluginManagerWindow()
    window.show()
    return application.exec()


def main(argv: Sequence[str] | None = None) -> int:
    build_manager_parser().parse_args(argv)
    return run_qt_manager()


if __name__ == "__main__":
    raise SystemExit(main())
