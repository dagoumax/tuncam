from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CameraInfo:
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
