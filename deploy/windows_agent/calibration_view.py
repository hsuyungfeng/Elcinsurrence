"""HIS UI Automation First-Use Calibration Wizard View (Phase 30 & Phase 32 Plan 32-04, B7).

Tkinter desktop window presenting step-by-step UI calibration:
- One item at a time presentation
- Doctor clicks on HIS field instead of writing JSON selectors
- Advisory-only items (ICD10, ORDER, MED) are read-only without a confirm button
- Readback test verification with fixed probe string before enabling finalize
- Tkinter is imported lazily inside run_calibration_wizard so this module is safe to import on headless Linux.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Ensure project root and src are on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
_src_dir = str(_project_root / "src")
_root_dir = str(_project_root)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

try:
    from deploy.windows_agent.calibration_wizard import (
        CalibrationWizard,
        NotReadyError,
        PROBE_TEXT,
    )
except ImportError:
    from calibration_wizard import (  # type: ignore[no-redef]
        CalibrationWizard,
        NotReadyError,
        PROBE_TEXT,
    )

logger = logging.getLogger("windows_agent.calibration_view")

SECTION_TITLES = {
    "S": "S (主訴欄位)",
    "O": "O (客觀檢查欄位)",
    "A": "A (臨床評估欄位)",
    "P": "P (治療計畫欄位)",
    "PATIENT_ID": "PATIENT_ID (病歷號比對欄位)",
    "SAVE_BUTTON": "SAVE_BUTTON (病歷儲存按鈕)",
    "ICD10": "ICD10 (主診斷碼建議)",
    "ORDER": "ORDER (醫令處置建議)",
    "MED": "MED (藥令處方建議)",
}

KIND_LABELS = {
    "writable": "可寫入欄位",
    "save_action": "動作按鈕",
    "identity_check": "病患身分核對",
    "advisory_only": "僅供參考（唯讀）",
}


def describe_item(item: Any) -> str:
    """Return a plain Chinese description of the detected/suggested element without formatting symbols."""
    if item is None:
        return "未指定項目"

    detected = getattr(item, "detected", None)
    suggested = getattr(item, "suggested", None)

    if detected or suggested:
        source = detected or suggested
        auto_id = source.get("automation_id") if isinstance(source, dict) else getattr(source, "automation_id", None)
        name = source.get("name") if isinstance(source, dict) else getattr(source, "name", None)
        ctype = source.get("control_type") if isinstance(source, dict) else getattr(source, "control_type", None)

        details = []
        if auto_id:
            details.append(f"識別碼: {auto_id}")
        if name:
            details.append(f"名稱: {name}")
        if ctype:
            details.append(f"控制項類型: {ctype}")

        detail_str = f" ({', '.join(details)})" if details else ""
        return f"已找到相符控制項{detail_str}"
    else:
        return "未偵測到相符欄位（找不到）"


def handle_pick_result(wizard: Any, selector: Optional[Dict[str, Any]]) -> str:
    """Pure logic handling for element pick result."""
    if selector and isinstance(selector, dict):
        wizard.correct(selector)
        return "corrected"
    else:
        wizard.skip()
        return "need_installer"


def run_calibration_wizard(
    wizard: CalibrationWizard,
    write_and_read_fn: Optional[Callable[[str], str]] = None,
) -> None:
    """Launch the Tkinter calibration wizard window.

    Tkinter is imported inside this function to allow Linux headless imports.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"Elcinsurrence - HIS 首次使用校正精靈 ({wizard.vendor_key})")
    root.geometry("740x560")
    root.minsize(640, 480)
    from deploy.windows_agent.window_utils import keep_on_top

    keep_on_top(root)

    # Ensure actor_id is present
    if not wizard.actor_id:
        wizard.actor_id = "installer"

    if wizard.profile is None:
        try:
            wizard.start()
        except Exception as exc:
            messagebox.showerror("快照取得失敗", f"無法自 HIS 取得視窗元素：\n{exc}")
            root.destroy()
            return

    # Header frame
    header_frame = ttk.Frame(root, padding=12)
    header_frame.pack(fill="x")

    title_var = tk.StringVar()
    title_lbl = ttk.Label(header_frame, textvariable=title_var, font=("Helvetica", 12, "bold"))
    title_lbl.pack(anchor="w")

    vendor_info_lbl = ttk.Label(
        header_frame,
        text=f"HIS 廠商: {wizard.vendor_key} | 工作站: {wizard.machine_id[:8]}... | 操作者: {wizard.actor_id}",
        foreground="#666666",
    )
    vendor_info_lbl.pack(anchor="w", pady=(2, 0))

    # Content container
    content_frame = ttk.LabelFrame(root, text="項目詳情", padding=12)
    content_frame.pack(fill="both", expand=True, padx=12, pady=6)

    desc_var = tk.StringVar()
    desc_lbl = ttk.Label(content_frame, textvariable=desc_var, wraplength=680)
    desc_lbl.pack(anchor="w", pady=(0, 8))

    detected_text = tk.Text(content_frame, height=6, wrap="word", font=("Consolas", 10), bg="#f8f9fa")
    detected_text.pack(fill="x", pady=(0, 8))

    suggested_var = tk.StringVar()
    suggested_lbl = ttk.Label(content_frame, textvariable=suggested_var, font=("Consolas", 10, "bold"))
    suggested_lbl.pack(anchor="w", pady=(0, 8))

    advisory_warning_var = tk.StringVar()
    advisory_warning_lbl = ttk.Label(
        content_frame,
        textvariable=advisory_warning_var,
        foreground="#c0392b",
        font=("Helvetica", 10, "bold"),
    )
    advisory_warning_lbl.pack(anchor="w", pady=(0, 4))

    # Bottom action frame
    action_frame = ttk.Frame(root, padding=12)
    action_frame.pack(fill="x", side="bottom")

    btn_confirm = ttk.Button(action_frame, text="✔ 確認此項控制項")
    btn_correct = ttk.Button(action_frame, text="👆 我來點選欄位")
    btn_skip = ttk.Button(action_frame, text="⏭ 略過")

    # Readback / Finalize section in final step
    readback_frame = ttk.Frame(content_frame, padding=8)
    readback_status_var = tk.StringVar(value="讀寫測試狀態：尚未執行")
    readback_status_lbl = ttk.Label(readback_frame, textvariable=readback_status_var, font=("Helvetica", 10))
    readback_status_lbl.pack(anchor="w", pady=(0, 6))

    btn_run_readback = ttk.Button(readback_frame, text="執行讀寫測試 (PROBE)")
    btn_finalize = ttk.Button(readback_frame, text="✔ 完成校正並存檔", state="disabled")

    def _render_current():
        detected_text.delete("1.0", tk.END)
        advisory_warning_var.set("")

        # Check if done with item list
        if wizard.is_done:
            title_var.set("步驟：執行讀寫測試與完成校正")
            desc_var.set("所有項目檢視已結束。請在測試病歷畫面上執行讀寫驗證，確認無誤後方可完成校正。")
            detected_text.pack_forget()
            suggested_lbl.pack_forget()
            advisory_warning_lbl.pack_forget()
            btn_confirm.pack_forget()
            btn_correct.pack_forget()
            btn_skip.pack_forget()

            readback_frame.pack(fill="both", expand=True)
            btn_run_readback.pack(side="left", padx=5)
            btn_finalize.pack(side="left", padx=5)
            return

        item = wizard.current()
        if not item:
            return

        total_count = len(wizard.items)
        idx = wizard.current_index + 1
        sec_name = SECTION_TITLES.get(item.section, item.section)
        kind_name = KIND_LABELS.get(item.kind, item.kind)

        title_var.set(f"項目 ({idx}/{total_count})：{sec_name} — {kind_name}")
        desc_var.set(f"項目識別碼: {item.item_key} | 類別: {kind_name}")

        item_desc = describe_item(item)
        detected_text.insert("1.0", f"欄位偵測狀態:\n{item_desc}")
        suggested_var.set(f"建議狀態: {item_desc}")

        # Reset action buttons
        btn_confirm.pack_forget()
        btn_correct.pack_forget()
        btn_skip.pack_forget()

        if item.kind == "advisory_only":
            advisory_warning_var.set("【僅供參考，不參與自動寫入】（D-30-12）\n此項目（如診斷碼/醫令）僅供審核介面參考顯示，HIS 代理人不會對其進行自動寫入。")
            btn_skip.config(text="下一步")
            btn_skip.pack(side="right", padx=5)
        else:
            btn_confirm.pack(side="left", padx=5)
            btn_correct.pack(side="left", padx=5)
            btn_skip.config(text="略過此項")
            btn_skip.pack(side="right", padx=5)

    def _on_confirm():
        try:
            wizard.confirm()
            _render_current()
        except Exception as exc:
            messagebox.showerror("確認失敗", str(exc))

    def _on_correct():
        item = wizard.current()
        if not item:
            return
        sec_name = SECTION_TITLES.get(item.section, item.section)
        messagebox.showinfo(
            "請點選欄位",
            f"請在 5 秒內用滑鼠點一下 HIS 上的「{sec_name}」欄位。\n點選後請將焦點停留在該欄位上。",
            parent=root,
        )

        def _do_pick():
            try:
                from deploy.windows_agent.pick_control import default_point_fn, pick_selector
            except ImportError:
                from pick_control import default_point_fn, pick_selector  # type: ignore[no-redef]

            sel = pick_selector(wizard.runner_snapshot_fn, wizard.app_name, default_point_fn)
            res = handle_pick_result(wizard, sel)
            if res == "need_installer":
                messagebox.showinfo(
                    "提示",
                    "找不到這個欄位，請聯絡安裝人員。其他欄位仍可繼續設定。",
                    parent=root,
                )
            _render_current()

        root.after(5000, _do_pick)

    def _on_skip():
        wizard.skip()
        _render_current()

    def _on_readback():
        if write_and_read_fn is None:
            # fail-closed：未提供真實讀寫函式時絕不自動通過（D-30-11）
            readback_status_var.set("讀寫測試尚未實作，無法通過；校正不得完成。")
            wizard.profile.readback_test_passed = False  # type: ignore[union-attr]
            btn_finalize.config(state="disabled")
            return

        passed = wizard.readback_test(write_and_read_fn)
        if passed:
            readback_status_var.set(f"讀寫測試通過！探針字串 '{PROBE_TEXT}' 成功寫入並讀回比對一致。")
            btn_finalize.config(state="normal")
        else:
            readback_status_var.set("讀寫測試失敗：寫入值與讀回值不一致，請檢查 HIS 焦點或欄位控制項。")
            btn_finalize.config(state="disabled")

    def _on_finalize():
        try:
            save_path = wizard.finalize()
            messagebox.showinfo("校正完成", f"校正檔已成功存檔至：\n{save_path}\n代理人現在已就緒允許正式寫入。")
            root.destroy()
        except NotReadyError as exc:
            messagebox.showerror("尚未就緒", f"無法完成校正：\n{exc}")
        except Exception as exc:
            messagebox.showerror("存檔失敗", f"寫入設定檔時發生錯誤：\n{exc}")

    btn_confirm.config(command=_on_confirm)
    btn_correct.config(command=_on_correct)
    btn_skip.config(command=_on_skip)
    btn_run_readback.config(command=_on_readback)
    btn_finalize.config(command=_on_finalize)

    _render_current()
    root.mainloop()
