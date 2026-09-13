from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ...app.dashboard import DashboardStore
from .application import create_qt_application
from .dashboard_window import QtDashboardWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RetroArch Overlay companion dashboard")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--theme", default="dark")
    args = parser.parse_args(argv)
    application = create_qt_application([] if argv is not None else None)
    window = QtDashboardWindow(DashboardStore(args.state_dir), theme=args.theme)
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())