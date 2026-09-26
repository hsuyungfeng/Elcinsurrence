"""請求期取用 app 注入的依賴（取代原本 server.py 的模組全域變數）。

`create_app` 把 CaseStore 等服務放進 `app.extensions["elc"]`，路由一律經
`case_store()` 取用——測試因此可用 `create_app(case_store=...)` 注入暫存
資料庫，不必 monkeypatch 模組屬性。
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import current_app, g

from elc_audit_engine.case_store import CaseStore

EXTENSION_KEY = "elc"


@dataclass
class Services:
    case_store: CaseStore


def case_store() -> CaseStore:
    return current_app.extensions[EXTENSION_KEY].case_store


def caller_id() -> str | None:
    return getattr(g, "caller_id", None)
