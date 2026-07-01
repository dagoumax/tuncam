@echo off
setlocal

set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%"

if exist "%APP_ROOT%.venv\Scripts\tucam-control.exe" (
    start "" "%APP_ROOT%.venv\Scripts\tucam-control.exe"
) else (
    start "" uv run tucam-control
)
