"""病歷補強報告生成器測試（06-01-PLAN Task 1-3）。

涵蓋：D-01 報告結構（標題/病歷號/逐醫令/病史摘要）、D-02 checkbox 初始
未勾選、支持度徽章、警告區（records_degraded/unknown/manual）、D-03 審核
軌跡 JSON（四狀態＋原文＋編輯後文＋時間）、D-04 時間戳注入、D-05 檔案輸出。
"""

import json
import os
from datetime import date

from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    VERDICT_MANUAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    CandidateNarrative,
    CaseComparisonResult,
    CheckItem,
    Judgment,
    OrderJudgment,
)
from elc_audit_engine.generators import (
    STATUS_ADOPT,
    STATUS_ADOPT_EDITED,
    STATUS_DECLINE,
    STATUS_FLAG,
    STATUS_PENDING,
    render_report,
    render_timeline_summary,
    render_tracking,
    write_report,
)
from elc_audit_engine.record_aggregator.models import (
    ImagingRecord,
    LabRecord,
    PatientTimeline,
    VisitRecord,
)


def _comparison(
    *,
    degraded=False,
    unknowns=(),
    manual=(),
    with_narratives=True,
    case_record_no="M220518024",
):
    judgments = [
        OrderJudgment(
            order_code="64140C",
            order_seq="1",
            rule_found=True,
            rule_source="docx",
            check_item=CheckItem(
                rule_text="應記載檢驗結果",
                rule_location="西醫基層-內科 > 一",
                rule_source="docx",
            ),
            judgment=Judgment(VERDICT_UNSUPPORTED, "", "病歷無檢驗記載"),
            support_level=SUPPORT_NONE,
            narratives=(
                CandidateNarrative(
                    text="病歷已記載疼痛，可補強執行紀錄",
                    rule_location="西醫基層-內科 > 一",
                    prompt_only=False,
                ),
                CandidateNarrative(
                    text="若實際有執行，請補充：檢驗日期",
                    rule_location="西醫基層-內科 > 一",
                    prompt_only=True,
                ),
            )
            if with_narratives
            else (),
        ),
        OrderJudgment(
            order_code="48010C",
            order_seq="2",
            rule_found=True,
            rule_source="docx",
            check_item=CheckItem(
                rule_text="應記載處置",
                rule_location="西醫基層-外科 > 二",
                rule_source="docx",
            ),
            judgment=Judgment(VERDICT_SUPPORTED, "病歷記載處置完成", "符合"),
            support_level=SUPPORT_SUFFICIENT,
        ),
        OrderJudgment(
            order_code="99999X",
            order_seq="3",
            rule_found=False,
            note="查無規則依據，建議人工查核",
        ),
    ]
    return CaseComparisonResult(
        case_record_no=case_record_no,
        order_judgments=tuple(judgments),
        records_degraded=degraded,
        unknown_orders=tuple(unknowns),
        manual_review_orders=tuple(manual),
    )


def _timeline():
    return PatientTimeline(
        patient_id="M220518024",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 8, 1),
        visits=(VisitRecord(patient_id="M220518024", date=date(2026, 7, 20), clinic="骨科",
                            soap_text="主訴：手腕疼痛"),),
        labs=(LabRecord(patient_id="M220518024", date=date(2026, 2, 15),
                        test_name="HbA1c", result="7.2", unit="%"),),
        exams=(),
        imaging=(ImagingRecord(patient_id="M220518024", date=date(2026, 6, 1),
                               modality="CT", body_part="胸部", impression="無異常"),),
        source_provider="local:test",
    )


# ---------------------------------------------------------------- 報告渲染

def test_render_report_structure():
    report = render_report(_comparison())
    assert "# 病歷補強報告" in report
    assert "`M220518024`" in report
    assert "## 逐醫令支持度" in report
    assert "### 64140C" in report
    assert "### 48010C" in report
    assert "### 99999X" in report


def test_render_report_badges():
    report = render_report(_comparison())
    assert "✅ 充分" in report
    assert "❌ 裸奔" in report
    assert "❓ 查無規則" in report


def test_render_report_undetermined_badge_is_not_confused_with_others():
    """P1-1：規則查到但判定全部待人工（LLM 故障）→「待判定」。

    此態的 support_level 也是 None，但與「查無規則」（rule_found=False）
    成因不同，必須分辨；更不得顯示為裸奔——否則醫師會照著一個系統故障
    產生的「完全未記載」結論去補強不存在的缺漏。
    """
    comparison = CaseComparisonResult(
        case_record_no="M220518024",
        order_judgments=(
            OrderJudgment(
                order_code="64140C",
                rule_found=True,
                check_item=CheckItem(rule_text="規則全文"),
                judgment=Judgment(VERDICT_MANUAL, "", "LLM 逾時"),
                support_level=None,
                manual_review=True,
            ),
        ),
        manual_review_orders=("64140C",),
    )
    report = render_report(comparison)
    assert "⏳ 待判定" in report
    assert "❌ 裸奔" not in report
    assert "❓ 查無規則" not in report


def test_render_report_checkbox_narratives():
    report = render_report(_comparison())
    assert "- [ ] 病歷已記載疼痛，可補強執行紀錄（西醫基層-內科 > 一）" in report
    assert "- [ ] 若實際有執行，請補充：檢驗日期〔提示型〕（西醫基層-內科 > 一）" in report


def test_render_report_verdict_quote():
    report = render_report(_comparison())
    assert "無記載" in report
    assert "> 病歷記載處置完成" in report


def test_render_report_warnings():
    report = render_report(
        _comparison(degraded=True, unknowns=("ABC01",), manual=("DEF02",))
    )
    assert "⚠ 本報告未含病史佐證" in report
    assert "`ABC01`" in report
    assert "`DEF02`" in report


def test_render_report_timeline_summary():
    report = render_report(_comparison(), timeline=_timeline())
    assert "## 半年病史摘要" in report
    assert "就診 1 筆" in report
    assert "檢驗 1 筆" in report
    assert "影像 1 筆" in report
    assert "HbA1c = 7.2 %" in report


def test_render_timeline_summary_none_returns_empty():
    assert render_timeline_summary(None) == ""


# ---------------------------------------------------------------- 審核軌跡

def test_render_tracking_pending_defaults():
    tracking = json.loads(render_tracking(_comparison(), reviewed_at="2026-08-03T10:00:00+00:00"))
    assert tracking["case_record_no"] == "M220518024"
    assert tracking["reviewed_at"] == "2026-08-03T10:00:00+00:00"
    entries = tracking["entries"]
    assert len(entries) == 2  # 只有 64140C 有 2 條敘述；48010C/99999X 無敘述
    assert entries[0]["status"] == STATUS_PENDING
    assert entries[0]["order_code"] == "64140C"
    assert entries[0]["narrative_text"] == "病歷已記載疼痛，可補強執行紀錄"


def test_render_tracking_decisions():
    tracking = json.loads(
        render_tracking(
            _comparison(),
            decisions={
                0: (STATUS_ADOPT, None),
                1: (STATUS_ADOPT_EDITED, "補充：執行日期 2026-07-20"),
            },
            reviewed_at="2026-08-03T10:00:00+00:00",
        )
    )
    entries = tracking["entries"]
    assert entries[0]["status"] == STATUS_ADOPT
    assert entries[0]["edited_text"] is None
    assert entries[1]["status"] == STATUS_ADOPT_EDITED
    assert entries[1]["edited_text"] == "補充：執行日期 2026-07-20"


def test_render_tracking_flag_and_decline():
    tracking = json.loads(
        render_tracking(
            _comparison(),
            decisions={
                0: (STATUS_FLAG, "事實不符：未執行"),
                1: (STATUS_DECLINE, None),
            },
            reviewed_at="2026-08-03T10:00:00+00:00",
        )
    )
    entries = tracking["entries"]
    assert entries[0]["status"] == STATUS_FLAG
    assert entries[0]["edited_text"] == "事實不符：未執行"
    assert entries[1]["status"] == STATUS_DECLINE


def test_render_tracking_invalid_status_pending():
    tracking = json.loads(
        render_tracking(
            _comparison(),
            decisions={0: ("胡亂狀態", None)},
            reviewed_at="2026-08-03T10:00:00+00:00",
        )
    )
    assert tracking["entries"][0]["status"] == STATUS_PENDING


def test_render_tracking_no_narratives():
    tracking = json.loads(
        render_tracking(_comparison(with_narratives=False), reviewed_at="2026-08-03T10:00:00+00:00")
    )
    assert tracking["entries"] == []


# ---------------------------------------------------------------- 檔案輸出

def test_write_report_writes_md_and_json(tmp_path):
    paths = write_report(
        str(tmp_path),
        "M220518024",
        _comparison(),
        decisions={0: (STATUS_ADOPT, None)},
        reviewed_at="2026-08-03T10:00:00+00:00",
    )
    report_path, tracking_path = paths
    assert os.path.isfile(report_path)
    assert os.path.isfile(tracking_path)
    assert report_path.endswith("病歷補強報告_M220518024.md")
    assert tracking_path.endswith("審核軌跡_M220518024.json")

    md = open(report_path, encoding="utf-8").read()
    assert "# 病歷補強報告" in md
    assert "- [ ] 病歷已記載疼痛" in md

    tr = json.load(open(tracking_path, encoding="utf-8"))
    assert tr["entries"][0]["status"] == STATUS_ADOPT
