"""Portable probe definitions and conservative image-band detection."""

import csv
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from .row_groups import MAX_ROW_GROUPS

HEADERS = ["名称", "起始行", "结束行"]


def validate_rows(rows):
    if len(rows) > MAX_ROW_GROUPS:
        raise ValueError(f"最多支持 {MAX_ROW_GROUPS} 个探头")
    names, ranges = set(), set()
    for name, start, end in rows:
        if not name.strip() or len(name) > 32 or any(c in name for c in "\r\n\t"):
            raise ValueError("名称必须为 1–32 个字符，不能包含换行或制表符")
        if name.casefold() in names or (start, end) in ranges:
            raise ValueError("名称或行范围重复")
        if not 1 <= start <= end <= 1_000_000:
            raise ValueError("行范围必须为正整数，且起始行不大于结束行")
        names.add(name.casefold())
        ranges.add((start, end))
    return rows


def read_groups_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != HEADERS:
            raise ValueError("CSV 表头必须为：名称,起始行,结束行")
        rows = []
        for row in reader:
            if None in row or any(row.get(key) is None for key in HEADERS):
                raise ValueError("CSV 每行必须包含名称、起始行、结束行三列")
            rows.append((row[HEADERS[0]].strip(), int(row[HEADERS[1]]), int(row[HEADERS[2]])))
    return validate_rows(rows)


def write_groups_csv(path, rows):
    validate_rows(rows)
    with open(path, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def detect_profile_groups(profile, prominence_percent=8.0, minimum_distance=20):
    """Detect locally prominent bands and divide adjacent bands at valleys."""
    profile = np.asarray(profile, dtype=float)
    if profile.ndim != 1 or len(profile) < 7 or not np.isfinite(profile).all():
        raise ValueError("图像行强度数据无效")
    if not 0 < prominence_percent <= 100 or minimum_distance < 1:
        raise ValueError("显著度必须为 0–100% 之间的正数，最小间距至少为 1 行")
    profile = gaussian_filter1d(profile, 3)
    noise = np.median(np.abs(np.diff(profile) - np.median(np.diff(profile)))) * 1.4826
    background = float(np.percentile(profile, 20))
    noise_floor = max(6 * noise, 0.5)
    peaks, properties = find_peaks(
        profile, prominence=noise_floor, distance=minimum_distance, width=3,
    )
    heights = profile[peaks] - background
    # A bright probe must not set the rejection threshold for a dim neighbour.
    keep = (heights > noise_floor) & (
        properties["prominences"] >= heights * prominence_percent / 100
    )
    peaks = peaks[keep]
    if len(peaks) > MAX_ROW_GROUPS:
        raise ValueError("候选行带超过 16 个，请提高显著度或增大最小间距后重试")
    if not len(peaks):
        raise ValueError("未找到可靠的亮行带，请检查图像或降低显著度")
    valleys = [int(a + np.argmin(profile[a:b + 1])) for a, b in zip(peaks[:-1], peaks[1:])]
    # Extend to 20% of each peak above background. Adjacent illuminated bands
    # share a valley boundary; a genuinely dark gap remains excluded.
    edges = []
    for i, peak in enumerate(peaks):
        level = background + max(noise_floor, 0.2 * (profile[peak] - background))
        lo_limit = valleys[i - 1] + 1 if i else 0
        hi_limit = valleys[i] if i < len(valleys) else len(profile) - 1
        lo = hi = int(peak)
        while lo > lo_limit and profile[lo - 1] >= level:
            lo -= 1
        while hi < hi_limit and profile[hi + 1] >= level:
            hi += 1
        edges.append([lo, hi])
    for i, valley in enumerate(valleys):
        dark_level = background + max(
            noise_floor, 0.2 * min(profile[peaks[i]] - background, profile[peaks[i + 1]] - background),
        )
        if profile[valley] > dark_level:
            edges[i][1] = valley
            edges[i + 1][0] = valley + 1
    numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四", "十五", "十六"]
    rows = []
    for i, (lo, hi) in enumerate(edges):
        rows.append((f"第{numerals[i]}个探头", lo + 1, hi + 1))
    return validate_rows(rows)


def detect_folder_groups(folder, prominence_percent=8.0, minimum_distance=20):
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in {".tif", ".tiff"})
    if not files:
        raise ValueError("文件夹中没有 TIF/TIFF 图像")
    # At most five evenly spaced frames; retain only row profiles in memory.
    profiles = []
    shape = None
    for index in np.unique(np.linspace(0, len(files) - 1, min(5, len(files)), dtype=int)):
        with Image.open(files[index]) as image:
            array = np.asarray(image, dtype=np.float64)
        if array.ndim != 2 or (shape is not None and shape != array.shape):
            raise ValueError("识别需要尺寸一致的二维灰度 TIFF 图像")
        shape = array.shape
        # Remove each row's offset and trim isolated hot pixels before projection.
        positive = np.maximum(array - np.median(array, axis=1)[:, None], 0)
        cap = np.percentile(positive, 99.5, axis=1)
        profiles.append(np.minimum(positive, cap[:, None]).mean(axis=1))
    return detect_profile_groups(np.median(profiles, axis=0), prominence_percent, minimum_distance)
