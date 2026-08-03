"""申復理由草稿生成器測試（07-01-PLAN Task 1-3）。

涵蓋：D10 四段組裝（①案情摘要/②醫療必要性/③規則依據/④病歷佐證）、
字數控制器（C4/Q15：每欄 1000／合計 2000、④→② 優先裁剪、①③不動）、
P6 不申覆強制填 0（C3/Q13）、D-15 核減上界檢查、審核軌跡消費（D-08）、
每筆核減醫令獨立生成、C7 輸出命名（申復草稿_{流水號}.md＋appeal_{流水號}.json）。
"""

import json
from datetime import date

from elc_audit_engine.generators import (
    MAX_FIELD_CHARS,
    MAX_TOTAL_CHARS,
    adopted_narratives_from_tracking,
    build_appeal_draft,
    build_necessity,
    render_appeal_json,
    render_appeal_markdown,
    resolve_p6_points,
    validate_appeal_claim,
    write_appeal,
)
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.record_aggregator.models import (
    LabRecord,
    PatientTimeline,
    VisitRecord,
)


def _record(**overrides):
    base = dict(
        non_reimbursed_amount=300,
        institution_code="1234567890",
        fee_year_month="202106",
        submit_date="2021-08-03",
        case_class="D2",
        case_seq="18",
        visit_date="2021-06-23",
        birth_date="1944-09-01",
        id_number="F10291****",
        order_seq="1",
        order_code="E5002C",
        exec_start="2021-06-23",
        region="1",
        split_amount=300,
        pay_date="2021-08-20",
        deduction_reason="VPN資料複核不通過",
        appeal_item_code="A",
        appeal_item_desc="檢驗結果確實於時效內上傳",
        institution_note="檢附VPN佐證資料。",
    )
    base.update(overrides)
    return DeductionRecord(**base)


def _timeline(n_visits=1, n_labs=1, soap_len=0):
    visits = tuple(
        VisitRecord(
            patient_id="M220518024",
            date=date(2021, 6, 23),
            clinic="內科",
            soap_text="主訴咳嗽、發燒。" + "證" * soap_len,
            diagnoses=("J18",),
        )
        for _ in range(n_visits)
    )
    labs = tuple(
        LabRecord(
            patient_id="M220518024",
            date=date(2021, 6, 20),
            test_name="白血球",
            result="12.5",
            unit="10^3/uL",
            reference_range="4.0-10.0",
            abnormal=True,
        )
        for _ in range(n_labs)
    )
    return PatientTimeline(
        patient_id="M220518024",
        window_start=date(2021, 1, 1),
        window_end=date(2021, 6, 30),
        visits=visits,
        labs=labs,
        exams=(),
        imaging=(),
        source_provider="local",
    )


def _evidence_items(n=2):
    return [
        {"text": f"補強敘述{i}", "rule_location": "西醫基層-內科 > 一"}
        for i in range(1, n + 1)
    ]


def _tracking_dict():
    return {
        "case_record_no": "M220518024",
        "reviewed_at": "2026-08-03T10:00:00+00:00",
        "entries": [
            {
                "order_code": "E5002C",
                "narrative_text": "原文敘述一",
                "status": "採用",
                "edited_text": None,
                "rule_location": "西醫基層-內科 > 一",
            },
            {
                "order_code": "E5002C",
                "narrative_text": "原文敘述二",
                "status": "編輯後採用",
                "edited_text": "編輯後敘述二",
                "rule_location": "西醫基層-內科 > 二",
            },
            {
                "order_code": "E5002C",
                "narrative_text": "略過的敘述",
                "status": "略過",
                "edited_text": None,
                "rule_location": None,
            },
            {
                "order_code": "E5002C",
                "narrative_text": "不符事實的敘述",
                "status": "標記不符事實",
                "edited_text": None,
                "rule_location": None,
            },
            {
                "order_code": "E5002C",
                "narrative_text": "未審核的敘述",
                "status": "未審核",
                "edited_text": None,
                "rule_location": None,
            },
        ],
    }


def _draft(**kwargs):
    kwargs.setdefault("is_appealing", True)
    kwargs.setdefault("claimed_points", 300)
    kwargs.setdefault("timeline", _timeline())
    kwargs.setdefault("rule_text", "應記載檢驗結果並留存紀錄。")
    kwargs.setdefault("rule_location", "西醫基層-內科 > 一")
    kwargs.setdefault("evidence", _evidence_items())
    return build_appeal_draft(_record(), **kwargs)


# ── Task 1: 四段組裝與 P6 硬檢查 ──────────────────────────────


def test_four_sections_in_order():
    draft = _draft()
    assert [s.key for s in draft.sections] == [
        "case_summary",
        "necessity",
        "rule_basis",
        "evidence",
    ]
    assert draft.sections[0].title == "①案情摘要"
    assert draft.sections[1].title.startswith("②醫療必要性")
    assert draft.sections[2].title.startswith("③規則依據")
    assert draft.sections[3].title.startswith("④病歷佐證")


def test_case_summary_content():
    draft = _draft()
    text = draft.sections[0].text
    for expected in (
        "E5002C",
        "VPN資料複核不通過",
        "300",
        "202106",
        "2021-06-23",
        "D2",
        "18",
        "檢驗結果確實於時效內上傳",
    ):
        assert expected in text, expected


def test_necessity_from_timeline():
    draft = _draft(timeline=_timeline(n_visits=2, n_labs=1))
    text = draft.sections[1].text
    assert "就診 2 次、檢驗 1 筆" in text
    assert "就診 2021-06-23 內科" in text
    assert "白血球 = 12.5 10^3/uL" in text


def test_necessity_degraded_without_timeline():
    draft = _draft(timeline=None)
    assert "病歷缺席" in draft.sections[1].text


def test_rule_basis_with_text_and_location():
    draft = _draft(rule_text="條文全文ＡＢＣ", rule_location="總則 > 三")
    text = draft.sections[2].text
    assert "條文全文ＡＢＣ" in text
    assert "出處：總則 > 三" in text


def test_rule_basis_missing_is_honest():
    draft = _draft(rule_text=None)
    assert "查無規則依據" in draft.sections[2].text
    assert "E5002C" in draft.sections[2].text


def test_adopted_narratives_from_tracking_dict_and_str():
    adopted = adopted_narratives_from_tracking(_tracking_dict())
    assert len(adopted) == 2
    assert adopted[0]["text"] == "原文敘述一"
    assert adopted[1]["text"] == "編輯後敘述二"  # edited_text 優先
    assert adopted[1]["rule_location"] == "西醫基層-內科 > 二"

    adopted_str = adopted_narratives_from_tracking(json.dumps(_tracking_dict()))
    assert adopted_str == adopted


def test_evidence_only_adopted():
    draft = _draft(evidence=adopted_narratives_from_tracking(_tracking_dict()))
    text = draft.sections[3].text
    assert "原文敘述一" in text
    assert "編輯後敘述二" in text
    assert "略過的敘述" not in text
    assert "不符事實的敘述" not in text
    assert "未審核的敘述" not in text


def test_evidence_empty_placeholder():
    draft = _draft(evidence=())
    assert "尚無醫師採用的補強敘述" in draft.sections[3].text


def test_resolve_p6_points_hard_check():
    assert resolve_p6_points(False, 999) == 0  # 不申覆 → 強制 0
    assert resolve_p6_points(False, None) == 0
    assert resolve_p6_points(True, 300) == 300
    assert resolve_p6_points(True, None) == 0


def test_validate_appeal_claim_errors():
    # 申覆點數超過核減上界（D-15）
    errors = validate_appeal_claim(True, 500, 300)
    assert any("超過核減上界" in e for e in errors)
    # 負數
    errors = validate_appeal_claim(True, -5, 300)
    assert any("不得為負" in e for e in errors)
    # 申覆缺點數
    errors = validate_appeal_claim(True, None, 300)
    assert any("必須填報申復點數" in e for e in errors)
    # 不申覆 → 無錯誤
    assert validate_appeal_claim(False, 999, 300) == ()


def test_draft_validation_errors_wired():
    draft = _draft(claimed_points=500)
    assert draft.p6_points == 500
    assert any("超過核減上界" in e for e in draft.validation_errors)

    clean = _draft(claimed_points=300)
    assert clean.validation_errors == ()


# ── Task 2: 字數控制器＋p8/p9 切分（C4/Q15）──────────────────


def test_word_limit_under_no_trim():
    draft = _draft()
    assert draft.total_chars <= MAX_TOTAL_CHARS
    assert draft.over_limit is False
    assert all(not s.trimmed for s in draft.sections)
    full = "".join(s.text for s in draft.sections)
    assert draft.reason1 == full
    assert draft.reason2 == ""  # ≤1000 字 → p9 免填


def test_split_p8_p9_at_1000():
    draft = _draft(evidence=[{"text": "證" * 1500, "rule_location": None}])
    full = "".join(s.text for s in draft.sections)
    assert draft.total_chars == len(full)
    assert draft.reason1 == full[:1000]
    assert draft.reason2 == full[1000:]
    assert len(draft.reason1) <= MAX_FIELD_CHARS
    assert len(draft.reason2) <= MAX_FIELD_CHARS


def test_trim_evidence_first_necessity_untouched():
    record = _record()
    evidence = [{"text": "證" * 40, "rule_location": "出處"} for _ in range(60)]
    draft = build_appeal_draft(
        record,
        is_appealing=True,
        claimed_points=300,
        timeline=_timeline(n_visits=1),
        rule_text="條文",
        rule_location="處",
        evidence=evidence,
    )
    assert draft.total_chars <= MAX_TOTAL_CHARS
    sections = {s.key: s for s in draft.sections}
    assert sections["evidence"].trimmed is True
    assert sections["necessity"].trimmed is False  # ④ 先裁，② 未動
    assert sections["case_summary"].trimmed is False
    assert sections["rule_basis"].trimmed is False
    # ①③ 內容完整保留
    assert "VPN資料複核不通過" in sections["case_summary"].text
    assert "條文" in sections["rule_basis"].text


def test_trim_necessity_after_evidence_exhausted():
    draft = build_appeal_draft(
        _record(),
        is_appealing=True,
        claimed_points=300,
        timeline=_timeline(n_visits=60, soap_len=60),
        rule_text="條文",
        rule_location="處",
        evidence=[{"text": "短敘述", "rule_location": None}],
    )
    assert draft.total_chars <= MAX_TOTAL_CHARS
    sections = {s.key: s for s in draft.sections}
    assert sections["evidence"].trimmed is True
    assert sections["necessity"].trimmed is True  # ④ 裁完仍超 → ② 壓縮
    assert sections["case_summary"].trimmed is False
    assert sections["rule_basis"].trimmed is False


def test_over_limit_flag_when_skeleton_exceeds():
    draft = build_appeal_draft(
        _record(),
        is_appealing=True,
        claimed_points=300,
        timeline=_timeline(n_visits=100, soap_len=80),
        rule_text="條" * (MAX_TOTAL_CHARS + 100),  # ③ 骨架單獨即超
        rule_location=None,
        evidence=[{"text": "證" * 6000, "rule_location": None}],
    )
    assert draft.over_limit is True
    md = render_appeal_markdown(draft)
    assert "已盡最大裁剪" in md


def test_markdown_warns_trimmed_sections():
    draft = build_appeal_draft(
        _record(),
        is_appealing=True,
        claimed_points=300,
        timeline=_timeline(n_visits=60, soap_len=60),
        rule_text="條文",
        rule_location="處",
        evidence=[{"text": "短敘述", "rule_location": None}],
    )
    md = render_appeal_markdown(draft)
    assert "已裁剪" in md
    assert "⚠" in md


# ── Task 3: 渲染與檔案輸出（D-05/D-06/C7）────────────────────


def test_p6_zero_and_empty_reasons_when_not_appealing():
    draft = _draft(is_appealing=False, claimed_points=300)
    assert draft.p6_points == 0
    assert draft.reason1 == ""
    assert draft.reason2 == ""
    md = render_appeal_markdown(draft)
    assert "不申覆" in md
    assert "強制填 0" in md
    payload = json.loads(render_appeal_json(draft))
    assert payload["p6_points"] == 0
    assert payload["p8_reason1"] == ""
    assert payload["p9_reason2"] == ""


def test_json_fields_and_attachment():
    draft = _draft(has_attachment=True)
    payload = json.loads(render_appeal_json(draft))
    assert payload["format"] == "appeal-draft/v1"
    assert payload["p1_order_seq"] == "1"
    assert payload["p2_order_code"] == "E5002C"
    assert payload["p3_change_seq"] is None
    assert payload["p4_rate"] is None
    assert payload["p5_quantity"] is None
    assert payload["p6_points"] == 300
    assert payload["p7_attachment"] == "Y"
    assert len(payload["p8_reason1"]) <= MAX_FIELD_CHARS
    assert len(payload["p9_reason2"]) <= MAX_FIELD_CHARS
    assert payload["deduction_upper_bound"] == 300
    assert len(payload["sections"]) == 4
    assert payload["word_stats"]["max_total"] == MAX_TOTAL_CHARS
    assert payload["word_stats"]["per_field_max"] == MAX_FIELD_CHARS

    no_attach = json.loads(render_appeal_json(_draft(has_attachment=False)))
    assert no_attach["p7_attachment"] == "N"


def test_per_order_independent():
    draft1 = _draft()
    draft2 = _draft(
        evidence=[{"text": "另一筆敘述", "rule_location": None}],
        claimed_points=150,
    )
    record2 = _record(order_seq="2", order_code="64140C", non_reimbursed_amount=150)
    draft3 = build_appeal_draft(
        record2,
        is_appealing=True,
        claimed_points=150,
        timeline=_timeline(),
        rule_text="條文",
        rule_location="處",
        evidence=[{"text": "另一筆敘述", "rule_location": None}],
    )
    assert draft1.order_code == "E5002C"
    assert draft3.order_code == "64140C"
    assert "64140C" in draft3.sections[0].text
    payload = json.loads(render_appeal_json(draft3))
    assert payload["p2_order_code"] == "64140C"
    assert payload["p1_order_seq"] == "2"


def test_write_appeal_default_naming(tmp_path):
    draft = _draft()
    md_path, json_path = write_appeal(str(tmp_path), "18", draft)
    assert md_path.endswith(f"申復草稿_18.md")
    assert json_path.endswith("appeal_18.json")
    assert md_path == str(tmp_path / "申復草稿_18.md")
    assert json_path == str(tmp_path / "appeal_18.json")

    md = __import__("pathlib").Path(md_path).read_text(encoding="utf-8")
    assert "# 申復理由草稿" in md
    payload = json.loads(__import__("pathlib").Path(json_path).read_text(encoding="utf-8"))
    assert payload["p6_points"] == 300
    assert payload["p2_order_code"] == "E5002C"


def test_write_appeal_file_stem_avoids_overwrite(tmp_path):
    d1 = _draft()
    d2 = build_appeal_draft(
        _record(order_seq="2", order_code="64140C"),
        is_appealing=True,
        claimed_points=150,
        timeline=_timeline(),
        rule_text="條文",
        rule_location="處",
        evidence=[{"text": "另一筆", "rule_location": None}],
    )
    p1 = write_appeal(str(tmp_path), "18", d1, file_stem="18_1")
    p2 = write_appeal(str(tmp_path), "18", d2, file_stem="18_2")
    assert p1[0] != p2[0]
    assert (tmp_path / "申復草稿_18_1.md").exists()
    assert (tmp_path / "appeal_18_1.json").exists()
    assert (tmp_path / "申復草稿_18_2.md").exists()
    assert (tmp_path / "appeal_18_2.json").exists()


def test_build_necessity_pure():
    assert "病歷缺席" in build_necessity(None)
    text = build_necessity(_timeline(n_visits=1, n_labs=1))
    assert "半年病史" in text
    assert "就診 1 次、檢驗 1 筆" in text
