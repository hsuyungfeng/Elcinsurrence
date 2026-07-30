"""llama.cpp OpenAI 相容 chat completion 端點的薄封裝。

僅供 `build_mapping.py` 這個一次性批次建置腳本使用（D-04）。
查詢階段（Phase 3-5）絕不呼叫此模組（D-05）。

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

import requests

from config.settings import LLAMA_CPP_BASE_URL, load_llama_config


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

    response = requests.post(
        f"{LLAMA_CPP_BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


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
