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

import numpy as np

from .debug_log import get_debug_logger
from .camera_types import CameraInfo
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
        cam.set_fan_gear(0)
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
        self._temperature_target_attr: TUCAM_PROP_ATTR | None = None
        self._temperature_target_supported: bool | None = None
        self._temperature_target_c: float | None = None
        self._last_frame_error: str | None = None

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
        self._temperature_target_attr = None
        self._temperature_target_supported = None
        self._temperature_target_c = None

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

    @property
    def last_frame_error(self) -> str | None:
        return self._last_frame_error

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
        """Configure the fixed scientific frame format used by Dhyana 95 V2."""
        self._check_open()
        # DATAFORMAT is not supported by Dhyana 95 V2 and BITOFDEPTH is fixed.
        # The requested format is supplied through TUCAM_FRAME.ucFormatGet.
        log.info("Dhyana 95 V2 frame format: USUAL, fixed 16-bit sensor data")

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
    # Temperature
    # ------------------------------------------------------------------

    def _temperature_attr(self, prop: TUCAM_IDPROP = TUCAM_IDPROP.TUIDP_TEMPERATURE) -> TUCAM_PROP_ATTR:
        attr = TUCAM_PROP_ATTR()
        attr.idProp = prop.value
        attr.nIdxChn = 0
        result = TUCAM_Prop_GetAttr(self._hcam, pointer(attr))
        log.debug(
            "%s attr returned %s; min=%s max=%s default=%s step=%s",
            prop.name,
            describe_tucam_ret(result),
            attr.dbValMin,
            attr.dbValMax,
            attr.dbValDft,
            attr.dbValStep,
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get {prop.name} range failed: {describe_tucam_ret(result)}")
        return attr

    def _target_attr(self) -> TUCAM_PROP_ATTR | None:
        if self._temperature_target_supported is False:
            return None
        if self._temperature_target_attr is not None:
            return self._temperature_target_attr
        try:
            attr = self._temperature_attr(TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET)
        except RuntimeError as exc:
            self._temperature_target_supported = False
            log.info("Dedicated temperature target is unavailable; using legacy control: %s", exc)
            return None
        if attr.dbValMax <= attr.dbValMin:
            self._temperature_target_supported = False
            log.info(
                "Dedicated temperature target returned an invalid range %.1f-%.1f; using legacy control",
                attr.dbValMin,
                attr.dbValMax,
            )
            return None
        self._temperature_target_supported = True
        self._temperature_target_attr = attr
        return attr

    @staticmethod
    def _encode_temperature(temp_c: float, attr: TUCAM_PROP_ATTR) -> float:
        if attr.dbValMin < 0.0:
            return temp_c
        scale = 10.0 if attr.dbValMax >= 500.0 else 1.0
        return (temp_c + 50.0) * scale

    @staticmethod
    def _decode_temperature(value: float, attr: TUCAM_PROP_ATTR) -> float:
        if attr.dbValMin < 0.0 or value < 0.0:
            return value
        scale = 10.0 if attr.dbValMax >= 500.0 else 1.0
        return value / scale - 50.0

    def set_temperature_target(self, temp_c: float) -> None:
        """Set target temperature in Celsius using the model-supported property."""
        self._check_open()
        attr = self._target_attr()
        prop = TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET
        if attr is None:
            prop = TUCAM_IDPROP.TUIDP_TEMPERATURE
            attr = self._temperature_attr(prop)
        sdk_value = self._encode_temperature(temp_c, attr)
        if sdk_value < attr.dbValMin or sdk_value > attr.dbValMax:
            raise ValueError(
                f"Temperature {temp_c:.1f} C encodes to {sdk_value:.1f}, "
                f"outside SDK range {attr.dbValMin:.1f}-{attr.dbValMax:.1f}"
            )
        result = TUCAM_Prop_SetValue(
            self._hcam, prop.value, c_double(sdk_value), 0
        )
        log.info(
            "Set temperature target %.3f C via %s (sdk_value=%.3f) returned %s",
            temp_c,
            prop.name,
            sdk_value,
            describe_tucam_ret(result),
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Set temperature target failed: {describe_tucam_ret(result)}")
        self._temperature_target_c = temp_c

    def get_temperature_target(self) -> float:
        """Get the configured target temperature in Celsius."""
        self._check_open()
        attr = self._target_attr()
        if attr is None:
            if self._temperature_target_c is None:
                raise RuntimeError("Temperature target readback is not supported")
            return self._temperature_target_c
        val = c_double(0)
        result = TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE_TARGET.value, byref(val), 0
        )
        log.debug(
            "TUCAM_Prop_GetValue(TEMPERATURE_TARGET) returned %s; sdk_value=%s",
            describe_tucam_ret(result),
            val.value,
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get temperature target failed: {describe_tucam_ret(result)}")
        return self._decode_temperature(val.value, attr)

    def get_sensor_temperature(self) -> float:
        """Get the current sensor temperature in Celsius."""
        self._check_open()
        val = c_double(0)
        result = TUCAM_Prop_GetValue(
            self._hcam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, byref(val), 0
        )
        log.debug(
            "TUCAM_Prop_GetValue(TEMPERATURE) returned %s; value_c=%s",
            describe_tucam_ret(result),
            val.value,
        )
        if result.value != TUCAMRET.TUCAMRET_SUCCESS.value:
            raise RuntimeError(f"Get sensor temperature failed: {describe_tucam_ret(result)}")
        return val.value

    def get_temperature_range(self) -> tuple[float, float]:
        """Get min/max temperature target range."""
        self._check_open()
        attr = self._target_attr() or self._temperature_attr()
        return (
            self._decode_temperature(attr.dbValMin, attr),
            self._decode_temperature(attr.dbValMax, attr),
        )

    # ------------------------------------------------------------------
    # Fan Gear  (TUIDC_FAN_GEAR)
    # ------------------------------------------------------------------

    def set_fan_gear(self, gear: int) -> None:
        """Set Dhyana 95 V2 fan speed: 0=high, 1=medium, 2=low."""
        self._check_open()
        if gear not in (0, 1, 2):
            raise ValueError("Fan value must be 0 (high), 1 (medium), or 2 (low); 3 disables the fan")
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
        """Return the requested frame format; DATAFORMAT capability is unsupported."""
        self._check_open()
        return TUFRM_FORMATS.TUFRM_FMT_USUAl.value

    def get_bit_depth(self) -> int:
        """Get frame bit depth, fixed at 16 for Dhyana 95 V2."""
        self._check_open()
        if self._frame is not None and self._frame.ucDepth:
            return int(self._frame.ucDepth)
        return 16

    # ------------------------------------------------------------------
    # Working Mode  (TUIDC_IMGMODESELECT)
    # ------------------------------------------------------------------

    MODE_LABELS = {0: "HDR", 1: "Std_High", 2: "Std_Low"}

    def set_working_mode(self, mode: int) -> None:
        """Set working mode. 0=HDR, 1=Std_High, 2=Std_Low."""
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
        self._frame.ucFormatGet = TUFRM_FORMATS.TUFRM_FMT_USUAl.value
        self._frame.uiRsdSize = 1
        result = TUCAM_Buf_Alloc(self._hcam, pointer(self._frame))
        log.info(
            "TUCAM_Buf_Alloc returned %s; requested_format=%s actual_format_get=%s",
            describe_tucam_ret(result),
            TUFRM_FORMATS.TUFRM_FMT_USUAl.name,
            self._frame.ucFormatGet,
        )
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
        self._last_frame_error = None
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
        self.abort_wait()
        self.finish_stop_capture()

    def abort_wait(self) -> None:
        """Interrupt a blocking frame wait without releasing its buffer."""
        if not self._capturing:
            return
        result = TUCAM_Buf_AbortWait(self._hcam)
        log.debug("TUCAM_Buf_AbortWait returned %s", describe_tucam_ret(result))

    def finish_stop_capture(self) -> None:
        """Stop SDK capture and release the buffer after the wait loop exits."""
        if not self._capturing:
            return
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
            benign_results = {
                TUCAMRET.TUCAMRET_ABORT.value,
                TUCAMRET.TUCAMRET_TIMEOUT.value,
                TUCAMRET.TUCAMRET_LOSTFRAME.value,
                TUCAMRET.TUCAMRET_MISSFRAME.value,
            }
            if result.value not in benign_results:
                self._last_frame_error = describe_tucam_ret(result)
            else:
                self._last_frame_error = None
            if result.value != TUCAMRET.TUCAMRET_TIMEOUT.value:
                log.warning("TUCAM_Buf_WaitForFrame returned %s", describe_tucam_ret(result))
            return None

        self._last_frame_error = None
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
