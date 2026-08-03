"""SOAP 病歷文字分段器 → SOAPDocument。

設計決策（03-CONTEXT.md）：
- D-10 兩層策略：先試標記偵測（正則，涵蓋 `S:`、`S)`、`【S】`、`主訴：`
  等變體）；偵測不到才回退關鍵詞分類。
- D-11 信度標記：marker-based（high）vs keyword-based（low），供 Phase 5
  判斷分段可不可信。
- D-12 移植 soap-classifier.js 的 240+ 關鍵詞（見 soap_keywords.py），
  演算法用 Python 重寫；修正原版「無關鍵詞命中時預設歸類 subjective」的
  行為為「未分類」（UNKNOWN），避免無依據的猜測污染下游。
- D-13 輸入為獨立文字檔（.txt/.md）。
"""

from __future__ import annotations

import re

from .models import SOAPCategory, SOAPDocument, SOAPSegment
from .soap_keywords import SOAP_KEYWORDS

# 類別英文鍵 → 字母（SOAP 四段）。
_CATEGORY_LETTERS: dict[str, SOAPCategory] = {
    "subjective": "S",
    "objective": "O",
    "assessment": "A",
    "plan": "P",
}

# D-10 標記變體（行首）。S/O/A/P 字母 + 常見中文標籤，冒號/括號/方括號皆容。
_MARKER_PATTERNS: dict[SOAPCategory, re.Pattern[str]] = {
    "S": re.compile(r"^\s*(?:【S】|S\s*[:：)）]|主訴\s*[:：])"),
    "O": re.compile(r"^\s*(?:【O】|O\s*[:：)）]|客觀\s*[:：])"),
    "A": re.compile(r"^\s*(?:【A】|A\s*[:：)）]|評估\s*[:：])"),
    "P": re.compile(r"^\s*(?:【P】|P\s*[:：)）]|計劃\s*[:：]|計畫\s*[:：])"),
}

# 關鍵詞分類的斷句分隔符（沿用 JS 版：。.！!？?\n）。
_SENTENCE_SPLIT_RE = re.compile(r"[。.！!？?\n]+")


def _classify_sentence(sentence: str) -> tuple[SOAPCategory, float]:
    """以關鍵詞計分分類單句（D-12：無命中回傳 UNKNOWN，非 subjective）。

    Returns:
        (類別字母或 UNKNOWN, 最高分數)。同分時依主觀→客觀→評估→計劃
        的順序取先者（沿用 JS reduce 的 > 語意）。
    """
    best_cat: str | None = None
    best_score = 0.0
    for cat, data in SOAP_KEYWORDS.items():
        score = sum(data["weight"] for kw in data["keywords"] if kw in sentence)
        if score > best_score:
            best_cat = cat
            best_score = score
    if best_cat is None or best_score <= 0:
        return "UNKNOWN", 0.0
    return _CATEGORY_LETTERS[best_cat], best_score


def _parse_with_markers(lines: list[str]) -> tuple[list[SOAPSegment], list[str]]:
    """標記偵測路徑：依行首標記分段（高信度）。

    首個標記前的內容歸 unclassified（不猜測其段落）。
    """
    segments: list[SOAPSegment] = []
    unclassified: list[str] = []
    current: dict[str, object] | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched: SOAPCategory | None = None
        for cat, pattern in _MARKER_PATTERNS.items():
            if pattern.match(stripped):
                matched = cat
                break

        if matched is not None:
            if current is not None:
                segments.append(_finish_segment(current))
            content = _MARKER_PATTERNS[matched].sub("", stripped, count=1).strip()
            current = {"cat": matched, "text": content, "method": "marker"}
            if not content:
                # 標記行本身無內容（如「S：」）——不產出空段，繼續等待內文
                current = None
        elif current is not None:
            # 標記段落內的多行內文，以換行連接
            current["text"] = current["text"] + "\n" + stripped  # type: ignore[operator]
        else:
            unclassified.append(stripped)

    if current is not None:
        segments.append(_finish_segment(current))
    return segments, unclassified


def _finish_segment(current: dict[str, object]) -> SOAPSegment:
    return SOAPSegment(
        text=str(current["text"]),
        category=str(current["cat"]),  # type: ignore[arg-type]
        method=str(current["method"]),
        score=1.0,
    )


def _parse_with_keywords(text: str) -> tuple[list[SOAPSegment], list[str]]:
    """關鍵詞路徑：斷句→計分→argmax（低信度，D-10 回退）。"""
    segments: list[SOAPSegment] = []
    unclassified: list[str] = []
    for raw_sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = raw_sentence.strip()
        if not sentence:
            continue
        category, score = _classify_sentence(sentence)
        segments.append(
            SOAPSegment(
                text=sentence,
                category=category,
                method="keyword",
                score=score,
            )
        )
        if category == "UNKNOWN":
            unclassified.append(sentence)
    return segments, unclassified


def parse_soap_text(text: str) -> SOAPDocument:
    """分段 SOAP 病歷文字（D-10 兩層策略）。

    Args:
        text: 病歷文字內容（已解碼的 str；.txt/.md 讀檔由呼叫端處理）。

    Returns:
        SOAPDocument：sections（S/O/A/P 彙整）、segments（含 UNKNOWN，
        依原文順序）、method（marker/keyword）、confidence（high/low）、
        unclassified（未分類段落）。
    """
    lines = text.splitlines()

    # D-10：任一列命中標記 → 整份走 marker 路徑
    has_marker = any(
        pattern.match(line.strip())
        for line in lines
        for pattern in _MARKER_PATTERNS.values()
    )

    if has_marker:
        segments, unclassified = _parse_with_markers(lines)
        method = "marker"
        confidence = "high"
    else:
        segments, unclassified = _parse_with_keywords(text)
        method = "keyword"
        confidence = "low"

    sections: dict[str, tuple[str, ...]] = {}
    for letter in ("S", "O", "A", "P"):
        texts = tuple(seg.text for seg in segments if seg.category == letter)
        if texts:
            sections[letter] = texts

    return SOAPDocument(
        sections=sections,
        segments=tuple(segments),
        method=method,
        confidence=confidence,
        unclassified=tuple(unclassified),
    )
