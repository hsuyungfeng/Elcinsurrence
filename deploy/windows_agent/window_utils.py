"""共用視窗工具：讓 agent 的視窗浮在最上層（Phase 30 使用者需求）。

本模組不匯入 tkinter，避免啟動時載入 GUI 相依（延遲匯入規範）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def keep_on_top(root: Any) -> None:
    """將 Tk 視窗設為最上層並取得焦點。

    -topmost 讓視窗壓在 HIS 等其他程式之上；lift／focus_force 確保目前就顯示在前景。
    設定失敗只記錄警告，不中斷校正或審核流程。
    """
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
    except Exception as exc:  # 平台不支援時仍讓視窗可用
        logger.warning("無法設定視窗置頂：%s", exc)
