from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tucam_control.ui.row_group_dialog import RowGroupDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_dialog_returns_custom_names_and_ranges() -> None:
    _app()
    dialog = RowGroupDialog(
        [(890, 930), (980, 1000)],
        {
            "rows:890:930": "哈龙检测通道",
            "rows:980:1000": "参考通道",
        },
    )

    groups, names = dialog.values()

    assert groups == [(890, 930), (980, 1000)]
    assert names == {
        "rows:890:930": "哈龙检测通道",
        "rows:980:1000": "参考通道",
    }
