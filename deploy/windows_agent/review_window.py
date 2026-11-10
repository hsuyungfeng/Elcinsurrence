"""Physician SOAP Review Window (Phase 30: D-30-03, D-30-05, D-30-12).

Tkinter desktop window for physician SOAP review.
Tkinter is imported lazily inside run_review_window so this module can be safely imported on headless Linux.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

from deploy.windows_agent.review_client import (
    DraftChangedError,
    ReviewClient,
    build_review_view_model,
)

logger = logging.getLogger("windows_agent.review_window")


def run_review_window(client: ReviewClient, poll_seconds: float = 10.0) -> None:
    """Launch the Tkinter review window.

    Tkinter is imported inside this function to allow Linux headless import.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Elcinsurrence - SOAP 審核視窗")
    root.geometry("960x680")
    root.minsize(800, 600)
    from deploy.windows_agent.window_utils import keep_on_top

    keep_on_top(root)

    current_draft: Optional[dict] = None
    current_vm: Optional[dict] = None

    # Top Frame: Pending list
    top_frame = ttk.LabelFrame(root, text="待審清單", padding=10)
    top_frame.pack(fill="x", padx=10, pady=5)

    list_var = tk.StringVar()
    draft_selector = ttk.Combobox(top_frame, textvariable=list_var, state="readonly", width=60)
    draft_selector.pack(side="left", padx=5)

    # Main split: Left editors, Right advisory
    main_frame = ttk.Frame(root, padding=10)
    main_frame.pack(fill="both", expand=True, padx=10, pady=5)

    editor_frame = ttk.LabelFrame(main_frame, text="SOAP 內容編輯（S/O/A/P）", padding=10)
    editor_frame.pack(side="left", fill="both", expand=True, padx=5)

    text_widgets: dict[str, tk.Text] = {}
    for key, label in [("s", "S (主訴)"), ("o", "O (客觀檢查)"), ("a", "A (評估與診斷)"), ("p", "P (計畫與處置)")]:
        lbl = ttk.Label(editor_frame, text=label, font=("Helvetica", 10, "bold"))
        lbl.pack(anchor="w", pady=(4, 1))
        txt = tk.Text(editor_frame, height=5, wrap="word", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, pady=(0, 4))
        text_widgets[key] = txt

    # Right Frame: Advisory (D-30-12, Read-only suggestions)
    advisory_frame = ttk.LabelFrame(main_frame, text="醫令與診斷建議 (僅供參考，不自動寫入)", padding=10)
    advisory_frame.pack(side="right", fill="both", padx=5)
    advisory_frame.config(width=300)

    advisory_text = tk.Text(advisory_frame, width=32, wrap="word", state="disabled", bg="#f4f4f4")
    advisory_text.pack(fill="both", expand=True)

    # Status & Action Buttons
    status_var = tk.StringVar(value="就緒")
    status_bar = ttk.Label(root, textvariable=status_var, relief="sunken", anchor="w", padding=5)
    status_bar.pack(side="bottom", fill="x")

    btn_frame = ttk.Frame(root, padding=10)
    btn_frame.pack(side="bottom", fill="x", padx=10)

    def _load_draft_into_ui(draft_id: str):
        nonlocal current_draft, current_vm
        try:
            draft_data = client.get_draft(draft_id)
            current_draft = draft_data
            current_vm = build_review_view_model(draft_data)

            for k in ("s", "o", "a", "p"):
                text_widgets[k].delete("1.0", tk.END)
                val = current_vm["editors"][k]["value"]
                text_widgets[k].insert("1.0", val)

            # Update advisory text
            advisory_text.config(state="normal")
            advisory_text.delete("1.0", tk.END)

            adv = current_vm["advisory"]
            advisory_text.insert(tk.END, "【ICD-10 診斷建議】\n")
            for item in adv["icd10"]["items"]:
                advisory_text.insert(tk.END, f"• {item}\n")

            advisory_text.insert(tk.END, "\n【處置/醫令建議】\n")
            for item in adv["order"]["items"]:
                advisory_text.insert(tk.END, f"• {item}\n")

            advisory_text.insert(tk.END, "\n【用藥建議】\n")
            for item in adv["med"]["items"]:
                advisory_text.insert(tk.END, f"• {item}\n")

            advisory_text.config(state="disabled")
            status_var.set(f"已載入草稿：{draft_id} (版本 v{current_vm['version']})")
        except Exception as exc:
            messagebox.showerror("載入失敗", f"無法載入草稿內容：{exc}")

    def _refresh_pending():
        try:
            pending = client.list_pending()
            if not pending:
                status_var.set("目前無待審草稿")
                draft_selector["values"] = []
                return
            items = [f"{p['draft_id']} ({p.get('patient_ref', '***')})" for p in pending]
            draft_selector["values"] = items
            if items and not current_draft:
                draft_selector.current(0)
                _load_draft_into_ui(pending[0]["draft_id"])
        except Exception as exc:
            status_var.set(f"輪詢失敗: {exc}")
        finally:
            root.after(int(poll_seconds * 1000), _refresh_pending)

    def _on_select(event):
        sel = draft_selector.get()
        if sel:
            draft_id = sel.split(" ")[0]
            _load_draft_into_ui(draft_id)

    draft_selector.bind("<<ComboboxSelected>>", _on_select)

    def _on_approve():
        if not current_draft or not current_vm:
            return
        draft_id = current_draft["draft_id"]
        content_hash = current_vm["content_hash"]
        try:
            client.approve(draft_id, content_hash)
            messagebox.showinfo("核准成功", f"草稿 {draft_id} 已排入 HIS 寫入佇列。")
            _refresh_pending()
        except DraftChangedError:
            messagebox.showwarning("內容已變更", "伺服器端內容已被其他程序或使用者更新，請重新載入！")
            _load_draft_into_ui(draft_id)
        except Exception as exc:
            messagebox.showerror("核准失敗", str(exc))

    def _on_edit():
        if not current_draft or not current_vm:
            return
        draft_id = current_draft["draft_id"]
        base_hash = current_vm["content_hash"]
        new_soap = {
            "s": text_widgets["s"].get("1.0", tk.END).strip(),
            "o": text_widgets["o"].get("1.0", tk.END).strip(),
            "a": text_widgets["a"].get("1.0", tk.END).strip(),
            "p": text_widgets["p"].get("1.0", tk.END).strip(),
        }
        try:
            res = client.edit(draft_id, new_soap, base_hash)
            messagebox.showinfo("儲存成功", f"草稿已更新至版本 v{res.get('version', 2)}")
            _load_draft_into_ui(draft_id)
        except DraftChangedError:
            messagebox.showwarning("更新衝突", "伺服器端內容已被其他程序更新，請重新載入！")
            _load_draft_into_ui(draft_id)
        except Exception as exc:
            messagebox.showerror("儲存失敗", str(exc))

    def _on_reject():
        if not current_draft:
            return
        draft_id = current_draft["draft_id"]
        try:
            client.reject(draft_id, reason_code="PHYSICIAN_REJECT", reason_text="醫師手動退回")
            messagebox.showinfo("退回成功", f"草稿 {draft_id} 已退回。")
            _refresh_pending()
        except Exception as exc:
            messagebox.showerror("退回失敗", str(exc))

    btn_approve = ttk.Button(btn_frame, text="✅ 核准並排入 HIS", command=_on_approve)
    btn_approve.pack(side="right", padx=5)

    btn_edit = ttk.Button(btn_frame, text="💾 儲存修改內容", command=_on_edit)
    btn_edit.pack(side="right", padx=5)

    btn_reject = ttk.Button(btn_frame, text="❌ 退回草稿", command=_on_reject)
    btn_reject.pack(side="left", padx=5)

    btn_refresh = ttk.Button(btn_frame, text="🔄 立即重整", command=_refresh_pending)
    btn_refresh.pack(side="left", padx=5)

    _refresh_pending()
    root.mainloop()
