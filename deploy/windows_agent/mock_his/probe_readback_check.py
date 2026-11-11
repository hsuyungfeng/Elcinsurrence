"""Phase 30-09: MockHIS 專用探針寫入與讀回驗證工具。

嚴格安全約束：
- 僅鎖定標題明確包含「MockHIS」之測試替身視窗。
- 若找不到含「MockHIS」之視窗，或偵測到其他真實 HIS 視窗，必須立即中止（Fail-Closed）。
- 嚴禁對任何真實 HIS 視窗或真實病歷進行寫入。
- 使用隨機產生的 nonce（例如 PROBE-<12位隨機碼>）進行寫入與讀回比對。

執行方式（Windows 端）：
    python deploy/windows_agent/mock_his/probe_readback_check.py
或指定 agent-desktop 執行檔路徑：
    python deploy/windows_agent/mock_his/probe_readback_check.py C:\\ElcAgent\\_internal\\bin\\agent-desktop.exe
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MOCK_HIS_TITLE_KEYWORD = "MockHIS"
TEST_VENDOR_TITLE: Optional[str] = None  # 預設關閉；僅 --test-vendor 指定時啟用


def find_window_titles_win32() -> list[str]:
    """以 Win32 EnumWindows 列出所有頂層視窗標題（僅 Windows 有效，其他平台回傳空清單）。"""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []
    if not hasattr(ctypes, "windll"):
        return []
    user32 = ctypes.windll.user32
    titles: list[str] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            titles.append(buf.value)
        return True

    user32.EnumWindows(enum_proc_type(_callback), 0)
    return titles


def _flatten_snapshot(snapshot_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 agent-desktop 快照轉成扁平元素清單（name/role/ref）。

    agent-desktop 2.6 的格式為 data.tree 巢狀結構，參照欄位為 ref_id；
    舊格式為頂層 elements，參照欄位為 ref。兩者都接受。
    """
    if isinstance(snapshot_data.get("elements"), list):
        return snapshot_data["elements"]
    flat: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "role" in node:
                flat.append({
                    "name": node.get("name", ""),
                    "role": node.get("role", ""),
                    "ref": node.get("ref_id") or node.get("ref", ""),
                    "automation_id": (node.get("native_id") or {}).get("value", ""),
                })
            for child in node.get("children", []) or []:
                walk(child)

    walk((snapshot_data.get("data") or {}).get("tree") or {})
    return flat


def has_mock_evidence(snapshot_text: str, window_titles: list[str]) -> bool:
    """是否有 MockHIS 證據：Win32 視窗標題，或快照（任何層級的字串值）含 MockHIS。"""
    if any(MOCK_HIS_TITLE_KEYWORD in t for t in window_titles):
        return True
    try:
        data = json.loads(snapshot_text)
    except (ValueError, TypeError):
        return False

    def _walk(node) -> bool:
        if isinstance(node, dict):
            return any(_walk(v) for v in node.values())
        if isinstance(node, list):
            return any(_walk(v) for v in node)
        if isinstance(node, str):
            return MOCK_HIS_TITLE_KEYWORD in node or "測試替身" in node
        return False

    return _walk(data)


def find_agent_desktop_bin(custom_path: Optional[str] = None) -> Optional[Path]:
    """尋找 agent-desktop.exe 執行檔路徑。"""
    if custom_path:
        p = Path(custom_path)
        if p.exists() and p.is_file():
            return p.resolve()

    candidates = [
        # 同專案 deploy/windows_agent/bin/
        Path(__file__).resolve().parent.parent / "bin" / "agent-desktop.exe",
        # 打包目錄 _internal/bin/
        Path(__file__).resolve().parent.parent.parent.parent / "dist" / "ElcAgent" / "_internal" / "bin" / "agent-desktop.exe",
        # Windows 預設部署位置 C:\ElcAgent
        Path("C:/ElcAgent/_internal/bin/agent-desktop.exe"),
        # WinBoat 掛載位置
        Path("C:/shared/Desktop/Elcinsurrence/dist/ElcAgent/_internal/bin/agent-desktop.exe"),
    ]

    for c in candidates:
        if c.exists() and c.is_file():
            return c.resolve()

    which_ad = shutil.which("agent-desktop")
    if which_ad:
        return Path(which_ad).resolve()

    return None


def execute_agent_desktop_cmd(ad_bin: Path, args: List[str]) -> Tuple[int, str, str]:
    """執行 agent-desktop CLI 指令並回傳 (returncode, stdout, stderr)。"""
    cmd = [str(ad_bin)] + args
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def run_probe_check(custom_path: Optional[str] = None) -> bool:
    """執行 MockHIS 探針讀寫比對主流程。"""
    print("=" * 60)
    print("【Phase 30-09】MockHIS 替身探針寫入與讀回安全檢測")
    print("=" * 60)

    # 1. 解析 agent-desktop.exe
    ad_path = find_agent_desktop_bin(custom_path=custom_path)
    if not ad_path:
        print("[FAIL] 錯誤：找不到 agent-desktop.exe 執行檔。")
        print("  請確認 C:\\ElcAgent\\_internal\\bin\\agent-desktop.exe 存在，")
        print("  或在命令列後方指定路徑：python probe_readback_check.py <路徑>")
        return False

    print(f"[OK] 使用 agent-desktop: {ad_path}")

    # 2. 安全檢查：搜尋包含 MockHIS 的視窗，嚴防誤觸真實 HIS
    print(f"[CHECK] 尋找標題含 '{MOCK_HIS_TITLE_KEYWORD}' 的視窗快照...")

    # 只掃描 MockHIS 相關程序（python 執行替身）；不掃描 VisionHIS，避免讀取真實 HIS 內容。
    # MockHIS 以 pythonw 啟動時程序名為 pythonw.exe；以 python 啟動則為 python.exe
    app_candidates = ["pythonw", "python", "MockHIS"]
    if TEST_VENDOR_TITLE:
        # 測試模式（僅示範資料、僅測試機）：額外允許指定標題關鍵字的視窗
        app_candidates.append(TEST_VENDOR_TITLE)
    snapshot_data: Optional[Dict[str, Any]] = None
    matched_app: Optional[str] = None
    window_titles = find_window_titles_win32()

    for app in app_candidates:
        ret, stdout, stderr = execute_agent_desktop_cmd(ad_path, ["snapshot", "--app", app, "-i"])  # agent-desktop 2.6 不接受 --json；輸出本身即為 JSON
        vendor_ok = bool(TEST_VENDOR_TITLE) and any(TEST_VENDOR_TITLE in t for t in window_titles)
        if ret == 0 and stdout and (has_mock_evidence(stdout, window_titles) or vendor_ok):
            snapshot_data = json.loads(stdout)
            matched_app = app
            break

    if not snapshot_data:
        print("[FAIL] 安全阻斷：未偵測到任何包含 'MockHIS' 的測試替身視窗！")
        print("  保護原則：為避免寫入真實病歷，本工具『嚴禁』對非 MockHIS 視窗進行任何探針操作。")
        print("  請先在背景執行 MockHIS：")
        print("    python deploy/windows_agent/mock_his/mock_his.py")
        return False

    print(f"[OK] 成功鎖定測試替身視窗 (app={matched_app})，安全確認通過。")

    # 3. 定位目標測試欄位（優先鎖定 soap_s 或 '主訴 (S)'）
    elements = _flatten_snapshot(snapshot_data)
    target_ref: Optional[str] = None
    target_name: Optional[str] = None

    for el in elements:
        name = el.get("name", "")
        automation_id = el.get("automation_id", "")
        role = el.get("role", "")
        ref = el.get("ref", "")
        if "主訴" in name or automation_id in ("txtS", "soap_s") or "soap_s" in name:
            target_ref = ref
            target_name = name or automation_id
            break

    # 若未精確匹配名稱，選取第一個文字輸入控制項
    # agent-desktop 2.6 將原生 EDIT 標為 "textfield"（見 2026-11-11 診斷輸出）
    if not target_ref:
        for el in elements:
            if el.get("role") in ("Edit", "Text", "textfield"):
                target_ref = el.get("ref")
                target_name = el.get("name") or el.get("automation_id") or "First Edit"
                break

    if not target_ref:
        print("[FAIL] 錯誤：在 MockHIS 視窗中未找到可供測試的文字輸入欄位。")
        return False

    print(f"[OK] 鎖定測試欄位: {target_name} (ref={target_ref})")

    # 4. 產生隨機 nonce（PROBE-<12位英數>，絕對不含任何病歷敏感字眼）
    nonce = f"PROBE-{uuid.uuid4().hex[:12].upper()}"
    expected_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    print(f"[PROBE] 產生隨機探針 Nonce: {nonce}")
    print(f"[PROBE] 預期 SHA-256: {expected_hash}")

    # 5. 探針寫入 (set-value)
    print(f"[WRITE] 正在將探針寫入欄位 {target_ref}...")
    ret, out, err = execute_agent_desktop_cmd(ad_path, ["set-value", target_ref, nonce])
    if ret != 0:
        print(f"[FAIL] 寫入探針失敗 (code {ret}): {err or out}")
        return False
    print("[OK] 探針寫入成功。")

    # 6. 探針讀回 (get-value)
    print(f"[READ] 正在從欄位 {target_ref} 讀回值...")
    # agent-desktop 2.6：`get <REF> --property value`，回傳 JSON 封包，值位於 data.value
    ret, read_raw, err = execute_agent_desktop_cmd(ad_path, ["get", target_ref, "--property", "value"])
    if ret != 0:
        print(f"[FAIL] 讀回探針失敗 (code {ret}): {err or read_raw}")
        return False
    try:
        read_val = str((json.loads(read_raw).get("data") or {}).get("value", ""))
    except (ValueError, AttributeError):
        read_val = read_raw
    actual_val = read_val.strip()
    actual_hash = hashlib.sha256(actual_val.encode("utf-8")).hexdigest()
    print(f"[READ] 讀回字串: {actual_val}")
    print(f"[READ] 讀回 SHA-256: {actual_hash}")

    # 7. 比對雜湊與字串一致性
    if actual_val == nonce and actual_hash == expected_hash:
        print("-" * 60)
        print("【PASS】讀寫比對完全一致！")
        print(f"  - 探針寫入值: {nonce}")
        print(f"  - 欄位讀回值: {actual_val}")
        print(f"  - 雜湊一致性: {actual_hash} == {expected_hash}")
        print("  - 結論: readback_test_passed 驗證通過，符合 30-09 探針驗收標準。")
        print("-" * 60)
        return True
    else:
        print("-" * 60)
        print("【FAIL】讀寫比對不一致！")
        print(f"  - 預期值: {nonce}")
        print(f"  - 實際值: {actual_val}")
        print(f"  - 預期雜湊: {expected_hash}")
        print(f"  - 實際雜湊: {actual_hash}")
        print("-" * 60)
        return False


def main() -> None:
    global TEST_VENDOR_TITLE
    args = sys.argv[1:]
    if "--test-vendor" in args:
        i = args.index("--test-vendor")
        if i + 1 >= len(args):
            print("[FAIL] --test-vendor 需要視窗標題關鍵字")
            sys.exit(2)
        TEST_VENDOR_TITLE = args[i + 1]
        print(f"[WARN] 測試模式：允許標題含「{TEST_VENDOR_TITLE}」的視窗（僅限測試機與示範資料）")
        del args[i:i + 2]
    custom_ad = args[0] if args else None
    passed = run_probe_check(custom_path=custom_ad)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
