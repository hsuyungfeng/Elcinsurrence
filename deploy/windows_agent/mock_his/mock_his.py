"""MockHIS：校正探針用的替身 HIS 視窗（僅供測試，非真實 HIS）。

目的：讓 ElcAgent 的校正精靈（calibration_wizard）與 agent-desktop 探針，
能在不接觸真實 HIS、不接觸真實病歷的前提下，驗證「寫入 → 讀回 → 比對」流程。

技術選擇（重要）：
- 使用 Win32 原生 EDIT / STATIC 控制項（透過 ctypes），而非 Tkinter。
  原因：Tkinter 在 Windows 上不會把子控制項匯出到 UI 自動化（UIA）樹，
  agent-desktop 快照只會看到標題列，探針因此找不到可寫入欄位。
  原生控制項會以 role=Edit 出現在無障礙樹中。

安全約束：
- 所有病患資料皆為假資料（TEST-*），不得替換為真實資料。
- 不連網、不讀寫任何檔案（不存檔、不寫入資料庫）。
- 視窗標題明確標示「MockHIS（測試替身）」，避免與真實 HIS 混淆。
- 欄位名稱對應展望（Vision）設定檔的 S/O/A/P 欄位（主訴／客觀檢查／評估／處置）。

執行（Windows，WinBoat 內）：
    pythonw mock_his.py        （pythonw 不會開啟 console 視窗，避免探針 --app 匹配到多個視窗）
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TITLE = "VisionHIS - MockHIS（測試替身，非真實 HIS）"
FIELDS = (
    ("soap_s", "主訴 (S)"),
    ("soap_o", "客觀檢查 (O)"),
    ("soap_a", "評估 (A)"),
    ("soap_p", "處置 (P)"),
)
FAKE_PATIENT = "TEST-0000000000 / 測試病患（假資料）"
NOTE = "MockHIS：僅供校正測試，內容不會儲存。"

# ---- Win32 常數 ----
WM_DESTROY = 0x0002
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_WANTRETURN = 0x1000
CW_USEDEFAULT = 0x80000000
SW_SHOW = 5
COLOR_WINDOW_PLUS_1 = 6
DEFAULT_GUI_FONT = 17
WM_SETFONT = 0x0030

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = ctypes.c_void_p


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_WNDPROC_REF = WNDPROC(_wnd_proc)  # 保持參考，避免被 GC 回收


def _create(cls: str, text: str, style: int, x: int, y: int, w: int, h: int, parent) -> wintypes.HWND:
    hwnd = user32.CreateWindowExW(0, cls, text, style, x, y, w, h, parent, None, None, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    user32.SendMessageW(hwnd, WM_SETFONT, gdi32.GetStockObject(DEFAULT_GUI_FONT), 1)
    return hwnd


def build(parent) -> dict[str, wintypes.HWND]:
    """在主視窗上建立原生控制項，回傳欄位名稱 → EDIT 控制項句柄。"""
    _create("STATIC", f"病患：{FAKE_PATIENT}", WS_CHILD | WS_VISIBLE, 10, 10, 600, 20, parent)
    widgets: dict[str, wintypes.HWND] = {}
    y = 40
    for key, label in FIELDS:
        _create("STATIC", label, WS_CHILD | WS_VISIBLE, 10, y, 600, 20, parent)
        style = WS_CHILD | WS_VISIBLE | WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN
        widgets[key] = _create("EDIT", "", style, 10, y + 22, 600, 70, parent)
        y += 100
    _create("STATIC", NOTE, WS_CHILD | WS_VISIBLE, 10, y + 10, 600, 20, parent)
    return widgets


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("MockHIS 只能在 Windows 上執行。")
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _WNDPROC_REF
    wc.hInstance = hinst
    wc.lpszClassName = "MockHISWindow"
    wc.hbrBackground = wintypes.HBRUSH(COLOR_WINDOW_PLUS_1)
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())

    hwnd = user32.CreateWindowExW(
        0, "MockHISWindow", TITLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        CW_USEDEFAULT, CW_USEDEFAULT, 660, 560, None, None, hinst, None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    build(hwnd)
    user32.ShowWindow(hwnd, SW_SHOW)

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
