from __future__ import annotations

from tucam_control.gas_analyzer import GasConfig
from tucam_control.settings_store import load_user_settings, save_user_settings


def test_settings_round_trip(tmp_path) -> None:
    path = tmp_path / "config" / "user_settings.json"
    settings = {
        "row_groups_text": "1-10,20-30",
        "row_aggregation": "sum",
        "exposure_time_ms": 1000.0,
    }
    gases = [GasConfig("O2", 123, 10, 2.5, 1555.0)]

    saved_path = save_user_settings(settings, gases, path)
    loaded_settings, loaded_gases = load_user_settings(path)

    assert saved_path == path
    assert loaded_settings == settings
    assert loaded_gases == gases
