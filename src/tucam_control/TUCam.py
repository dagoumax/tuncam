# -*- coding: utf-8 -*-
"""
TUCam SDK Python Wrapper — adapted for tucam_control project.
Loads TUCam.dll from the project's lib/x64/ directory.
"""

import os
from ctypes import *
from enum import Enum

# Locate DLLs relative to this file
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_PACKAGE_DIR))
_DLL_PATH = os.path.join(_PROJECT_ROOT, "lib", "x64", "TUCam.dll")

if not os.path.exists(_DLL_PATH):
    raise FileNotFoundError(f"TUCam.dll not found at {_DLL_PATH}")

TUSDKdll = OleDLL(_DLL_PATH)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TUCAMRET(Enum):
    TUCAMRET_SUCCESS = 0x00000001
    TUCAMRET_FAILURE = 0x80000000
    TUCAMRET_NO_MEMORY = 0x80000101
    TUCAMRET_NO_RESOURCE = 0x80000102
    TUCAMRET_NO_MODULE = 0x80000103
    TUCAMRET_NO_DRIVER = 0x80000104
    TUCAMRET_NO_CAMERA = 0x80000105
    TUCAMRET_NO_GRABBER = 0x80000106
    TUCAMRET_NO_PROPERTY = 0x80000107
    TUCAMRET_FAILOPEN_CAMERA = 0x80000110
    TUCAMRET_FAILOPEN_BULKIN = 0x80000111
    TUCAMRET_FAILOPEN_BULKOUT = 0x80000112
    TUCAMRET_FAILOPEN_CONTROL = 0x80000113
    TUCAMRET_FAILCLOSE_CAMERA = 0x80000114
    TUCAMRET_FAILOPEN_FILE = 0x80000115
    TUCAMRET_FAILOPEN_CODEC = 0x80000116
    TUCAMRET_FAILOPEN_CONTEXT = 0x80000117
    TUCAMRET_INIT = 0x80000201
    TUCAMRET_BUSY = 0x80000202
    TUCAMRET_NOT_INIT = 0x80000203
    TUCAMRET_EXCLUDED = 0x80000204
    TUCAMRET_NOT_BUSY = 0x80000205
    TUCAMRET_NOT_READY = 0x80000206
    TUCAMRET_ABORT = 0x80000207
    TUCAMRET_TIMEOUT = 0x80000208
    TUCAMRET_LOSTFRAME = 0x80000209
    TUCAMRET_MISSFRAME = 0x8000020A
    TUCAMRET_USB_STATUS_ERROR = 0x8000020B
    TUCAMRET_INVALID_CAMERA = 0x80000301
    TUCAMRET_INVALID_HANDLE = 0x80000302
    TUCAMRET_INVALID_OPTION = 0x80000303
    TUCAMRET_INVALID_IDPROP = 0x80000304
    TUCAMRET_INVALID_IDCAPA = 0x80000305
    TUCAMRET_INVALID_IDPARAM = 0x80000306
    TUCAMRET_INVALID_PARAM = 0x80000307
    TUCAMRET_INVALID_FRAMEIDX = 0x80000308
    TUCAMRET_INVALID_VALUE = 0x80000309
    TUCAMRET_INVALID_EQUAL = 0x8000030A
    TUCAMRET_INVALID_CHANNEL = 0x8000030B
    TUCAMRET_INVALID_SUBARRAY = 0x8000030C
    TUCAMRET_INVALID_VIEW = 0x8000030D
    TUCAMRET_INVALID_PATH = 0x8000030E
    TUCAMRET_INVALID_IDVPROP = 0x8000030F
    TUCAMRET_NO_VALUETEXT = 0x80000310
    TUCAMRET_OUT_OF_RANGE = 0x80000311
    TUCAMRET_NOT_SUPPORT = 0x80000312
    TUCAMRET_NOT_WRITABLE = 0x80000313
    TUCAMRET_NOT_READABLE = 0x80000314
    TUCAMRET_WRONG_HANDSHAKE = 0x80000410
    TUCAMRET_NEWAPI_REQUIRED = 0x80000411
    TUCAMRET_ACCESSDENY = 0x80000412
    TUCAMRET_NO_CORRECTIONDATA = 0x80000501
    TUCAMRET_INVALID_PRFSETS = 0x80000601
    TUCAMRET_INVALID_IDPPROP = 0x80000602
    TUCAMRET_DECODE_FAILURE = 0x80000701
    TUCAMRET_COPYDATA_FAILURE = 0x80000702
    TUCAMRET_ENCODE_FAILURE = 0x80000703
    TUCAMRET_WRITE_FAILURE = 0x80000704
    TUCAMRET_FAIL_READ_CAMERA = 0x83001001
    TUCAMRET_FAIL_WRITE_CAMERA = 0x83001002
    TUCAMRET_OPTICS_UNPLUGGED = 0x83001003
    TUCAMRET_RECEIVE_FINISH = 0x00000002
    TUCAMRET_EXTERNAL_TRIGGER = 0x00000003


class TUCAM_IDINFO(Enum):
    TUIDI_BUS = 0x01
    TUIDI_VENDOR = 0x02
    TUIDI_PRODUCT = 0x03
    TUIDI_VERSION_API = 0x04
    TUIDI_VERSION_FRMW = 0x05
    TUIDI_VERSION_FPGA = 0x06
    TUIDI_VERSION_DRIVER = 0x07
    TUIDI_TRANSFER_RATE = 0x08
    TUIDI_CAMERA_MODEL = 0x09
    TUIDI_CURRENT_WIDTH = 0x0A
    TUIDI_CURRENT_HEIGHT = 0x0B
    TUIDI_CAMERA_CHANNELS = 0x0C
    TUIDI_BCDDEVICE = 0x0D
    TUIDI_TEMPALARMFLAG = 0x0E
    TUIDI_UTCTIME = 0x0F
    TUIDI_LONGITUDE_LATITUDE = 0x10
    TUIDI_WORKING_TIME = 0x11
    TUIDI_FAN_SPEED = 0x12
    TUIDI_FPGA_TEMPERATURE = 0x13
    TUIDI_PCBA_TEMPERATURE = 0x14
    TUIDI_ENV_TEMPERATURE = 0x15
    TUIDI_DEVICE_ADDRESS = 0x16
    TUIDI_USB_PORT_ID = 0x17
    TUIDI_CONNECTSTATUS = 0x18
    TUIDI_TOTALBUFFRAMES = 0x19
    TUIDI_CURRENTBUFFRAMES = 0x1A
    TUIDI_HDRRATIO = 0x1B
    TUIDI_HDRKHVALUE = 0x1C
    TUIDI_ZEROTEMPERATURE_VALUE = 0x1D
    TUIDI_VALID_FRAMEBIT = 0x1E
    TUIDI_CONFIG_HDR_HIGH_GAIN_K = 0x1F
    TUIDI_CONFIG_HDR_RATIO = 0x20
    TUIDI_CAMERA_PAYLOADSIZE = 0x21
    TUIDI_CAMERA_LOG = 0x22
    TUIDI_ENDINFO = 0x23


class TUCAM_IDCAPA(Enum):
    TUIDC_RESOLUTION = 0x00
    TUIDC_PIXELCLOCK = 0x01
    TUIDC_BITOFDEPTH = 0x02
    TUIDC_ATEXPOSURE = 0x03
    TUIDC_HORIZONTAL = 0x04
    TUIDC_VERTICAL = 0x05
    TUIDC_ATWBALANCE = 0x06
    TUIDC_FAN_GEAR = 0x07
    TUIDC_ATLEVELS = 0x08
    TUIDC_SHIFT = 0x09
    TUIDC_HISTC = 0x0A
    TUIDC_CHANNELS = 0x0B
    TUIDC_ENHANCE = 0x0C
    TUIDC_DFTCORRECTION = 0x0D
    TUIDC_ENABLEDENOISE = 0x0E
    TUIDC_FLTCORRECTION = 0x0F
    TUIDC_RESTARTLONGTM = 0x10
    TUIDC_DATAFORMAT = 0x11
    TUIDC_DRCORRECTION = 0x12
    TUIDC_VERCORRECTION = 0x13
    TUIDC_MONOCHROME = 0x14
    TUIDC_BLACKBALANCE = 0x15
    TUIDC_IMGMODESELECT = 0x16
    TUIDC_CAM_MULTIPLE = 0x17
    TUIDC_ENABLEPOWEEFREQUENCY = 0x18
    TUIDC_ROTATE_R90 = 0x19
    TUIDC_ROTATE_L90 = 0x1A
    TUIDC_NEGATIVE = 0x1B
    TUIDC_HDR = 0x1C
    TUIDC_ENABLEIMGPRO = 0x1D
    TUIDC_ENABLELED = 0x1E
    TUIDC_ENABLETIMESTAMP = 0x1F
    TUIDC_ENABLEBLACKLEVEL = 0x20
    TUIDC_ATFOCUS = 0x21
    TUIDC_ATFOCUS_STATUS = 0x22
    TUIDC_PGAGAIN = 0x23
    TUIDC_ATEXPOSURE_MODE = 0x24
    TUIDC_BINNING_SUM = 0x25
    TUIDC_BINNING_AVG = 0x26
    TUIDC_FOCUS_C_MOUNT = 0x27
    TUIDC_ENABLEPI = 0x28
    TUIDC_ATEXPOSURE_STATUS = 0x29
    TUIDC_ATWBALANCE_STATUS = 0x2A
    TUIDC_TESTIMGMODE = 0x2B
    TUIDC_SENSORRESET = 0x2C
    TUIDC_PGAHIGH = 0x2D
    TUIDC_PGALOW = 0x2E
    TUIDC_PIXCLK1_EN = 0x2F
    TUIDC_PIXCLK2_EN = 0x30
    TUIDC_ATLEVELGEAR = 0x31
    TUIDC_ENABLEDSNU = 0x32
    TUIDC_ENABLEOVERLAP = 0x33
    TUIDC_CAMSTATE = 0x34
    TUIDC_ENABLETRIOUT = 0x35
    TUIDC_ROLLINGSCANMODE = 0x36
    TUIDC_ROLLINGSCANLTD = 0x37
    TUIDC_ROLLINGSCANSLIT = 0x38
    TUIDC_ROLLINGSCANDIR = 0x39
    TUIDC_ROLLINGSCANRESET = 0x3A
    TUIDC_ENABLETEC = 0x3B
    TUIDC_ENABLEBLC = 0x3C
    TUIDC_ENABLETHROUGHFOG = 0x3D
    TUIDC_ENABLEGAMMA = 0x3E
    TUIDC_ENABLEFILTER = 0x3F
    TUIDC_ENABLEHLC = 0x40
    TUIDC_CAMPARASAVE = 0x41
    TUIDC_CAMPARALOAD = 0x42
    TUIDC_ENABLEISP = 0x43
    TUIDC_BUFFERHEIGHT = 0x44
    TUIDC_VISIBILITY = 0x45
    TUIDC_SHUTTER = 0x46
    TUIDC_SIGNALFILTER = 0x47
    TUIDC_ATEXPOSURE_TYPE = 0x48
    TUIDC_ENDCAPABILITY = 0x49


class TUCAM_IDPROP(Enum):
    TUIDP_GLOBALGAIN = 0x00
    TUIDP_EXPOSURETM = 0x01
    TUIDP_BRIGHTNESS = 0x02
    TUIDP_BLACKLEVEL = 0x03
    TUIDP_TEMPERATURE = 0x04
    TUIDP_SHARPNESS = 0x05
    TUIDP_NOISELEVEL = 0x06
    TUIDP_HDR_KVALUE = 0x07
    TUIDP_GAMMA = 0x08
    TUIDP_CONTRAST = 0x09
    TUIDP_LFTLEVELS = 0x0A
    TUIDP_RGTLEVELS = 0x0B
    TUIDP_CHNLGAIN = 0x0C
    TUIDP_SATURATION = 0x0D
    TUIDP_CLRTEMPERATURE = 0x0E
    TUIDP_CLRMATRIX = 0x0F
    TUIDP_DPCLEVEL = 0x10
    TUIDP_BLACKLEVELHG = 0x11
    TUIDP_BLACKLEVELLG = 0x12
    TUIDP_POWEEFREQUENCY = 0x13
    TUIDP_HUE = 0x14
    TUIDP_LIGHT = 0x15
    TUIDP_ENHANCE_STRENGTH = 0x16
    TUIDP_NOISELEVEL_3D = 0x17
    TUIDP_FOCUS_POSITION = 0x18
    TUIDP_FRAME_RATE = 0x19
    TUIDP_START_TIME = 0x1A
    TUIDP_FRAME_NUMBER = 0x1B
    TUIDP_INTERVAL_TIME = 0x1C
    TUIDP_GPS_APPLY = 0x1D
    TUIDP_AMB_TEMPERATURE = 0x1E
    TUIDP_AMB_HUMIDITY = 0x1F
    TUIDP_AUTO_CTRLTEMP = 0x20
    TUIDP_AVERAGEGRAY = 0x21
    TUIDP_AVERAGEGRAYTHD = 0x22
    TUIDP_ENHANCETHD = 0x23
    TUIDP_ENHANCEPARA = 0x24
    TUIDP_EXPOSUREMAX = 0x25
    TUIDP_EXPOSUREMIN = 0x26
    TUIDP_GAINMAX = 0x27
    TUIDP_GAINMIN = 0x28
    TUIDP_THROUGHFOGPARA = 0x29
    TUIDP_ATLEVEL_PERCENTAGE = 0x2A
    TUIDP_TEMPERATURE_TARGET = 0x2B
    TUIDP_PIXELRATIO = 0x2C
    TUIDP_ENDPROPERTY = 0x2D


class TUCAM_CAPTURE_MODES(Enum):
    TUCCM_SEQUENCE = 0x00
    TUCCM_TRIGGER_STANDARD = 0x01
    TUCCM_TRIGGER_SYNCHRONOUS = 0x02
    TUCCM_TRIGGER_GLOBAL = 0x03
    TUCCM_TRIGGER_SOFTWARE = 0x04
    TUCCM_TRIGGER_GPS = 0x05
    TUCCM_TRIGGER_STANDARD_NONOVERLAP = 0x11


class TUIMG_FORMATS(Enum):
    TUFMT_RAW = 0x01
    TUFMT_TIF = 0x02
    TUFMT_PNG = 0x04
    TUFMT_JPG = 0x08
    TUFMT_BMP = 0x10


class TUFRM_FORMATS(Enum):
    TUFRM_FMT_RAW = 0x10
    TUFRM_FMT_USUAl = 0x11
    TUFRM_FMT_RGB888 = 0x12


class TUGAIN_MODE(Enum):
    TUGAIN_HDR = 0x00
    TUGAIN_HIGH = 0x01
    TUGAIN_LOW = 0x02


# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class TUCAM_INIT(Structure):
    _fields_ = [
        ("uiCamCount", c_uint32),
        ("pstrConfigPath", c_char_p),
    ]


class TUCAM_OPEN(Structure):
    _fields_ = [
        ("uiIdxOpen", c_uint32),
        ("hIdxTUCam", c_void_p),
    ]


class TUCAM_VALUE_INFO(Structure):
    _fields_ = [
        ("nID", c_int32),
        ("nValue", c_int32),
        ("pText", c_char_p),
        ("nTextSize", c_int32),
    ]


class TUCAM_VALUE_TEXT(Structure):
    _fields_ = [
        ("nID", c_int32),
        ("dbValue", c_double),
        ("pText", c_char_p),
        ("nTextSize", c_int32),
    ]


class TUCAM_CAPA_ATTR(Structure):
    _fields_ = [
        ("idCapa", c_int32),
        ("nValMin", c_int32),
        ("nValMax", c_int32),
        ("nValDft", c_int32),
        ("nValStep", c_int32),
    ]


class TUCAM_PROP_ATTR(Structure):
    _fields_ = [
        ("idProp", c_int32),
        ("nIdxChn", c_int32),
        ("dbValMin", c_double),
        ("dbValMax", c_double),
        ("dbValDft", c_double),
        ("dbValStep", c_double),
    ]


class TUCAM_ROI_ATTR(Structure):
    _fields_ = [
        ("bEnable", c_int32),
        ("nHOffset", c_int32),
        ("nVOffset", c_int32),
        ("nWidth", c_int32),
        ("nHeight", c_int32),
    ]


class TUCAM_TRIGGER_ATTR(Structure):
    _fields_ = [
        ("nTgrMode", c_int32),
        ("nExpMode", c_int32),
        ("nEdgeMode", c_int32),
        ("nDelayTm", c_int32),
        ("nFrames", c_int32),
        ("nBufFrames", c_int32),
    ]


class TUCAM_TRGOUT_ATTR(Structure):
    _fields_ = [
        ("nTgrOutPort", c_int32),
        ("nTgrOutMode", c_int32),
        ("nEdgeMode", c_int32),
        ("nDelayTm", c_int32),
        ("nWidth", c_int32),
    ]


class TUCAM_BIN_ATTR(Structure):
    _fields_ = [
        ("bEnable", c_int32),
        ("nMode", c_int32),
        ("nWidth", c_int32),
        ("nHeight", c_int32),
    ]


class TUCAM_FRAME(Structure):
    _fields_ = [
        ("szSignature", c_char * 8),
        ("usHeader", c_ushort),
        ("usOffset", c_ushort),
        ("usWidth", c_ushort),
        ("usHeight", c_ushort),
        ("uiWidthStep", c_uint),
        ("ucDepth", c_ubyte),
        ("ucFormat", c_ubyte),
        ("ucChannels", c_ubyte),
        ("ucElemBytes", c_ubyte),
        ("ucFormatGet", c_ubyte),
        ("uiIndex", c_uint),
        ("uiImgSize", c_uint),
        ("uiRsdSize", c_uint),
        ("uiHstSize", c_uint),
        ("pBuffer", c_void_p),
    ]


class TUCAM_FILE_SAVE(Structure):
    _fields_ = [
        ("nSaveFmt", c_int32),
        ("pstrSavePath", c_char_p),
        ("pFrame", POINTER(TUCAM_FRAME)),
    ]


class TUCAM_REG_RW(Structure):
    _fields_ = [
        ("nRegType", c_int32),
        ("pBuf", c_char_p),
        ("nBufSize", c_int32),
    ]


class TUCAM_IMG_BACKGROUND(Structure):
    _fields_ = [
        ("bEnable", c_int32),
        ("ImgHeader", c_void_p),
    ]


class TUCAM_IMG_MATH(Structure):
    _fields_ = [
        ("bEnable", c_int32),
        ("nMode", c_int32),
        ("usGray", c_ushort),
    ]


# ---------------------------------------------------------------------------
# API function bindings
# ---------------------------------------------------------------------------

TUCAM_Api_Init = TUSDKdll.TUCAM_Api_Init
TUCAM_Api_Init.argtypes = [POINTER(TUCAM_INIT), c_int32]
TUCAM_Api_Init.restype = TUCAMRET

TUCAM_Api_Uninit = TUSDKdll.TUCAM_Api_Uninit
TUCAM_Api_Uninit.restype = TUCAMRET

TUCAM_Dev_Open = TUSDKdll.TUCAM_Dev_Open
TUCAM_Dev_Open.argtypes = [POINTER(TUCAM_OPEN)]
TUCAM_Dev_Open.restype = TUCAMRET

TUCAM_Dev_Close = TUSDKdll.TUCAM_Dev_Close
TUCAM_Dev_Close.argtypes = [c_void_p]
TUCAM_Dev_Close.restype = TUCAMRET

TUCAM_Dev_GetInfo = TUSDKdll.TUCAM_Dev_GetInfo
TUCAM_Dev_GetInfo.argtypes = [c_void_p, POINTER(TUCAM_VALUE_INFO)]
TUCAM_Dev_GetInfo.restype = TUCAMRET

TUCAM_Dev_GetInfoEx = TUSDKdll.TUCAM_Dev_GetInfoEx
TUCAM_Dev_GetInfoEx.argtypes = [c_uint, POINTER(TUCAM_VALUE_INFO)]
TUCAM_Dev_GetInfoEx.restype = TUCAMRET

TUCAM_Capa_GetAttr = TUSDKdll.TUCAM_Capa_GetAttr
TUCAM_Capa_GetAttr.argtypes = [c_void_p, POINTER(TUCAM_CAPA_ATTR)]
TUCAM_Capa_GetAttr.restype = TUCAMRET

TUCAM_Capa_GetValue = TUSDKdll.TUCAM_Capa_GetValue
TUCAM_Capa_GetValue.argtypes = [c_void_p, c_int32, c_void_p]
TUCAM_Capa_GetValue.restype = TUCAMRET

TUCAM_Capa_SetValue = TUSDKdll.TUCAM_Capa_SetValue
TUCAM_Capa_SetValue.argtypes = [c_void_p, c_int32, c_int32]
TUCAM_Capa_SetValue.restype = TUCAMRET

TUCAM_Prop_GetAttr = TUSDKdll.TUCAM_Prop_GetAttr
TUCAM_Prop_GetAttr.argtypes = [c_void_p, POINTER(TUCAM_PROP_ATTR)]
TUCAM_Prop_GetAttr.restype = TUCAMRET

TUCAM_Prop_GetValue = TUSDKdll.TUCAM_Prop_GetValue
TUCAM_Prop_GetValue.argtypes = [c_void_p, c_int32, c_void_p, c_int32]
TUCAM_Prop_GetValue.restype = TUCAMRET

TUCAM_Prop_SetValue = TUSDKdll.TUCAM_Prop_SetValue
TUCAM_Prop_SetValue.argtypes = [c_void_p, c_int32, c_double, c_int32]
TUCAM_Prop_SetValue.restype = TUCAMRET

TUCAM_Buf_Alloc = TUSDKdll.TUCAM_Buf_Alloc
TUCAM_Buf_Alloc.argtypes = [c_void_p, POINTER(TUCAM_FRAME)]
TUCAM_Buf_Alloc.restype = TUCAMRET

TUCAM_Buf_Release = TUSDKdll.TUCAM_Buf_Release
TUCAM_Buf_Release.argtypes = [c_void_p]
TUCAM_Buf_Release.restype = TUCAMRET

TUCAM_Buf_AbortWait = TUSDKdll.TUCAM_Buf_AbortWait
TUCAM_Buf_AbortWait.argtypes = [c_void_p]
TUCAM_Buf_AbortWait.restype = TUCAMRET

TUCAM_Buf_WaitForFrame = TUSDKdll.TUCAM_Buf_WaitForFrame
TUCAM_Buf_WaitForFrame.argtypes = [c_void_p, POINTER(TUCAM_FRAME), c_int32]
TUCAM_Buf_WaitForFrame.restype = TUCAMRET

TUCAM_Cap_Start = TUSDKdll.TUCAM_Cap_Start
TUCAM_Cap_Start.argtypes = [c_void_p, c_uint]
TUCAM_Cap_Start.restype = TUCAMRET

TUCAM_Cap_Stop = TUSDKdll.TUCAM_Cap_Stop
TUCAM_Cap_Stop.argtypes = [c_void_p]
TUCAM_Cap_Stop.restype = TUCAMRET

TUCAM_File_SaveImage = TUSDKdll.TUCAM_File_SaveImage
TUCAM_File_SaveImage.argtypes = [c_void_p, TUCAM_FILE_SAVE]
TUCAM_File_SaveImage.restype = TUCAMRET

TUCAM_Reg_Read = TUSDKdll.TUCAM_Reg_Read
TUCAM_Reg_Read.argtypes = [c_void_p, TUCAM_REG_RW]
TUCAM_Reg_Read.restype = TUCAMRET
