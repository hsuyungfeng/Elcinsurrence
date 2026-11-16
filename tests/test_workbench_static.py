"""測試 static/index.html 拆檔、data-action 事件委派與 CSP 收緊 (Plan 32-16 / E8)。"""

import re
import subprocess
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


def test_index_html_has_no_style_or_inline_script():
    """index.html 不含 <style> 標籤與無 src 的 <script> 標籤。"""
    index_path = STATIC_DIR / "index.html"
    content = index_path.read_text(encoding="utf-8")

    assert "<style>" not in content
    assert "</style>" not in content

    # 檢查所有 <script> 標籤皆具有 src 屬性
    script_tags = re.findall(r"<script([^>]*)>", content, re.IGNORECASE)
    assert len(script_tags) > 0, "應至少有一個 <script src> 標籤"
    for tag_attrs in script_tags:
        assert "src=" in tag_attrs, f"<script> 標籤缺少 src 屬性: <script{tag_attrs}>"


def test_extracted_css_and_js_preserve_head_content():
    """新 css 內容包含 git HEAD 基準中 style 區塊內容，新 js 包含基準核心函式。"""
    head_html = subprocess.check_output(["git", "show", "01e1a13:static/index.html"], text=True)

    style_m = re.search(r"<style>([\s\S]*?)</style>", head_html)
    assert style_m, "HEAD index.html 應含 <style> 區塊"
    expected_css = style_m.group(1).strip()

    css_path = STATIC_DIR / "css" / "workbench.css"
    actual_css = css_path.read_text(encoding="utf-8").strip()
    assert expected_css in actual_css

    js_path = STATIC_DIR / "js" / "workbench.js"
    actual_js = js_path.read_text(encoding="utf-8").strip()
    core_functions = [
        "function switchWorkflowMode",
        "function loadFacilityConfig",
        "function runSamplingAudit",
        "function openMonthlyHtmlReport",
        "function toggleFullscreen",
    ]
    for fn in core_functions:
        assert fn in actual_js, f"核心函式 {fn} 應保留於 workbench.js"


def test_terminology_three_tracks():
    """index.html 與 README.md 統一為「三軌」，不出現「雙軌」(E9)。"""
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "雙軌" not in index_html, "index.html 仍包含「雙軌」詞彙"
    assert "三軌" in index_html

    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert "雙軌控制台" not in readme_text, "README.md 仍包含「雙軌控制台」"
    assert "三軌控制台" in readme_text


def test_plain_language_buttons():
    """index.html 內所有 button 標籤與屬性不含 UIA, agent-desktop, Big5 等工程術語 (E4)。"""
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    button_matches = re.findall(r"<button[^>]*>[\s\S]*?</button>", index_html, re.IGNORECASE)

    forbidden_terms = ["UIA", "agent-desktop", "Big5"]
    for btn in button_matches:
        for term in forbidden_terms:
            assert term not in btn, f"按鈕包含工程術語 '{term}': {btn}"


def test_no_inline_style_attributes_in_index_html():
    """index.html 內 0 處 inline style 屬性，全部轉移為 CSS 類別 (E3)。"""
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    style_attrs = re.findall(r'\bstyle="[^"]*"', index_html)
    assert len(style_attrs) == 0, f"index.html 仍有 {len(style_attrs)} 處 inline style: {style_attrs[:5]}"


def test_button_min_height_and_body_font_size():
    """workbench.css 包含全域基礎字級 15px、按鈕最小高度 40px 及大字模式 (E3)。"""
    css_text = (STATIC_DIR / "css" / "workbench.css").read_text(encoding="utf-8")
    assert "font-size: 15px" in css_text
    assert "min-height: 40px" in css_text
    assert "body.font-size-large" in css_text


def test_doctor_mode_elements():
    """工作台包含醫師/進階模式開關與 advanced-only 類別標記 (E1)。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="btnToggleDoctorMode"' in html
    assert 'data-action="toggleDoctorMode"' in html
    assert 'advanced-only' in html

    css = (STATIC_DIR / "css" / "workbench.css").read_text(encoding="utf-8")
    assert ".doctor-mode .advanced-only" in css


def test_stepper_and_empty_state():
    """工作台包含步驟化導引列與空白狀態引導 (E2, E6)。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="workflow-stepper"' in html
    assert "上傳申報檔" in html
    assert "智慧檢查" in html
    assert "下載送審檔" in html

    assert 'id="empty-state-guide"' in html
    assert "目前尚無申報資料，請先上傳本月申報檔" in html


def test_doctor_mode_js_logic():
    """workbench.js 的 ACTIONS 包含 toggleDoctorMode 且支援模式切換 (E1)。"""
    js = (STATIC_DIR / "js" / "workbench.js").read_text(encoding="utf-8")
    assert "toggleDoctorMode" in js


def test_destructive_buttons_isolated():
    """破壞性按鈕收納於「⋯ 更多」下拉選單中，避免醫師日常誤觸 (E5)。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "dropdown" in html
    assert "⋯ 更多" in html
    assert 'data-action="toggleMoreMenu"' in html


def test_structured_error_function():
    """workbench.js 提供三段式錯誤訊息函式 showStructuredError (E7)。"""
    js = (STATIC_DIR / "js" / "workbench.js").read_text(encoding="utf-8")
    assert "function showStructuredError" in js
    assert "狀況說明" in js
    assert "資料狀態" in js
    assert "建議動作" in js


def test_all_web_endpoints_have_strict_csp(test_client):
    """GET /, /clients, /status, /setup 的 CSP script-src 均為 'self' 且不含 'unsafe-inline'。"""
    for endpoint in ["/", "/clients", "/status", "/setup"]:
        res = test_client.get(endpoint)
        assert res.status_code in (200, 302)
        csp = res.headers.get("Content-Security-Policy", "")
        assert csp, f"{endpoint} 缺少 CSP 標頭"
        script_src = re.search(r"script-src\s+([^;]+)", csp).group(1)
        assert "'unsafe-inline'" not in script_src
        assert "'self'" in script_src


def test_all_referenced_static_assets_exist():
    """static/*.html 所有引用的 JS 與 CSS 檔案真實存在且非空。"""
    for html_file in STATIC_DIR.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for src in re.findall(r'src="([^"]+)"', content):
            if src.startswith("/static/"):
                rel_path = STATIC_DIR / src[len("/static/"):]
                assert rel_path.exists(), f"{html_file.name} 引用的檔案不存在: {rel_path}"
                assert rel_path.stat().st_size > 0, f"{html_file.name} 引用的檔案為空: {rel_path}"

        for href in re.findall(r'href="([^"]+)"', content):
            if href.startswith("/static/") and href.endswith(".css"):
                rel_path = STATIC_DIR / href[len("/static/"):]
                assert rel_path.exists(), f"{html_file.name} 引用的樣式不存在: {rel_path}"
                assert rel_path.stat().st_size > 0, f"{html_file.name} 引用的樣式為空: {rel_path}"


def test_no_inline_on_attributes_in_static_html_and_workbench_js():
    """static/ 下所有 html 及 workbench.js 的 innerHTML 皆不含 on* 事件屬性。"""
    # 檢查 static/ 下所有 .html 檔案
    for html_file in STATIC_DIR.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        on_matches = re.findall(r'\bon[a-z]+="[^"]*"', content)
        assert not on_matches, f"{html_file.name} 仍包含 inline on* 事件屬性: {on_matches}"

    # 檢查 workbench.js 不含 innerHTML 中拼接的 on* 屬性
    js_content = (STATIC_DIR / "js" / "workbench.js").read_text(encoding="utf-8")
    js_on_matches = re.findall(r'innerHTML\s*[\+]?=\s*["\x27][^"\x27]*\bon[a-z]+=', js_content)
    assert not js_on_matches, f"workbench.js innerHTML 仍含 on* 屬性: {js_on_matches}"


def test_data_actions_registered_in_actions_whitelist():
    """index.html 每個 data-action 與 data-change/input-action 值都出現在 workbench.js 的 ACTIONS 白名單中。"""
    html_content = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js_content = (STATIC_DIR / "js" / "workbench.js").read_text(encoding="utf-8")

    # 取得 ACTIONS 物件區塊
    actions_match = re.search(r"const\s+ACTIONS\s*=\s*\{([\s\S]*?)\n\s*\};", js_content)
    assert actions_match, "workbench.js 缺少 ACTIONS 白名單物件"
    actions_block = actions_match.group(1)

    # 提取 ACTIONS 鍵名
    defined_actions = set(re.findall(r"^\s*([a-zA-Z0-9_]+)\s*:", actions_block, re.MULTILINE))

    # 驗證 data-action
    data_actions = set(re.findall(r'data-action="([a-zA-Z0-9_]+)"', html_content))
    for action in data_actions:
        assert action in defined_actions, f"data-action '{action}' 未於 ACTIONS 白名單中定義"

    # 驗證 data-change-action
    change_actions = set(re.findall(r'data-change-action="([a-zA-Z0-9_]+)"', html_content))
    for action in change_actions:
        assert action in defined_actions, f"data-change-action '{action}' 未於 ACTIONS 白名單中定義"

    # 驗證 data-input-action
    input_actions = set(re.findall(r'data-input-action="([a-zA-Z0-9_]+)"', html_content))
    for action in input_actions:
        assert action in defined_actions, f"data-input-action '{action}' 未於 ACTIONS 白名單中定義"


def test_csp_header_tightened_without_unsafe_inline_for_script(test_client):
    """GET / 回應之 CSP 標頭 script-src 不含 'unsafe-inline'，style-src 保留。"""
    res = test_client.get("/")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert csp, "缺少 Content-Security-Policy 標頭"

    # 檢查 script-src
    script_src_m = re.search(r"script-src\s+([^;]+)", csp)
    assert script_src_m, "CSP 缺少 script-src 指令"
    script_src = script_src_m.group(1)
    assert "'unsafe-inline'" not in script_src, f"script-src 不得含 'unsafe-inline': {script_src}"
    assert "'self'" in script_src

    # 檢查 style-src（暫留 unsafe-inline）
    style_src_m = re.search(r"style-src\s+([^;]+)", csp)
    assert style_src_m, "CSP 缺少 style-src 指令"
    style_src = style_src_m.group(1)
    assert "'unsafe-inline'" in style_src, "style-src 於 E3 前暫保留 'unsafe-inline'"


def test_static_assets_http_200(test_client):
    """GET /static/js/workbench.js 與 /static/css/workbench.css 回應 200。"""
    res_js = test_client.get("/static/js/workbench.js")
    assert res_js.status_code == 200
    assert len(res_js.data) > 1000

    res_css = test_client.get("/static/css/workbench.css")
    assert res_css.status_code == 200
    assert len(res_css.data) > 500

    res_clients_js = test_client.get("/static/js/clients.js")
    assert res_clients_js.status_code == 200
