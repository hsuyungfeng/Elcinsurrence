"""當月申報預審下載包（Phase 29）：報告＋每案病歷文件，打包為 ZIP 供使用者下載到本機。

規則：
- 有 SOAP（語音比對結果）→ 貼上該案 SOAP。
- 無 SOAP → 依申報醫令使用「已快取」的範例病歷（只讀快取，不在下載時呼叫 LLM）。
  無快取者明確標示「尚未預生成」，絕不捏造內容（AGENTs.md §2.1）。
- 院所資料必須完整且已由使用者確認（首次下載時填表）；否則拒絕產生（見 FacilityProfileError）。
- 下載包含病患識別資訊（與報告相同），故只供已認證呼叫者取得；日誌不記錄內容。
"""

from __future__ import annotations

import html
import io
import zipfile
from dataclasses import dataclass
from typing import Any

from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.monthly_audit import audit_batch
from elc_audit_engine.monthly_pregen import is_pregen_target, load_templates
from elc_audit_engine.monthly_report_html import render_batch_report_html

# 下載前必須具備的院所欄位（與 POST /api/facility 的 web 必填欄位一致）。
REQUIRED_PROFILE_FIELDS = ("code", "name", "email")
PROFILE_CONFIRMED_KEY = "profile_confirmed"


class FacilityProfileError(Exception):
    """院所資料不完整或尚未由使用者確認（屬呼叫端需補填的前置條件，回 412）。"""

    def __init__(self, missing: list[str], confirmed: bool):
        self.missing = missing
        self.confirmed = confirmed
        super().__init__("院所資料尚未完成或未確認，請先填寫診所表單")


@dataclass(frozen=True)
class ProfileStatus:
    complete: bool
    confirmed: bool
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.complete and self.confirmed


def _is_placeholder_name(name: str, code: str) -> bool:
    """`save_facility_config` 僅有代碼時會自動補「醫療院所 (代碼)」；此為佔位，視同未填。"""
    return name == f"醫療院所 ({code})"


def profile_status(cfg: dict | None) -> ProfileStatus:
    """判斷院所資料是否可用於下載：必填欄位齊全（名稱不得為自動佔位），且 `profile_confirmed` 為 True。"""
    cfg = cfg or {}
    code = str(cfg.get("code") or "").strip()
    name = str(cfg.get("name") or "").strip()
    missing: list[str] = []
    for key in REQUIRED_PROFILE_FIELDS:
        value = str(cfg.get(key) or "").strip()
        if not value or (key == "name" and _is_placeholder_name(name, code)):
            missing.append(key)
    confirmed = cfg.get(PROFILE_CONFIRMED_KEY) is True
    return ProfileStatus(complete=not missing, confirmed=confirmed, missing=tuple(missing))


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _soap_from_payload(payload: dict) -> dict[str, str] | None:
    """回傳案件 SOAP（s/o/a/p 皆非空才算有 SOAP）；否則 None。"""
    soap = payload.get("soap")
    if isinstance(soap, dict):
        parts = {k: str(soap.get(k) or "").strip() for k in ("s", "o", "a", "p")}
        if any(parts.values()):
            return parts
    text = str(payload.get("soap_text") or "").strip()
    if text:
        return {"text": text}
    return None


def _soap_block(soap: dict[str, str]) -> str:
    if "text" in soap:
        return f'<section class="soap"><h3>門診 SOAP（語音比對）</h3><pre>{_e(soap["text"])}</pre></section>'
    rows = "".join(
        f"<tr><th>{label}</th><td>{_e(soap.get(key))}</td></tr>"
        for key, label in (("s", "S"), ("o", "O"), ("a", "A"), ("p", "P"))
    )
    return f'<section class="soap"><h3>門診 SOAP（語音比對）</h3><table>{rows}</table></section>'


def _template_block(order_code: str, dx: str, soap: dict[str, str]) -> str:
    rows = "".join(
        f"<tr><th>{label}</th><td>{_e(soap.get(key))}</td></tr>"
        for key, label in (("s", "S"), ("o", "O"), ("a", "A"), ("p", "P"))
    )
    return (
        '<section class="template">'
        f"<h3>範例病歷（依申報醫令預生成：{_e(order_code)}／{_e(dx)}）</h3>"
        '<p class="warn">非實際病歷，僅供參考；須醫師審核後才可使用。</p>'
        f"<table>{rows}</table></section>"
    )


def _case_document(store: CaseStore, case, record_payload: dict, templates: dict) -> str:
    """單案病歷文件（HTML）。SOAP 優先；否則依申報醫令取快取範本；皆無則明確標示。"""
    soap = _soap_from_payload(record_payload)
    blocks: list[str] = []
    if soap is not None:
        blocks.append(_soap_block(soap))
    else:
        procedure = [f for f in case.findings if is_pregen_target(f)]
        if not procedure:
            blocks.append(
                '<section class="missing"><h3>無 SOAP</h3>'
                "<p>本案無處置／手術高價醫令，故不產生範例病歷。</p></section>"
            )
        for finding in procedure:
            key = (finding.code.strip().upper(), (case.primary_diagnosis or "").strip().upper())
            cached = templates.get(key)
            if cached is not None:
                blocks.append(_template_block(finding.code, case.primary_diagnosis or "", cached))
            else:
                blocks.append(
                    '<section class="missing"><h3>尚未預生成</h3>'
                    f"<p>醫令 {_e(finding.code)} 尚無範例病歷快取；請先於批次頁按「先預生成再下載」。</p></section>"
                )

    orders = "".join(
        f"<tr><td>{_e(f.code)}</td><td>{_e(f.rule_name or '')}</td><td>{_e(f.points or '')}</td></tr>"
        for f in case.findings
    )
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        f"<title>病歷 {_e(case.case_id)}</title>"
        "<style>body{font-family:sans-serif;margin:24px;color:#111}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px;text-align:left;vertical-align:top}"
        "th{width:70px;background:#f3f4f6}.warn{color:#b45309}pre{white-space:pre-wrap}</style></head><body>"
        f"<h1>病歷文件 · {_e(case.case_id)}</h1>"
        "<p class=\"warn\">本文件含病患個資，請依個資規範保管。</p>"
        "<table>"
        f"<tr><th>流水號</th><td>{_e(case.case_seq)}</td></tr>"
        f"<tr><th>病歷號</th><td>{_e(record_payload.get('record_no') or case.patient_id)}</td></tr>"
        f"<tr><th>姓名</th><td>{_e(case.patient_name)}</td></tr>"
        f"<tr><th>就醫日</th><td>{_e(case.visit_date)}</td></tr>"
        f"<tr><th>科別</th><td>{_e(case.department)}</td></tr>"
        f"<tr><th>主診斷</th><td>{_e(case.primary_diagnosis)}</td></tr>"
        "</table>"
        "<h3>申報醫令</h3>"
        f"<table><tr><th>代碼</th><th>名稱</th><th>點數</th></tr>{orders}</table>"
        + "".join(blocks)
        + "</body></html>"
    )


def _facility_header_html(facility: dict) -> str:
    return (
        f"<p>院所：{_e(facility.get('name'))}（機構代碼 {_e(facility.get('code'))}）"
        f"　負責醫師：{_e(facility.get('physician_name') or '—')}</p>"
    )


def build_batch_package(
    store: CaseStore,
    batch_id: str,
    *,
    facility: dict,
    rules_db_path: str | None = None,
) -> bytes:
    """組出批次下載包（ZIP bytes）。院所資料不完整／未確認時拋出 FacilityProfileError。

    ZIP 內容：
    - `報告.html`：當月申報視覺化審核卡片（與批次頁「開啟視覺化審核卡片」相同）。
    - `病歷/<case_id>.html`：每案病歷文件（SOAP 或快取範本或「尚未預生成」標示）。
    """
    status = profile_status(facility)
    if not status.ready:
        raise FacilityProfileError(list(status.missing), status.confirmed)

    audit = audit_batch(store, batch_id, rules_db_path=rules_db_path, persist=False)
    # 範本以「全部處置醫令」查詢（不套用報告的給付規定篩選）：無規則的處置醫令仍可能有已快取範本。
    templates = load_templates(store, audit)

    report_html = render_batch_report_html(audit, templates=templates)
    report_html = report_html.replace("<body>", "<body>" + _facility_header_html(facility), 1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("報告.html", report_html.encode("utf-8"))
        for case in audit.cases:
            record = store.get(case.case_id)
            payload = dict(record.payload or {}) if record is not None else {}
            doc = _case_document(store, case, payload, templates)
            zf.writestr(f"病歷/{case.case_id}.html", doc.encode("utf-8"))
    return buf.getvalue()


__all__ = [
    "FacilityProfileError",
    "PROFILE_CONFIRMED_KEY",
    "ProfileStatus",
    "build_batch_package",
    "profile_status",
]
