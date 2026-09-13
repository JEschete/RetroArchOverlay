@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python launcher not found. Install Python 3.11 or newer and try again.
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 goto :bootstrap_failed
)

".venv\Scripts\python.exe" -c "import keyring; import PIL; import PySide6.QtWidgets; import retroarch_overlay" >nul 2>nul
if errorlevel 1 (
    echo Installing RetroArch Overlay and runtime dependencies...
    ".venv\Scripts\python.exe" -m pip install -e ".[qt]"
    if errorlevel 1 goto :bootstrap_failed
)

if exist ".venv\Scripts\pythonw.exe" (
    start "RetroArch Overlay" ".venv\Scripts\pythonw.exe" -m retroarch_overlay.manager_gui --ui qt
) else (
    ".venv\Scripts\python.exe" -m retroarch_overlay.manager_gui --ui qt
)
exit /b 0

:bootstrap_failed
echo.
echo RetroArch Overlay setup failed. Review the messages above and try again.
pause
exit /b 1