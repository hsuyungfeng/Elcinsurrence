"""A-CR-11：build_deduction_print --csv 必須以路徑解析 CSV。"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import build_deduction_print  # noqa: E402

FIXTURE = os.path.join(PROJECT_ROOT, "tests", "fixtures", "deduction_sample.csv")


def test_csv_path_is_parsed_and_passed_to_writer(monkeypatch, tmp_path):
    captured = {}

    def fake_write(output_dir, stem, records, facility, **kw):
        captured.update(stem=stem, records=records)
        return str(tmp_path / f"核減明細_{stem}.pdf"), []

    monkeypatch.setattr(build_deduction_print, "write_deduction_print", fake_write)
    rc = build_deduction_print.main(["--csv", FIXTURE])
    assert rc == 0
    assert captured["stem"] == "deduction_sample"
    assert captured["records"]
    assert all("raw" not in r for r in captured["records"])
    assert all("order_code" in r for r in captured["records"])
