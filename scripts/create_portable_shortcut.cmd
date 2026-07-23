@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_portable_shortcut.ps1"
if errorlevel 1 pause
