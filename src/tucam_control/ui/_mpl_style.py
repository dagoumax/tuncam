# -*- coding: utf-8 -*-
"""Shared matplotlib configuration — CJK fonts, colors, styling."""

from __future__ import annotations

import matplotlib
import matplotlib.font_manager as fm

_CJK_FONTS = [
    "Microsoft YaHei", "SimHei", "SimSun",
    "WenQuanYi Micro Hei", "Noto Sans CJK SC",
]
_available = {f.name for f in fm.fontManager.ttflist}
_cjk_font = None
for _f in _CJK_FONTS:
    if _f in _available:
        _cjk_font = _f
        break
if _cjk_font:
    matplotlib.rcParams["font.family"] = ["sans-serif"]
    matplotlib.rcParams["font.sans-serif"] = [_cjk_font, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

WINDOW_SIZE = 100


def fix_tick_labels(ax) -> None:
    """Ensure tick labels use a font with proper minus sign."""
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_family("DejaVu Sans")
