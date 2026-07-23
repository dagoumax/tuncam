# -*- coding: utf-8 -*-
"""Portable JSON persistence for user-editable application settings."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from .gas_analyzer import GasConfig
from .resources import user_settings_path


SETTINGS_VERSION = 1


def load_user_settings(path: Path | None = None) -> tuple[dict, list[GasConfig]]:
    target = path or user_settings_path()
    if not target.exists():
        return {}, []
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Settings file root must be an object")
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("Settings field must be an object")

    gases: list[GasConfig] = []
    gas_rows = data.get("gas_configs", [])
    if not isinstance(gas_rows, list):
        raise ValueError("Gas configuration must be a list")
    for row in gas_rows:
        if not isinstance(row, dict):
            continue
        try:
            alarm_value = row.get("alarm_concentration")
            detection_value = row.get("detection_sigma")
            gases.append(
                GasConfig(
                    name=str(row["name"]),
                    position=int(row["position"]),
                    window=int(row.get("window", 15)),
                    coefficient=float(row.get("coefficient", 1.0)),
                    raman_shift=float(row.get("raman_shift", 0.0)),
                    alarm_concentration=(
                        float(alarm_value) if alarm_value not in (None, "") else None
                    ),
                    detection_sigma=(
                        float(detection_value)
                        if detection_value not in (None, "")
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return settings, gases


def save_user_settings(
    settings: dict,
    gas_configs: list[GasConfig],
    path: Path | None = None,
) -> Path:
    target = path or user_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SETTINGS_VERSION,
        "settings": settings,
        "gas_configs": [asdict(config) for config in gas_configs],
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
