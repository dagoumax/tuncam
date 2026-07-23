# -*- coding: utf-8 -*-
"""Resource lookup helpers for the application."""

from __future__ import annotations

from pathlib import Path
import sys


def project_root() -> Path:
    """Return the repository root when running from the source tree."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_icon_path() -> Path | None:
    """Return the shared application icon path if it exists."""
    candidates = [
        project_root() / "assets" / "wut_logo.ico",
        Path(__file__).resolve().parent / "assets" / "wut_logo.ico",
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "wut_logo.ico")
    for path in candidates:
        if path.exists():
            return path
    return None


def user_settings_path() -> Path:
    """Return the portable per-project settings file path."""
    return project_root() / "config" / "user_settings.json"
