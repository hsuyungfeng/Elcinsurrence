"""第 2、3 階審查報告統一格式（Plan 18-02 骨架）。

比照 MONTHLY-202307 當月申報預審報告（`monthly_report_html.py`）的版面，讓第 2 階
（抽審事前預審）與第 3 階（核減事後申復）共用同一套區塊順序與視覺樣式。

骨架狀態：
- 型別、常數與公開函式簽章已定義；實作函式以 NotImplementedError 佔位。
- 對應測試：tests/test_unified_review_report.py（strict xfail，實作後須移除標記）。
"""

from __future__ import annotations

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
    ("images", "🖼️ 相片"),
    ("audio", "🎙️ 錄音"),
    ("reports", "📄 檢驗檢查報告"),
    ("records", "📝 病歷紀錄"),
)

_SOAP_KEYS = ("s", "o", "a", "p")

_CSS = """
:root { --bg:#f6f7f9; --fg:#1d2330; --card:#fff; --line:#e3e6ec; --muted:#6b7385; --accent:#2563eb; --box:#f1f5f9; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#0f1419; --fg:#e6e9ef; --card:#171d26; --line:#2a3340; --muted:#9aa3b5; --accent:#60a5fa; --box:#1e2733; }
}
:root[data-theme="dark"] { --bg:#0f1419; --fg:#e6e9ef; --card:#171d26; --line:#2a3340; --muted:#9aa3b5; --accent:#60a5fa; --box:#1e2733; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.6 -apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",sans-serif; }
main { max-width:900px; margin:0 auto; padding:20px 14px 40px; }
h1 { font-size:20px; margin:4px 0 8px; }
.stage { color:var(--accent); font-size:12px; font-weight:600; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin:12px 0; }
.card h2 { font-size:15px; margin:0 0 8px; color:var(--accent); }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; margin:12px 0; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px; }
.kpi .num { font-size:20px; font-weight:700; }
.kpi .lbl, .label, .muted { color:var(--muted); font-size:12px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:8px 14px; }
.rule-payment { background:var(--box); border-radius:8px; padding:8px 10px; margin-bottom:8px; }
details summary { cursor:pointer; color:var(--accent); }
pre { white-space:pre-wrap; word-break:break-word; margin:6px 0 0; font:inherit; }
.soap-grid { display:grid; grid-template-columns:1fr; gap:10px; }
@media (min-width:640px) { .soap-grid { grid-template-columns:1fr 1fr; } }
.soap-box { background:var(--box); border-radius:8px; padding:8px 10px; }
.soap-box b { color:var(--accent); }
button.btn-copy { margin-top:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:6px; padding:4px 10px; cursor:pointer; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
footer { margin-top:24px; color:var(--muted); font-size:12px; }
"""

_COPY_SCRIPT = (
    "function copySoap(btn){"
    "var t=btn.closest('.card').querySelector('.soap-grid').innerText;"
    "if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){btn.textContent='已複製';});}"
    "}"
)

# 區塊呈現順序（比照 MONTHLY-202307）：KPI → 案件基本資訊 → 給付規定 → SOAP → 佐證庫清單。
SECTION_ORDER: tuple[str, ...] = ("warning", "kpi", "header", "rule", "soap", "lab", "cloud", "vault")

STAGE_TITLES: dict[Stage, str] = {
    2: "第 2 階｜抽審事前預審",
    3: "第 3 階｜核減事後申復",
}


@dataclass(frozen=True)
class RuleBlock:
    """給付規定／條文依據的一段文字。

    is_payment_text=True 時直接展開（對應 payment_text）；否則以 <details> 折疊。
    """

    label: str
    text: str
    is_payment_text: bool = False


@dataclass(frozen=True)
class ReviewCaseView:
    """統一報告的單一案件檢視模型（與 HTML 渲染解耦，便於測試）。

    Attributes:
        case_id: 案件識別（流水號或抽樣案件 ID）。
        stage: 2 或 3，決定標題與 KPI 集合。
        header: 案件基本資訊（label → value），缺值的欄位不輸出。
        kpis: KPI 數值（label → count）。
        rules: 給付規定與條文依據區塊。
        soap: {"s","o","a","p"}；None 表示整段省略。
        soap_source: "case"（案件本身）／"template"（範本降級）／"none"。
            與 sampling_closed_loop 的 template_specific／template_general 皆以 "template" 前綴判斷。
        vault_key: 佐證庫鍵（身分證-YYMM）；None 表示無佐證庫。
        vault_files: 分類（images/audio/reports/records）→ 檔名清單。
        warnings: 閉環產生的警示文字（病歷缺席、範本降級等）。
        labs: 檢驗數據（dict：name／value／unit／date）。
        cloud_text: 健保跨院雲端病歷文字；None 表示無。
        attachments: 上傳附件檔名（影像、報告等）。
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
    warnings: tuple[str, ...] = ()
    labs: tuple[dict, ...] = ()
    cloud_text: str | None = None
    attachments: tuple[str, ...] = ()


def build_review_case_view(
    stage: Stage,
    case_id: str,
    payload: dict,
    *,
    rules: tuple[RuleBlock, ...] = (),
    vault_listing: dict[str, list[dict]] | None = None,
    soap_template: dict | None = None,
    attachments: tuple[str, ...] = (),
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
    }
    kpis = {label: count for label, count in kpis.items() if count}
    id_no = payload.get("record_no") or payload.get("patient_id")
    vault_key = evidence_vault.vault_key_for_case(id_no, payload.get("visit_date"))
    review = payload.get("review") or {}
    labs = tuple(
        item for item in (payload.get("lab_results") or [])
        if isinstance(item, dict) and item.get("name")
    )
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


def _section_kpi(view: ReviewCaseView) -> str:
    if not view.kpis:
        return ""
    items = "".join(
        f'<div class="kpi"><div class="num">{int(num):,}</div><div class="lbl">{escape(str(label))}</div></div>'
        for label, num in view.kpis.items()
    )
    return f'<section class="kpis">{items}</section>'


def _section_header(view: ReviewCaseView) -> str:
    if not view.header:
        return ""
    cells = "".join(
        f'<div><div class="label">{escape(label)}</div><div>{escape(value)}</div></div>'
        for label, value in view.header.items()
    )
    return f'<section class="card"><h2>👤 案件基本資訊</h2><div class="grid">{cells}</div></section>'


def _section_rule(view: ReviewCaseView) -> str:
    if not view.rules:
        return ""
    parts = []
    for block in view.rules:
        if block.is_payment_text:
            parts.append(
                f'<div class="rule-payment"><div class="label">{escape(block.label)}</div>'
                f"<div>{escape(block.text)}</div></div>"
            )
        else:
            parts.append(
                f'<details class="rule-fulltext"><summary>{escape(block.label)}</summary>'
                f"<pre>{escape(block.text)}</pre></details>"
            )
    return f'<section class="card"><h2>📜 給付規定與條文依據</h2>{"".join(parts)}</section>'


def _section_soap(view: ReviewCaseView) -> str:
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
    if view.soap_source.startswith("template"):
        caption = "範本降級（非本案病歷），須醫師審核後方可使用。"
    else:
        caption = "取自本案病歷。"
    return (
        '<section class="card"><h2>📝 SOAP 病歷</h2>'
        f'<div class="soap-grid">{boxes}</div>'
        f'<button type="button" class="btn-copy" onclick="copySoap(this)">📋 複製 SOAP</button>'
        f'<p class="muted">{escape(caption)}</p></section>'
    )


def _section_vault(view: ReviewCaseView) -> str:
    has_vault = bool(view.vault_key) and any(view.vault_files.values())
    if not has_vault and not view.attachments:
        return ""
    rows = ""
    if has_vault:
        rows = "".join(
            f"<tr><td>{escape(label)}</td><td>{escape(', '.join(view.vault_files.get(cat, ())) or '—')}</td></tr>"
            for cat, label in _VAULT_LABELS
        )
    if view.attachments:
        rows += f"<tr><td>📎 上傳附件</td><td>{escape(', '.join(view.attachments))}</td></tr>"
    title = f"📁 佐證庫（{escape(view.vault_key)}）" if has_vault else "📎 上傳附件"
    return (
        f'<section class="card"><h2>{title}</h2>'
        f"<table><thead><tr><th>分類</th><th>檔名</th></tr></thead><tbody>{rows}</tbody></table>"
        '<p class="muted">檔案內容須經佐證庫／附件下載端點取得（需 API Key）。</p></section>'
    )


def _section_warning(view: ReviewCaseView) -> str:
    if not view.warnings:
        return ""
    items = "".join(f"<li>{escape(text)}</li>" for text in view.warnings)
    return f'<section class="card warn"><h2>⚠ 審查警示</h2><ul>{items}</ul></section>'


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


def _section_cloud(view: ReviewCaseView) -> str:
    if not view.cloud_text:
        return ""
    return f'<section class="card"><h2>☁️ 健保雲端跨院紀錄</h2><pre>{escape(view.cloud_text)}</pre></section>'


def render_unified_review_html(view: ReviewCaseView) -> str:
    """回傳自包含 HTML（已 html.escape、無外部資源），依 SECTION_ORDER 輸出。

    空區塊整段省略（與 sampling_preview 一致）。SOAP 區塊需提供一鍵複製；
    頁尾沿用 PHI 警語（含身分證字號、姓名、出生日期）。

    第 2 階預審卡片（preview-html）與第 3 階申復草稿共用本函式輸出。
    """
    builders = {
        "warning": _section_warning,
        "kpi": _section_kpi,
        "header": _section_header,
        "rule": _section_rule,
        "soap": _section_soap,
        "lab": _section_lab,
        "cloud": _section_cloud,
        "vault": _section_vault,
    }
    body = "".join(builders[name](view) for name in SECTION_ORDER)
    title = STAGE_TITLES[view.stage]
    return (
        "<!doctype html>"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} {escape(view.case_id)}</title>"
        f"<style>{_CSS}</style></head><body><main>"
        f'<header><div class="stage">{escape(title)}</div>'
        f"<h1>{escape(view.case_id)}</h1></header>"
        f"{body}"
        '<footer>本報告內含個人資料，請依院內規範保管與傳送。'
        "比對輔助；不產生支持／裸奔或給付判定，最終判定由審查人員作成。</footer>"
        f"<script>{_COPY_SCRIPT}</script></main></body></html>"
    )


__all__ = [
    "SECTION_ORDER",
    "STAGE_TITLES",
    "ReviewCaseView",
    "RuleBlock",
    "Stage",
    "build_review_case_view",
    "render_unified_review_html",
]
