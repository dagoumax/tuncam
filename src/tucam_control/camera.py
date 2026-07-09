# -*- coding: utf-8 -*-
"""
Camera acquisition controller for Dhyana-95-V2 via TUCam SDK.
"""

import ctypes
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
from dataclasses import dataclass

import numpy as np

from .debug_log import get_debug_logger
from .TUCam import (
    TUCAM_CAPTURE_MODES,
    TUCAM_FRAME,
    TUCAM_FILE_SAVE,
    TUCAM_IDCAPA,
    TUCAM_IDINFO,
    TUCAM_IDPROP,
    TUCAM_INIT,
    TUCAM_OPEN,
    TUCAM_CAPA_ATTR,
    TUCAM_PROP_ATTR,
    TUCAM_REG_RW,
    TUCAM_VALUE_INFO,
    TUCAMRET,
    TUFRM_FORMATS,
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
    TUCAM_Capa_GetAttr,
    TUCAM_Capa_SetValue,
    TUCAM_Dev_Close,
    TUCAM_Dev_GetInfo,
    TUCAM_Dev_Open,
    TUCAM_File_SaveImage,
    TUCAM_Prop_GetAttr,
    TUCAM_Prop_GetValue,
    TUCAM_Prop_SetValue,
    TUCAM_Reg_Read,
    describe_tucam_ret,
    sdk_config_path_bytes,
    sdk_diagnostics,
)


log = get_debug_logger("camera")


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
            log.debug("TUCAM_Api_Init skipped; already initialized cam_count=%s", self._cam_count)
            return self._cam_count
        log.info("SDK diagnostics: %s", sdk_diagnostics())
        log.info("Calling TUCAM_Api_Init")
        init_param = TUCAM_INIT(0, sdk_config_path_bytes())
        result = TUCAM_Api_Init(pointer(init_param), 5000)
        log.info("TUCAM_Api_Init returned %s; cam_count=%s", describe_tucam_ret(result), init_param.uiCamCount)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"TUCAM_Api_Init failed: {describe_tucam_ret(result)}")
        self._cam_count = init_param.uiCamCount
        self._initialized = True
        return self._cam_count

    def open(self, index: int = 0) -> None:
        """Open camera at *index*."""
        if not self._initialized:
            raise RuntimeError("API not initialized")
        log.info("Calling TUCAM_Dev_Open index=%s", index)
        open_param = TUCAM_OPEN(index, 0)
        result = TUCAM_Dev_Open(pointer(open_param))
        log.info("TUCAM_Dev_Open returned %s; handle=%s", describe_tucam_ret(result), open_param.hIdxTUCam)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"TUCAM_Dev_Open failed: {describe_tucam_ret(result)}")
        if open_param.hIdxTUCam == 0:
            raise RuntimeError("Camera handle is null after open")
        self._hcam = open_param.hIdxTUCam
        self._opened = True

    def close(self) -> None:
        """Close the currently open camera."""
        if not self._opened or self._hcam == 0:
            return
        log.info("Closing camera handle=%s", self._hcam)
        self.stop_capture()
        result = TUCAM_Dev_Close(self._hcam)
        log.info("TUCAM_Dev_Close returned %s", describe_tucam_ret(result))
        self._hcam = 0
        self._opened = False

    def uninitialize(self) -> None:
        """Uninitialize the TUCam API."""
        self.close()
        if self._initialized:
            log.info("Calling TUCAM_Api_Uninit")
            result = TUCAM_Api_Uninit()
            log.info("TUCAM_Api_Uninit returned %s", describe_tucam_ret(result))
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
            result = TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
                log.debug("TUCAM_Dev_GetInfo(%s) returned %s", info_id.name, describe_tucam_ret(result))
            return buf.value.decode(enc, errors="replace") if buf.value else ""

        def _read_int(info_id: TUCAM_IDINFO) -> int:
            vi = TUCAM_VALUE_INFO(info_id.value, 0, 0, 0)
            result = TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
                log.debug("TUCAM_Dev_GetInfo(%s) returned %s", info_id.name, describe_tucam_ret(result))
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

        log.debug(
            "Device info: model=%r serial=%r api=%r driver=%r size=%sx%s channels=%s",
            info.model,
            info.serial_number,
            info.api_version,
            info.driver_version,
            info.sensor_width,
            info.sensor_height,
            info.channels,
        )
        return info

    # ------------------------------------------------------------------
    # Exposure Time  (TUIDP_EXPOSURETM, unit: ms)
    # ------------------------------------------------------------------

    def set_exposure_time(self, time_ms: float) -> None:
        """Set exposure time in milliseconds."""
        self._check_open()
        result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
        log.debug("TUCAM_Capa_SetValue(ATEXPOSURE=0) returned %s", describe_tucam_ret(result))
        result = TUCAM_Prop_SetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, c_double(time_ms), 0
        )
        log.info("Set exposure %.3f ms returned %s", time_ms, describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Set exposure failed: {describe_tucam_ret(result)}")

    def configure_scientific_frame_format(self) -> None:
        """Prefer raw/high-bit-depth frames over RGB preview frames."""
        self._check_open()

        def _query_capa_attr(capa: TUCAM_IDCAPA) -> TUCAM_CAPA_ATTR:
            attr = TUCAM_CAPA_ATTR()
            attr.idCapa = capa.value
            result = TUCAM_Capa_GetAttr(self._hcam, pointer(attr))
            log.info(
                "%s attr returned %s; min=%s max=%s default=%s step=%s",
                capa.name,
                describe_tucam_ret(result),
                attr.nValMin,
                attr.nValMax,
                attr.nValDft,
                attr.nValStep,
            )
            if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
                raise RuntimeError(f"Get {capa.name} attr failed: {describe_tucam_ret(result)}")
            return attr

        try:
            attr = _query_capa_attr(TUCAM_IDCAPA.TUIDC_DATAFORMAT)
            preferred_formats = (
                TUFRM_FORMATS.TUFRM_FMT_RAW.value,
                TUFRM_FORMATS.TUFRM_FMT_USUAl.value,
            )
            for fmt in preferred_formats:
                if attr.nValMin <= fmt <= attr.nValMax:
                    result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_DATAFORMAT.value, fmt)
                    log.info("Set data format %s returned %s", fmt, describe_tucam_ret(result))
                    break
            val = c_int32(0)
            result = TUCAM_Capa_GetValue(self._hcam, TUCAM_IDCAPA.TUIDC_DATAFORMAT.value, byref(val))
            log.info("Data format readback returned %s; value=%s", describe_tucam_ret(result), val.value)
        except Exception as exc:
            log.warning("Could not configure data format: %s", exc)

        try:
            attr = _query_capa_attr(TUCAM_IDCAPA.TUIDC_BITOFDEPTH)
            target_depth = attr.nValMax
            result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_BITOFDEPTH.value, target_depth)
            log.info("Set bit depth %s returned %s", target_depth, describe_tucam_ret(result))
            val = c_int32(0)
            result = TUCAM_Capa_GetValue(self._hcam, TUCAM_IDCAPA.TUIDC_BITOFDEPTH.value, byref(val))
            log.info("Bit depth readback returned %s; value=%s", describe_tucam_ret(result), val.value)
        except Exception as exc:
            log.warning("Could not configure bit depth: %s", exc)

    def get_exposure_time(self) -> float:
        """Get current exposure time in milliseconds."""
        self._check_open()
        val = c_double(0)
        result = TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, byref(val), 0
        )
        log.debug("TUCAM_Prop_GetValue(EXPOSURETM) returned %s; value=%s", describe_tucam_ret(result), val.value)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get exposure failed: {describe_tucam_ret(result)}")
        return val.value

    def get_exposure_range(self) -> tuple[float, float]:
        """Get min/max exposure time (ms)."""
        self._check_open()
        attr = TUCAM_PROP_ATTR()
        attr.idProp = TUCAM_IDPROP.TUIDP_EXPOSURETM.value
        attr.nIdxChn = 0
        result = TUCAM_Prop_GetAttr(self._hcam, pointer(attr))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get exposure range failed: {describe_tucam_ret(result)}")
        return (attr.dbValMin, attr.dbValMax)

    # ------------------------------------------------------------------
    # Temperature  (TUIDP_TEMPERATURE_TARGET / TUIDC_ENABLETEC)
    # ------------------------------------------------------------------

    def set_temperature_target(self, temp_c: float) -> None:
        """Set target temperature in Celsius. Enables TEC automatically."""
        self._check_open()
        result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_ENABLETEC.value, 1)
        log.debug("TUCAM_Capa_SetValue(ENABLETEC=1) returned %s", describe_tucam_ret(result))
        result = TUCAM_Prop_SetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, c_double(temp_c), 0
        )
        log.info("Set temperature %.3f C returned %s", temp_c, describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Set temperature target failed: {describe_tucam_ret(result)}")

    def get_temperature_target(self) -> float:
        """Get current target temperature in Celsius."""
        self._check_open()
        val = c_double(0)
        result = TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, byref(val), 0
        )
        log.debug(
            "TUCAM_Prop_GetValue(TEMPERATURE_TARGET) returned %s; value=%s",
            describe_tucam_ret(result),
            val.value,
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get temperature target failed: {describe_tucam_ret(result)}")
        return val.value

    def get_temperature_range(self) -> tuple[float, float]:
        """Get min/max temperature target range."""
        self._check_open()
        attr = TUCAM_PROP_ATTR()
        attr.idProp = TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value
        attr.nIdxChn = 0
        result = TUCAM_Prop_GetAttr(self._hcam, pointer(attr))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get temperature range failed: {describe_tucam_ret(result)}")
        return (attr.dbValMin, attr.dbValMax)

    # ------------------------------------------------------------------
    # Fan Gear  (TUIDC_FAN_GEAR)
    # ------------------------------------------------------------------

    def set_fan_gear(self, gear: int) -> None:
        """Set fan gear (1-4). Gear 0 is NOT allowed per requirements."""
        self._check_open()
        if gear < 1 or gear > 4:
            raise ValueError("Fan gear must be 1-4 (gear 0 / off is not permitted)")
        try:
            attr = TUCAM_CAPA_ATTR()
            attr.idCapa = TUCAM_IDCAPA.TUIDC_FAN_GEAR.value
            attr_result = TUCAM_Capa_GetAttr(self._hcam, pointer(attr))
            log.info(
                "Fan gear attr returned %s; min=%s max=%s default=%s step=%s",
                describe_tucam_ret(attr_result),
                attr.nValMin,
                attr.nValMax,
                attr.nValDft,
                attr.nValStep,
            )
        except Exception as exc:
            log.warning("Failed to query fan gear attr: %s", exc)
        result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, gear)
        log.info("Set fan gear %s returned %s", gear, describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Set fan gear failed: {describe_tucam_ret(result)}")
        try:
            current = self.get_fan_gear()
            log.info("Fan gear readback after set: %s", current)
        except Exception as exc:
            log.warning("Fan gear readback failed after set: %s", exc)

    def get_fan_gear(self) -> int:
        """Get current fan gear."""
        self._check_open()
        val = c_int32(0)
        result = TUCAM_Capa_GetValue(
            self._hcam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, byref(val)
        )
        log.debug("TUCAM_Capa_GetValue(FAN_GEAR) returned %s; value=%s", describe_tucam_ret(result), val.value)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get fan gear failed: {describe_tucam_ret(result)}")
        return val.value

    def get_data_format(self) -> int:
        """Get current frame data format capability value."""
        self._check_open()
        val = c_int32(0)
        result = TUCAM_Capa_GetValue(
            self._hcam, TUCAM_IDCAPA.TUIDC_DATAFORMAT.value, byref(val)
        )
        log.debug("TUCAM_Capa_GetValue(DATAFORMAT) returned %s; value=%s", describe_tucam_ret(result), val.value)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get data format failed: {describe_tucam_ret(result)}")
        return val.value

    def get_bit_depth(self) -> int:
        """Get current bit-depth capability value."""
        self._check_open()
        val = c_int32(0)
        result = TUCAM_Capa_GetValue(
            self._hcam, TUCAM_IDCAPA.TUIDC_BITOFDEPTH.value, byref(val)
        )
        log.debug("TUCAM_Capa_GetValue(BITOFDEPTH) returned %s; value=%s", describe_tucam_ret(result), val.value)
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get bit depth failed: {describe_tucam_ret(result)}")
        return val.value

    # ------------------------------------------------------------------
    # Working Mode  (TUIDC_IMGMODESELECT)
    # ------------------------------------------------------------------

    MODE_LABELS = {0: "HDR", 1: "High Gain", 2: "Low Gain"}

    def set_working_mode(self, mode: int) -> None:
        """Set working mode. 0=HDR, 1=High Gain, 2=Low Gain."""
        self._check_open()
        if mode not in (0, 1, 2):
            raise ValueError(f"Invalid mode: {mode}")
        result = TUCAM_Capa_SetValue(self._hcam, TUCAM_IDCAPA.TUIDC_IMGMODESELECT.value, mode)
        log.info("Set working mode %s returned %s", mode, describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Set working mode failed: {describe_tucam_ret(result)}")

    def get_working_mode(self) -> int:
        """Get current working mode."""
        self._check_open()
        val = c_int32(0)
        result = TUCAM_Capa_GetValue(
            self._hcam, TUCAM_IDCAPA.TUIDC_IMGMODESELECT.value, byref(val)
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get working mode failed: {describe_tucam_ret(result)}")
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
        log.info("TUCAM_Buf_Alloc returned %s", describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Buffer alloc failed: {describe_tucam_ret(result)}")

    def _release_buffer(self) -> None:
        if self._frame is not None:
            result = TUCAM_Buf_Release(self._hcam)
            log.debug("TUCAM_Buf_Release returned %s", describe_tucam_ret(result))
            self._frame = None

    def start_capture(self) -> None:
        """Alloc buffer and start sequence capture."""
        self._check_open()
        self._alloc_buffer()
        result = TUCAM_Cap_Start(
            self._hcam, TUCAM_CAPTURE_MODES.TUCCM_SEQUENCE.value
        )
        log.info("TUCAM_Cap_Start(SEQUENCE) returned %s", describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            self._release_buffer()
            raise RuntimeError(f"Capture start failed: {describe_tucam_ret(result)}")
        self._capturing = True

    def stop_capture(self) -> None:
        """Stop capture and release buffer."""
        if not self._capturing:
            return
        result = TUCAM_Buf_AbortWait(self._hcam)
        log.debug("TUCAM_Buf_AbortWait returned %s", describe_tucam_ret(result))
        result = TUCAM_Cap_Stop(self._hcam)
        log.info("TUCAM_Cap_Stop returned %s", describe_tucam_ret(result))
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
            if result.value != TUCAMRET.TUCAMRET_TIMEOUT.value:
                log.warning("TUCAM_Buf_WaitForFrame returned %s", describe_tucam_ret(result))
            return None

        log.debug(
            (
                "Frame received: index=%s size=%sx%s width_step=%s depth=%s "
                "format=%s channels=%s elem_bytes=%s format_get=%s "
                "header=%s offset=%s img_size=%s rsd_size=%s hst_size=%s"
            ),
            self._frame.uiIndex,
            self._frame.usWidth,
            self._frame.usHeight,
            self._frame.uiWidthStep,
            self._frame.ucDepth,
            self._frame.ucFormat,
            self._frame.ucChannels,
            self._frame.ucElemBytes,
            self._frame.ucFormatGet,
            self._frame.usHeader,
            self._frame.usOffset,
            self._frame.uiImgSize,
            self._frame.uiRsdSize,
            self._frame.uiHstSize,
        )
        arr = self._frame_to_array(self._frame)
        log.info(
            "Frame array stats: shape=%s dtype=%s min=%s max=%s mean=%.3f",
            arr.shape,
            arr.dtype,
            int(arr.min()) if arr.size else "n/a",
            int(arr.max()) if arr.size else "n/a",
            float(arr.mean()) if arr.size else 0.0,
        )
        return arr

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
        total_size = frame.uiImgSize
        if not frame.pBuffer:
            raise RuntimeError("Frame buffer pointer is null")
        if w <= 0 or h <= 0:
            raise RuntimeError(f"Invalid frame dimensions: {w}x{h}")
        if elem_bytes <= 0:
            raise RuntimeError(f"Invalid frame element size: {elem_bytes}")
        if total_size <= 0:
            raise RuntimeError(f"Invalid frame image size: {total_size}")
        row_step = frame.uiWidthStep or (w * max(1, elem_bytes))
        channels = frame.ucChannels or max(1, row_step // max(1, w * max(1, elem_bytes)))
        data_offset = frame.usOffset or frame.usHeader
        payload_size = min(total_size, row_step * h) if row_step > 0 else total_size
        if row_step <= 0 or payload_size <= 0:
            raise RuntimeError(f"Invalid frame stride/payload: row_step={row_step} payload={payload_size}")

        buf = create_string_buffer(payload_size)
        ptr_data = c_void_p(frame.pBuffer + data_offset)
        memmove(buf, ptr_data, payload_size)

        if elem_bytes == 1:
            raw = np.frombuffer(buf, dtype=np.uint8, count=payload_size)
            if row_step >= w * channels and channels > 1:
                if payload_size < row_step * h:
                    raise RuntimeError(
                        f"Frame payload too small for multi-channel rows: payload={payload_size} expected={row_step * h}"
                    )
                rows = raw[: row_step * h].reshape((h, row_step))
                planes = rows[:, : w * channels].reshape((h, w, channels))
                arr = planes.max(axis=2)
                log.debug("Converted multi-channel uint8 frame using max projection channels=%s", channels)
                return arr.copy()
            if payload_size < w * h:
                raise RuntimeError(
                    f"Frame payload too small for uint8 image: payload={payload_size} expected={w * h}"
                )
            arr = raw[: w * h].reshape((h, w))
            return arr.copy()

        bytes_per_pixel = max(2, elem_bytes)
        if row_step >= w * bytes_per_pixel:
            if payload_size < row_step * h:
                raise RuntimeError(
                    f"Frame payload too small for padded rows: payload={payload_size} expected={row_step * h}"
                )
            raw = np.frombuffer(buf, dtype=np.uint8, count=payload_size)
            rows = raw[: row_step * h].reshape((h, row_step))
            pixel_bytes = rows[:, : w * bytes_per_pixel].reshape((h, w, bytes_per_pixel))
            if bytes_per_pixel == 2:
                arr = pixel_bytes.reshape((h, w * 2)).view("<u2").reshape((h, w))
            else:
                arr32 = pixel_bytes.astype(np.uint32)
                arr = arr32[:, :, 0] | (arr32[:, :, 1] << 8) | (arr32[:, :, 2] << 16)
            return arr.copy()

        if payload_size < w * h * 2:
            raise RuntimeError(
                f"Frame payload too small for uint16 image: payload={payload_size} expected={w * h * 2}"
            )
        arr = np.frombuffer(buf, dtype=np.uint16, count=w * h).reshape((h, w))
        return arr.copy()

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
        log.info("TUCAM_File_SaveImage(%s) returned %s", filepath, describe_tucam_ret(result))
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Save image failed: {describe_tucam_ret(result)}")

    # ------------------------------------------------------------------
    # Connection monitoring
    # ------------------------------------------------------------------

    def connection_status(self) -> bool | None:
        """
        Check if the physical device is still connected.

        Returns ``None`` when the SDK/camera does not support querying this
        status, which should be treated as "unknown", not disconnected.
        """
        if not self._opened or self._hcam == 0:
            return False
        try:
            vi = TUCAM_VALUE_INFO(TUCAM_IDINFO.TUIDI_CONNECTSTATUS.value, 0, 0, 0)
            result = TUCAM_Dev_GetInfo(self._hcam, pointer(vi))
            if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
                log.info("Connection status query unsupported/failed: %s", describe_tucam_ret(result))
                return None
            log.debug("Connection status value=%s", vi.nValue)
            if vi.nValue == 0:
                log.info(
                    "Connection status returned 0 while the device may still work; "
                    "treating it as unknown to avoid false disconnect warnings"
                )
                return None
            return True
        except Exception as exc:
            log.exception("Connection status query raised: %s", exc)
            return None

    def is_connected(self) -> bool:
        """Check if the physical device is still connected."""
        status = self.connection_status()
        return True if status is None else status

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
