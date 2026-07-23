Dhyana-95-V2 Camera Control - Portable Package

1. Copy the entire Dhyana-95-V2-Camera-Control folder to the new computer.
   Do not copy only the EXE file.
2. Install the 64-bit TUCam SDK camera driver before connecting the camera.
3. Double-click Dhyana-95-V2-Camera-Control.exe to start.
4. To create a desktop shortcut, right-click create_portable_shortcut.ps1 and
   run it with PowerShell.
5. Configuration is stored in config/user_settings.json.
6. Logs are written to logs/. Auto-saved images use data/ by default.

The packaged program includes Python dependencies and TUCam user-mode DLLs.
The hardware driver is not portable and must be installed separately.
