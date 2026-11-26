# -*- coding: utf-8 -*-
"""Row-group range and display-name editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from ..row_group_io import read_groups_csv, write_groups_csv, detect_folder_groups


class _DetectionSignals(QObject):
    finished = Signal(object, str)


class _DetectionTask(QRunnable):
    def __init__(self, folder, prominence, distance):
        super().__init__()
        self.args = (folder, prominence, distance)
        self.signals = _DetectionSignals()

    def run(self):
        try:
            rows = detect_folder_groups(*self.args)
            self.signals.finished.emit(rows, "")
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))

from ..row_groups import (
    MAX_ROW_GROUPS,
    default_row_group_name,
    describe_row_groups,
    row_group_key,
)


class RowGroupDialog(QDialog):
    """Edit up to sixteen named row ranges without exposing names as IDs."""

    def __init__(
        self,
        groups: list[tuple[int, int]],
        custom_names: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("行组管理 / Row Group Manager")
        self.resize(720, 480)
        self._setup_ui()
        self._detection_task = None
        descriptors = describe_row_groups(groups, custom_names=custom_names)
        self._replace_rows(
            [(item.label, item.start, item.end) for item in descriptors]
        )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("名称用于图例、筛选、诊断和导出；起始行与结束行仅在此处显示。")
        )

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["顺序", "自定义名称", "起始行", "结束行"]
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

        tools = QHBoxLayout()
        self._add_button = QPushButton("添加")
        self._delete_button = QPushButton("删除")
        self._up_button = QPushButton("上移")
        self._down_button = QPushButton("下移")
        self._add_button.clicked.connect(self._add_row)
        self._delete_button.clicked.connect(self._delete_row)
        self._up_button.clicked.connect(lambda: self._move_row(-1))
        self._down_button.clicked.connect(lambda: self._move_row(1))
        for button in (
            self._add_button,
            self._delete_button,
            self._up_button,
            self._down_button,
        ):
            tools.addWidget(button)
        tools.addStretch()
        self._count_label = QLabel()
        tools.addWidget(self._count_label)
        layout.addLayout(tools)

        file_tools = QHBoxLayout()
        self._import_button = QPushButton("导入 CSV")
        self._export_button = QPushButton("导出 CSV")
        self._detect_button = QPushButton("从 TIFF 文件夹识别")
        self._import_button.clicked.connect(self._import_csv)
        self._export_button.clicked.connect(self._export_csv)
        self._detect_button.clicked.connect(self._detect_folder)
        for button in (self._import_button, self._export_button, self._detect_button):
            file_tools.addWidget(button)
        layout.addLayout(file_tools)
        detection_options = QHBoxLayout()
        detection_options.addWidget(QLabel("显著度 (%)"))
        self._prominence = QSpinBox()
        self._prominence.setRange(1, 80)
        self._prominence.setValue(8)
        detection_options.addWidget(self._prominence)
        detection_options.addWidget(QLabel("最小间距 (行)"))
        self._distance = QSpinBox()
        self._distance.setRange(5, 500)
        self._distance.setValue(20)
        detection_options.addWidget(self._distance)
        self._detection_status = QLabel()
        self._detection_status.setWordWrap(True)
        detection_options.addWidget(self._detection_status, 1)
        layout.addLayout(detection_options)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入探头配置", "", "CSV (*.csv)")
        if not path:
            return
        try:
            rows = read_groups_csv(path)
            self._replace_rows(rows)
            self._detection_status.setText(f"已导入 {len(rows)} 个探头，待保存")
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出探头配置", "probes.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            write_groups_csv(path, self._all_rows())
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def _detect_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 TIFF 文件夹")
        if not folder:
            return
        self._detect_button.setEnabled(False)
        self._import_button.setEnabled(False)
        self._detection_status.setText("正在识别…")
        task = _DetectionTask(folder, self._prominence.value(), self._distance.value())
        task.signals.finished.connect(self._detection_finished)
        self._detection_task = task
        self._table.setEnabled(False)
        for button in (self._add_button, self._delete_button, self._up_button, self._down_button):
            button.setEnabled(False)
        QThreadPool.globalInstance().start(task)

    def _detection_finished(self, rows, error):
        self._detection_task = None
        self._detect_button.setEnabled(True)
        self._import_button.setEnabled(True)
        self._table.setEnabled(True)
        for button in (self._add_button, self._delete_button, self._up_button, self._down_button):
            button.setEnabled(True)
        if error:
            self._detection_status.setText(error)
            return
        self._replace_rows(rows)
        self._detection_status.setText(f"识别到 {len(rows)} 个候选探头，待核对并保存")

    @staticmethod
    def _spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 1_000_000)
        spin.setValue(int(value))
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return spin

    def _append_row(self, name: str, start: int, end: int) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        order = QTableWidgetItem(str(row + 1))
        order.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        order.setFlags(order.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, order)
        name_edit = QLineEdit(str(name))
        name_edit.setMaxLength(32)
        self._table.setCellWidget(row, 1, name_edit)
        self._table.setCellWidget(row, 2, self._spin(start))
        self._table.setCellWidget(row, 3, self._spin(end))
        self._update_count()

    def _replace_rows(self, rows: list[tuple[str, int, int]]) -> None:
        self._table.setRowCount(0)
        for name, start, end in rows:
            self._append_row(name, start, end)
        self._update_count()

    def _row_values(self, row: int) -> tuple[str, int, int]:
        name_edit = self._table.cellWidget(row, 1)
        start_spin = self._table.cellWidget(row, 2)
        end_spin = self._table.cellWidget(row, 3)
        return (
            name_edit.text().strip(),
            int(start_spin.value()),
            int(end_spin.value()),
        )

    def _all_rows(self) -> list[tuple[str, int, int]]:
        return [self._row_values(row) for row in range(self._table.rowCount())]

    def _selected_row(self) -> int:
        selected = self._table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1

    def _add_row(self) -> None:
        count = self._table.rowCount()
        if count >= MAX_ROW_GROUPS:
            QMessageBox.information(
                self,
                "行组数量已满",
                f"最多支持 {MAX_ROW_GROUPS} 个行组。",
            )
            return
        if count:
            _, _, previous_end = self._row_values(count - 1)
            start = previous_end + 1
        else:
            start = 1
        self._append_row(default_row_group_name(count), start, start + 39)
        self._table.selectRow(count)

    def _delete_row(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        self._table.removeRow(row)
        self._renumber()

    def _move_row(self, offset: int) -> None:
        row = self._selected_row()
        target = row + int(offset)
        if row < 0 or target < 0 or target >= self._table.rowCount():
            return
        rows = self._all_rows()
        rows[row], rows[target] = rows[target], rows[row]
        self._replace_rows(rows)
        self._table.selectRow(target)

    def _renumber(self) -> None:
        for row in range(self._table.rowCount()):
            self._table.item(row, 0).setText(str(row + 1))
        self._update_count()

    def _update_count(self) -> None:
        if hasattr(self, "_count_label"):
            self._count_label.setText(
                f"{self._table.rowCount()} / {MAX_ROW_GROUPS} 个行组"
            )

    def values(self) -> tuple[list[tuple[int, int]], dict[str, str]]:
        rows = self._all_rows()
        groups = [(start, end) for _, start, end in rows]
        names = {
            row_group_key(start, end): name
            for name, start, end in rows
        }
        return groups, names

    def accept(self) -> None:
        if self._detection_task is not None:
            self._detection_status.setText("识别尚未完成，请等待或取消窗口")
            return
        rows = self._all_rows()
        names_seen: set[str] = set()
        ranges_seen: set[tuple[int, int]] = set()
        for index, (name, start, end) in enumerate(rows, start=1):
            if not name:
                QMessageBox.warning(self, "名称无效", f"第 {index} 个行组名称不能为空。")
                return
            if any(character in name for character in ("\r", "\n", "\t")):
                QMessageBox.warning(
                    self,
                    "名称无效",
                    f"第 {index} 个行组名称不能包含换行或制表符。",
                )
                return
            normalized_name = name.casefold()
            if normalized_name in names_seen:
                QMessageBox.warning(self, "名称重复", f"行组名称“{name}”重复。")
                return
            names_seen.add(normalized_name)
            if start > end:
                QMessageBox.warning(
                    self,
                    "范围无效",
                    f"行组“{name}”的起始行不能大于结束行。",
                )
                return
            row_range = (start, end)
            if row_range in ranges_seen:
                QMessageBox.warning(
                    self,
                    "范围重复",
                    f"行组“{name}”使用了重复的行范围。",
                )
                return
            ranges_seen.add(row_range)
        super().accept()
