"""第 2、3 階審查報告統一格式（Plan 18-02；Phase 19 高資訊密度 Case Report）。

比照 MONTHLY-202307 當月申報預審報告（`monthly_report_html.py`）的內容順序，讓第 2 階
（抽審事前預審）與第 3 階（核減事後申復）共用同一套版面與視覺樣式。

版面（Phase 19-01）：
- 頂部：Case Summary 卡片（基本資訊）與 KPI 徽章。
- 核心：SOAP 臨床病歷與佐證庫（影像縮圖畫廊＋檔案清單）並排對照；影像點擊可放大（燈箱）。
- 折疊：給付規定條文與跨院雲端病歷預設收合（<details>），按下才展開。
- 全部為單一自包含 HTML：無外部 CDN、無外部資源；縮圖以 data URI 內嵌。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from html import escape
from typing import Literal

from elc_audit_engine import evidence_vault
from elc_audit_engine.sampling_preview import split_soap

Stage = Literal[2, 3]

_HEADER_FIELDS: tuple[tuple[str, str], ...] = (
    ("流水號", "case_seq"),
    ("病患", "patient_name"),
    ("身分證字號", "record_no"),
    ("就醫日", "visit_date"),
    ("科別", "clinic"),
    ("醫令", "order_code"),
    ("醫令名稱", "order_name"),
    ("總點數", "total_points"),
)

_VAULT_LABELS: tuple[tuple[str, str], ...] = (
    ("audio", "🎙️ 錄音"),
    ("reports", "📄 檢驗檢查報告"),
    ("records", "📝 病歷紀錄"),
)

_SOAP_KEYS = ("s", "o", "a", "p")

_THUMB_MAX_SIDE = 240

_CSS = """
:root { --bg:#f6f7f9; --fg:#1d2330; --card:#fff; --line:#e3e6ec; --muted:#6b7385; --accent:#2563eb; --box:#f1f5f9; --warn:#b45309; --warnbg:#fffbeb; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#0f1419; --fg:#e6e9ef; --card:#171d26; --line:#2a3340; --muted:#9aa3b5; --accent:#60a5fa; --box:#1e2733; --warn:#fbbf24; --warnbg:#2a2110; }
}
:root[data-theme="dark"] { --bg:#0f1419; --fg:#e6e9ef; --card:#171d26; --line:#2a3340; --muted:#9aa3b5; --accent:#60a5fa; --box:#1e2733; --warn:#fbbf24; --warnbg:#2a2110; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.6 -apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif; }
main { max-width:1040px; margin:0 auto; padding:16px 14px 40px; }
header.top { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-end; gap:6px 16px; margin-bottom:8px; }
h1 { font-size:20px; margin:2px 0 0; word-break:break-all; }
.stage { color:var(--accent); font-size:12px; font-weight:600; letter-spacing:.02em; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin:10px 0; min-width:0; }
.card h2 { font-size:14px; margin:0 0 8px; color:var(--accent); }
.summary { display:grid; gap:10px; }
.badges { display:flex; flex-wrap:wrap; gap:8px; }
.badge { display:inline-flex; align-items:baseline; gap:6px; background:var(--box); border:1px solid var(--line); border-radius:999px; padding:3px 12px; font-size:12px; }
.badge .num { font-size:16px; font-weight:700; color:var(--accent); }
.badge.amber .num { color:var(--warn); }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px 14px; }
.label, .muted { color:var(--muted); font-size:12px; }
.warn { background:var(--warnbg); border-color:var(--warn); }
.warn h2 { color:var(--warn); }
.warn ul { margin:0; padding-left:18px; }
.core { display:grid; grid-template-columns:1fr; gap:0 12px; }
@media (min-width:760px) { .core { grid-template-columns:1fr 1fr; } .core .full { grid-column:1 / -1; } }
.soap-grid { display:grid; grid-template-columns:1fr; gap:8px; }
.soap-box { background:var(--box); border-radius:8px; padding:8px 10px; }
.soap-box b { color:var(--accent); }
pre { white-space:pre-wrap; word-break:break-word; margin:6px 0 0; font:inherit; }
button.btn-copy { margin-top:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:6px; padding:4px 10px; cursor:pointer; }
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)); gap:8px; }
.tile { margin:0; background:var(--box); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.tile img { display:block; width:100%; height:96px; object-fit:cover; cursor:zoom-in; }
.tile figcaption, .tile .ph { font-size:11px; padding:4px 6px; word-break:break-all; color:var(--muted); }
.tile .ph { height:96px; display:flex; align-items:center; justify-content:center; text-align:center; }
.chips { list-style:none; margin:6px 0 0; padding:0; display:flex; flex-direction:column; gap:6px; }
.chips li { background:var(--box); border-radius:6px; padding:4px 8px; font-size:13px; word-break:break-all; }
.chips .cat { color:var(--muted); font-size:12px; margin-right:6px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
details.fold { background:var(--card); border:1px solid var(--line); border-radius:12px; margin:10px 0; padding:10px 14px; }
details.fold > summary { cursor:pointer; color:var(--accent); font-weight:600; font-size:14px; }
details.fold .fold-body { margin-top:8px; }
.rule-block { background:var(--box); border-radius:8px; padding:8px 10px; margin-bottom:8px; }
.lb { position:fixed; inset:0; background:rgba(0,0,0,.85); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:16px; z-index:50; cursor:zoom-out; }
.lb[hidden] { display:none; }
.lb img { max-width:96vw; max-height:84vh; border-radius:8px; }
.lb .cap { color:#fff; font-size:13px; margin-top:8px; word-break:break-all; text-align:center; }
footer { margin-top:24px; color:var(--muted); font-size:12px; }
"""

# 腳本：一鍵複製 SOAP、影像燈箱（點擊放大，Esc 或點擊遮罩關閉）。純原生 JS，無外部資源。
_SCRIPT = """
function copySoap(btn){
  var t=btn.closest('.card').querySelector('.soap-grid').innerText;
  if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){btn.textContent='已複製';});}
}
document.addEventListener('click',function(e){
  var lb=document.getElementById('lb');
  if(!lb){return;}
  var tile=e.target.closest?e.target.closest('.tile img'):null;
  if(tile){
    lb.querySelector('img').src=tile.src;
    lb.querySelector('.cap').textContent=tile.alt||'';
    lb.hidden=false;
    return;
  }
  if(e.target.closest&&e.target.closest('#lb')){lb.hidden=true;}
});
document.addEventListener('keydown',function(e){
  var lb=document.getElementById('lb');
  if(lb&&e.key==='Escape'){lb.hidden=true;}
});
"""

# 區塊順序：警示 → 摘要（KPI＋基本資訊）→ 核心對照（SOAP｜佐證庫）→ 檢驗 → 折疊（給付規定、雲端病歷）。
SECTION_ORDER: tuple[str, ...] = ("warning", "summary", "core", "lab", "rule", "cloud")

STAGE_TITLES: dict[Stage, str] = {
    2: "第 2 階｜抽審事前預審",
    3: "第 3 階｜核減事後申復",
}


@dataclass(frozen=True)
class RuleBlock:
    """給付規定／條文依據的一段文字（預設收合於 <details>）。"""

    label: str
    text: str
    is_payment_text: bool = False


@dataclass(frozen=True)
class ReviewCaseView:
    """統一報告的單一案件檢視模型（與 HTML 渲染解耦，便於測試）。

    Attributes:
        case_id: 案件識別（流水號或抽樣案件 ID）。
        stage: 2 或 3，決定標題。
        header: 案件基本資訊（label → value），缺值的欄位不輸出。
        kpis: KPI 數值（label → count），為 0 者不輸出。
        rules: 給付規定與條文依據區塊（收合顯示）。
        soap: {"s","o","a","p"} 或 {"raw": ...}；None 表示整段省略。
        soap_source: "case"（案件本身）／"template*"（範本降級）／"none"。
        vault_key: 佐證庫鍵（身分證-YYMM）；None 表示無佐證庫。
        vault_files: 分類（images/audio/reports/records）→ 檔名清單。
        thumbnails: 影像檔名 → 縮圖 data URI（由路由產生；缺者以佔位方塊顯示）。
        warnings: 閉環產生的警示文字（病歷缺席、範本降級等）。
        labs: 檢驗數據（dict：name／value／unit／date）。
        cloud_text: 健保跨院雲端病歷文字（收合顯示）；None 表示無。
        attachments: 上傳附件檔名。
    """

    case_id: str
    stage: Stage
    header: dict[str, str] = field(default_factory=dict)
    kpis: dict[str, int] = field(default_factory=dict)
    rules: tuple[RuleBlock, ...] = ()
    soap: dict[str, str] | None = None
    soap_source: str = "none"
    vault_key: str | None = None
    vault_files: dict[str, tuple[str, ...]] = field(default_factory=dict)
    thumbnails: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    labs: tuple[dict, ...] = ()
    cloud_text: str | None = None
    attachments: tuple[str, ...] = ()


def make_thumbnail_data_uri(path: str) -> str | None:
    """影像縮圖：長邊 240px 的 JPEG data URI；非影像或無法讀取回 None，不拋例外。"""
    from PIL import Image

    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((_THUMB_MAX_SIDE, _THUMB_MAX_SIDE))
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=80)
    except (OSError, ValueError):
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_review_case_view(
    stage: Stage,
    case_id: str,
    payload: dict,
    *,
    rules: tuple[RuleBlock, ...] = (),
    vault_listing: dict[str, list[dict]] | None = None,
    soap_template: dict | None = None,
    attachments: tuple[str, ...] = (),
    thumbnails: dict[str, str] | None = None,
) -> ReviewCaseView:
    """把案件 payload、規則文字、佐證庫清單組成統一檢視模型。

    SOAP 來源優先序：payload["soap"]（案件本身）→ soap_template（範本降級，{"s","o","a","p"}）→ 無。
    身分證字號一律取 record_no（缺值時退回 patient_id）；vault_key 由身分證字號與就醫日推導（身分證-YYMM）。
    vault_listing 為 evidence_vault 風格的分類 → [{"filename": ...}]。
    警示與檢驗、雲端病歷由 payload 讀取（閉環寫入的 payload["review"]["warnings"]）。
    """
    soap, soap_source = _pick_soap(payload, soap_template)
    vault_files = {
        category: tuple(str(item.get("filename", "")) for item in files)
        for category, files in (vault_listing or {}).items()
        if files
    }
    header = {}
    for label, field_name in _HEADER_FIELDS:
        value = payload.get(field_name)
        if (value is None or value == "") and field_name == "record_no":
            value = payload.get("patient_id")
        if value not in (None, ""):
            header[label] = str(value).strip()
    kpis = {
        "給付規定段落": len(rules),
        "佐證檔案": sum(len(files) for files in vault_files.values()),
        "檢驗筆數": 0,
    }
    review = payload.get("review") or {}
    labs = tuple(
        item for item in (payload.get("lab_results") or [])
        if isinstance(item, dict) and item.get("name")
    )
    kpis["檢驗筆數"] = len(labs)
    kpis = {label: count for label, count in kpis.items() if count}
    id_no = payload.get("record_no") or payload.get("patient_id")
    vault_key = evidence_vault.vault_key_for_case(id_no, payload.get("visit_date"))
    return ReviewCaseView(
        case_id=case_id,
        stage=stage,
        header=header,
        kpis=kpis,
        rules=tuple(rules),
        soap=soap,
        soap_source=soap_source,
        vault_key=vault_key,
        vault_files=vault_files,
        thumbnails=dict(thumbnails or {}),
        warnings=tuple(str(w) for w in (review.get("warnings") or [])),
        labs=labs,
        cloud_text=str(payload.get("cloud_records") or "").strip() or None,
        attachments=tuple(attachments),
    )


def _pick_soap(payload: dict, soap_template: dict | None) -> tuple[dict[str, str] | None, str]:
    """案件 SOAP 優先，其次範本；皆無回 (None, "none")。無標記的原文保留在 raw 鍵。"""
    text = str(payload.get("soap") or "")
    if text.strip():
        return (split_soap(text) or {"raw": text.strip()}), "case"
    if soap_template:
        soap = {key: str(soap_template.get(key) or "") for key in _SOAP_KEYS}
        if any(soap.values()):
            return soap, "template"
    return None, "none"


def _section_warning(view: ReviewCaseView) -> str:
    if not view.warnings:
        return ""
    items = "".join(f"<li>{escape(text)}</li>" for text in view.warnings)
    return f'<section class="card warn"><h2>⚠ 審查警示</h2><ul>{items}</ul></section>'


def _section_summary(view: ReviewCaseView) -> str:
    """Case Summary：KPI 徽章＋基本資訊。兩者皆空時整段省略。"""
    if not view.kpis and not view.header:
        return ""
    badges = "".join(
        f'<span class="badge{" amber" if label == "給付規定段落" else ""}">'
        f'<span class="num">{int(count):,}</span>{escape(label)}</span>'
        for label, count in view.kpis.items()
    )
    cells = "".join(
        f'<div><div class="label">{escape(label)}</div><div>{escape(value)}</div></div>'
        for label, value in view.header.items()
    )
    parts = []
    if badges:
        parts.append(f'<div class="badges">{badges}</div>')
    if cells:
        parts.append(f'<div class="grid">{cells}</div>')
    return f'<section class="card summary"><h2>👤 案件摘要</h2>{"".join(parts)}</section>'


def _section_soap_panel(view: ReviewCaseView) -> str:
    if view.soap is None:
        return ""
    if "raw" in view.soap:
        boxes = f'<div class="soap-box"><pre>{escape(view.soap["raw"])}</pre></div>'
    else:
        boxes = "".join(
            f'<div class="soap-box"><b>{key.upper()}</b><pre>{escape(view.soap.get(key, ""))}</pre></div>'
            for key in _SOAP_KEYS
            if view.soap.get(key)
        )
    caption = (
        "範本降級（非本案病歷），須醫師審核後方可使用。"
        if view.soap_source.startswith("template")
        else "取自本案病歷。"
    )
    return (
        '<section class="card"><h2>📝 SOAP 臨床病歷</h2>'
        f'<div class="soap-grid">{boxes}</div>'
        f'<button type="button" class="btn-copy" onclick="copySoap(this)">📋 複製 SOAP</button>'
        f'<p class="muted">{escape(caption)}</p></section>'
    )


def _gallery_html(view: ReviewCaseView) -> str:
    """影像畫廊：有縮圖者可點擊放大；無縮圖者以檔名佔位，不可放大。"""
    names = view.vault_files.get("images", ())
    if not names:
        return ""
    tiles = []
    for name in names:
        uri = view.thumbnails.get(name)
        if uri:
            tiles.append(
                f'<figure class="tile"><img src="{escape(uri, quote=True)}" alt="{escape(name, quote=True)}">'
                f"<figcaption>{escape(name)}</figcaption></figure>"
            )
        else:
            tiles.append(f'<figure class="tile"><div class="ph">{escape(name)}</div></figure>')
    return f'<div class="gallery">{"".join(tiles)}</div>'


def _section_vault_panel(view: ReviewCaseView) -> str:
    has_vault = bool(view.vault_key) and any(view.vault_files.values())
    if not has_vault and not view.attachments:
        return ""
    gallery = _gallery_html(view)
    chips = []
    for cat, label in _VAULT_LABELS:
        for name in view.vault_files.get(cat, ()):
            chips.append(f'<li><span class="cat">{escape(label)}</span>{escape(name)}</li>')
    for name in view.attachments:
        chips.append(f'<li><span class="cat">📎 附件</span>{escape(name)}</li>')
    chip_list = f'<ul class="chips">{"".join(chips)}</ul>' if chips else ""
    title = f"📁 佐證庫（{escape(view.vault_key)}）" if has_vault else "📎 上傳附件"
    return (
        f'<section class="card"><h2>{title}</h2>{gallery}{chip_list}'
        '<p class="muted">影像點擊可放大；檔案內容須經佐證庫／附件下載端點取得（需 API Key）。</p></section>'
    )


def _section_core(view: ReviewCaseView) -> str:
    """核心對照區：SOAP 與佐證庫並排；缺一邊時另一邊獨占整列。"""
    soap = _section_soap_panel(view)
    vault = _section_vault_panel(view)
    if not soap and not vault:
        return ""
    if soap and vault:
        return f'<div class="core">{soap}{vault}</div>'
    return f'<div class="core"><div class="full">{soap}{vault}</div></div>'


def _section_lab(view: ReviewCaseView) -> str:
    if not view.labs:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('value', '')))} {escape(str(item.get('unit') or ''))}</td>"
        f"<td>{escape(str(item.get('date') or ''))}</td>"
        "</tr>"
        for item in view.labs
    )
    return (
        '<section class="card"><h2>🧪 檢驗數據</h2><table>'
        "<thead><tr><th>項目</th><th>數值</th><th>日期</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _section_rule(view: ReviewCaseView) -> str:
    """給付規定條文：預設收合，按下才展開。"""
    if not view.rules:
        return ""
    blocks = "".join(
        f'<div class="rule-block"><div class="label">{escape(block.label)}</div>'
        f"<pre>{escape(block.text)}</pre></div>"
        for block in view.rules
    )
    return (
        '<details class="fold"><summary>📜 給付規定條文（點擊展開）</summary>'
        f'<div class="fold-body">{blocks}</div></details>'
    )


def _section_cloud(view: ReviewCaseView) -> str:
    """健保跨院雲端病歷：預設收合，按下才展開。"""
    if not view.cloud_text:
        return ""
    return (
        '<details class="fold"><summary>☁️ 健保跨院雲端病歷（點擊展開）</summary>'
        f'<div class="fold-body"><pre>{escape(view.cloud_text)}</pre></div></details>'
    )


_LIGHTBOX = (
    '<div id="lb" class="lb" hidden><img alt=""><div class="cap"></div></div>'
)


def render_unified_review_html(view: ReviewCaseView) -> str:
    """回傳自包含 HTML（已 html.escape、無外部資源），依 SECTION_ORDER 輸出。

    空區塊整段省略。核心區 SOAP 與佐證庫並排；給付規定與雲端病歷預設收合。
    頁尾沿用 PHI 警語（含身分證字號、姓名、出生日期）。
    第 2 階預審卡片（preview-html）與第 3 階申復草稿共用本函式輸出。
    """
    builders = {
        "warning": _section_warning,
        "summary": _section_summary,
        "core": _section_core,
        "lab": _section_lab,
        "rule": _section_rule,
        "cloud": _section_cloud,
    }
    body = "".join(builders[name](view) for name in SECTION_ORDER)
    lightbox = _LIGHTBOX if view.vault_files.get("images") else ""
    title = STAGE_TITLES[view.stage]
    return (
        "<!doctype html>"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} {escape(view.case_id)}</title>"
        f"<style>{_CSS}</style></head><body><main>"
        f'<header class="top"><div><div class="stage">{escape(title)}</div>'
        f"<h1>{escape(view.case_id)}</h1></div></header>"
        f"{body}"
        f"{lightbox}"
        '<footer>本報告內含個人資料，請依院內規範保管與傳送。'
        "比對輔助；不產生支持／裸奔或給付判定，最終判定由審查人員作成。</footer>"
        f"<script>{_SCRIPT}</script></main></body></html>"
    )


__all__ = [
    "SECTION_ORDER",
    "STAGE_TITLES",
    "ReviewCaseView",
    "RuleBlock",
    "Stage",
    "build_review_case_view",
    "make_thumbnail_data_uri",
    "render_unified_review_html",
]
