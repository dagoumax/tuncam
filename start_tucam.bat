@echo off
setlocal

set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%"

if exist "%APP_ROOT%.venv\Scripts\pythonw.exe" (
    start "" "%APP_ROOT%.venv\Scripts\pythonw.exe" -m tucam_control.main
) else if exist "%APP_ROOT%.venv\Scripts\python.exe" (
    start "" "%APP_ROOT%.venv\Scripts\python.exe" -m tucam_control.main
) else (
    start "" uv run python -m tucam_control.main
)
