"""核心工作台 API 與前端掛勾煙霧測試 (Plan 32-22, E1-E9)。"""

import re
from pathlib import Path
import pytest
from elc_audit_engine.api.app import create_app

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    store_file = tmp_path / "test_store.json"
    monkeypatch.setenv("CASE_STORE_PATH", str(store_file))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_workbench_page_renders_without_csp_violations(test_client):
    """GET / 載入主頁，驗證包含所有主要流程所需的 DOM 容器與嚴格 CSP 標頭。"""
    res = test_client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # 驗證嚴格 CSP 標頭
    csp = res.headers.get("Content-Security-Policy", "")
    assert csp, "缺少 CSP 標頭"
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in re.search(r"script-src\s+([^;]+)", csp).group(1)

    # 驗證四大作業視圖容器存在
    assert 'id="workflow1View"' in html  # 抽樣事前預審
    assert 'id="workflow2View"' in html  # 核減事後申復
    assert 'id="workflow3View"' in html  # 當月申報檔預審
    assert 'id="workflow4View"' in html  # 診間即時 SOAP

    # 驗證核心互動組件容器（Phase 36：移除 workflow-stepper 釋放版面空間）
    assert 'id="workflow-stepper"' not in html
    assert 'id="empty-state-guide"' in html
    assert 'id="confirm-destructive-modal"' in html
    assert 'id="structured-error-modal"' in html
    assert 'id="moreActionsMenu"' in html
    assert 'id="btnToggleDoctorMode"' in html


def test_workbench_all_actions_bound_and_no_dangling_listeners():
    """驗證所有主要操作按鈕之 data-action 或 id 與 workbench.js 中的 ACTIONS 一一對應，無懸空按鈕。"""
    html_content = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js_content = (STATIC_DIR / "js" / "workbench.js").read_text(encoding="utf-8")

    # 提取 ACTIONS 白名單
    actions_match = re.search(r"const\s+ACTIONS\s*=\s*\{([\s\S]*?)\n\s*\};", js_content)
    assert actions_match, "缺少 ACTIONS 物件"
    actions_block = actions_match.group(1)
    defined_actions = set(re.findall(r"^\s*([a-zA-Z0-9_]+)\s*:", actions_block, re.MULTILINE))

    # 驗證所有 data-action
    used_actions = set(re.findall(r'data-action="([a-zA-Z0-9_]+)"', html_content))
    for act in used_actions:
        assert act in defined_actions, f"按鈕使用的 action '{act}' 未於 ACTIONS 白名單中定義"

    # 驗證所有 data-change-action
    used_change = set(re.findall(r'data-change-action="([a-zA-Z0-9_]+)"', html_content))
    for act in used_change:
        assert act in defined_actions, f"change action '{act}' 未於 ACTIONS 白名單中定義"

    # 驗證所有 data-input-action
    used_input = set(re.findall(r'data-input-action="([a-zA-Z0-9_]+)"', html_content))
    for act in used_input:
        assert act in defined_actions, f"input action '{act}' 未於 ACTIONS 白名單中定義"


def test_workbench_doctor_mode_classes_and_stepper_attributes():
    """驗證步驟引導與醫師模式樣式宣告完整。"""
    css_content = (STATIC_DIR / "css" / "workbench.css").read_text(encoding="utf-8")

    # 驗證進階按鈕隱藏規則
    assert ".doctor-mode .advanced-only" in css_content
    assert "display: none !important" in css_content

    # 驗證步驟導引樣式
    assert ".step-indicator" in css_content
    assert ".step-item" in css_content
    assert ".step-active" in css_content

    # 驗證空白狀態樣式
    assert ".empty-state-box" in css_content
    assert ".empty-state-upload-btn" in css_content


def test_workbench_static_pages_utf8_encoding():
    """驗證 static/ 下所有 html, js, css 皆為合法 UTF-8 編碼且無 BOM。"""
    for asset in STATIC_DIR.glob("**/*"):
        if asset.is_file() and asset.suffix in (".html", ".js", ".css"):
            raw_bytes = asset.read_bytes()
            assert not raw_bytes.startswith(b"\xef\xbb\xbf"), f"{asset.name} 含有 BOM"
            # 應可順利以 utf-8 解碼
            raw_bytes.decode("utf-8")
