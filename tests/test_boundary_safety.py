"""Phase 22-02 測試：批次截斷揭露（P1-10）、例外不被靜默吞掉（P1-11）、bare except 清理（P1-12）。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from elc_audit_engine.api.batch_limits import read_batch
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

KEY = {"X-API-Key": "valid-key-123"}
SRC_ROUTES = Path(__file__).resolve().parents[1] / "src" / "elc_audit_engine" / "api"


@pytest.fixture
def api(make_api_app):
    return make_api_app()


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


@pytest.fixture
def store(tmp_path):
    return CaseStore(db_path=str(tmp_path / "boundary.sqlite3"))


@pytest.fixture
def small_limit(monkeypatch):
    """把批次上限降為 2，避免測試建立 1000 筆案件。"""
    from elc_audit_engine.services import batch_reads

    monkeypatch.setattr(batch_reads, "BATCH_READ_LIMIT", 2)
    return 2


def _seed(store, kind: str, n: int, payload: dict | None = None):
    for i in range(n):
        store.create(
            case_id=f"{kind.upper()}-{i:04d}",
            kind=kind,
            payload=payload if payload is not None else {"order_code": "14050B"},
            actor="test",
        )


# ---------------------------------------------------------------- P1-10：截斷揭露


def test_read_batch_reports_truncation_over_limit(store, small_limit):
    _seed(store, "sampling", 5)
    records, meta = read_batch(store, "sampling")
    assert len(records) == 2
    assert meta == {"total": 5, "returned": 2, "truncated": True, "limit": 2}


def test_read_batch_not_truncated_within_limit(store, small_limit):
    _seed(store, "sampling", 2)
    records, meta = read_batch(store, "sampling")
    assert len(records) == 2
    assert meta["truncated"] is False
    assert meta["total"] == 2


def test_sampling_export_xml_refuses_truncated_batch(client, api, small_limit):
    _seed(api.extensions["elc"].case_store, "sampling", 3)
    res = client.get("/api/sampling/export-batch-xml", headers=KEY)
    assert res.status_code == 409
    assert "3 筆" in res.get_json()["message"]


def test_sampling_batch_report_refuses_truncated_batch(client, api, small_limit):
    _seed(api.extensions["elc"].case_store, "sampling", 3)
    res = client.get("/api/sampling/batch-report", headers=KEY)
    assert res.status_code == 409


def test_appeal_export_batch_xml_refuses_truncated_batch(client, api, small_limit):
    _seed(api.extensions["elc"].case_store, "appeal", 3)
    res = client.get("/api/appeal/export-batch-xml", headers=KEY)
    assert res.status_code == 409


def test_appeal_batch_report_refuses_truncated_batch(client, api, small_limit):
    _seed(api.extensions["elc"].case_store, "appeal", 3)
    res = client.get("/api/appeal/batch-report", headers=KEY)
    assert res.status_code == 409


def test_truncated_batch_is_not_refused_when_within_limit(client, api, small_limit):
    _seed(api.extensions["elc"].case_store, "appeal", 2)
    res = client.get("/api/appeal/export-batch-xml", headers=KEY)
    assert res.status_code != 409


def test_stage2_linkage_discloses_source_truncation(client, api, small_limit, monkeypatch):
    """JSON 連動端點必須回傳 source_window，揭露來源是否被 1000 筆（此處為 2 筆）上限截斷。"""
    from elc_audit_engine.api.routes import appeal as appeal_routes

    _seed(api.extensions["elc"].case_store, "sampling", 3)
    captured = {}

    def fake_link(store, sources, *, count, seed, actor):
        captured["n"] = len(sources)
        return {"linked": 0, "items": []}

    monkeypatch.setattr(appeal_routes, "link_stage2_to_appeal", fake_link)
    res = client.post("/api/appeal/sample-from-stage2", json={"count": 1}, headers=KEY)
    assert res.status_code == 200
    body = res.get_json()
    assert captured["n"] == 2
    assert body["source_window"] == {"total": 3, "returned": 2, "truncated": True, "limit": 2}


# ---------------------------------------------------------------- P1-11：例外不被靜默吞掉


def test_stage2_rule_repository_error_degrades_gracefully(api, store, monkeypatch):
    from elc_audit_engine.api.routes import sampling as sampling_routes
    from elc_audit_engine.services import sampling_service

    _seed(store, "sampling", 1)
    record = store.list_all(kind="sampling")[0]

    def boom(code):
        raise RuleRepositoryError("規則庫暫時故障")

    monkeypatch.setattr(sampling_service, "get_rule", boom)
    with api.app_context():
        view = sampling_routes._stage2_view(store, record, with_thumbnails=False)
    assert view is not None


def test_stage2_programming_error_is_not_swallowed(api, store, monkeypatch):
    from elc_audit_engine.api.routes import sampling as sampling_routes
    from elc_audit_engine.services import sampling_service

    _seed(store, "sampling", 1)
    record = store.list_all(kind="sampling")[0]

    def buggy(code):
        raise NameError("order_name 未定義")

    monkeypatch.setattr(sampling_service, "get_rule", buggy)
    with api.app_context(), pytest.raises(NameError):
        sampling_routes._stage2_view(store, record, with_thumbnails=False)


def test_stage3_programming_error_is_not_swallowed(api, store, monkeypatch):
    from elc_audit_engine.api.routes import appeal as appeal_routes

    _seed(store, "appeal", 1)
    record = store.list_all(kind="appeal")[0]

    def buggy(code):
        raise KeyError("missing")

    monkeypatch.setattr(appeal_routes, "get_rule", buggy)
    with api.app_context(), pytest.raises(KeyError):
        appeal_routes._stage3_view(store, record, with_thumbnails=False)


def test_stage3_rule_repository_error_degrades_gracefully(api, store, monkeypatch):
    from elc_audit_engine.api.routes import appeal as appeal_routes

    _seed(store, "appeal", 1)
    record = store.list_all(kind="appeal")[0]

    def boom(code):
        raise RuleRepositoryError("規則庫暫時故障")

    monkeypatch.setattr(appeal_routes, "get_rule", boom)
    with api.app_context():
        view = appeal_routes._stage3_view(store, record, with_thumbnails=False)
    assert view is not None


def test_appeal_generate_passes_order_name_to_llm(client, monkeypatch):
    """回歸：先前 order_name 未定義的 NameError 被 except 吞掉，導致 LLM 建議恆為 None。"""
    from elc_audit_engine.api.routes import appeal as appeal_routes

    captured = {}

    def fake_advice(**kwargs):
        captured.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(appeal_routes, "generate_soap_advice", fake_advice)
    body = {
        "case_seq": "301",
        "order_code": "14050B",
        "order_name": "某某測試醫令",
        "deduction_reason": "超過次數",
    }
    res = client.post("/api/appeal/generate", json=body, headers=KEY)
    assert res.status_code == 200
    assert captured["order_name"] == "某某測試醫令"


def test_appeal_generate_order_name_falls_back_to_code(client, monkeypatch):
    from elc_audit_engine.api.routes import appeal as appeal_routes

    captured = {}
    monkeypatch.setattr(
        appeal_routes, "generate_soap_advice", lambda **kw: captured.update(kw) or {"status": "success"}
    )
    body = {"case_seq": "302", "order_code": "14050B", "deduction_reason": "超過次數"}
    assert client.post("/api/appeal/generate", json=body, headers=KEY).status_code == 200
    assert captured["order_name"] == "14050B"


def test_appeal_generate_surfaces_programming_error_instead_of_none(client, monkeypatch):
    """LLM 建議函式若發生程式錯誤，不得被靜默吞掉成 soap_advice=None。"""
    from elc_audit_engine.api.routes import appeal as appeal_routes

    def buggy(**kwargs):
        raise KeyError("程式錯誤")

    monkeypatch.setattr(appeal_routes, "generate_soap_advice", buggy)
    body = {"case_seq": "303", "order_code": "14050B", "deduction_reason": "超過次數"}
    res = client.post("/api/appeal/generate", json=body, headers=KEY)
    # 統一錯誤處理器記錄並回 500，而非靜默成功回傳 soap_advice=None
    assert res.status_code == 500


# ---------------------------------------------------------------- P1-12：bare except 清理


def _route_files():
    return sorted(SRC_ROUTES.rglob("*.py"))


def test_no_bare_except_anywhere_in_api_package():
    offenders = []
    for path in _route_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f"{path.relative_to(SRC_ROUTES)}:{node.lineno}")
    assert offenders == [], f"發現 bare except：{offenders}"


def test_no_silent_broad_except_pass_in_routes():
    """禁止 `except Exception: pass`（整段吞掉）。"""
    offenders = []
    for path in (SRC_ROUTES / "routes").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
            only_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if broad and only_pass:
                offenders.append(f"{path.relative_to(SRC_ROUTES)}:{node.lineno}")
    assert offenders == [], f"發現籠統的 except Exception: pass：{offenders}"


# ---------------------------------------------------------------- 回歸：病史摘要不再靜默失效


def test_history_lines_uses_real_visit_fields_not_missing_events():
    """回歸：先前程式讀取不存在的 timeline.events，AttributeError 被 except 吞掉，病史永遠不進 LLM。"""
    from datetime import date

    from elc_audit_engine.record_aggregator.models import PatientTimeline, VisitRecord

    timeline = PatientTimeline(
        patient_id="P1",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 11, 1),
        visits=(
            VisitRecord(patient_id="P1", date=date(2026, 9, 2), clinic="內科", diagnoses=("E11.9",)),
            VisitRecord(patient_id="P1", date=date(2026, 6, 1), clinic="", diagnoses=()),
        ),
    )
    text = timeline.history_lines()
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("- [2026-06-01]")  # 依日期升冪
    assert "E11.9" in lines[1] and "內科" in lines[1]


def test_history_lines_empty_timeline_is_empty_string():
    from datetime import date

    from elc_audit_engine.record_aggregator.models import PatientTimeline

    assert PatientTimeline(patient_id="P1", window_start=date(2026, 5, 1), window_end=date(2026, 11, 1)).history_lines() == ""
