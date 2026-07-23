# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


root = Path(SPEC).resolve().parent
dlls = [(str(path), "lib/x64") for path in (root / "lib" / "x64").glob("*.dll")]
datas = [
    (str(root / "assets"), "assets"),
    (str(root / "config"), "config"),
]

a = Analysis(
    [str(root / "src" / "tucam_control" / "main.py")],
    pathex=[str(root / "src")],
    binaries=dlls,
    datas=datas,
    hiddenimports=["tucam_control.camera_process", "tucam_control.camera"],
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
    console=False,
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
