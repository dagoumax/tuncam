# -*- coding: utf-8 -*-
"""
Camera acquisition controller for Dhyana-95-V2 via TUCam SDK.
"""

import ctypes
import time
from ctypes import (
    byref,
    c_char_p,
    c_double,
    c_int32,
    c_void_p,
    cast,
    create_string_buffer,
    memmove,
    pointer,
    string_at,
)
from dataclasses import dataclass, field

import numpy as np

from .TUCam import (
    TUCAM_CAPA_ATTR,
    TUCAM_CAPTURE_MODES,
    TUCAM_FRAME,
    TUCAM_FILE_SAVE,
    TUCAM_IDCAPA,
    TUCAM_IDINFO,
    TUCAM_IDPROP,
    TUCAM_INIT,
    TUCAM_OPEN,
    TUCAM_PROP_ATTR,
    TUCAM_REG_RW,
    TUCAM_VALUE_INFO,
    TUCAMRET,
    TUIMG_FORMATS,
    TUCAM_Api_Init,
    TUCAM_Api_Uninit,
    TUCAM_Buf_AbortWait,
    TUCAM_Buf_Alloc,
    TUCAM_Buf_Release,
    TUCAM_Buf_WaitForFrame,
    TUCAM_Cap_Start,
    TUCAM_Cap_Stop,
    TUCAM_Capa_GetValue,
    TUCAM_Capa_SetValue,
    TUCAM_Dev_Close,
    TUCAM_Dev_GetInfo,
    TUCAM_Dev_Open,
    TUCAM_File_SaveImage,
    TUCAM_Prop_GetAttr,
    TUCAM_Prop_GetValue,
    TUCAM_Prop_SetValue,
    TUCAM_Reg_Read,
)


@dataclass
class CameraInfo:
    """Container for camera device information."""

    model: str = ""
    serial_number: str = ""
    vendor_id: int = 0
    product_id: int = 0
    api_version: str = ""
    firmware_version: str = ""
    fpga_version: str = ""
    driver_version: str = ""
    sensor_width: int = 0
    sensor_height: int = 0
    channels: int = 0
    bus_type: int = 0
    fan_speed: int = 0
    fpga_temperature: float = 0.0
    pcba_temperature: float = 0.0
    env_temperature: float = 0.0
    transfer_rate: int = 0


class CameraController:
    """
    Manages the lifecycle of a Dhyana series camera via TUCam SDK.

    Usage::

        cam = CameraController()
        cam.initialize()
        cam.open(0)
        info = cam.get_device_info()
        cam.set_exposure_time(1000)
        cam.set_temperature_target(-10)
        cam.set_fan_gear(2)
        frame = cam.capture_single()
        cam.stop_capture()
        cam.close()
        cam.uninitialize()
    """

    def __init__(self) -> None:
        self._hcam: int = 0
        self._cam_count: int = 0
        self._initialized: bool = False
        self._opened: bool = False
        self._capturing: bool = False
        self._frame: TUCAM_FRAME | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> int:
        """Initialize the TUCam API. Returns the number of cameras found."""
        if self._initialized:
            return self._cam_count
        init_param = TUCAM_INIT(0, b"./")
        result = TUCAM_Api_Init(pointer(init_param), 5000)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"TUCAM_Api_Init failed: {result}")
        self._cam_count = init_param.uiCamCount
        self._initialized = True
        return self._cam_count

    def open(self, index: int = 0) -> None:
        """Open camera at *index*."""
        if not self._initialized:
            raise RuntimeError("API not initialized")
        open_param = TUCAM_OPEN(index, 0)
        result = TUCAM_Dev_Open(pointer(open_param))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"TUCAM_Dev_Open failed: {result}")
        if open_param.hIdxTUCam == 0:
            raise RuntimeError("Camera handle is null after open")
        self._hcam = open_param.hIdxTUCam
        self._opened = True

    def close(self) -> None:
        """Close the currently open camera."""
        if not self._opened or self._hcam == 0:
            return
        self.stop_capture()
        TUCAM_Dev_Close(self._hcam)
        self._hcam = 0
        self._opened = False

    def uninitialize(self) -> None:
        """Uninitialize the TUCam API."""
        self.close()
        if self._initialized:
            TUCAM_Api_Uninit()
            self._initialized = False
            self._cam_count = 0

    @property
    def is_open(self) -> bool:
        return self._opened

    @property
    def is_capturing(self) -> bool:
        return self._capturing

    # ------------------------------------------------------------------
    # Device Information
    # ------------------------------------------------------------------

    def get_device_info(self) -> CameraInfo:
        """Retrieve all available camera information."""
        self._check_open()
        info = CameraInfo()

        enc = "utf-8"

        def _read_str(info_id: TUCAM_IDINFO, buf_size: int = 256) -> str:
            buf = create_string_buffer(buf_size)
            vi = TUCAM_VALUE_INFO(info_id.value, 0, cast(buf, c_char_p), buf_size)
            TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            return buf.value.decode(enc, errors="replace") if buf.value else ""

        def _read_int(info_id: TUCAM_IDINFO) -> int:
            vi = TUCAM_VALUE_INFO(info_id.value, 0, 0, 0)
            TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            return vi.nValue

        info.model = _read_str(TUCAM_IDINFO.TUIDI_CAMERA_MODEL)
        info.api_version = _read_str(TUCAM_IDINFO.TUIDI_VERSION_API)
        info.vendor_id = _read_int(TUCAM_IDINFO.TUIDI_VENDOR)
        info.product_id = _read_int(TUCAM_IDINFO.TUIDI_PRODUCT)
        info.bus_type = _read_int(TUCAM_IDINFO.TUIDI_BUS)
        info.channels = _read_int(TUCAM_IDINFO.TUIDI_CAMERA_CHANNELS)
        info.sensor_width = _read_int(TUCAM_IDINFO.TUIDI_CURRENT_WIDTH)
        info.sensor_height = _read_int(TUCAM_IDINFO.TUIDI_CURRENT_HEIGHT)
        info.transfer_rate = _read_int(TUCAM_IDINFO.TUIDI_TRANSFER_RATE)

        # Firmware / FPGA versions
        fw_text = _read_str(TUCAM_IDINFO.TUIDI_VERSION_FRMW)
        try:
            fw_int = _read_int(TUCAM_IDINFO.TUIDI_VERSION_FRMW)
            if fw_int != 0:
                info.firmware_version = hex(fw_int)
            else:
                info.firmware_version = fw_text
        except Exception:
            info.firmware_version = fw_text

        fpga_text = _read_str(TUCAM_IDINFO.TUIDI_VERSION_FPGA)
        try:
            fpga_int = _read_int(TUCAM_IDINFO.TUIDI_VERSION_FPGA)
            if fpga_int != 0:
                info.fpga_version = hex(fpga_int)
            else:
                info.fpga_version = fpga_text
        except Exception:
            info.fpga_version = fpga_text

        info.driver_version = _read_str(TUCAM_IDINFO.TUIDI_VERSION_DRIVER)

        # Temperatures
        try:
            info.fan_speed = _read_int(TUCAM_IDINFO.TUIDI_FAN_SPEED)
        except Exception:
            info.fan_speed = 0
        try:
            info.fpga_temperature = _read_int(TUCAM_IDINFO.TUIDI_FPGA_TEMPERATURE) / 10.0
        except Exception:
            info.fpga_temperature = 0.0
        try:
            info.pcba_temperature = _read_int(TUCAM_IDINFO.TUIDI_PCBA_TEMPERATURE) / 10.0
        except Exception:
            info.pcba_temperature = 0.0
        try:
            info.env_temperature = _read_int(TUCAM_IDINFO.TUIDI_ENV_TEMPERATURE) / 10.0
        except Exception:
            info.env_temperature = 0.0

        # Serial number via register read
        try:
            c_sn = (ctypes.c_char * 64)()
            p_sn = cast(c_sn, ctypes.c_char_p)
            reg_rw = TUCAM_REG_RW(1, p_sn, 64)
            TUCAM_Reg_Read(self._hcam, reg_rw)
            info.serial_number = string_at(p_sn).decode(enc, errors="replace").rstrip("\x00")
        except Exception:
            info.serial_number = "N/A"

        return info

    # ------------------------------------------------------------------
    # Exposure Time  (TUIDP_EXPOSURETM, unit: ms)
    # ------------------------------------------------------------------

    def set_exposure_time(self, time_ms: float) -> None:
        """Set exposure time in milliseconds."""
        self._check_open()
        TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
        TUCAM_Prop_SetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, c_double(time_ms), 0
        )

    def get_exposure_time(self) -> float:
        """Get current exposure time in milliseconds."""
        self._check_open()
        val = c_double(0)
        TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, byref(val), 0
        )
        return val.value

    def get_exposure_range(self) -> tuple[float, float]:
        """Get min/max exposure time (ms)."""
        self._check_open()
        attr = TUCAM_PROP_ATTR()
        attr.idProp = TUCAM_IDPROP.TUIDP_EXPOSURETM.value
        attr.nIdxChn = 0
        TUCAM_Prop_GetAttr(self._hcam, pointer(attr))
        return (attr.dbValMin, attr.dbValMax)

    # ------------------------------------------------------------------
    # Temperature  (TUIDP_TEMPERATURE_TARGET / TUIDC_ENABLETEC)
    # ------------------------------------------------------------------

    def set_temperature_target(self, temp_c: float) -> None:
        """Set target temperature in Celsius. Enables TEC automatically."""
        self._check_open()
        TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_ENABLETEC.value, 1)
        TUCAM_Prop_SetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, c_double(temp_c), 0
        )

    def get_temperature_target(self) -> float:
        """Get current target temperature in Celsius."""
        self._check_open()
        val = c_double(0)
        TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, byref(val), 0
        )
        return val.value

    def get_temperature_range(self) -> tuple[float, float]:
        """Get min/max temperature target range."""
        self._check_open()
        attr = TUCAM_PROP_ATTR()
        attr.idProp = TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value
        attr.nIdxChn = 0
        TUCAM_Prop_GetAttr(self._hcam, pointer(attr))
        return (attr.dbValMin, attr.dbValMax)

    # ------------------------------------------------------------------
    # Fan Gear  (TUIDC_FAN_GEAR)
    # ------------------------------------------------------------------

    def set_fan_gear(self, gear: int) -> None:
        """Set fan gear (1-4). Gear 0 is NOT allowed per requirements."""
        self._check_open()
        if gear < 1 or gear > 4:
            raise ValueError("Fan gear must be 1-4 (gear 0 / off is not permitted)")
        TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, gear)

    def get_fan_gear(self) -> int:
        """Get current fan gear."""
        self._check_open()
        val = c_int32(0)
        TUCAM_Capa_GetValue(
            self._hcam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, byref(val)
        )
        return val.value

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _alloc_buffer(self) -> None:
        """Allocate frame buffer. Must be called before capture start."""
        self._frame = TUCAM_FRAME()
        self._frame.pBuffer = 0
        self._frame.uiRsdSize = 1
        result = TUCAM_Buf_Alloc(self._hcam, pointer(self._frame))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Buffer alloc failed: {result}")

    def _release_buffer(self) -> None:
        if self._frame is not None:
            TUCAM_Buf_Release(self._hcam)
            self._frame = None

    def start_capture(self) -> None:
        """Alloc buffer and start sequence capture."""
        self._check_open()
        self._alloc_buffer()
        result = TUCAM_Cap_Start(
            self._hcam, TUCAM_CAPTURE_MODES.TUCCM_SEQUENCE.value
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            self._release_buffer()
            raise RuntimeError(f"Capture start failed: {result}")
        self._capturing = True

    def stop_capture(self) -> None:
        """Stop capture and release buffer."""
        if not self._capturing:
            return
        TUCAM_Buf_AbortWait(self._hcam)
        TUCAM_Cap_Stop(self._hcam)
        self._capturing = False
        self._release_buffer()

    def wait_for_frame(self, timeout_ms: int = 2000) -> np.ndarray | None:
        """
        Wait for a single frame and return as 2-D numpy uint16 array.

        Returns ``None`` on timeout or failure.
        """
        if not self._capturing or self._frame is None:
            return None

        result = TUCAM_Buf_WaitForFrame(self._hcam, pointer(self._frame), timeout_ms)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            return None

        return self._frame_to_array(self._frame)

    def capture_single(self) -> np.ndarray | None:
        """
        Convenience: start capture, grab one frame, stop capture.
        Returns 2-D numpy uint16 array.
        """
        self.start_capture()
        try:
            return self.wait_for_frame()
        finally:
            self.stop_capture()

    # ------------------------------------------------------------------
    # Frame data extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _frame_to_array(frame: TUCAM_FRAME) -> np.ndarray:
        """Extract pixel data from a TUCAM_FRAME into a 2-D numpy array."""
        w, h = frame.usWidth, frame.usHeight
        elem_bytes = frame.ucElemBytes
        header = frame.usHeader
        total_size = frame.uiImgSize

        buf = create_string_buffer(total_size)
        ptr_data = c_void_p(frame.pBuffer + header)
        memmove(buf, ptr_data, total_size)

        if elem_bytes == 1:
            arr = np.frombuffer(buf, dtype=np.uint8, count=w * h)
        else:
            arr = np.frombuffer(buf, dtype=np.uint16, count=w * h)

        return arr.reshape((h, w))

    def save_image(self, filepath: str, fmt: TUIMG_FORMATS | None = None) -> None:
        """Save the most recent frame buffer content to disk."""
        if self._frame is None:
            raise RuntimeError("No frame buffer allocated")
        if fmt is None:
            fmt = TUIMG_FORMATS.TUFMT_TIF
        fs = TUCAM_FILE_SAVE()
        fs.nSaveFmt = fmt.value
        fs.pstrSavePath = filepath.encode("utf-8")
        fs.pFrame = pointer(self._frame)
        result = TUCAM_File_SaveImage(self._hcam, fs)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Save image failed: {result}")

    # ------------------------------------------------------------------
    # Connection monitoring
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Check if the physical device is still connected."""
        if not self._opened or self._hcam == 0:
            return False
        try:
            vi = TUCAM_VALUE_INFO(TUCAM_IDINFO.TUIDI_CONNECTSTATUS.value, 0, 0, 0)
            TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            return vi.nValue != 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_open(self) -> None:
        if not self._opened or self._hcam == 0:
            raise RuntimeError("Camera is not open")

    def __del__(self) -> None:
        try:
            self.uninitialize()
        except Exception:
            pass
