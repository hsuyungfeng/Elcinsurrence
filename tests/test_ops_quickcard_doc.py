"""驗證《診所主機維運速查卡》存在性、編碼與關鍵指令準確性（Phase 37 Wave 2）。"""

from __future__ import annotations

import re
from pathlib import Path

QUICKCARD_PATH = Path("docs/CLINIC_SERVER_OPS_QUICKCARD.md")


def test_ops_quickcard_exists_utf8_no_bom():
    assert QUICKCARD_PATH.is_file(), "缺少 docs/CLINIC_SERVER_OPS_QUICKCARD.md"
    raw = QUICKCARD_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "速查卡不應含 UTF-8 BOM"
    raw.decode("utf-8")


def test_ops_quickcard_covers_all_required_commands_and_safety_rules():
    text = QUICKCARD_PATH.read_text(encoding="utf-8")

    required_tokens = (
        "elc-audit-engine.service",
        "elc-llama-server.service",
        "/api/health",
        "/api/rules/status",
        "rules.sqlite3.lock",
        "ps -p",
        "--check-asr-models",
        "--check-llama-cache",
        "--stale-vs-db",
        "REPLACE_RULES",
        "增量同步",
        "健保署官方公告",
        "rules.sqlite3.bak.",
    )
    for token in required_tokens:
        assert token in text, f"維運速查卡缺少必備指引項目：{token!r}"

    # 禁止過時認證語法或危險管線下載
    assert "X-API-Key" not in text
    assert not re.search(r"curl[^\n]*\|\s*(ba)?sh", text)
