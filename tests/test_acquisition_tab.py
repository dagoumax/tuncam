# -*- coding: utf-8 -*-

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from tucam_control.ui.acquisition_tab import AcquisitionTab


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_hidden_tab_defers_preview_but_still_emits_frame() -> None:
    app = _app()
    tab = AcquisitionTab()
    frame = np.arange(512 * 512, dtype=np.uint16).reshape(512, 512)
    emitted = []
    renders = []
    tab.frame_ready.connect(emitted.append)
    original_set_image = tab._img_label.set_image
    tab._img_label.set_image = lambda *args: renders.append(args)

    tab.display_frame(frame)

    assert len(emitted) == 1
    assert emitted[0] is frame
    assert renders == []

    tab._img_label.set_image = original_set_image
    tab.show()
    app.processEvents()
    assert tab._img_label._raw_array is frame


def test_preview_downsamples_display_but_keeps_original_frame() -> None:
    _app()
    tab = AcquisitionTab()
    frame = np.arange(2048 * 2048, dtype=np.uint16).reshape(2048, 2048)
    captured = []
    tab._img_label.set_image = lambda raw, display: captured.append((raw, display))

    tab._render_preview(frame)

    raw, display = captured[0]
    assert raw is frame
    assert display.shape[0] < frame.shape[0]
    assert display.shape[1] < frame.shape[1]
