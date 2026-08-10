"""Phase 09.1-03 CaseStore→submission 標準轉換層測試（D-05）。

測試矩陣：
- `build_submission_from_case` 單元：完整鍵／缺欄誠實降級／契約 8 鍵／
  真實 CaseStore payload 鍵集／id_number 防呆／orders 構造與直通
- 端到端：轉換後 submission 可直接餵 `render_appeal_print`（純函式段，
  不觸 soffice；完整鍵輸入患者層無 warnings、真實路徑缺欄 warnings 欄名
  明確且 id_number 照印）

資料構造器比照 test_appeal_print.py「base dict + overrides」慣例；
OFFICIAL_ODT 常量與 `_facility`/`_payload` 自 test_appeal_print.py 複製
最小量（不 import tests 模組，避免觸發 soffice 探測等模組級副作用）。
"""

import server
from elc_audit_engine.generators.appeal_print.case_to_submission import (
    build_submission_from_case,
)
from elc_audit_engine.parsers.models import DeductionRecord

# 官方模板路徑（git-tracked 版控資產，與 test_appeal_print.py 同源）。
OFFICIAL_ODT = (
    "officialdocument/電子申復文件格式/"
    "30396_1_1050105-1門診診療費用申復清單.odt"
)

# ── 資料構造器（「base dict + overrides」慣例）─────────────────


def _facility(**overrides):
    """院所層資料（D-04 dict）。"""
    base = {
        "code": "01015C",
        "name": "測試醫療院所",
        "address": "測試市測試區測試路1號",
        "physician_name": "測試醫師",
    }
    base.update(overrides)
    return base


def _case_payload(**overrides):
    """CaseStore 風格 appeal payload（完整鍵：8 契約鍵來源＋既有資料直通鍵）。"""
    base = {
        "id": "APP-0001",
        "demo": False,
        "case_class": "D2",
        "case_seq": "18",
        "record_no": "R-001",
        "id_number": "F10291****",
        "patient_name": "陳小明",
        "order_code": "E5002C",
        "order_name": "關節腔注射",
        "order_seq": "1",
        "primary_diagnosis": "J189",
        "clinic": "內科",
        "submit_date": "2021-08-03",
        "visit_date": "2021-06-23",
        "fee_year_month": "202106",
        "deduct_amount": 300,
        "deduction_reason": "VPN資料複核不通過",
        "soap": "主訴與理學檢查…",
        "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
        "source": "csv",
    }
    base.update(overrides)
    return base


def _appeal_payload(**overrides):
    """appeal_{流水號}.json 內容（render_appeal_json 格式 dict，端到端 render 用）。"""
    base = {
        "format": "appeal-draft/v1",
        "case_class": "D2",
        "case_seq": "18",
        "order_seq": "1",
        "order_code": "E5002C",
        "visit_date": "2021-06-23",
        "fee_year_month": "202106",
        "deduction_upper_bound": 300,
        "deduction_reason": "VPN資料複核不通過",
        "is_appealing": True,
        "p1_order_seq": "1",
        "p2_order_code": "E5002C",
        "p6_points": 300,
        "p8_reason1": "申復理由一",
        "p9_reason2": "申復理由二",
    }
    base.update(overrides)
    return base


def _real_case_payload():
    """plan 01 Task 3 補全後 `_to_appeal_case` 真實輸出鍵集（含 id_number、缺 case_class/patient_name/orders）。"""
    return {
        "id": "APP-0001",
        "demo": False,
        "case_seq": "18",
        "record_no": None,
        "id_number": "A123****",
        "patient_name": None,
        "order_code": "E5002C",
        "order_name": "關節腔注射",
        "deduct_amount": 300,
        "deduction_reason": "VPN資料複核不通過",
        "visit_date": "2021-06-23",
        "soap": "",
        "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
        "source": "csv",
    }


# ── Task 1: build_submission_from_case 單元測試 ──────────────


def test_build_submission_full_case_warnings_empty():
    """Test 1：含完整鍵的 CaseStore 風格 payload → submission 含 case_seq/orders/id_number 照印，warnings 為空。"""
    payload = _case_payload()
    submission, warnings = build_submission_from_case(payload)

    assert submission["case_seq"] == "18"
    assert submission["case_class"] == "D2"
    # 11.1-01：單筆構造分支新增 points 映射（_case_payload 含 deduct_amount=300）
    assert submission["orders"] == [
        {"code": "E5002C", "name": "關節腔注射", "seq": "1", "points": 300}
    ]
    # 遮罩 id_number 照印（不重建）
    assert submission["id_number"] == "F10291****"
    assert submission["patient_name"] == "陳小明"
    assert submission["primary_diagnosis"] == "J189"
    assert submission["clinic"] == "內科"
    assert submission["submit_date"] == "2021-08-03"
    assert warnings == []


def test_build_submission_missing_fields_honest_degrade():
    """Test 2：缺 case_class/patient_name/id_number → 對應鍵留空（None）且 warnings 含欄名、無推導/捏造值。"""
    payload = _case_payload(case_class=None, patient_name=None, id_number=None)
    submission, warnings = build_submission_from_case(payload)

    assert submission["case_class"] is None
    assert submission["patient_name"] is None
    assert submission["id_number"] is None
    # warnings 含欄名（欄名明確可歸因）
    for field in ("案件分類", "姓名", "身份證字號"):
        assert field in warnings
    # 不捏造：id_number 保持 None，不從他欄推導/重建
    assert submission["id_number"] is None


def test_build_submission_contract_8_keys_no_fabrication():
    """Test 3：契約 8 鍵 ⊆ 輸出 dict 鍵集合；輸出不含推導/捏造值（visit_date/fee_year_month 為既有資料直通）。"""
    payload = _case_payload()
    submission, warnings = build_submission_from_case(payload)

    contract_keys = {
        "case_class",
        "case_seq",
        "id_number",
        "patient_name",
        "primary_diagnosis",
        "clinic",
        "submit_date",
        "orders",
    }
    assert contract_keys <= set(submission.keys())
    # 既有資料直通（非捏造，warnings 不因多餘鍵觸發）
    assert submission["visit_date"] == "2021-06-23"
    assert submission["fee_year_month"] == "202106"
    assert warnings == []


def test_build_submission_real_case_payload_keyset():
    """真實 CaseStore payload 鍵集（plan 01 補全後）：id_number 照印、orders 由單筆案件構造、缺欄誠實留空＋warnings 欄名。"""
    payload = _real_case_payload()
    submission, warnings = build_submission_from_case(payload)

    # id_number 遮罩照印（可 join）
    assert submission["id_number"] == "A123****"
    # orders 由 order_code/order_name 構造（無 order_seq → 無 seq 鍵）；
    # 11.1-01：_real_case_payload 含 deduct_amount=300 → points 鍵在場
    assert submission["orders"] == [{"code": "E5002C", "name": "關節腔注射", "points": 300}]
    # 缺欄誠實留空（None）
    assert submission["case_class"] is None
    assert submission["patient_name"] is None
    assert submission["primary_diagnosis"] is None
    assert submission["clinic"] is None
    assert submission["submit_date"] is None
    # warnings 欄名明確（可歸因）
    for field in ("案件分類", "姓名", "傷病名稱", "審查科別"):
        assert field in warnings
    # 不捏造：傷病名稱/審查科別維持 None
    assert submission["primary_diagnosis"] is None
    assert submission["clinic"] is None
    # visit_date 既有資料直通
    assert submission["visit_date"] == "2021-06-23"


def test_build_submission_id_number_unmasked_warns():
    """id_number 疑似未遮罩（無 '*' 且長度 ≥8）→ 加 warning、不阻斷照印。"""
    payload = _case_payload(id_number="F102912345")
    submission, warnings = build_submission_from_case(payload)

    assert submission["id_number"] == "F102912345"
    assert any("疑似未遮罩" in w for w in warnings)


def test_build_submission_order_name_none_omits_key():
    """order_name 為 None → orders[0] 省略 name 鍵。"""
    payload = _case_payload(order_name=None)
    submission, _ = build_submission_from_case(payload)

    assert submission["orders"] == [{"code": "E5002C", "seq": "1", "points": 300}]
    assert "name" not in submission["orders"][0]


def test_build_submission_existing_orders_passthrough():
    """payload 已有完整 orders（SubmissionCase 風格）→ 直通不重造（直通非捏造）。"""
    orders = [{"code": "E5002C", "total_qty": "1", "points": "300", "seq": "1"}]
    payload = _case_payload(orders=orders)
    submission, warnings = build_submission_from_case(payload)

    assert submission["orders"] == orders
    assert warnings == []


def test_build_submission_no_order_empty_list():
    """無 order_code/order_name/orders → orders 為空 list（誠實留空）。"""
    payload = _case_payload(order_code=None, order_name=None)
    submission, _ = build_submission_from_case(payload)

    assert submission["orders"] == []


# ── 11.1-01: 整合鏈（真實 _to_appeal_case 輸出 → 轉換層 → build_rows）──


def test_to_appeal_case_passthroughs_order_seq():
    """11.1-01 Test 1：_to_appeal_case 透傳 rec.order_seq（值=rec.order_seq），並保留既有 deduct_amount。"""
    out = server._to_appeal_case(
        1,
        DeductionRecord(
            case_seq="201",
            order_code="14050B",
            order_seq="3",
            non_reimbursed_amount=300,
        ),
    )
    assert out["order_seq"] == "3"
    assert out["deduct_amount"] == 300


def test_build_submission_from_real_to_appeal_case_orders():
    """11.1-01 Test 2：真實 _to_appeal_case 輸出 → build_submission_from_case 的
    orders[0] 含 seq（=order_seq）與 points（=deduct_amount）。"""
    rec = DeductionRecord(
        case_seq="201",
        order_code="14050B",
        order_seq="3",
        non_reimbursed_amount=300,
    )
    submission, _ = build_submission_from_case(server._to_appeal_case(1, rec))
    order = submission["orders"][0]
    assert order["code"] == "14050B"
    assert order["seq"] == "3"
    assert order["points"] == 300


def test_build_rows_integration_chain_amount_and_seq():
    """11.1-01 Test 3（整合鏈，Success Criteria 4）：走真實 server._to_appeal_case
    輸出（非手工完整 fixture）→ build_submission_from_case → build_rows，
    金額欄=points、醫令序=seq，warnings 不含「金額」。（build_rows 為純函式，不需 soffice）"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_rows

    rec = DeductionRecord(
        case_seq="201",
        order_code="14050B",
        order_seq="3",
        non_reimbursed_amount=300,
    )
    submission, _ = build_submission_from_case(server._to_appeal_case(1, rec))
    rows, warnings = build_rows(
        _appeal_payload(order_seq="3", p1_order_seq="3"),
        _facility(),
        submission=submission,
    )
    assert rows[0]["金額"] == "300"
    assert rows[0]["醫令序"] == "3"
    assert "金額" not in warnings


def test_build_rows_missing_order_seq_honest_degrade():
    """11.1-01 Test 4（回歸）：rec 缺 order_seq 且 deduct_amount 缺省 →
    _to_appeal_case 的 order_seq 為 None（照印 None，與 id_number 同語意）；
    轉換層 orders[0] 無 seq/points 鍵；build_rows 金額留空＋warning「金額」
    （誠實降級不變、不捏造 0）。"""
    from elc_audit_engine.generators.appeal_print.field_mapping import build_rows

    rec = DeductionRecord(case_seq="201", order_code="14050B")
    out = server._to_appeal_case(1, rec)
    assert out["order_seq"] is None

    submission, _ = build_submission_from_case(out)
    order = submission["orders"][0]
    assert "seq" not in order
    assert "points" not in order

    rows, warnings = build_rows(_appeal_payload(), _facility(), submission=submission)
    assert rows[0]["金額"] == ""
    assert "金額" in warnings


# ── Task 2: 端到端（轉換層 → render_appeal_print 純函式段，不需 soffice）──


def test_e2e_full_keys_render_no_patient_warnings():
    """完整鍵輸入 → 轉換後 submission 直接餵 render_appeal_print：bytes 非空、warnings 不含患者層欄名（患者層 join 成功）。"""
    from elc_audit_engine.generators.appeal_print import render_appeal_print

    case_payload = _case_payload(
        orders=[{"code": "E5002C", "total_qty": "1", "points": "300", "seq": "1"}]
    )
    submission, convert_warnings = build_submission_from_case(case_payload)
    assert convert_warnings == []

    data, warnings = render_appeal_print(
        _appeal_payload(),
        _facility(),
        template_odt_path=OFFICIAL_ODT,
        submission=submission,
    )

    assert isinstance(data, bytes)
    assert len(data) > 0
    # 患者層欄位完整 join：無患者層缺欄 warning
    for field in ("身份證字號", "姓名", "傷病名稱", "審查科別", "數量", "金額"):
        assert field not in warnings


def test_e2e_real_path_degrade_warnings_and_id_number():
    """真實 CaseStore payload 鍵集 → 缺欄 warnings 欄名明確且 id_number 照印（可 join）。"""
    from elc_audit_engine.generators.appeal_print import render_appeal_print

    case_payload = _real_case_payload()
    submission, convert_warnings = build_submission_from_case(case_payload)

    # 缺欄歸因：warnings 含欄名（案件分類/姓名/傷病名稱/審查科別）
    for field in ("案件分類", "姓名", "傷病名稱", "審查科別"):
        assert field in convert_warnings
    # id_number 照印（遮罩值直通）
    assert submission["id_number"] == "A123****"

    data, warnings = render_appeal_print(
        _appeal_payload(),
        _facility(),
        template_odt_path=OFFICIAL_ODT,
        submission=submission,
    )

    assert isinstance(data, bytes)
    assert len(data) > 0
    # render 層（build_rows）缺欄亦歸因（患者層欄名），且 id_number 已 join → 無「身份證字號」warning
    for field in ("姓名", "傷病名稱", "審查科別"):
        assert field in warnings
    assert "身份證字號" not in warnings
