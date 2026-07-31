"""llama.cpp server 完成品質 smoke test（VALIDATION.md 手動驗證項目的自動化回歸守門）。

對應 RESEARCH.md Pitfall 5 / Open Question #2：research 階段對 live server
做的一次 JSON-mode ad-hoc 測試，回傳看起來像是 OpenAPI schema 樣板
（例如 `"content": string`）而非真正生成的文字。本測試確保在
`build_mapping.py` 批次邏輯依賴 `llm_client.chat_completion` 之前，
伺服器確實回傳真實生成內容。

若伺服器未啟動（`/health` 不是 200），以 `pytest.mark.skipif` 跳過，
避免 CI/離線環境因為環境前提未就緒而失敗 — 但伺服器啟動時，此測試
必須通過才能繼續 Task 2。
"""

import requests
import pytest

from elc_audit_engine.rule_repository.mapping import llm_client
from config.settings import LLAMA_CPP_BASE_URL


def _llama_server_is_up() -> bool:
    try:
        resp = requests.get(f"{LLAMA_CPP_BASE_URL}/health", timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False


SCHEMA_DESCRIPTOR_ANOMALY_SUBSTRINGS = [
    '"content": "string"',
    '"content": string',
    '"type": "string"',
]


@pytest.mark.skipif(
    not _llama_server_is_up(),
    reason="llama.cpp server 未在 localhost:8080 啟動（/health 未回傳 200）",
)
def test_llama_server_returns_real_text_not_schema_descriptor():
    result = llm_client.smoke_test()

    # (a) 非空字串
    assert isinstance(result, str)
    assert result.strip() != ""

    # (b) 不包含 schema-descriptor 異常樣式
    for anomaly in SCHEMA_DESCRIPTOR_ANOMALY_SUBSTRINGS:
        assert anomaly not in result, (
            f"llama.cpp 回傳疑似 schema-descriptor 樣板文字（含 {anomaly!r}），"
            "而非真正生成內容 — 參見 RESEARCH.md Pitfall 5"
        )

    # (c) 至少包含一個數字字元（smoke test prompt 要求回答數字）
    assert any(ch.isdigit() for ch in result), (
        f"smoke test 提示要求數字答案，但回應中找不到任何數字字元：{result!r}"
    )
