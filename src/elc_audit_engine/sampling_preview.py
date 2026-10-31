"""抽樣案件多源證據的視覺化預覽卡片（Plan 16-02）。

- 單一 HTML 檔，CSS 內嵌，無 JavaScript、無外部資源，可直接於 iframe 或獨立分頁開啟。
- 所有動態值經 `html.escape`（病歷、檢驗、雲端紀錄皆屬外部資料）。
- 無資料的區塊整段不輸出（SOAP 缺欄、無檢驗、無雲端紀錄、無附件皆不顯示空框）。
- 附件僅列出檔名與格式；影像須經附件下載端點取得（需 API Key），不以網址嵌入。
- 預覽為比對輔助，不呈現支持／裸奔或給付判定。
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

_SOAP_MARK_RE = re.compile(r"^\s*([SOAP])\s*[:：]\s*", re.IGNORECASE | re.MULTILINE)

_CSS = """
body { margin: 0; background: #f6f7f9; color: #1d2330;
  font: 14px/1.6 -apple-system, "Segoe UI", "Noto Sans TC", "Microsoft JhengHei", sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 20px 14px 40px; }
.card { background: #fff; border: 1px solid #e3e6ec; border-radius: 12px; padding: 14px 16px; margin: 12px 0; }
.card h2 { font-size: 15px; margin: 0 0 8px; color: #2563eb; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px 14px; }
.label { color: #6b7385; font-size: 12px; }
.soap-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
@media (min-width: 640px) { .soap-grid { grid-template-columns: 1fr 1fr; } }
.soap-box { background: #f1f5f9; border-radius: 8px; padding: 8px 10px; }
.soap-box b { color: #2563eb; }
pre { white-space: pre-wrap; word-break: break-word; margin: 0; font: inherit; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e3e6ec; }
th { color: #6b7385; font-weight: 600; }
.muted { color: #6b7385; font-size: 12px; }
@media (prefers-color-scheme: dark) {
  body { background: #0f1419; color: #e6e9ef; }
  .card { background: #171d26; border-color: #2a3340; }
  .soap-box, th { background: #1e2733; }
  .label, .muted { color: #9aa3b5; }
}
"""


def split_soap(text: str | None) -> dict[str, str]:
    """依行首 S:/O:/A:/P: 標記切分 SOAP；無任何標記回空 dict。同一欄多段時以換行合併。"""
    source = text or ""
    matches = list(_SOAP_MARK_RE.finditer(source))
    sections: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[match.end():end].strip()
        if body:
            sections.setdefault(match.group(1).lower(), []).append(body)
    return {key: "\n".join(parts) for key, parts in sections.items()}


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def _kb(size: Any) -> str:
    try:
        return f"{int(size) / 1024:.1f} KB"
    except (TypeError, ValueError):
        return ""


def _patient_card(payload: dict) -> str:
    fields = [
        ("就醫日", payload.get("visit_date")),
        ("科別", payload.get("clinic")),
        ("病歷號", payload.get("record_no")),
        ("病患", payload.get("patient_name")),
        ("醫令", " ".join(p for p in (payload.get("order_code"), payload.get("order_name")) if p) or None),
        ("流水號", payload.get("case_seq")),
    ]
    cells = "".join(
        f'<div><div class="label">{_e(label)}</div><div>{_e(value)}</div></div>'
        for label, value in fields
        if value
    )
    return f'<section class="card"><h2>👤 病患基本資料</h2><div class="grid">{cells}</div></section>' if cells else ""


def _soap_card(payload: dict) -> str:
    raw = payload.get("soap") or ""
    if not raw.strip():
        return ""
    sections = split_soap(raw)
    if sections:
        boxes = "".join(
            f'<div class="soap-box"><b>{key.upper()}</b><pre>{_e(sections[key])}</pre></div>'
            for key in ("s", "o", "a", "p")
            if key in sections
        )
    else:
        boxes = f'<div class="soap-box"><pre>{_e(raw)}</pre></div>'
    return f'<section class="card"><h2>📝 門診 SOAP 病歷</h2><div class="soap-grid">{boxes}</div></section>'


def _lab_card(payload: dict) -> str:
    labs = payload.get("lab_results") or []
    rows = "".join(
        "<tr>"
        f"<td>{_e(item.get('name'))}</td>"
        f"<td>{_e(item.get('value'))} {_e(item.get('unit') or '')}</td>"
        f"<td>{_e(item.get('date') or '')}</td>"
        "</tr>"
        for item in labs
        if isinstance(item, dict) and item.get("name")
    )
    if not rows:
        return ""
    return (
        '<section class="card"><h2>🧪 檢驗數據</h2><table>'
        "<thead><tr><th>項目</th><th>數值</th><th>日期</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _cloud_card(payload: dict) -> str:
    text = (payload.get("cloud_records") or "").strip()
    if not text:
        return ""
    return f'<section class="card"><h2>☁️ 健保雲端跨院紀錄</h2><pre>{_e(text)}</pre></section>'


def _attachment_card(attachments: list[dict]) -> str:
    if not attachments:
        return ""
    items = "".join(
        f"<tr><td>{_e(item.get('filename'))}</td><td>{_e(item.get('mime_type'))}</td><td>{_e(_kb(item.get('file_size')))}</td></tr>"
        for item in attachments
    )
    return (
        '<section class="card"><h2>🖼️ 影像佐證與報告</h2>'
        f'<table><thead><tr><th>檔名</th><th>格式</th><th>大小</th></tr></thead><tbody>{items}</tbody></table>'
        '<p class="muted">影像內容須經附件下載端點取得（需 API Key）。</p></section>'
    )


def render_sampling_preview_html(case_id: str, payload: dict, attachments: list[dict] | None = None) -> str:
    """回傳單一抽樣案件的完整預覽 HTML（自包含、已轉義）。"""
    sections = "".join([
        _patient_card(payload),
        _soap_card(payload),
        _lab_card(payload),
        _cloud_card(payload),
        _attachment_card(attachments or []),
    ])
    return (
        "<!doctype html>"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>抽樣預審 {_e(case_id)}</title><style>{_CSS}</style></head><body><main>"
        f'<header><div class="label">抽樣預審案件</div><h1 style="font-size:20px;margin:2px 0 8px;">{_e(case_id)}</h1></header>'
        f"{sections}"
        '<p class="muted">比對輔助預覽；不產生支持／裸奔或給付判定，最終判定由審查人員作成。</p>'
        "</main></body></html>"
    )


__all__ = ["render_sampling_preview_html", "split_soap"]
