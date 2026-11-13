"""Phase 31: 快捷列 Tkinter 浮動視窗 (D-31-09, D-31-10, D-31-11).

職責：
1. 置頂 (-topmost)、無工作列按鈕 (-toolwindow / overrideredirect)、可拖曳且記憶座標至本機設定 (D-31-09)。
2. 收合為紅綠黃三鈕；展開顯示目前狀態文字與伺服器連線狀態 (D-31-10)。
3. 按鈕嚴格限制點擊規則，只呼叫 controller，不包含任何錄音邏輯 (D-31-11)。
4. 嚴格不搶奪焦點，不干擾 HIS 視窗作業。
5. 包含純邏輯 BarViewModel，可在無 GUI / Linux 環境下進行單元測試。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from deploy.windows_agent.config import AgentSettings, save_settings
from deploy.windows_agent.traffic_bar.bar_position import clamp_position
from deploy.windows_agent.traffic_bar.bar_state import (
    ENABLED,
    on_press,
)
from deploy.windows_agent.traffic_bar.controller import BarController

logger = logging.getLogger("traffic_bar.window")

# 顏色定義
COLOR_RED_ACTIVE = "#E53935"
COLOR_RED_DIM = "#EF9A9A"
COLOR_GREEN_ACTIVE = "#43A047"
COLOR_GREEN_DIM = "#A5D6A7"
COLOR_YELLOW_ACTIVE = "#FB8C00"
COLOR_YELLOW_DIM = "#FFE082"
COLOR_BG = "#212121"
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_MUTED = "#B0BEC5"
COLOR_BORDER = "#424242"

COLLAPSED_WIDTH = 160
COLLAPSED_HEIGHT = 44
EXPANDED_WIDTH = 250
EXPANDED_HEIGHT = 100


class BarViewModel:
    """快捷列純邏輯檢視模型，供測試與 UI 繪製使用（不依賴 Tkinter）。"""

    def __init__(
        self,
        bar_state: str,
        display_status: str,
        server_online: bool,
        sv_online: bool,
        connection_text: str,
        red_enabled: bool,
        green_enabled: bool,
        yellow_enabled: bool,
        red_bg: str,
        green_bg: str,
        yellow_bg: str,
        is_expanded: bool,
        width: int,
        height: int,
        toast: Optional[str] = None,
    ):
        self.bar_state = bar_state
        self.status_text = display_status
        self.server_online = server_online
        self.sv_online = sv_online
        self.connection_text = connection_text
        self.red_enabled = red_enabled
        self.green_enabled = green_enabled
        self.yellow_enabled = yellow_enabled
        self.red_bg = red_bg
        self.green_bg = green_bg
        self.yellow_bg = yellow_bg
        self.is_expanded = is_expanded
        self.width = width
        self.height = height
        self.toast = toast


def build_view_model(
    controller: BarController,
    *,
    is_expanded: bool = False,
    toast_override: Optional[str] = None,
) -> BarViewModel:
    """由 BarController 當前狀態建構檢視模型純資料結構。"""
    st = controller.bar_state()
    txt = toast_override if toast_override else controller.status()

    red_en = "red" in ENABLED.get(st, frozenset()) and controller.pending_action is None
    green_en = "green" in ENABLED.get(st, frozenset()) and controller.pending_action is None
    yellow_en = "yellow" in ENABLED.get(st, frozenset()) and controller.pending_action is None

    red_bg = COLOR_RED_ACTIVE if red_en else COLOR_RED_DIM
    green_bg = COLOR_GREEN_ACTIVE if green_en else COLOR_GREEN_DIM
    yellow_bg = COLOR_YELLOW_ACTIVE if yellow_en else COLOR_YELLOW_DIM

    # 連線狀態文字
    conn_parts: List[str] = []
    if controller.server_online:
        conn_parts.append("Server 連線正常")
    else:
        conn_parts.append("Server 斷線")

    if controller.sv_online:
        conn_parts.append("SoapVoice 正常")
    else:
        conn_parts.append("SoapVoice 斷線")

    conn_text = " | ".join(conn_parts)

    w = EXPANDED_WIDTH if is_expanded else COLLAPSED_WIDTH
    h = EXPANDED_HEIGHT if is_expanded else COLLAPSED_HEIGHT

    return BarViewModel(
        bar_state=st,
        display_status=txt,
        server_online=controller.server_online,
        sv_online=controller.sv_online,
        connection_text=conn_text,
        red_enabled=red_en,
        green_enabled=green_en,
        yellow_enabled=yellow_en,
        red_bg=red_bg,
        green_bg=green_bg,
        yellow_bg=yellow_bg,
        is_expanded=is_expanded,
        width=w,
        height=h,
        toast=toast_override,
    )


class TrafficBarWindow:
    """Tkinter 浮動快捷列實作。"""

    def __init__(
        self,
        controller: BarController,
        settings: AgentSettings,
        settings_path: Optional[Path] = None,
        *,
        tk_root: Any = None,
        poll_interval_ms: int = 500,
    ):
        self.controller = controller
        self.settings = settings
        self.settings_path = settings_path
        self.poll_interval_ms = poll_interval_ms
        self.is_expanded: bool = False
        self._toast_message: Optional[str] = None
        self._toast_clear_time: float = 0.0

        # 拖曳記錄變數
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0
        self._current_x: int = 0
        self._current_y: int = 0

        self._server_tick_counter: int = 0

        self.root = tk_root
        if self.root is None:
            self._init_tk()

    def _init_tk(self) -> None:
        """延遲載入 Tkinter 並建立置頂無框浮動視窗。"""
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("ElcTrafficBar")

        # 1. 置頂屬性 (D-31-09)
        try:
            self.root.attributes("-topmost", True)
        except Exception as exc:
            logger.warning("無法設定視窗置頂: %s", exc)

        # 2. 無工作列圖示與工具視窗屬性 (D-31-09)
        # Windows 上使用 -toolwindow 配合 overrideredirect
        try:
            self.root.attributes("-toolwindow", True)
        except Exception:
            pass

        # 移除標題列以達成精巧浮動快捷列外觀
        self.root.overrideredirect(True)

        self.root.configure(bg=COLOR_BG)

        # 3. 計算並夾取初始位置 (D-31-09, bar_position)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        monitors = [(0, 0, screen_w, screen_h)]

        saved_pos = (
            self.settings.bar_x if self.settings.bar_x is not None else screen_w - COLLAPSED_WIDTH - 20,
            self.settings.bar_y if self.settings.bar_y is not None else screen_h - COLLAPSED_HEIGHT - 60,
        )
        clamped_x, clamped_y = clamp_position(
            saved_pos,
            monitors,
            bar_w=COLLAPSED_WIDTH,
            bar_h=COLLAPSED_HEIGHT,
        )
        self._current_x = clamped_x
        self._current_y = clamped_y
        self.root.geometry(f"{COLLAPSED_WIDTH}x{COLLAPSED_HEIGHT}+{clamped_x}+{clamped_y}")

        # 4. 建立 UI 元件
        self._build_ui()

        # 5. 綁定拖曳滑鼠事件 (D-31-09)
        self._bind_drag_events()

        # 6. 啟動定期輪詢控制器
        self.root.after(self.poll_interval_ms, self._on_tick)

    def _build_ui(self) -> None:
        import tkinter as tk

        self.main_frame = tk.Frame(self.root, bg=COLOR_BG, bd=1, relief="ridge")
        self.main_frame.pack(fill="both", expand=True)

        # 按鈕列 (紅綠黃三鈕 + 展開/收合按鈕)
        self.btn_frame = tk.Frame(self.main_frame, bg=COLOR_BG)
        self.btn_frame.pack(side="top", fill="x", padx=6, pady=4)

        # 拖曳手柄圖示
        self.drag_handle = tk.Label(
            self.btn_frame,
            text="⠿",
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG,
            font=("Arial", 11),
            cursor="fleur",
        )
        self.drag_handle.pack(side="left", padx=(0, 4))

        # 紅燈按鈕
        self.btn_red = tk.Button(
            self.btn_frame,
            text="●",
            font=("Arial", 14, "bold"),
            bg=COLOR_RED_DIM,
            fg="#FFFFFF",
            activebackground=COLOR_RED_ACTIVE,
            bd=0,
            width=2,
            relief="flat",
            command=self._on_red_click,
            cursor="hand2",
        )
        self.btn_red.pack(side="left", padx=2)

        # 綠燈按鈕
        self.btn_green = tk.Button(
            self.btn_frame,
            text="●",
            font=("Arial", 14, "bold"),
            bg=COLOR_GREEN_DIM,
            fg="#FFFFFF",
            activebackground=COLOR_GREEN_ACTIVE,
            bd=0,
            width=2,
            relief="flat",
            command=self._on_green_click,
            cursor="hand2",
        )
        self.btn_green.pack(side="left", padx=2)

        # 黃燈按鈕
        self.btn_yellow = tk.Button(
            self.btn_frame,
            text="●",
            font=("Arial", 14, "bold"),
            bg=COLOR_YELLOW_DIM,
            fg="#FFFFFF",
            activebackground=COLOR_YELLOW_ACTIVE,
            bd=0,
            width=2,
            relief="flat",
            command=self._on_yellow_click,
            cursor="hand2",
        )
        self.btn_yellow.pack(side="left", padx=2)

        # 展開/收合切換鈕
        self.btn_toggle = tk.Button(
            self.btn_frame,
            text="▼",
            font=("Arial", 8),
            bg=COLOR_BG,
            fg=COLOR_TEXT_MUTED,
            bd=0,
            relief="flat",
            command=self._toggle_expand,
            cursor="hand2",
        )
        self.btn_toggle.pack(side="right", padx=(4, 0))

        # 展開資訊面板 (預設隱藏)
        self.info_frame = tk.Frame(self.main_frame, bg=COLOR_BG)

        self.lbl_status = tk.Label(
            self.info_frame,
            text="待命",
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BG,
            font=("Microsoft JhengHei", 9),
            anchor="w",
            justify="left",
        )
        self.lbl_status.pack(fill="x", padx=6, pady=(0, 2))

        self.lbl_conn = tk.Label(
            self.info_frame,
            text="Server 連線正常",
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG,
            font=("Microsoft JhengHei", 8),
            anchor="w",
            justify="left",
        )
        self.lbl_conn.pack(fill="x", padx=6, pady=(0, 4))

        self._refresh_view()

    def _bind_drag_events(self) -> None:
        """綁定視窗拖曳事件與釋放記憶。"""
        drag_targets = [self.main_frame, self.btn_frame, self.drag_handle]
        for w in drag_targets:
            w.bind("<Button-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_start(self, event: Any) -> None:
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag_motion(self, event: Any) -> None:
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        self._current_x += dx
        self._current_y += dy
        w = EXPANDED_WIDTH if self.is_expanded else COLLAPSED_WIDTH
        h = EXPANDED_HEIGHT if self.is_expanded else COLLAPSED_HEIGHT
        self.root.geometry(f"{w}x{h}+{self._current_x}+{self._current_y}")

    def _on_drag_release(self, event: Any) -> None:
        """拖曳釋放時將新座標寫入設定檔記憶 (D-31-09)。"""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        monitors = [(0, 0, screen_w, screen_h)]

        w = EXPANDED_WIDTH if self.is_expanded else COLLAPSED_WIDTH
        h = EXPANDED_HEIGHT if self.is_expanded else COLLAPSED_HEIGHT

        clamped_x, clamped_y = clamp_position(
            (self._current_x, self._current_y),
            monitors,
            bar_w=w,
            bar_h=h,
        )
        self._current_x = clamped_x
        self._current_y = clamped_y
        self.root.geometry(f"{w}x{h}+{clamped_x}+{clamped_y}")

        self.settings.bar_x = clamped_x
        self.settings.bar_y = clamped_y
        try:
            save_settings(self.settings_path, self.settings)
            logger.info("Saved traffic bar position: (%d, %d)", clamped_x, clamped_y)
        except Exception as exc:
            logger.warning("Failed to save bar position: %s", exc)

    def _toggle_expand(self) -> None:
        """切換收合與展開狀態 (D-31-10)。"""
        self.is_expanded = not self.is_expanded
        w = EXPANDED_WIDTH if self.is_expanded else COLLAPSED_WIDTH
        h = EXPANDED_HEIGHT if self.is_expanded else COLLAPSED_HEIGHT
        self.root.geometry(f"{w}x{h}+{self._current_x}+{self._current_y}")

        if self.is_expanded:
            self.btn_toggle.configure(text="▲")
            self.info_frame.pack(side="top", fill="both", expand=True)
        else:
            self.btn_toggle.configure(text="▼")
            self.info_frame.pack_forget()

        self._refresh_view()

    def _show_toast(self, message: str, duration_sec: float = 3.0) -> None:
        """顯示暫時性操作提示。"""
        import time

        self._toast_message = message
        self._toast_clear_time = time.time() + duration_sec
        self._refresh_view()

    def _on_red_click(self) -> None:
        """按鈕點擊嚴格呼叫 controller，無任何錄音邏輯 (D-31-11)。"""
        allowed, toast_msg = on_press(
            "red",
            self.controller.bar_state(),
            pending_action=self.controller.pending_action,
        )
        if not allowed:
            self._show_toast(toast_msg or "目前無法開始錄音")
            return
        self.controller.on_red()
        self._refresh_view()

    def _on_green_click(self) -> None:
        allowed, toast_msg = on_press(
            "green",
            self.controller.bar_state(),
            pending_action=self.controller.pending_action,
        )
        if not allowed:
            self._show_toast(toast_msg or "目前無法結束錄音")
            return
        self.controller.on_green()
        self._refresh_view()

    def _on_yellow_click(self) -> None:
        allowed, toast_msg = on_press(
            "yellow",
            self.controller.bar_state(),
            pending_action=self.controller.pending_action,
        )
        if not allowed:
            self._show_toast(toast_msg or "目前無法封存")
            return
        self.controller.on_yellow()
        self._refresh_view()

    def _on_tick(self) -> None:
        """定時驅動 controller 通訊輪詢與介面更新。"""
        import time

        # 清除過期 Toast
        if self._toast_message and time.time() > self._toast_clear_time:
            self._toast_message = None

        # 輪詢 SoapVoice (約每 500ms 一次)
        try:
            self.controller.tick_soapvoice()
        except Exception as exc:
            logger.debug("tick_soapvoice error: %s", exc)

        # 輪詢 Server 心跳 (約每 3000ms 一次，即計數器達 6)
        self._server_tick_counter += 1
        if self._server_tick_counter >= 6:
            self._server_tick_counter = 0
            try:
                self.controller.tick_server()
            except Exception as exc:
                logger.debug("tick_server error: %s", exc)

        self._refresh_view()
        self.root.after(self.poll_interval_ms, self._on_tick)

    def _refresh_view(self) -> None:
        """根據 ViewModel 刷新 UI 視覺呈現。"""
        vm = build_view_model(
            self.controller,
            is_expanded=self.is_expanded,
            toast_override=self._toast_message,
        )

        self.btn_red.configure(bg=vm.red_bg)
        self.btn_green.configure(bg=vm.green_bg)
        self.btn_yellow.configure(bg=vm.yellow_bg)

        if hasattr(self, "lbl_status"):
            self.lbl_status.configure(text=vm.status_text)
        if hasattr(self, "lbl_conn"):
            self.lbl_conn.configure(text=vm.connection_text)


def run_traffic_bar(
    controller: BarController,
    settings: AgentSettings,
    settings_path: Optional[Path] = None,
) -> None:
    """啟動快捷列浮動視窗並進入 Tkinter 主事件迴圈。"""
    tb = TrafficBarWindow(controller, settings, settings_path)
    tb.root.mainloop()
