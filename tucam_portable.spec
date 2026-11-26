# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os


root = Path(SPEC).resolve().parent
dlls = [(str(path), "lib/x64") for path in (root / "lib" / "x64").glob("*.dll")]
datas = [
    (str(root / "assets"), "assets"),
    (
        str(root / "src" / "tucam_control" / "remote_dashboard.html"),
        "tucam_control",
    ),
    (
        str(root / "src" / "tucam_control" / "remote_dashboard.css"),
        "tucam_control",
    ),
    (
        str(root / "src" / "tucam_control" / "remote_dashboard.js"),
        "tucam_control",
    ),
]

a = Analysis(
    [str(root / "src" / "tucam_control" / "main.py")],
    pathex=[str(root / "src")],
    binaries=dlls,
    datas=datas,
    hiddenimports=[
        "tucam_control.camera_process", "tucam_control.camera",
        "tucam_control.processing_process", "tucam_control.background_io",
        "tucam_control.concentration_export",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dhyana-95-V2-Camera-Control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=os.environ.get("TUCAM_BUILD_CONSOLE") == "1",
    icon=str(root / "assets" / "wut_logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Dhyana-95-V2-Camera-Control",
)
