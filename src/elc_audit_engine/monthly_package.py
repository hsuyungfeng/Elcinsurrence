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
from elc_audit_engine.comparator.soap_advice import generate_template_soap_condensed
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.comparator.soap_comparison import compare_soap_with_template
from elc_audit_engine.monthly_pregen import (
    STATUS_GENERATED,
    is_pregen_target,
    load_templates,
    pregen_template,
)

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


def _case_targets(case) -> list:
    """案件中需範本的醫令（點數 > 350 且有規定原文），與 pregen 目標判定一致。"""
    return [f for f in case.findings if is_pregen_target(f)]


def build_batch_package(
    store: CaseStore,
    batch_id: str,
    *,
    facility: dict,
    rules_db_path: str | None = None,
    generate_limit: int = 0,
) -> bytes:
    """下載包（給沒有 SOAP、僅上傳申報檔的外來機構）：每個無 SOAP 案件一份範例病歷。

    - 只包含「無 SOAP」的案件；有 SOAP 的案件不在此下載（SOAP 比對請用缺項比對端點）。
    - 範例病歷來源：已快取範本；缺少者在 `generate_limit` 額度內由本機 LLM 生成（通過品質檢核才存庫）。
      額度用盡仍缺者標示「尚未預生成」。
    - 院所資料必須完整且已確認，否則拋出 FacilityProfileError。

    ZIP 內容：`病歷/<case_id>.html`（每案一份）。
    """
    status = profile_status(facility)
    if not status.ready:
        raise FacilityProfileError(list(status.missing), status.confirmed)

    audit = audit_batch(store, batch_id, rules_db_path=rules_db_path, persist=False)

    no_soap: list[tuple] = []
    for case in audit.cases:
        record = store.get(case.case_id)
        payload = dict(record.payload or {}) if record is not None else {}
        if _soap_from_payload(payload) is None:
            no_soap.append((case, payload))

    templates = load_templates(store, audit)
    if generate_limit > 0:
        generated = 0
        for case, _payload in no_soap:
            for finding in _case_targets(case):
                if generated >= generate_limit:
                    break
                key = (finding.code.strip().upper(), (case.primary_diagnosis or "").strip().upper())
                if key in templates:
                    continue
                outcome = pregen_template(
                    store,
                    order_code=finding.code,
                    order_name=finding.rule_name or finding.code,
                    primary_diagnosis=case.primary_diagnosis or "",
                    rule_text=finding.rule_full_text or "",
                    generator=generate_template_soap_condensed,
                )
                generated += 1
                if outcome.status == STATUS_GENERATED:
                    templates[key] = outcome.soap
        templates = load_templates(store, audit) | templates

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for case, payload in no_soap:
            doc = _case_document(store, case, payload, templates)
            zf.writestr(f"病歷/{case.case_id}.html", doc.encode("utf-8"))
    return buf.getvalue()


def build_gap_check(store: CaseStore, batch_id: str, *, rules_db_path: str | None = None) -> dict:
    """SOAP 缺項比對：有 SOAP 的案件，逐一與該醫令的標準範本（soap_templates）比對，列出缺少的描述。

    只讀快取範本，不呼叫 LLM。比對結果為 advisory，不改動案件狀態。
    """
    audit = audit_batch(store, batch_id, rules_db_path=rules_db_path, persist=False)
    cases_out: list[dict] = []
    for case in audit.cases:
        record = store.get(case.case_id)
        payload = dict(record.payload or {}) if record is not None else {}
        soap = _soap_from_payload(payload)
        if soap is None:
            continue
        targets = _case_targets(case)
        entry: dict = {"case_id": case.case_id, "case_seq": case.case_seq, "items": []}
        if "text" in soap:
            entry["note"] = "SOAP 為單段文字，無法分欄比對"
            cases_out.append(entry)
            continue
        if not targets:
            entry["note"] = "本案無需範本比對的醫令（點數 > 350 且有規定原文）"
            cases_out.append(entry)
            continue
        for finding in targets:
            template = store.get_soap_template(finding.code, case.primary_diagnosis or "")
            if template is None:
                entry["items"].append({"order_code": finding.code, "status": "no_template",
                                       "message": "尚無範本可比對（請先生成範本）"})
                continue
            result = compare_soap_with_template(soap, template["soap"], finding.rule_full_text or "")
            entry["items"].append({
                "order_code": finding.code,
                "status": "compared",
                "missing_sections": result["missing_sections"],
                "overall_similarity": result["overall_similarity"],
                "section_similarities": result["section_similarities"],
            })
        cases_out.append(entry)
    return {"batch": batch_id, "cases": cases_out, "advisory_only": True}


__all__ = [
    "FacilityProfileError",
    "PROFILE_CONFIRMED_KEY",
    "ProfileStatus",
    "build_batch_package",
    "build_gap_check",
    "profile_status",
]


# ── EMR 審查包（每案 XML 核算＋HTML 審查，影像內嵌）──────────────────

def build_emr_bundle(
    store: CaseStore,
    batch_id: str,
    *,
    facility_code: str,
    roc_date: str,
    tier1: str = "11",
    images_for_case=None,
    rules_db_path: str | None = None,
):
    """組出批次的 EMR 審查包。

    回傳 (zips, failures)：zips 為 [(zip檔名, bytes)]；failures 為 [{case_id, reason}]。
    任一案件失敗（缺來源、缺必要欄位、檔名衝突）即不產生任何 ZIP，避免殘缺上傳檔。
    `images_for_case(case_id) -> list[bytes]` 提供影像原始位元組（未提供則無影像）。
    """
    from elc_audit_engine.generators.emr_review_bundle import (
        BundleError,
        ReviewImage,
        build_base_name,
        build_case_bundle,
        compress_image,
        pack_zips,
    )
    from elc_audit_engine.generators.sampling_xml import SamplingXmlError, build_sampling_xml

    records = store.list_by_batch(batch_id)
    audit_cases = {c.case_id: c for c in audit_batch(store, batch_id, rules_db_path=rules_db_path, persist=False).cases}
    bundles = []
    failures: list[dict] = []
    seen_names: dict[str, str] = {}
    for record in records:
        payload = dict(record.payload or {})
        case_id = record.case_id
        try:
            base = build_base_name(tier1, "A", str(payload.get("case_class") or ""), str(payload.get("case_seq") or ""))
        except BundleError as exc:
            failures.append({"case_id": case_id, "reason": f"檔名：{exc}"})
            continue
        if base in seen_names:
            failures.append({"case_id": case_id, "reason": f"檔名衝突（與 {seen_names[base]} 相同）"})
            continue
        seen_names[base] = case_id
        try:
            build_sampling_xml({"batch": batch_id, "monthly_source": payload})  # 驗證必要欄位（結果另行組裝）
            xml_payload = {"batch": batch_id, "monthly_source": payload}
        except SamplingXmlError as exc:
            failures.append({"case_id": case_id, "reason": f"XML：{exc}"})
            continue

        soap = _soap_from_payload(payload)
        if soap is not None and "text" in soap:
            soap = {"s": soap["text"], "o": "", "a": "", "p": ""}  # 單段文字：整段列於 S，不分欄（不捏造）
        soap_note = None
        if soap is None:
            # 無 SOAP：以已快取的範例病歷 SOAP 代替（僅供 HTML 審查，標示為範例，不進入 XML）
            for finding in _case_targets(audit_cases.get(case_id)) if audit_cases.get(case_id) else []:
                template = store.get_soap_template(finding.code, payload.get("primary_diagnosis") or "")
                if template is not None:
                    soap = dict(template["soap"])
                    soap_note = f"範例病歷（依醫令 {finding.code} 預生成，非實際病歷，須醫師審核）"
                    break
        images = []
        if images_for_case is not None:
            for raw in images_for_case(case_id):
                jpeg = compress_image(raw)
                if jpeg is not None:
                    images.append(ReviewImage(caption=f"影像 {len(images) + 1}", jpeg=jpeg))
        bundle = build_case_bundle(
            base_name=base,
            xml_payload=xml_payload,
            case_title=f"{base}（流水號 {payload.get('case_seq') or '—'}）",
            soap=soap,
            orders=[
                {"code": o.get("p4"), "name": _rule_name(o.get("p4"), rules_db_path), "points": o.get("p12")}
                for o in (payload.get("orders") or []) if isinstance(o, dict)
            ],
            images=images,
            soap_note=soap_note,
        )
        bundles.append(bundle)

    if failures:
        return [], failures
    zips = pack_zips(bundles, facility_code=facility_code, roc_date=roc_date)
    return zips, []


def _rule_name(code: str | None, rules_db_path: str | None) -> str:
    """醫令名稱：由規則庫（payment/drug）查得；查無則回傳空字串，不捏造。"""
    if not code:
        return ""
    try:
        rule = get_rule(code, db_path=rules_db_path)
    except Exception:
        return ""
    return (rule.name or "") if rule.found else ""
