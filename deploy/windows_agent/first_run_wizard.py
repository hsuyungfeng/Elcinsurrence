"""B6: 首次啟動三步精靈 (Plan 32-17, D-32-14, D-31-03).

正常路徑三次點擊完成（是 → 下一步 → 完成），醫師不需打字或輸入位址與金鑰。
純邏輯控制器（FirstRunFlow）與視窗畫面（run_first_run_wizard）分離。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("windows_agent.first_run_wizard")

TEXTS: Dict[str, str] = {
    "title": "智慧病歷助理 - 首次設定",
    "step_progress": "步驟 {current}／{total}",
    "searching": "正在尋找診所伺服器…",
    "searching_hint": "請稍候，系統正透過區域網路搜尋…",
    "confirm_title": "確認診所",
    "confirm_prompt": "找到：{facility_name}。\n這是您的診所嗎？",
    "btn_yes": "是",
    "btn_no": "不是",
    "choose_room_title": "選擇診間",
    "choose_room_prompt": "請選擇本台電腦所在的診間：",
    "no_rooms_warning": "伺服器尚未設定診間，請聯絡安裝人員",
    "btn_next": "下一步",
    "choose_vendor_title": "選擇門診系統",
    "choose_vendor_prompt": "請選擇您使用的門診醫療系統：",
    "btn_finish": "完成",
    "not_found_title": "找不到伺服器",
    "not_found_msg": "找不到診所伺服器。請確認這台電腦已接上診所網路。",
    "btn_retry": "再找一次",
    "btn_contact": "聯絡安裝人員",
    "contact_info": "請安裝人員確認：\n1. 診所主機已開機並啟動服務\n2. 本電腦與主機接在同一診所網路\n3. 防火牆未阻擋連線",
    "manual_link": "手動輸入位址",
    "manual_prompt": "請輸入診所主機區域網路位址（例如 192.168.1.50:5000）：",
    "btn_confirm_manual": "確定",
    "btn_cancel_manual": "取消",
    "manual_invalid": "位址不正確或無法連線，請檢查後重試",
}

DEFAULT_VENDORS: Dict[str, str] = {
    "vision": "展望醫療資訊系統 (Vision HIS)",
    "yaosheng": "耀聖醫療資訊系統 (Yaosheng HIS)",
    "minger": "佲格門診系統 (Minger HIS)",
    "chihshi": "志氏醫療系統 (Chihshi HIS)",
}


@dataclass
class FirstRunResult:
    """首次啟動精靈完成產出之設定參數。"""
    server_url: str
    facility_code: str
    facility_name: str
    room_id: str
    vendor_key: str


class FirstRunFlow:
    """純邏輯狀態機：引導首次啟動三步流程。

    狀態序列：searching → confirm_server → choose_room → choose_vendor → done
    例外狀態：not_found（可 retry 或 manual 進入 confirm_server）
    """

    def __init__(
        self,
        discover_fn: Optional[Callable[[], Any]] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
        vendors: Optional[Dict[str, str]] = None,
    ):
        self.discover_fn = discover_fn
        self.client_factory = client_factory or self._default_client_factory
        self.vendors = dict(vendors) if vendors is not None else dict(DEFAULT_VENDORS)

        self.state: str = "searching"
        self.candidates: List[str] = []
        self._candidate_idx: int = 0
        self.server_url: str = ""
        self.facility_code: str = ""
        self.facility_name: str = ""
        self.rooms: List[Dict[str, Any]] = []
        self.selected_room_id: str = ""
        self.selected_vendor_key: str = ""
        self.error_message: str = ""

    @staticmethod
    def _default_client_factory(url: str) -> Any:
        from deploy.windows_agent.traffic_bar.server_client import CycleServerClient
        return CycleServerClient(base_url=url)

    def start(self) -> bool:
        """啟動搜尋流程。"""
        return self.search()

    def search(self) -> bool:
        """執行探索並嘗試健康檢查候選位址。"""
        self.state = "searching"
        self.error_message = ""
        candidates: List[str] = []

        if callable(self.discover_fn):
            try:
                res = self.discover_fn()
                if hasattr(res, "candidates"):
                    candidates = list(res.candidates)
                elif isinstance(res, (list, tuple)):
                    candidates = list(res)
                elif isinstance(res, str) and res:
                    candidates = [res]
            except Exception as exc:
                logger.warning(f"discover_fn 執行失敗: {exc}")
                candidates = []

        self.candidates = candidates
        self._candidate_idx = 0
        return self._try_next_candidate()

    def _try_next_candidate(self) -> bool:
        while self._candidate_idx < len(self.candidates):
            cand_url = self.candidates[self._candidate_idx]
            self._candidate_idx += 1
            try:
                client = self.client_factory(cand_url)
                health = client.get_health()
                fname = health.get("facility_name") if isinstance(health, dict) else ""
                fcode = health.get("facility_code") if isinstance(health, dict) else ""
                if fname:
                    self.server_url = cand_url
                    self.facility_name = str(fname)
                    self.facility_code = str(fcode or "")
                    self.state = "confirm_server"
                    return True
            except Exception as exc:
                logger.debug(f"候選伺服器 {cand_url} 探測失敗: {exc}")
                continue

        self.state = "not_found"
        return False

    def retry(self) -> bool:
        """未找到時重試探索。"""
        return self.search()

    def manual(self, raw_url: str) -> bool:
        """手動輸入伺服器位址驗證與採納。"""
        from deploy.windows_agent.discovery import validate_manual_server_url

        url_to_test = (raw_url or "").strip()
        if url_to_test and "://" not in url_to_test:
            url_to_test = f"http://{url_to_test}"

        try:
            valid_url = validate_manual_server_url(url_to_test)
        except Exception as exc:
            self.error_message = str(exc)
            return False

        try:
            client = self.client_factory(valid_url)
            health = client.get_health()
            fname = health.get("facility_name") if isinstance(health, dict) else ""
            fcode = health.get("facility_code") if isinstance(health, dict) else ""
            if not fname:
                self.error_message = TEXTS["manual_invalid"]
                return False

            self.server_url = valid_url
            self.facility_name = str(fname)
            self.facility_code = str(fcode or "")
            self.state = "confirm_server"
            self.error_message = ""
            return True
        except Exception as exc:
            logger.warning(f"手動輸入位址 {valid_url} 連線失敗: {exc}")
            self.error_message = TEXTS["manual_invalid"]
            return False

    def confirm(self, yes: bool) -> None:
        """確認是否為此診所伺服器。"""
        if yes:
            try:
                client = self.client_factory(self.server_url)
                self.rooms = client.get_rooms() or []
            except Exception as exc:
                logger.warning(f"取得診間清單失敗: {exc}")
                self.rooms = []

            if len(self.rooms) == 1:
                self.selected_room_id = str(self.rooms[0].get("id") or "")
            else:
                self.selected_room_id = ""

            self.state = "choose_room"
        else:
            # 排除目前候選，嘗試下一個候選或進入 not_found
            self.server_url = ""
            self.facility_name = ""
            self.facility_code = ""
            self._try_next_candidate()

    def choose_room(self, room_id: str) -> None:
        """選擇診間。伺服器尚未設定診間時允許傳入空字串。"""
        self.selected_room_id = room_id.strip()

        if len(self.vendors) == 1:
            self.selected_vendor_key = list(self.vendors.keys())[0]
        else:
            self.selected_vendor_key = ""

        self.state = "choose_vendor"

    def choose_vendor(self, vendor_key: str) -> None:
        """選擇門診系統 HIS 廠牌。"""
        if vendor_key not in self.vendors and vendor_key:
            raise ValueError(f"未知的 HIS 廠牌鍵值: {vendor_key}")
        self.selected_vendor_key = vendor_key
        self.state = "done"

    def finish(self) -> FirstRunResult:
        """產生首次啟動精靈結果。"""
        if self.state != "done":
            raise ValueError(f"精靈尚未完成（目前狀態：{self.state}）")
        return FirstRunResult(
            server_url=self.server_url,
            facility_code=self.facility_code,
            facility_name=self.facility_name,
            room_id=self.selected_room_id,
            vendor_key=self.selected_vendor_key,
        )


def run_first_run_wizard(flow: Optional[FirstRunFlow] = None) -> Optional[FirstRunResult]:
    """執行首次啟動精靈 GUI 介面（Tkinter）。

    在 Linux/非 GUI 環境或使用者關閉視窗時回傳 None。
    """
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        logger.warning("未安裝 tkinter，無法顯示 GUI 精靈")
        return None

    if flow is None:
        flow = FirstRunFlow()

    try:
        root = tk.Tk()
    except Exception as exc:
        logger.warning(f"無法初始化 Tkinter 視窗: {exc}")
        return None

    from deploy.windows_agent.window_utils import keep_on_top

    root.title(TEXTS["title"])
    root.geometry("520x380")
    root.resizable(False, False)
    keep_on_top(root)

    # 樣式設定
    font_main = ("Microsoft JhengHei UI", 13)
    font_large = ("Microsoft JhengHei UI", 15, "bold")
    font_progress = ("Microsoft JhengHei UI", 11)

    result_container: List[Optional[FirstRunResult]] = [None]

    container = tk.Frame(root, padx=24, pady=20)
    container.pack(fill=tk.BOTH, expand=True)

    def clear_container() -> None:
        for w in container.winfo_children():
            w.destroy()

    def show_searching() -> None:
        clear_container()
        lbl_p = tk.Label(container, text=TEXTS["step_progress"].format(current=1, total=3), font=font_progress, fg="#64748b")
        lbl_p.pack(anchor="w")

        lbl_title = tk.Label(container, text=TEXTS["searching"], font=font_large, pady=30)
        lbl_title.pack()

        lbl_hint = tk.Label(container, text=TEXTS["searching_hint"], font=font_main, fg="#475569")
        lbl_hint.pack()

        def do_search() -> None:
            ok = flow.start()
            if ok:
                show_confirm_server()
            else:
                show_not_found()

        root.after(100, do_search)

    def show_confirm_server() -> None:
        clear_container()
        lbl_p = tk.Label(container, text=TEXTS["step_progress"].format(current=1, total=3), font=font_progress, fg="#64748b")
        lbl_p.pack(anchor="w")

        lbl_title = tk.Label(container, text=TEXTS["confirm_title"], font=font_large, pady=10)
        lbl_title.pack()

        prompt_text = TEXTS["confirm_prompt"].format(facility_name=flow.facility_name or "未命名診所")
        lbl_msg = tk.Label(container, text=prompt_text, font=font_main, justify="center", pady=15)
        lbl_msg.pack()

        btn_box = tk.Frame(container, pady=20)
        btn_box.pack(fill=tk.X)

        btn_yes = tk.Button(
            btn_box,
            text=TEXTS["btn_yes"],
            font=font_large,
            bg="#0284c7",
            fg="white",
            height=2,
            width=10,
            command=on_confirm_yes,
        )
        btn_yes.pack(side=tk.LEFT, expand=True, padx=10)

        btn_no = tk.Button(
            btn_box,
            text=TEXTS["btn_no"],
            font=font_large,
            height=2,
            width=10,
            command=on_confirm_no,
        )
        btn_no.pack(side=tk.RIGHT, expand=True, padx=10)

    def on_confirm_yes() -> None:
        flow.confirm(True)
        show_choose_room()

    def on_confirm_no() -> None:
        flow.confirm(False)
        if flow.state == "confirm_server":
            show_confirm_server()
        else:
            show_not_found()

    def show_choose_room() -> None:
        clear_container()
        lbl_p = tk.Label(container, text=TEXTS["step_progress"].format(current=2, total=3), font=font_progress, fg="#64748b")
        lbl_p.pack(anchor="w")

        lbl_title = tk.Label(container, text=TEXTS["choose_room_title"], font=font_large, pady=10)
        lbl_title.pack()

        lbl_msg = tk.Label(container, text=TEXTS["choose_room_prompt"], font=font_main, pady=10)
        lbl_msg.pack()

        rooms = flow.rooms
        room_var = tk.StringVar()

        if not rooms:
            lbl_warn = tk.Label(container, text=TEXTS["no_rooms_warning"], font=font_main, fg="#dc2626")
            lbl_warn.pack(pady=10)
        else:
            room_names = [f"{r.get('name') or r.get('id')} ({r.get('id')})" for r in rooms]
            combo = ttk.Combobox(container, textvariable=room_var, values=room_names, state="readonly", font=font_main)
            combo.pack(fill=tk.X, padx=40, pady=10)
            combo.current(0)

        def on_next_room() -> None:
            sel_id = ""
            if rooms:
                idx = combo.current()
                if idx >= 0 and idx < len(rooms):
                    sel_id = str(rooms[idx].get("id") or "")
            flow.choose_room(sel_id)
            show_choose_vendor()

        btn_next = tk.Button(
            container,
            text=TEXTS["btn_next"],
            font=font_large,
            bg="#0284c7",
            fg="white",
            height=2,
            command=on_next_room,
        )
        btn_next.pack(fill=tk.X, padx=40, pady=25)

    def show_choose_vendor() -> None:
        clear_container()
        lbl_p = tk.Label(container, text=TEXTS["step_progress"].format(current=3, total=3), font=font_progress, fg="#64748b")
        lbl_p.pack(anchor="w")

        lbl_title = tk.Label(container, text=TEXTS["choose_vendor_title"], font=font_large, pady=10)
        lbl_title.pack()

        lbl_msg = tk.Label(container, text=TEXTS["choose_vendor_prompt"], font=font_main, pady=10)
        lbl_msg.pack()

        vendor_keys = list(flow.vendors.keys())
        vendor_labels = [flow.vendors[k] for k in vendor_keys]
        vendor_var = tk.StringVar()

        combo = ttk.Combobox(container, textvariable=vendor_var, values=vendor_labels, state="readonly", font=font_main)
        combo.pack(fill=tk.X, padx=40, pady=10)
        combo.current(0)

        def on_finish() -> None:
            idx = combo.current()
            sel_key = vendor_keys[idx] if 0 <= idx < len(vendor_keys) else ""
            flow.choose_vendor(sel_key)
            result_container[0] = flow.finish()
            root.destroy()

        btn_fin = tk.Button(
            container,
            text=TEXTS["btn_finish"],
            font=font_large,
            bg="#16a34a",
            fg="white",
            height=2,
            command=on_finish,
        )
        btn_fin.pack(fill=tk.X, padx=40, pady=25)

    def show_not_found() -> None:
        clear_container()
        lbl_title = tk.Label(container, text=TEXTS["not_found_title"], font=font_large, fg="#dc2626", pady=10)
        lbl_title.pack()

        lbl_msg = tk.Label(container, text=TEXTS["not_found_msg"], font=font_main, justify="center", pady=10)
        lbl_msg.pack()

        btn_box = tk.Frame(container, pady=10)
        btn_box.pack(fill=tk.X)

        def on_retry() -> None:
            show_searching()

        def on_contact() -> None:
            messagebox.showinfo(TEXTS["btn_contact"], TEXTS["contact_info"], parent=root)

        btn_retry = tk.Button(btn_box, text=TEXTS["btn_retry"], font=font_main, height=2, width=12, command=on_retry)
        btn_retry.pack(side=tk.LEFT, expand=True, padx=5)

        btn_contact = tk.Button(btn_box, text=TEXTS["btn_contact"], font=font_main, height=2, width=12, command=on_contact)
        btn_contact.pack(side=tk.RIGHT, expand=True, padx=5)

        # 手動輸入連結
        def show_manual_input() -> None:
            clear_container()
            lbl_m_title = tk.Label(container, text=TEXTS["manual_link"], font=font_large, pady=10)
            lbl_m_title.pack()

            lbl_m_prompt = tk.Label(container, text=TEXTS["manual_prompt"], font=font_main, pady=5)
            lbl_m_prompt.pack()

            entry_var = tk.StringVar(value="192.168.1.")
            entry = tk.Entry(container, textvariable=entry_var, font=font_main)
            entry.pack(fill=tk.X, padx=40, pady=10)
            entry.focus_set()

            lbl_err = tk.Label(container, text="", font=font_progress, fg="#dc2626")
            lbl_err.pack()

            def on_submit_manual() -> None:
                ok = flow.manual(entry_var.get().strip())
                if ok:
                    show_confirm_server()
                else:
                    lbl_err.config(text=flow.error_message or TEXTS["manual_invalid"])

            btn_box_m = tk.Frame(container, pady=10)
            btn_box_m.pack(fill=tk.X)

            btn_ok = tk.Button(btn_box_m, text=TEXTS["btn_confirm_manual"], font=font_main, bg="#0284c7", fg="white", height=2, width=10, command=on_submit_manual)
            btn_ok.pack(side=tk.LEFT, expand=True, padx=5)

            btn_cancel = tk.Button(btn_box_m, text=TEXTS["btn_cancel_manual"], font=font_main, height=2, width=10, command=show_not_found)
            btn_cancel.pack(side=tk.RIGHT, expand=True, padx=5)

        lbl_manual = tk.Label(container, text=TEXTS["manual_link"], font=font_progress, fg="#0284c7", cursor="hand2")
        lbl_manual.pack(pady=15)
        lbl_manual.bind("<Button-1>", lambda e: show_manual_input())

    show_searching()
    root.mainloop()
    return result_container[0]
