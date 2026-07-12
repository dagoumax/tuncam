from __future__ import annotations

from ctypes import c_double

import pytest

import tucam_control.camera as camera_module
from tucam_control.TUCam import TUCAMRET, TUCAM_FRAME, TUCAM_IDPROP
from tucam_control.camera import CameraController


def _open_controller() -> CameraController:
    camera = CameraController()
    camera._opened = True
    camera._hcam = 1
    return camera


def test_temperature_target_uses_dedicated_property_and_sdk_encoding(monkeypatch) -> None:
    writes: list[tuple[int, float]] = []

    def fake_get_attr(_handle, attr_ptr):
        attr = attr_ptr.contents
        assert attr.idProp == TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value
        attr.dbValMin = 0.0
        attr.dbValMax = 1000.0
        attr.dbValDft = 400.0
        attr.dbValStep = 1.0
        return TUCAMRET.TUCAMRET_SUCCESS

    def fake_set_value(_handle, prop, value: c_double, _channel):
        writes.append((prop, value.value))
        return TUCAMRET.TUCAMRET_SUCCESS

    monkeypatch.setattr(camera_module, "TUCAM_Prop_GetAttr", fake_get_attr)
    monkeypatch.setattr(camera_module, "TUCAM_Prop_SetValue", fake_set_value)

    camera = _open_controller()
    camera.set_temperature_target(-20.0)

    assert writes == [(TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, 300.0)]
    assert camera.get_temperature_range() == (-50.0, 50.0)


def test_fan_off_value_is_rejected_before_sdk_call() -> None:
    camera = _open_controller()

    with pytest.raises(ValueError, match="disables the fan"):
        camera.set_fan_gear(3)


def test_capture_stop_aborts_before_stopping_and_releasing(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        camera_module,
        "TUCAM_Buf_AbortWait",
        lambda _handle: calls.append("abort") or TUCAMRET.TUCAMRET_SUCCESS,
    )
    monkeypatch.setattr(
        camera_module,
        "TUCAM_Cap_Stop",
        lambda _handle: calls.append("stop") or TUCAMRET.TUCAMRET_SUCCESS,
    )
    monkeypatch.setattr(
        camera_module,
        "TUCAM_Buf_Release",
        lambda _handle: calls.append("release") or TUCAMRET.TUCAMRET_SUCCESS,
    )

    camera = _open_controller()
    camera._capturing = True
    camera._frame = TUCAM_FRAME()
    camera.stop_capture()

    assert calls == ["abort", "stop", "release"]
    assert camera.is_capturing is False
    assert camera._frame is None
