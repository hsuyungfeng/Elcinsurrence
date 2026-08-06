"""Phase 9-01 存取審計日誌測試（record_access／read_entries，零 PHI 斷言）。"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from elc_audit_engine.audit_log import AuditFieldError, read_entries, record_access


def test_record_access_writes_and_reads_back(tmp_path):
    log_path = str(tmp_path / "access.log")
    record_access(
        caller_id="his1",
        method="GET",
        path="/api/sampling/cases",
        status=200,
        log_path=log_path,
    )
    entries = read_entries(log_path)
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry.keys()) == {"ts", "caller_id", "method", "path", "status", "detail"}
    assert entry["caller_id"] == "his1"
    assert entry["method"] == "GET"
    assert entry["path"] == "/api/sampling/cases"
    assert entry["status"] == 200
    # ts 須可被 fromisoformat 解析（UTC ISO 格式）
    datetime.fromisoformat(entry["ts"])


def test_record_access_appends_not_overwrites(tmp_path):
    log_path = str(tmp_path / "access.log")
    record_access(caller_id="his1", method="GET", path="/a", status=200, log_path=log_path)
    record_access(caller_id="his2", method="POST", path="/b", status=401, log_path=log_path)
    entries = read_entries(log_path)
    assert len(entries) == 2
    assert entries[0]["caller_id"] == "his1"
    assert entries[1]["caller_id"] == "his2"


def test_record_access_rejects_record_no(tmp_path):
    log_path = str(tmp_path / "access.log")
    with pytest.raises(AuditFieldError):
        record_access(
            caller_id="his1",
            method="GET",
            path="/x",
            status=200,
            detail={"record_no": "M1001"},
            log_path=log_path,
        )


def test_record_access_rejects_soap_text(tmp_path):
    log_path = str(tmp_path / "access.log")
    with pytest.raises(AuditFieldError):
        record_access(
            caller_id="his1",
            method="POST",
            path="/x",
            status=200,
            detail={"soap_text": "S: ..."},
            log_path=log_path,
        )


def test_record_access_rejects_long_string_value(tmp_path):
    log_path = str(tmp_path / "access.log")
    with pytest.raises(AuditFieldError):
        record_access(
            caller_id="his1",
            method="GET",
            path="/x",
            status=200,
            detail={"note": "x" * 101},
            log_path=log_path,
        )


def test_record_access_allows_order_code(tmp_path):
    log_path = str(tmp_path / "access.log")
    line = record_access(
        caller_id="his1",
        method="POST",
        path="/api/sampling/audit",
        status=200,
        detail={"order_code": "14050B"},
        log_path=log_path,
    )
    assert "14050B" in line
    entries = read_entries(log_path)
    assert entries[0]["detail"] == {"order_code": "14050B"}


def test_record_access_no_phi_leak_in_serialized_output(tmp_path):
    """審計日誌整列序列化後不得含 PHI 樣本值（record_no／patient_name）。

    本測試在後續端點接線後（Task 3）仍必須成立——即便呼叫端疏忽把
    PHI 塞進 detail 的非禁止鍵，本函式的禁止清單與長度限制也應攔下
    常見洩漏路徑（本測試涵蓋合法呼叫下不含 PHI 的正常路徑）。
    """
    log_path = str(tmp_path / "access.log")
    record_access(
        caller_id="his1",
        method="GET",
        path="/api/sampling/cases",
        status=200,
        detail={"order_code": "14050B"},
        log_path=log_path,
    )
    entries = read_entries(log_path)
    serialized = json.dumps(entries, ensure_ascii=False)
    assert "M1001" not in serialized
    assert "林聰明" not in serialized


def test_read_entries_missing_file_returns_empty_list(tmp_path):
    assert read_entries(str(tmp_path / "does_not_exist.log")) == []
