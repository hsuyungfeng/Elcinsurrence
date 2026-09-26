"""llama.cpp OpenAI 相容 chat completion 端點的薄封裝。

使用者：`build_mapping.py`（一次性批次建置，D-04），以及執行期的
comparator 判定器（judger）與候選補強生成器（narratives）。規則查詢
（`get_rule`）本身不呼叫 LLM（D-05）。

呼叫前一律檢查 LLM 位址為本機／私有網段（`assert_local_llm_url`）：
判定與補強會送出病歷原文，不得離開本機（D2 紅線）。

RESEARCH.md Pitfall 5 記錄了一個可疑現象：對 live server 做一次
JSON-mode 的 ad-hoc 測試，回傳看起來像是 OpenAPI schema 樣板
（欄位名稱被 `"content": string` 這種型別描述取代），而非真正生成的文字。
因此本模組刻意使用「純 chat completion」（不帶 JSON-mode / response_format
限制）作為較安全的第一種嘗試方式，並要求呼叫端在批次邏輯依賴此模組前，
先執行 `smoke_test()` 確認伺服器回傳的是真實生成文字。

執行期間額外發現（Task 2 批次建置階段）：目前載入的模型
（Ornith-1.0-9B）預設會輸出完整的 reasoning/thinking trace
（`message.reasoning_content`），單次呼叫耗時約 25-35 秒，且在
`max_tokens` 較小時思考過程可能耗盡整個 token 預算，導致
`message.content` 為空字串（`finish_reason=length`）。這會讓
~13,942 筆代碼的批次建置在時間上不可行，也會提高空回應機率。
llama.cpp 的 OpenAI 相容端點支援 `chat_template_kwargs.enable_thinking`
（chat template 層級參數，非 hack）用來關閉思考過程，實測回應時間
從 ~30 秒降至 ~0.6 秒，且 `content` 直接產出實際答案。因此
`chat_completion` 預設在請求中帶入 `"chat_template_kwargs":
{"enable_thinking": false}`。
"""

import ipaddress
import os
from urllib.parse import urlparse

import requests

from config.settings import LLAMA_CPP_BASE_URL, load_llama_config


class RemoteLLMRefusedError(RuntimeError):
    """LLM 位址不是本機／私有網段——病歷原文不得送出本機（D2 紅線，B-IN-09）。"""


def assert_local_llm_url(url: str) -> None:
    """確認 LLM 位址為 localhost、loopback 或私有網段 IP。

    主機名稱（非 localhost）無法在此判定是否在內網，預設拒絕；確有需要時
    設定 ELC_ALLOW_REMOTE_LLM=1 明示放行（部署者須自行確保不出內網）。
    """
    if os.environ.get("ELC_ALLOW_REMOTE_LLM") == "1":
        return
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise RemoteLLMRefusedError(
            f"LLM 位址 {host!r} 非本機／私有 IP，拒絕送出病歷內容（可設 ELC_ALLOW_REMOTE_LLM=1 明示放行）"
        ) from None
    if not (ip.is_loopback or ip.is_private):
        raise RemoteLLMRefusedError(f"LLM 位址 {host!r} 為公網 IP，拒絕送出病歷內容")


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """呼叫 llama.cpp server 的 OpenAI 相容 `/v1/chat/completions` 端點。

    Args:
        system_prompt: system role 訊息內容。
        user_prompt: user role 訊息內容。
        max_tokens: 覆寫設定檔的 `inference.max_tokens`（若提供）。
        temperature: 覆寫設定檔的 `inference.temperature`（若提供）。

    Returns:
        模型生成的回覆文字（`choices[0].message.content`）。

    Raises:
        requests.RequestException: HTTP 請求失敗（連線錯誤、逾時等）。
        KeyError, IndexError: 回應 JSON 結構不符預期（伺服器異常回應）。
    """
    cfg = load_llama_config()
    inference_cfg = cfg["inference"]

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens if max_tokens is not None else inference_cfg["max_tokens"],
        "temperature": temperature if temperature is not None else inference_cfg["temperature"],
        # 關閉 reasoning/thinking trace：大幅縮短單次呼叫時間（~30s -> ~0.6s
        # 實測），並避免思考過程耗盡 max_tokens 導致 content 為空字串。
        "chat_template_kwargs": {"enable_thinking": False},
    }

    assert_local_llm_url(LLAMA_CPP_BASE_URL)
    response = requests.post(
        f"{LLAMA_CPP_BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    # content 可能為 null（B-IN-13）；以空字串交由呼叫端的解析失敗路徑處理
    return response.json()["choices"][0]["message"]["content"] or ""


def smoke_test() -> str:
    """對 llama.cpp server 送出一個簡單、可人工/自動檢查的請求。

    用於在批次建置邏輯依賴 `chat_completion` 之前，確認伺服器
    回傳的是真正生成的文字，而不是 RESEARCH.md Pitfall 5 觀察到的
    schema-descriptor 樣板（例如 `"content": string`）。

    Returns:
        原始回應字串，供呼叫端檢查。
    """
    return chat_completion(
        system_prompt="你是醫療給付規則比對助手。",
        user_prompt="請回答：1+1等於多少？只需回答數字。",
    )
