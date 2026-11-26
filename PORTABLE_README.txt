Dhyana-95-V2 Camera Control - Portable Package

1. Extract the entire ZIP to a writable local folder on the new computer,
   such as D:\Raman\Dhyana-95-V2. Do not run inside the ZIP or copy only the EXE.
   Keep the _internal folder beside the EXE. Avoid Program Files and network drives.
2. Install the 64-bit TUCam SDK camera driver before connecting the camera.
3. Double-click Dhyana-95-V2-Camera-Control.exe to start.
4. Double-click create_portable_shortcut.cmd to create the desktop shortcut.
   Repeat this step after moving the folder. Old shortcuts point to the old folder.
5. Configuration is stored in config/user_settings.json.
6. Logs are written to logs/. Auto-saved images use data/ by default.
7. Python is included; no Python installation, pip or internet is needed to run.
8. Probe names, gas coefficients, smoothing and processing parameters are copied
   from the current project. Verify exposure, row ranges and calibration on site.
9. Remote access is disabled in this package and the old access key is removed.
   Enable it in Settings and use the newly generated key at the destination.
10. BUILD_INFO.json records the source revision and packaged self-test results.
    A passing self-test does not replace real camera/driver testing.

First run:

This version keeps the Raman cursor during continuous frame updates.
Probe Manager supports UTF-8 CSV import/export and background TIFF folder detection.
The CSV header is documented in README.md. A 15-probe candidate file is included
in examples/probes_0.5s_air_100um_candidates.csv. Review its boundaries before
saving and applying; it is not applied automatically. Changing row ranges clears
concentration history. Display, alarm-limit and smoothing changes preserve history;
the status bar reports whether history was retained or cleared.

1. Install the camera driver, connect USB 3.0, then start the EXE as a normal user.
2. Without a camera, dismiss the connection message and load a TIF for offline testing.
3. Check the save folder and disk space before enabling automatic storage.
4. If plotting fails on the target GPU, disable OpenGL in Settings and restart.
5. Keep logs/ when reporting a problem. Do not repeatedly launch additional copies.

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
