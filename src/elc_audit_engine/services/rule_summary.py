"""給付規定（payment_text）精簡摘要擷取器（確定性純原文擷取，不呼叫 LLM）。

設計原則：
- 絕不捏造條文：所有文字均自 `payment_text` 原文擷取，僅去除 Markdown 裝飾符號（`**`、`>` 等）。
- 嚴格不與完整條文相同：回傳值保證比原文精簡且不同於原文；若原文已是單句短文（無法再精簡），
  回傳 ``None``，讓呼叫端避免在「給付規定（payment_text）」與「檢視完整給付規定條文」重複顯示相同文字。
"""

from __future__ import annotations

import re

# 標題列／版本列／備註列（精簡摘要時略過，完整條文仍保留）
_HEADER_LINE_RE = re.compile(
    r"^(?:\([^)）]{1,8}\)|（[^)）]{1,8}）).*(?:審查原則|支付標準)"
    r"|^(?:\*{0,2}版本|（版別|\(\d{2,4}[/-]\d{1,2}[/-]\d{1,2}\))"
    r"|^>\s*\*{0,2}備註",
    re.IGNORECASE,
)

# 編號段落標題，例如：`1. **申報條件**`、`2.應檢附文件：...`、`3. 重複申報限制`
_SECTION_HEAD_RE = re.compile(
    r"^\s*\d+\.\s*\*{0,2}([^：:*\n]{2,16}?)\*{0,2}\s*(?:[：:]\s*(.*))?$"
)

# 項目符號前綴，例如：`- `、`• `、`a. `、`1) `、`1.1 `
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-•*]\s+|\d+(?:\.\d+)?[.)]\s+|[a-zA-Z][.)]\s+)")

# 句末切分（中英文句號／分號）
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；;])\s*")

_MAX_ITEM_CHARS = 58
_MAX_SECTIONS = 3


def _strip_md(text: str) -> str:
    s = text.replace("**", "").replace("__", "")
    s = re.sub(r"^\s*>\s*", "", s)
    s = re.sub(r"[ \t\u202f\u00a0]+", " ", s)
    return s.strip()


def _truncate(text: str, limit: int) -> str:
    s = text.strip()
    if len(s) <= limit:
        return s
    # 盡量在標點處截斷，避免切在詞彙中間
    cut = s[:limit]
    for sep in ("。", "；", "，", "、", ";", ","):
        idx = cut.rfind(sep)
        if idx >= limit // 2:
            return cut[: idx + 1].rstrip("，、, ") + "…"
    return cut.rstrip() + "…"


def _extract_structured_points(raw: str, *, max_chars: int) -> list[str]:
    """從編號分節（1. 申報條件 / 2. 應檢附文件 / 3. 重複申報限制…）擷取每節首條重點。"""
    lines = [ln.rstrip() for ln in raw.splitlines()]
    points: list[str] = []
    current_title: str | None = None
    current_items: list[str] = []

    def _flush() -> None:
        nonlocal current_title, current_items
        if not current_title:
            return
        if current_items:
            if "文件" in current_title or "檢附" in current_title:
                # 應檢附文件常為多條短項，合併前 2–3 項更直觀
                joined = "、".join(
                    re.sub(r"[。；;.]+$", "", it) for it in current_items[:3]
                )
                body = _truncate(joined, _MAX_ITEM_CHARS)
            else:
                body = _truncate(current_items[0], _MAX_ITEM_CHARS)
            points.append(f"• {current_title}：{body}")
        current_title = None
        current_items = []

    for ln in lines:
        cleaned = _strip_md(ln)
        if not cleaned or _HEADER_LINE_RE.match(cleaned):
            continue
        sec_m = _SECTION_HEAD_RE.match(ln.strip())
        if sec_m:
            _flush()
            if len(points) >= _MAX_SECTIONS:
                break
            title = _strip_md(sec_m.group(1))
            inline_body = _strip_md(sec_m.group(2) or "")
            # 忽略如「1. 備註」等次要節
            if title in ("備註", "附註"):
                current_title = None
                continue
            current_title = title
            if inline_body:
                current_items.append(inline_body)
            continue
        if current_title is not None:
            item = _BULLET_PREFIX_RE.sub("", cleaned).strip()
            if item and not _HEADER_LINE_RE.match(item):
                current_items.append(item)

    _flush()
    if not points:
        return []

    # 控制總長度在 max_chars 以內
    result: list[str] = []
    used = 0
    for pt in points:
        extra = len(pt) + (1 if result else 0)
        if result and used + extra > max_chars:
            break
        result.append(pt)
        used += extra
    return result


def summarize_payment_text(text: str | None, *, max_chars: int = 180) -> str | None:
    """從 `payment_text` 原文擷取精簡重點摘要。

    Returns:
        精簡摘要字串（保證嚴格短於且不同於原文）；若原文為單句短文無法再精簡則回傳 ``None``。
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # 1. 結構化條列格式（如 62010C、05315C 等多節審查原則）
    structured = _extract_structured_points(raw, max_chars=max_chars)
    if structured:
        summary = "\n".join(structured)
        # 若原文已極短（≤140 字）且擷取結果長度仍達原文 85% 以上（僅去掉標題或換項目符號），
        # 視為無法實質精簡，回傳 None 以免與下方完整條文幾乎重複顯示（Phase 38）。
        if len(raw) <= 140 and len(summary) >= len(raw) * 0.85:
            return None
        if summary != raw and len(summary) < len(raw):
            return summary

    # 2. 一般條文段落：取首句重點並截短
    flat = _strip_md(re.sub(r"\s*\n+\s*", " ", raw))
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(flat) if s.strip()]
    if len(sentences) >= 2:
        first = _truncate(sentences[0], max_chars - 1)
        summary = first if first.endswith("…") else f"{first}…"
        if summary != raw and len(summary) < len(raw):
            return summary

    if len(flat) > max_chars:
        summary = _truncate(flat, max_chars)
        if summary != raw and len(summary) < len(raw):
            return summary

    # 單句短文（≤ max_chars 且無多句／多節）：避免與完整條文重複，回傳 None
    return None
