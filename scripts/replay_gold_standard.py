#!/usr/bin/env python
"""LLM 判定金標準 30 組回放 CLI（C6-3：換模型時的回歸基準）。

用法（需 llama.cpp server 於 localhost:8080 健康）:
    .venv/bin/python scripts/replay_gold_standard.py [fixture_path]

對每筆金標準案例以真實 LLMJudger 判定（支持/部分支持/無記載），輸出
逐筆結果表＋各判定統計＋總正確率。伺服器未啟動時說明並 exit 1
（回放是評測工具，不是 CI 測試 — 測試以替身 judge_fn 驗證 harness）。
"""

from __future__ import annotations

import sys

import requests

from config.settings import LLAMA_CPP_BASE_URL
from elc_audit_engine.comparator import create_judger
from elc_audit_engine.eval import evaluate, load_gold_standard


def _server_is_up() -> bool:
    try:
        resp = requests.get(f"{LLAMA_CPP_BASE_URL}/health", timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    fixture_path = argv[0] if argv else None

    if not _server_is_up():
        print(
            "llama.cpp server 未在 localhost:8080 啟動（/health 非 200）。"
            "請先啟動 server 再回放金標準。",
            file=sys.stderr,
        )
        return 1

    cases = load_gold_standard(fixture_path)
    result = evaluate(create_judger(), cases)

    print(
        f"金標準回放：{result.total} 筆，正確 {result.correct} 筆，"
        f"正確率 {result.accuracy:.1%}"
    )
    for verdict, stat in result.per_verdict.items():
        print(f"  {verdict}: {stat['correct']}/{stat['total']}")
    if result.mismatches:
        print("\n逐筆不符：")
        for case_id, expected, actual in result.mismatches:
            print(f"  {case_id}: 預期 {expected}，實際 {actual}")
    else:
        print("\n全部相符。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
