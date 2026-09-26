"""B-CR-03：半年病史窗必須以就醫日為迄日，就醫日之後的紀錄不得入窗。"""
import json
from datetime import date

import pytest

import server
from elc_audit_engine.record_aggregator import LocalFileProvider


@pytest.fixture
def provider(tmp_path):
    d = tmp_path / "records" / "P001"
    d.mkdir(parents=True)
    (d / "records.json").write_text(
        json.dumps(
            {
                "visits": [
                    {"date": "2026-03-01", "clinic": "內科", "soap_text": "就醫前"},
                    {"date": "2026-08-01", "clinic": "內科", "soap_text": "就醫後"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return LocalFileProvider(str(tmp_path / "records"))


def test_window_ends_at_visit_date(provider):
    timeline, source = server._resolve_records_source(provider, "P001", date(2026, 7, 10))
    assert source == "ok"
    assert timeline.window_end == date(2026, 7, 10)
    assert [v.date for v in timeline.visits] == [date(2026, 3, 1)]
    assert timeline.excluded_counts["visits"] == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-07-10", date(2026, 7, 10)),
        ("20260710", date(2026, 7, 10)),
        ("1150710", date(2026, 7, 10)),
        ("115/07/10", date(2026, 7, 10)),
        ("2026/07/10", date(2026, 7, 10)),
        ("", None),
        (None, None),
        ("garbage", None),
        ("115/13/40", None),
    ],
)
def test_parse_visit_date_formats(raw, expected):
    assert server._parse_visit_date(raw) == expected


def test_visit_date_falls_back_to_case_payload(client):
    server._case_store.create(
        case_id="APP-X", kind="appeal", case_seq="1", payload={"visit_date": "2026-07-10"}
    )
    assert server._resolve_visit_date({}, "APP-X") == date(2026, 7, 10)
    assert server._resolve_visit_date({"visit_date": "2026-01-02"}, "APP-X") == date(2026, 1, 2)
    assert server._resolve_visit_date({}, "NOPE") is None
