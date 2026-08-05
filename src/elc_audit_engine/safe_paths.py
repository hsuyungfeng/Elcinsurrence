"""檔名／路徑安全工具（P1-3 路徑穿越統一防線）。

三處識別碼會直接進入檔案路徑，均來自外部檔案而非程式常數：

- `patient_id`（申報 XML 欄位 `d3`）→ 讀取型：`LocalFileProvider._records_path`
- `case_record_no`（病歷號）→ 寫入型：`write_report`
- `case_seq`／`file_stem`（案件流水號）→ 寫入型：`write_appeal`

**採「校驗後拒絕」而非「清洗取代」**：清洗會讓 `A/1` 與 `A_1` 收斂成同一
檔名，兩個不同案件的 PHI 報告互相覆寫且無人察覺；拒絕則讓非法輸入變成
呼叫端必須處理的錯誤。此與 P1-1／P0-2 同源原則——**系統故障必須與業務
結論可區分，不得靜默產生看似正常的結果**。

白名單允許中文（CJK）：健保檔案的病歷號／流水號可能含中文字元，純
ASCII 白名單會把真實資料判為非法（2026-08-05 使用者裁示）。
"""

from __future__ import annotations

import re

# 允許：ASCII 英數、底線、連字號、CJK 統一表意文字（含擴充 A）與注音／全形中文常用區。
# 刻意不使用 `\w`——它在 Python 是 Unicode-aware，會連帶允許所有語系的
# 文字與數字（含各種易混淆字元），範圍遠大於此處需要的「中文＋英數」。
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-\u3400-\u4DBF\u4E00-\u9FFF]+$")


class UnsafeIdentifierError(ValueError):
    """識別碼含路徑穿越或不允許的字元，拒絕用於組成檔名。"""


def safe_filename(value: object, field_name: str = "identifier") -> str:
    """校驗識別碼可安全作為單一路徑段，通過則原樣回傳。

    以白名單校驗原始值（不做任何清洗）；因此 `../etc/passwd`、`rec/../x`、
    `C:\\x`、`..` 等一律拋錯，而非被悄悄改寫成合法檔名。

    Args:
        value: 待校驗的識別碼（會先轉字串）。
        field_name: 欄位名稱，僅用於錯誤訊息定位問題來源。

    Returns:
        校驗通過的檔名片段（與輸入相同）。

    Raises:
        UnsafeIdentifierError: 空值、含路徑分隔符、`..`、控制字元、
            空白或其他白名單外字元。
    """
    raw = "" if value is None else str(value)
    # 直接校驗原始值，**不可**先取 basename——`os.path.basename('../etc/passwd')`
    # 回傳 'passwd'（白名單可通過），等於把攻擊悄悄清洗成合法檔名，正是本模組
    # 明確拒絕的「靜默改寫」行為。路徑分隔符與 `.` 都不在白名單內，故穿越、
    # 絕對路徑、`..` 一律在此拋錯。
    if not raw or not _SAFE_FILENAME_RE.match(raw):
        raise UnsafeIdentifierError(
            f"{field_name} 含不允許的字元或路徑成分，拒絕作為檔名：{raw!r}"
        )
    return raw
