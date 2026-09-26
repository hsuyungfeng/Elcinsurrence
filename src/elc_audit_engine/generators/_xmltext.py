"""產出 XML／ODT 文字的共用防呆（review A-WR-07、A-WR-10）。

- `xml_safe`：移除 XML 1.0 不允許的控制字元。ElementTree 會轉義 `<>&`，
  但不會擋 \\x00-\\x08、\\x0b、\\x0c、\\x0e-\\x1f；核減 CSV（Big5／Excel 匯出）
  夾帶這些字元時，申復 XML 會被健保署拒收、ODT 會讓 soffice 失敗。
- `set_odf_paragraph_text`：以 `text:line-break` 表示換行。ODF 會把
  `text:p` 內的 `\\n` 壓成空白，多段文字（如申復理由各段）會黏成一段。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_XML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_LINE_BREAK = f"{{{_TEXT_NS}}}line-break"


def xml_safe(value: str) -> str:
    """移除 XML 1.0 非法控制字元（保留 \\t \\n \\r）。"""
    return _XML_ILLEGAL_RE.sub("", value)


def has_xml_illegal(value: str) -> bool:
    return bool(_XML_ILLEGAL_RE.search(value))


def set_odf_paragraph_text(p: ET.Element, value: str) -> None:
    """清空 `text:p` 後寫入文字；換行轉成 `text:line-break` 子元素。"""
    for child in list(p):
        p.remove(child)
    lines = xml_safe(value).replace("\r\n", "\n").split("\n")
    p.text = lines[0]
    for line in lines[1:]:
        br = ET.SubElement(p, _LINE_BREAK)
        br.tail = line
