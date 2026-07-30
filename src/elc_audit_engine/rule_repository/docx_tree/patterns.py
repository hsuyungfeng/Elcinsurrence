"""繁體中文文件階層規則式（regex）偵測。

真實來源文件中，至少有 2 份文件（2-2-7 手術、牙醫）100% 使用 Word 的
「Normal」樣式、完全沒有自訂標題樣式，因此樣式名稱（style name）不可靠，
必須以文字內容的正規表示式作為主要階層偵測機制。

8 層深度定義（depth 1 為最外層，depth 8 為最內層），已於本次 session
針對真實檔案驗證過。
"""

import re

HEADING_PATTERNS: list[tuple[int, re.Pattern]] = [
    (1, re.compile(r"^第[一二三四五六七八九十百]+部")),
    (2, re.compile(r"^第[一二三四五六七八九十百]+章")),
    (3, re.compile(r"^第[一二三四五六七八九十百]+節")),
    (4, re.compile(r"^第[一二三四五六七八九十百]+項")),
    (5, re.compile(r"^[一二三四五六七八九十]+、")),
    (6, re.compile(r"^\([一二三四五六七八九十]+\)")),
    (6, re.compile(r"^\d+\.")),
    (7, re.compile(r"^\([0-9]+\)")),
    (8, re.compile(r"^[甲乙丙丁戊己庚辛壬癸]、")),
]


def detect_heading_depth(text: str) -> int | None:
    """偵測段落文字所屬的階層深度。

    依 HEADING_PATTERNS 順序（depth 由淺至深）逐一比對，回傳第一個
    命中的深度；若皆未命中，代表此段落為內文（非標題），回傳 None。

    Args:
        text: 段落文字（建議先 strip 過）。

    Returns:
        命中的深度（1-8），或 None（非標題內文）。
    """
    stripped = text.strip()
    for depth, pattern in HEADING_PATTERNS:
        if pattern.match(stripped):
            return depth
    return None
