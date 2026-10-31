"""當月申報預審的自包含 HTML 報告（精簡版）。

設計原則：
- 單一 HTML 檔，CSS 內嵌，無 JavaScript；展開／收合使用原生 `<details>`。
- 亮色／暗色主題以 CSS 變數與 `prefers-color-scheme` 切換；版面響應式。
- **所有動態值一律經 `html.escape`**：規則原文與代碼皆屬外部資料，不信任其內容。
- 只列「有給付規定」且「超過門檻」的醫令，且案件醫療總點數 > 1000 才納入（見
  `monthly_audit.report_view`）。推理樹與 SOAP 清單屬後台比對，不輸出。
- 內含身分證字號、姓名與出生日期（PHI）。報告為比對輔助，不呈現支持／裸奔或給付判定。
"""

from __future__ import annotations

from html import escape

from elc_audit_engine.monthly_audit import (
    STATUS_RESTRICTION,
    STATUS_UNDETERMINED,
    BatchAudit,
    CaseAudit,
    OrderFinding,
    report_view,
)
from elc_audit_engine.rule_repository.icd_titles import get_icd_chinese_title
from elc_audit_engine.monthly_pregen import is_procedure_finding

_SOAP_CSS = """
details.soap-example { margin-top: 8px; }
details.soap-example > summary { cursor: pointer; color: var(--accent); font-size: 13px; font-weight: 600; }
.soap-box { margin-top: 6px; }
textarea.soap-text { width: 100%; min-height: 150px; font: 12px/1.6 monospace; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink); resize: vertical; }
.soap-actions { display: flex; gap: 10px; align-items: center; margin-top: 4px; }
button.btn-copy { background: #10b981; color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
button.btn-soap-modal { background: var(--accent, #0284c7); color: #fff; border: none; border-radius: 4px; padding: 4px 10px; font-size: 12px; font-weight: 600; cursor: pointer; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; }
button.btn-soap-modal:hover { opacity: 0.9; }

"""

_COPY_SCRIPT = """
function copySoap(btn) {
  var ta = btn.closest('.soap-box').querySelector('textarea');
  ta.select();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value).then(function () { btn.textContent = '已複製'; },
      function () { btn.textContent = '請手動複製'; });
  } else {
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    btn.textContent = ok ? '已複製' : '請手動複製';
  }
}

function openSoapModal(orderCode, diagCode, caseId) {
  if (window.parent && window.parent.generateExampleRecord) {
    window.parent.generateExampleRecord(orderCode, diagCode, caseId);
  } else if (typeof generateExampleRecord === 'function') {
    generateExampleRecord(orderCode, diagCode, caseId);
  } else {
    window.parent.postMessage({ type: 'OPEN_EX_MODAL', order_code: orderCode, primary_diagnosis: diagCode, case_id: caseId }, '*');
  }
}
"""

_FLAG_LABELS = {
    "points_over_350": "醫令點數 > 350",
    "drug_over_5": "藥品單價 > 5 元",
    "drug_unpriced": "藥品單價缺漏／0",
}

_SOURCE_LABELS = {
    "payment_text": "給付規定（payment_text）",
    "article_full_text": "條文全文（article_full_text）",
}

_CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #1d2330; --muted: #6b7385; --line: #e3e6ec;
  --amber: #b45309; --amber-bg: #fef3c7; --red: #b91c1c; --red-bg: #fee2e2;
  --slate: #475569; --slate-bg: #e2e8f0; --accent: #2563eb; --quote-bg: #f1f5f9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1419; --card: #171d26; --ink: #e6e9ef; --muted: #9aa3b5; --line: #2a3340;
    --amber: #fbbf24; --amber-bg: #3b2e10; --red: #f87171; --red-bg: #3b1616;
    --slate: #cbd5e1; --slate-bg: #273142; --accent: #60a5fa; --quote-bg: #1e2733;
  }
}
:root[data-theme="dark"] {
  --bg: #0f1419; --card: #171d26; --ink: #e6e9ef; --muted: #9aa3b5; --line: #2a3340;
  --amber: #fbbf24; --amber-bg: #3b2e10; --red: #f87171; --red-bg: #3b1616;
  --slate: #cbd5e1; --slate-bg: #273142; --accent: #60a5fa; --quote-bg: #1e2733;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.6 -apple-system, "Segoe UI", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
}
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 26px; margin: 4px 0 6px; }
h2 { font-size: 18px; margin: 28px 0 10px; }
.hero { padding: 8px 0 4px; }
.batch { color: var(--accent); font-weight: 600; letter-spacing: .04em; }
.note { color: var(--muted); font-size: 13px; margin: 0; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 16px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
.kpi .num { font-size: 24px; font-weight: 700; }
.kpi .lbl { color: var(--muted); font-size: 12px; }
.kpi.amber .num { color: var(--amber); }
.kpi.red .num { color: var(--red); }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); font-size: 13px; vertical-align: top; }
th { color: var(--muted); font-weight: 600; background: var(--quote-bg); }
.wrap { overflow-x: auto; }
details.case { background: var(--card); border: 1px solid var(--line); border-radius: 12px; margin: 10px 0; padding: 0 14px; }
details.case > summary { cursor: pointer; padding: 12px 0; }
.case-head { font-size: 15px; font-weight: 600; }
.meta { color: var(--muted); font-size: 13px; margin: 2px 0 6px; }
.item { border-top: 1px dashed var(--line); padding: 10px 0; }
.item-title { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.item-title strong { font-size: 14px; }
.pill { display: inline-block; border-radius: 999px; padding: 1px 10px; font-size: 12px; background: var(--line); color: var(--ink); }
.amounts { font-size: 14px; font-weight: 600; margin: 6px 0 2px; font-variant-numeric: tabular-nums; }
.rule-blocks { margin-top: 8px; }
.rule-payment { background: var(--quote-bg); border-left: 3px solid var(--accent); border-radius: 4px; padding: 8px 12px; margin: 6px 0; }
.rule-payment-title { font-size: 12px; font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.rule-payment-text { font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
details.rule-fulltext { margin-top: 6px; }
details.rule-fulltext > summary { cursor: pointer; color: var(--accent); font-size: 13px; font-weight: 600; }
.rule-body { margin-top: 8px; }
.rule-src + .rule-src { margin-top: 10px; }
.src { color: var(--muted); font-size: 11px; }
pre.rule-text { white-space: pre-wrap; word-break: break-word; background: var(--quote-bg); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; font: 13px/1.7 "Noto Sans TC", "Microsoft JhengHei", sans-serif; margin: 4px 0 0; }
.btn-soap-gen { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600; cursor: pointer; margin-top: 6px; display: inline-flex; align-items: center; gap: 4px; }
.btn-soap-gen:hover { opacity: 0.9; }
footer { margin-top: 32px; color: var(--muted); font-size: 12px; }
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value))


def _kpi(label: str, value: int, tone: str = "") -> str:
    return f'<div class="kpi {tone}"><div class="num">{value:,}</div><div class="lbl">{_e(label)}</div></div>'


def _counter_table(title: str, rows: dict[str, dict]) -> str:
    head = (
        "<tr><th>" + _e(title) + "</th><th>納入案件</th><th>醫令數</th>"
        "<th>有給付限制條文</th></tr>"
    )
    body = []
    for key, bucket in rows.items():
        status = bucket.get("rule_status", {})
        body.append(
            "<tr>"
            f"<td>{_e(key)}</td>"
            f"<td>{bucket.get('cases_flagged', 0):,}</td>"
            f"<td>{bucket.get('findings', 0):,}</td>"
            f"<td>{status.get(STATUS_RESTRICTION, 0):,}</td>"
            "</tr>"
        )
    if not body:
        body.append('<tr><td colspan="4">無符合條件的案件</td></tr>')
    return f'<div class="wrap"><table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def _amount_text(finding: OrderFinding) -> str:
    """單價 p11／點數 p12／總量 p10；藥品官方支付價若有則明示來源。缺漏欄位不顯示。"""
    parts = []
    if finding.unit_price not in (None, ""):
        parts.append(f"單價: {finding.unit_price} 元")
    if finding.points not in (None, ""):
        parts.append(f"點數: {finding.points} 點")
    if finding.total_qty not in (None, ""):
        parts.append(f"總量: {finding.total_qty}")
    if finding.official_unit_price not in (None, ""):
        label = "官方支付價" if finding.price_source == "official" else "官方支付價（未採用）"
        parts.append(f"{label}: {finding.official_unit_price} 元")
    return " · ".join(parts)


def _rule_fulltext_html(finding: OrderFinding) -> str:
    """📜 規則全文展開區：
    - 給付規定（payment_text）：有內容時以 .rule-payment 直接展開顯示。
    - 條文全文（article_full_text）或完整給付條文總覽：以 <details class="rule-fulltext"> 折疊，按壓 summary 展開全文。
    """
    if not finding.source_texts:
        return ""

    payment_boxes = []
    blocks = []
    for name, text in finding.source_texts:
        label = _SOURCE_LABELS.get(name, name)
        if name == "payment_text":
            payment_boxes.append(
                f'<div class="rule-payment">'
                f'<div class="rule-payment-title">📜 給付規定（payment_text）</div>'
                f'<div class="rule-payment-text">{_e(text)}</div>'
                f'</div>'
            )
        blocks.append(
            f'<div class="rule-src"><div class="src">{_e(label)}</div>'
            f'<pre class="rule-text">{_e(text)}</pre></div>'
        )

    expander = (
        '<details class="rule-fulltext"><summary>📜 檢視完整給付規定條文</summary>'
        f'<div class="rule-body">{"".join(blocks)}</div></details>'
    )
    if payment_boxes:
        return f'<div class="rule-blocks">{"".join(payment_boxes)}{expander}</div>'
    return expander


def _soap_example_html(finding: OrderFinding, case: CaseAudit | None, templates) -> str:
    """處置／手術高價醫令的範例病歷：
    - 若已有快取範本，直接輸出可展開與複製的 <details> 區塊。
    - 若尚未快取，提供按鈕開啟範例病歷彈窗進行即時生成與預覽。
    """
    if case is None or not is_procedure_finding(finding):
        return ""
    order_code = (finding.code or "").strip().upper()
    primary_diag = (case.primary_diagnosis or "").strip().upper()
    key = (order_code, primary_diag)
    soap = templates.get(key) if templates else None

    # 按鈕：開啟彈窗（同步該病人主診斷與醫令代碼）
    c_id = _e(case.case_id or "")
    c_order = _e(order_code)
    c_diag = _e(primary_diag)
    modal_btn = (
        f'<button type="button" class="btn-soap-modal" '
        f'onclick="openSoapModal(\'{c_order}\', \'{c_diag}\', \'{c_id}\')">'
        f'🧾 範例病歷彈窗'
        f'</button>'
    )

    if soap:
        body = "\n".join(f"{k.upper()}: {soap.get(k, '')}" for k in ("s", "o", "a", "p"))
        return (
            '<details class="soap-example"><summary>📝 範例病歷（可複製、可修改）</summary>'
            '<div class="soap-box">'
            f'<textarea class="soap-text" spellcheck="false">{_e(body)}</textarea>'
            '<div class="soap-actions">'
            '<button type="button" class="btn-copy" onclick="copySoap(this)">📋 複製</button>'
            f'{modal_btn}'
            '<span class="src">AI 範例，須醫師審核後方可使用；非病歷事實紀錄。</span></div>'
            "</div></details>"
        )

    # 尚未快取：提供按鈕供醫師點擊生成
    return (
        f'<div style="margin-top:6px;">{modal_btn}</div>'
    )


def _finding_html(finding: OrderFinding, case: CaseAudit | None = None, templates=None) -> str:
    flags = "".join(f'<span class="pill">{_e(_FLAG_LABELS.get(flag, flag))}</span>' for flag in finding.flags)
    title = f"<strong>{_e(finding.code)}</strong> {_e(finding.rule_name or '')} {flags}"
    amounts = _amount_text(finding)
    amount_line = f'<div class="amounts">{_e(amounts)}</div>' if amounts else ""
    return (
        f'<div class="item"><div class="item-title">{title}</div>{amount_line}'
        f"{_rule_fulltext_html(finding)}{_soap_example_html(finding, case, templates)}</div>"
    )


def _case_header(case: CaseAudit) -> str:
    """案件標題：流水號 · 身分證字號 [d3] · 姓名 [d49] · 出生日期 [d11] · 醫療總費用 [d39] 點 · 科別 [d8] · 醫師 [d30] · 就醫日 [d9] · 主診斷 [d19]（含中文名稱，缺漏不顯示）。"""
    diag_text = None
    if case.primary_diagnosis:
        c_title = get_icd_chinese_title(case.primary_diagnosis)
        diag_text = f"{case.primary_diagnosis} ({c_title})" if c_title else case.primary_diagnosis

    segments = [
        ("流水號", case.case_seq),
        ("身分證字號", case.patient_id),
        ("姓名", case.patient_name),
        ("出生日期", case.birth_date),
        ("醫療總費用", f"{case.total_points} 點" if case.total_points else None),
        ("科別", case.department),
        ("醫師", case.doctor_code),
        ("就醫日", case.visit_date),
        ("主診斷", diag_text),
    ]
    parts = []
    for label, value in segments:
        if value:
            parts.append(f"{label}: {value}" if label == "醫療總費用" else f"{label} {value}")
    return f'<span class="case-head">{_e(" · ".join(parts))}</span>'


def _case_html(case: CaseAudit, templates=None) -> str:
    secondary = (
        f'<p class="meta">次診斷：{_e("、".join(case.secondary_diagnoses))}</p>'
        if case.secondary_diagnoses
        else ""
    )
    findings = "".join(_finding_html(f, case, templates) for f in case.findings)
    return f'<details class="case"><summary>{_case_header(case)}</summary>{secondary}{findings}</details>'


def render_batch_report_html(batch: BatchAudit, *, templates=None) -> str:
    """把 BatchAudit 渲染成精簡版自包含 HTML（先套用 report_view 的納入規則）。"""
    view = report_view(batch)
    totals = view.report.get("totals", {})
    status = totals.get("rule_status", {})

    kpis = "".join(
        [
            _kpi("批次案件總數", view.cases_total),
            _kpi("納入報告案件", totals.get("cases_flagged", 0), "amber"),
            _kpi("納入醫令", totals.get("findings", 0)),
            _kpi("有給付限制條文", status.get(STATUS_RESTRICTION, 0), "amber"),
            _kpi("待判定（系統故障）", status.get(STATUS_UNDETERMINED, 0), "red"),
        ]
    )
    cases_html = "".join(_case_html(case, templates) for case in view.cases) or (
        '<p class="meta">本批次無符合條件（醫療總點數 > 1000，且有給付規定超過門檻）的案件。</p>'
    )

    return (
        "<!doctype html>"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>當月申報預審 {_e(view.batch)}</title>"
        f"<style>{_CSS}{_SOAP_CSS}</style></head><body><main>"
        '<header class="hero">'
        f'<div class="batch">{_e(view.batch)}</div>'
        "<h1>當月申報預審報告</h1>"
        '<p class="note">納入條件：醫療總點數 &gt; 1000，且醫令具給付規定並超過門檻（醫令點數 &gt; 350 或藥品單價 &gt; 5）。'
        "規則引文為原文逐字擷取；不產生支持／裸奔或給付判定，最終判定由審查人員作成。</p>"
        "</header>"
        f'<section class="kpis">{kpis}</section>'
        "<h2>科別彙總</h2>"
        f"{_counter_table('科別', view.report.get('by_department', {}))}"
        "<h2>醫師彙總</h2>"
        f"{_counter_table('醫師代號（d30）', view.report.get('by_doctor', {}))}"
        "<h2>案件明細</h2>"
        f"{cases_html}"
        "<footer>本報告由 elc-audit-engine 產生；內含身分證字號、姓名與出生日期（個人資料），請依院內規範保管與傳送。</footer>"
        f"</main><script>{_COPY_SCRIPT}</script></body></html>"
    )


__all__ = ["render_batch_report_html"]
