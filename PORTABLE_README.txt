Dhyana-95-V2 Camera Control - Portable Package

1. Copy the entire Dhyana-95-V2-Camera-Control folder to the new computer.
   Do not copy only the EXE file.
2. Install the 64-bit TUCam SDK camera driver before connecting the camera.
3. Double-click Dhyana-95-V2-Camera-Control.exe to start.
4. To create a desktop shortcut, right-click create_portable_shortcut.ps1 and
   run it with PowerShell.
5. Configuration is stored in config/user_settings.json.
6. Logs are written to logs/. Auto-saved images use data/ by default.

Offline LAN remote control:

1. Keep this program running on the field computer.
2. In Settings, enable LAN Remote Control, keep port 8765, set the control-room
   computer IP, and apply the settings.
3. Allow TCP port 8765 on Windows Private networks when prompted.
4. Open the URL shown in Settings from the control-room browser and enter the
   displayed access key.
5. Internet access is not required. A direct Ethernet cable or switch is enough.
6. The browser fetches incremental data once per second and renders at about
   30 FPS. Display delay can be set to 1, 3, 5, or 10 seconds (default: 3).

The packaged program includes Python dependencies and TUCam user-mode DLLs.
The hardware driver is not portable and must be installed separately.
