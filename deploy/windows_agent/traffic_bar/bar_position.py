"""Phase 31: 快捷列視窗位置計算與多螢幕防脫逸邊界夾取 (D-31-09, 研究 Pitfall 11).

純邏輯函式，不呼叫 Windows API 或 Tkinter。
"""

from __future__ import annotations

from typing import Sequence, Tuple


def default_position(
    screen_w: int,
    screen_h: int,
    bar_w: int,
    bar_h: int,
    taskbar_h: int = 48,
    margin: int = 8,
) -> Tuple[int, int]:
    """計算主螢幕右下角工作列上方的預設座標。"""
    x = screen_w - bar_w - margin
    y = screen_h - taskbar_h - bar_h - margin
    return x, y


def clamp_position(
    saved: Tuple[int, int],
    monitors: Sequence[Tuple[int, int, int, int]],
    bar_w: int = 180,
    bar_h: int = 60,
    taskbar_h: int = 48,
    margin: int = 8,
) -> Tuple[int, int]:
    """將記憶之座標夾取回任一可視螢幕內；若完全脫逸則回傳主螢幕預設位置。

    monitors: [(x, y, w, h), ...] 各螢幕幾何矩形。第一項視為主螢幕。
    saved: (x, y) 欲還原之視窗左上角座標。
    """
    if not monitors:
        return default_position(1920, 1080, bar_w, bar_h, taskbar_h, margin)

    primary = monitors[0]
    p_x, p_y, p_w, p_h = primary
    def_x, def_y = default_position(p_w, p_h, bar_w, bar_h, taskbar_h, margin)
    primary_default = (p_x + def_x, p_y + def_y)

    x, y = saved
    best_monitor: Tuple[int, int, int, int] | None = None
    max_overlap = 0

    for m in monitors:
        mx, my, mw, mh = m
        overlap_w = max(0, min(x + bar_w, mx + mw) - max(x, mx))
        overlap_h = max(0, min(y + bar_h, my + mh) - max(y, my))
        area = overlap_w * overlap_h
        if area > max_overlap:
            max_overlap = area
            best_monitor = m

    # 若與所有螢幕均無重疊（完全落在可視範圍外），回到預設位置
    if best_monitor is None or max_overlap <= 0:
        return primary_default

    mx, my, mw, mh = best_monitor
    max_x = mx + mw - bar_w
    max_y = my + mh - bar_h

    clamped_x = max(mx, min(x, max_x)) if max_x >= mx else mx
    clamped_y = max(my, min(y, max_y)) if max_y >= my else my

    return clamped_x, clamped_y
