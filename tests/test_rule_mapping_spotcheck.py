"""20 個常見醫令代碼人工核對回歸測試（REQ-rule-repository 驗收標準 3）。

只匯入 `json`（不匯入 rule_repository），因此本檔案在 Wave 0 不會
ImportError — 它會收集並執行成功，但 `test_fixture_all_entries_verified`
預期失敗（fixture 全部 verified=false），直到 Plan 05 的人工核對
checkpoint 將 fixture 更新為全部 verified=true 為止。
"""

import json
import os

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "rule_mapping_20_spotcheck.json"
)


def _load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_fixture_has_20_entries():
    data = _load_fixture()
    assert len(data) == 20


def test_fixture_all_entries_verified():
    data = _load_fixture()
    assert all(entry["verified"] for entry in data)
