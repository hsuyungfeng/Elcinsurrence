"""Contract and unit tests for capacity forecast (Phase 32 Plan 32-08, D3, D5, D6)."""

from pathlib import Path
import pytest

from elc_audit_engine.capacity import (
    DEFAULT_RED_DAYS,
    DEFAULT_YELLOW_DAYS,
    classify_runway,
    days_until_full,
    growth_bytes_per_day,
    record_daily_sample,
)


def test_capacity_forecast_days_until_full():
    # Samples < 7 returns None
    short_samples = [("2026-11-01", 1000), ("2026-11-02", 2000)]
    assert days_until_full(short_samples, free_bytes=10000) is None

    # Daily growth 1GB, remaining 90GB -> ~90 days
    gb = 1024 * 1024 * 1024
    growing_samples = [(f"2026-11-{i:02d}", i * gb) for i in range(1, 11)]
    days = days_until_full(growing_samples, free_bytes=90 * gb)
    assert days is not None
    assert 89.0 <= days <= 91.0

    # Flat or negative growth returns None
    flat_samples = [(f"2026-11-{i:02d}", 10 * gb) for i in range(1, 10)]
    assert days_until_full(flat_samples, free_bytes=90 * gb) is None


def test_capacity_classify_runway():
    assert classify_runway(200.0, yellow_days=180, red_days=90) == "green"
    assert classify_runway(150.0, yellow_days=180, red_days=90) == "yellow"
    assert classify_runway(30.0, yellow_days=180, red_days=90) == "red"
    assert classify_runway(None, yellow_days=180, red_days=90) == "unknown"


def test_default_thresholds_match_d32_13():
    assert DEFAULT_YELLOW_DAYS == 180
    assert DEFAULT_RED_DAYS == 90


def test_growth_bytes_per_day():
    samples = [(f"2026-11-{i:02d}", i * 1000) for i in range(1, 10)]
    slope = growth_bytes_per_day(samples)
    assert slope is not None
    assert 990.0 <= slope <= 1010.0


def test_record_daily_sample_idempotent(tmp_path):
    store = tmp_path / "samples.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "file.bin").write_bytes(b"x" * 100)

    res1 = record_daily_sample(data_dir, store, today="2026-11-14")
    assert "date" in res1
    assert res1["bytes"] == 100

    res2 = record_daily_sample(data_dir, store, today="2026-11-14")
    assert res1 == res2


def test_capacity_never_deletes():
    capacity_file = Path("src/elc_audit_engine/capacity.py")
    assert capacity_file.exists(), "src/elc_audit_engine/capacity.py must exist"
    content = capacity_file.read_text(encoding="utf-8")
    for forbidden in ["unlink(", "rmtree", "os.remove"]:
        assert forbidden not in content, f"Forbidden deletion operation found: {forbidden}"
