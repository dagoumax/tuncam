# -*- coding: utf-8 -*-
"""Small reusable Qt models for the application's tabular data."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class TableDataModel(QAbstractTableModel):
    """A compact table model supporting editable columns and highlighted rows."""

    def __init__(
        self,
        headers: Sequence[str],
        *,
        editable_columns: Iterable[int] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._headers = tuple(headers)
        self._rows: list[list[str]] = []
        self._editable_columns = frozenset(int(column) for column in editable_columns)
        self._highlighted_rows: set[int] = set()
        self._warning_background = QColor("#ffd6d6")
        self._warning_foreground = QColor("#8b0000")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        column = index.column()
        if row >= len(self._rows) or column >= len(self._headers):
            return None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._rows[row][column]
        if role == Qt.ItemDataRole.BackgroundRole and row in self._highlighted_rows:
            return self._warning_background
        if role == Qt.ItemDataRole.ForegroundRole and row in self._highlighted_rows:
            return self._warning_foreground
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() in self._editable_columns:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(  # noqa: N802
        self,
        index: QModelIndex,
        value,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.EditRole
            or not index.isValid()
            or index.column() not in self._editable_columns
        ):
            return False
        text = str(value)
        if self._rows[index.row()][index.column()] == text:
            return True
        self._rows[index.row()][index.column()] = text
        self.dataChanged.emit(
            index,
            index,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
        )
        return True

    def set_headers(self, headers: Sequence[str]) -> None:
        normalized = tuple(headers)
        if normalized == self._headers:
            return
        self.beginResetModel()
        self._headers = normalized
        self._rows = [
            row[: len(normalized)] + [""] * max(0, len(normalized) - len(row))
            for row in self._rows
        ]
        self.endResetModel()

    def replace_rows(
        self,
        rows: Iterable[Sequence[object]],
        *,
        highlighted_rows: Iterable[int] = (),
    ) -> None:
        normalized = [
            [str(value) for value in row[: len(self._headers)]]
            + [""] * max(0, len(self._headers) - len(row))
            for row in rows
        ]
        highlighted = {int(row) for row in highlighted_rows}
        dimensions_changed = (
            len(normalized) != len(self._rows)
            or any(len(row) != len(self._headers) for row in self._rows)
        )
        if dimensions_changed:
            self.beginResetModel()
            self._rows = normalized
            self._highlighted_rows = highlighted
            self.endResetModel()
            return

        if normalized == self._rows and highlighted == self._highlighted_rows:
            return
        self._rows = normalized
        self._highlighted_rows = highlighted
        if self._rows and self._headers:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(self._headers) - 1),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.EditRole,
                    Qt.ItemDataRole.BackgroundRole,
                    Qt.ItemDataRole.ForegroundRole,
                ],
            )

    def append_row(self, values: Sequence[object]) -> int:
        row = len(self._rows)
        normalized = [str(value) for value in values[: len(self._headers)]]
        normalized.extend([""] * (len(self._headers) - len(normalized)))
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(normalized)
        self.endInsertRows()
        return row

    def remove_row(self, row: int) -> bool:
        if row < 0 or row >= len(self._rows):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        self._highlighted_rows = {
            value - 1 if value > row else value
            for value in self._highlighted_rows
            if value != row
        }
        self.endRemoveRows()
        return True

    def clear(self) -> None:
        if not self._rows:
            self._highlighted_rows.clear()
            return
        self.beginResetModel()
        self._rows.clear()
        self._highlighted_rows.clear()
        self.endResetModel()

    def rows(self) -> list[list[str]]:
        return [list(row) for row in self._rows]

    def cell_text(self, row: int, column: int) -> str:
        if row < 0 or row >= len(self._rows):
            return ""
        if column < 0 or column >= len(self._headers):
            return ""
        return self._rows[row][column]
