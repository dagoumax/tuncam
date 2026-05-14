# -*- coding: utf-8 -*-
"""Acquisition tab — live image display, capture controls, device info."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal, Slot, QPoint, QRect
from PySide6.QtGui import (
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QColor,
    QFont,
    QMouseEvent,
    QKeyEvent,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

from ..camera import CameraInfo

_GEAR_LABELS = {1: "一档 / Gear 1", 2: "二档 / Gear 2", 3: "三档 / Gear 3", 4: "四档 / Gear 4"}


class ImageLabel(QLabel):
    """QLabel subclass with crosshair cursor and pixel value readout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(800, 600)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet("background-color: #1a1a1a; color: #888;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._raw_array: np.ndarray | None = None
        self._cursor_enabled: bool = False
        self._cursor_image_x: int = 0
        self._cursor_image_y: int = 0
        self._img_w: int = 0
        self._img_h: int = 0

    def set_image(self, raw_array: np.ndarray, display_array: np.ndarray) -> None:
        self._raw_array = raw_array
        h, w = display_array.shape
        self._img_w = w
        self._img_h = h
        qimg = QImage(display_array.data, w, h, w, QImage.Format.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg)
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _widget_to_image(self, wx: int, wy: int) -> tuple[int, int]:
        """Map widget coordinates to image pixel coordinates."""
        pixmap = self.pixmap()
        if pixmap is None or self._img_w == 0:
            return 0, 0
        pw = pixmap.width()
        ph = pixmap.height()
        if pw <= 0 or ph <= 0:
            return 0, 0
        lw = self.width()
        lh = self.height()
        ox = (lw - pw) // 2
        oy = (lh - ph) // 2
        ix = int((wx - ox) / pw * self._img_w)
        iy = int((wy - oy) / ph * self._img_h)
        ix = max(0, min(ix, self._img_w - 1))
        iy = max(0, min(iy, self._img_h - 1))
        return ix, iy

    def _image_to_widget(self, ix: int, iy: int) -> tuple[int, int]:
        """Map image coordinates to widget coordinates for drawing."""
        pixmap = self.pixmap()
        if pixmap is None or self._img_w == 0:
            return 0, 0
        pw = pixmap.width()
        ph = pixmap.height()
        lw = self.width()
        lh = self.height()
        ox = (lw - pw) // 2
        oy = (lh - ph) // 2
        wx = int(ix / self._img_w * pw + ox)
        wy = int(iy / self._img_h * ph + oy)
        return wx, wy

    def _get_value_str(self) -> str:
        if self._raw_array is None:
            return ""
        val = self._raw_array[self._cursor_image_y, self._cursor_image_x]
        return f"({self._cursor_image_x}, {self._cursor_image_y}) = {val}"

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._cursor_enabled or self._raw_array is None:
            return
        try:
            wx, wy = self._image_to_widget(self._cursor_image_x, self._cursor_image_y)
            painter = QPainter(self)
            pen = QPen(QColor(255, 0, 0), 1)
            painter.setPen(pen)
            painter.drawLine(wx - 8, wy, wx + 8, wy)
            painter.drawLine(wx, wy - 8, wx, wy + 8)
            painter.fillRect(wx + 10, wy + 4, 220, 20, QColor(0, 0, 0, 180))
            painter.setPen(QColor(0, 255, 0))
            painter.setFont(QFont("Consolas", 9))
            painter.drawText(wx + 14, wy + 18, self._get_value_str())
            painter.end()
        except Exception:
            pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        try:
            if event.button() == Qt.MouseButton.RightButton:
                self._cursor_enabled = False
                self.update()
                return
            if event.button() == Qt.MouseButton.LeftButton and self._raw_array is not None:
                ix, iy = self._widget_to_image(int(event.position().x()), int(event.position().y()))
                self._cursor_image_x = ix
                self._cursor_image_y = iy
                self._cursor_enabled = True
                self.setFocus()
                self.update()
                return
        except Exception:
            import traceback
            traceback.print_exc()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        try:
            if not self._cursor_enabled or self._raw_array is None:
                super().keyPressEvent(event)
                return
            moved = False
            if event.key() == Qt.Key.Key_Left:
                self._cursor_image_x = max(0, self._cursor_image_x - 1)
                moved = True
            elif event.key() == Qt.Key.Key_Right:
                self._cursor_image_x = min(self._img_w - 1, self._cursor_image_x + 1)
                moved = True
            elif event.key() == Qt.Key.Key_Up:
                self._cursor_image_y = max(0, self._cursor_image_y - 1)
                moved = True
            elif event.key() == Qt.Key.Key_Down:
                self._cursor_image_y = min(self._img_h - 1, self._cursor_image_y + 1)
                moved = True
            elif event.key() == Qt.Key.Key_Escape:
                self._cursor_enabled = False
            else:
                super().keyPressEvent(event)
                return
            if moved:
                self.update()
        except Exception:
            import traceback
            traceback.print_exc()



class AcquisitionTab(QWidget):
    """First tab: image preview, capture buttons, device info panel."""

    start_single = Signal()
    start_continuous = Signal()
    stop_requested = Signal()
    save_requested = Signal()
    connect_requested = Signal()
    load_tif_requested = Signal(str)
    batch_load_requested = Signal(str)
    batch_start_requested = Signal()
    batch_stop_requested = Signal()
    frame_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self._img_label = ImageLabel()
        self._cursor_info = QLabel("光标: 左键设置 / 右键取消 / 方向键移动 / Esc 关闭")
        self._cursor_info.setStyleSheet("color: #aaa; padding: 2px;")

        btn_row = QHBoxLayout()
        self._btn_single = QPushButton("单帧采集\nSingle")
        self._btn_cont = QPushButton("连续采集\nContinuous")
        self._btn_stop = QPushButton("停止采集中\nStop")
        self._btn_stop.setEnabled(False)
        self._btn_save = QPushButton("保存图片\nSave Image")
        self._btn_connect = QPushButton("重新连接\nReconnect")
        self._btn_load = QPushButton("载入TIF\nLoad TIF")
        self._btn_batch = QPushButton("批量测试\nBatch Test")
        self._btn_batch_stop = QPushButton("停止批量\nStop Batch")
        self._btn_batch_stop.setEnabled(False)

        self._btn_single.clicked.connect(self.start_single)
        self._btn_cont.clicked.connect(self.start_continuous)
        self._btn_stop.clicked.connect(self.stop_requested)
        self._btn_save.clicked.connect(self.save_requested)
        self._btn_connect.clicked.connect(self.connect_requested)
        self._btn_load.clicked.connect(self._on_load_tif)
        self._btn_batch.clicked.connect(self._on_batch_load)
        self._btn_batch_stop.clicked.connect(self.batch_stop_requested)

        for btn in (self._btn_single, self._btn_cont, self._btn_stop,
                     self._btn_save, self._btn_connect, self._btn_load,
                     self._btn_batch, self._btn_batch_stop):
            btn.setMinimumHeight(48)

        btn_row.addWidget(self._btn_single)
        btn_row.addWidget(self._btn_cont)
        btn_row.addWidget(self._btn_stop)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_load)
        btn_row.addWidget(self._btn_batch)
        btn_row.addWidget(self._btn_batch_stop)

        left.addWidget(self._img_label, 1)
        left.addWidget(self._cursor_info)
        left.addLayout(btn_row)

        right = QVBoxLayout()
        gb = QGroupBox("设备信息 / Device Info")
        self._info_text = QTextEdit()
        self._info_text.setReadOnly(True)
        self._info_text.setMinimumWidth(400)
        gb_layout = QVBoxLayout(gb)
        gb_layout.addWidget(self._info_text)
        right.addWidget(gb)

        gb_tel = QGroupBox("实时状态 / Telemetry")
        self._tel_label = QLabel("温度: --  /  风扇: --  /  速度: --")
        self._tel_label.setWordWrap(True)
        gbt_layout = QVBoxLayout(gb_tel)
        gbt_layout.addWidget(self._tel_label)
        right.addWidget(gb_tel)

        right.addStretch()

        layout.addLayout(left, 3)
        layout.addLayout(right, 1)

    def set_capturing_state(self, active: bool) -> None:
        self._capturing = active
        self._btn_single.setEnabled(not active)
        self._btn_cont.setEnabled(not active)
        self._btn_stop.setEnabled(active)
        self._btn_batch.setEnabled(not active)
        self._btn_batch_stop.setEnabled(active)

    def set_batch_state(self, active: bool) -> None:
        self._btn_single.setEnabled(not active)
        self._btn_cont.setEnabled(not active)
        self._btn_stop.setEnabled(False)
        self._btn_batch.setEnabled(not active)
        self._btn_batch_stop.setEnabled(active)

    def show_device_info(self, info: CameraInfo) -> None:
        lines = [
            f"型号/Model:          {info.model}",
            f"序列号/SN:           {info.serial_number}",
            f"VID:                 {hex(info.vendor_id)}",
            f"PID:                 {hex(info.product_id)}",
            f"API 版本:            {info.api_version}",
            f"固件版本/FW:         {info.firmware_version}",
            f"FPGA 版本:           {info.fpga_version}",
            f"驱动版本/Driver:     {info.driver_version}",
            f"传感器宽度/Width:    {info.sensor_width} px",
            f"传感器高度/Height:   {info.sensor_height} px",
            f"通道数/Channels:     {info.channels}",
            f"总线类型/Bus:        0x{info.bus_type:X}",
            f"传输速率/Rate:       {info.transfer_rate}",
        ]
        self._info_text.setPlainText("\n".join(lines))

    def update_telemetry(self, info: CameraInfo) -> None:
        gear_name = _GEAR_LABELS.get(info.fan_speed, f"{info.fan_speed}")
        text = (
            f"FPGA 温度: {info.fpga_temperature:.1f} °C  |  "
            f"PCBA 温度: {info.pcba_temperature:.1f} °C  |  "
            f"环境温度: {info.env_temperature:.1f} °C\n"
            f"风扇: {gear_name}"
        )
        self._tel_label.setText(text)

    def display_frame(self, arr: np.ndarray) -> None:
        h, w = arr.shape
        mn = arr.min()
        mx = arr.max()
        if mx > mn:
            display = ((arr.astype(np.float64) - mn) / (mx - mn) * 255).astype(np.uint8)
        else:
            display = np.zeros_like(arr, dtype=np.uint8)
        self._img_label.set_image(arr, display)
        self.frame_ready.emit(arr)

    @Slot()
    def _on_load_tif(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "载入 TIF 图片 / Load TIF Images",
            "",
            "TIFF (*.tif *.tiff);;所有文件 (*.*)",
        )
        for path in paths:
            self.load_tif_requested.emit(path)

    @Slot()
    def _on_batch_load(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择含 TIF 的文件夹 / Select TIF Folder",
            "",
        )
        if folder:
            self.batch_load_requested.emit(folder)
