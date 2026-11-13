"""Tests for deploy.windows_agent.traffic_bar.bar_position (Phase 31 Task 2)."""

from deploy.windows_agent.traffic_bar.bar_position import clamp_position, default_position


def test_default_position():
    """Test 1: default_position 回傳右下角工作列上方座標 (1732, 964)。"""
    pos = default_position(
        screen_w=1920,
        screen_h=1080,
        bar_w=180,
        bar_h=60,
        taskbar_h=48,
        margin=8,
    )
    assert pos == (1732, 964)


def test_clamp_position_single_monitor():
    """Test 2: 對螢幕內座標原樣回傳；對完全落在螢幕外回傳 default_position。"""
    monitors = [(0, 0, 1920, 1080)]
    # 螢幕內
    inside = clamp_position((500, 400), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert inside == (500, 400)

    # 完全落在螢幕外 (x=3000, y=200)
    outside = clamp_position((3000, 200), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert outside == (1732, 964)

    # 完全落在螢幕負向外 (x=-500, y=-200)
    outside_neg = clamp_position((-500, -200), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert outside_neg == (1732, 964)


def test_clamp_position_multi_monitor():
    """Test 3: 多螢幕時，落在第二螢幕內的座標保留。"""
    monitors = [(0, 0, 1920, 1080), (1920, 0, 1280, 1024)]
    # 第二螢幕內
    sec_inside = clamp_position((2000, 200), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert sec_inside == (2000, 200)

    # 落在所有螢幕外
    both_outside = clamp_position((5000, 500), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert both_outside == (1732, 964)


def test_clamp_position_partial_overflow():
    """Test 4: 部分超出邊界（視窗右緣超出）時夾回可視範圍內。"""
    monitors = [(0, 0, 1920, 1080)]
    # 右緣超出: x=1800, bar_w=180 -> 右緣 1980 > 1920. 應夾回 1920 - 180 = 1740
    clamped_right = clamp_position((1800, 300), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert clamped_right == (1740, 300)

    # 下緣超出: y=1050, bar_h=60 -> 下緣 1110 > 1080. 應夾回 1080 - 60 = 1020
    clamped_bottom = clamp_position((500, 1050), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert clamped_bottom == (500, 1020)

    # 左緣負向部分超出: x=-50 (部分在螢幕內) -> 應夾回 0
    clamped_left = clamp_position((-50, 300), monitors, bar_w=180, bar_h=60, taskbar_h=48, margin=8)
    assert clamped_left == (0, 300)
