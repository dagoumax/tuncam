from __future__ import annotations

import pytest

from tucam_control.camera_process import ProcessCameraController


def test_sdk_process_can_start_and_shutdown() -> None:
    camera = ProcessCameraController()
    try:
        assert camera.ping() > 0
    finally:
        camera.uninitialize()


def test_sdk_method_error_does_not_restart_process() -> None:
    camera = ProcessCameraController()
    try:
        pid = camera.ping()
        with pytest.raises(RuntimeError, match="Camera is not open"):
            camera.get_device_info()
        assert camera.ping() == pid
    finally:
        camera.uninitialize()
