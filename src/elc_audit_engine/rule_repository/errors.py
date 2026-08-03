"""規則庫查詢的錯誤型別。

`get_rule()` 原本把「查無此醫令」（正常結果）與「資料庫故障」（系統異常）
混在一起，一律回傳 `found=False` —— Phase 5 比對器會把 DB 損毀／檔案
不存在誤判成「這醫令真的沒有規則」。本模組新增 `RuleRepositoryError`，
讓系統性故障與正常查無可以區分（P0-2）。
"""


class RuleRepositoryError(RuntimeError):
    """規則庫查詢路徑上的系統性故障（非「查無此醫令」）。

    涵蓋：SQLite 檔案不存在／表不存在／損毀、連線失敗等 `sqlite3.Error`
    子類別。呼叫端（Phase 5）應視此為 infra 故障處理（記錄、警示、降級），
    不應把它當成「該醫令無規則」。
    """
