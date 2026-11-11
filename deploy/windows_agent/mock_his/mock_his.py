"""MockHIS：校正探針用的替身 HIS 視窗（僅供測試，非真實 HIS）。

目的：讓 ElcAgent 的校正精靈（calibration_wizard）與 agent-desktop 探針，
能在不接觸真實 HIS、不接觸真實病歷的前提下，驗證「寫入 → 讀回 → 比對」流程。

安全約束：
- 所有病患資料皆為假資料（TEST-*），不得替換為真實資料。
- 不連網、不讀寫任何檔案（不存檔、不寫入資料庫）。
- 視窗標題明確標示「MockHIS（測試替身）」，避免與真實 HIS 混淆。
- 欄位名稱對應展望（Vision）設定檔的 S/O/A/P 欄位（主訴／客觀檢查／評估／處置）。

執行（Windows，WinBoat 內）：
    python mock_his.py
或打包為 VisionHIS.exe 以符合設定檔的 exe_names 偵測：
    pyinstaller --onefile --name VisionHIS mock_his.py
"""

from __future__ import annotations

import tkinter as tk

TITLE = "VisionHIS - MockHIS（測試替身，非真實 HIS）"
FIELDS = (
    ("soap_s", "主訴 (S)"),
    ("soap_o", "客觀檢查 (O)"),
    ("soap_a", "評估 (A)"),
    ("soap_p", "處置 (P)"),
)
FAKE_PATIENT = "TEST-0000000000 / 測試病患（假資料）"


def build(root: tk.Tk) -> dict[str, tk.Text]:
    """建立替身視窗，回傳欄位名稱 → Text 元件（供探針以名稱定位）。"""
    root.title(TITLE)
    root.geometry("640x520")
    tk.Label(root, text=f"病患：{FAKE_PATIENT}", anchor="w", fg="#7f1d1d").pack(fill="x", padx=10, pady=(10, 4))
    widgets: dict[str, tk.Text] = {}
    for key, label in FIELDS:
        tk.Label(root, text=label, anchor="w").pack(fill="x", padx=10)
        text = tk.Text(root, height=4, wrap="word")
        text.pack(fill="x", padx=10, pady=(0, 8))
        widgets[key] = text
    tk.Label(root, text="MockHIS：僅供校正測試，內容不會儲存。", fg="#555").pack(fill="x", padx=10, pady=8)
    return widgets


def main() -> None:
    root = tk.Tk()
    build(root)
    root.mainloop()


if __name__ == "__main__":
    main()
