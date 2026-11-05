"""測試工作台第 2 階（抽樣事前預審）與第 3 階（核減事後申復）所有按鈕功能及與 WebBrain 互動之 DOM 元素支援。"""

from pathlib import Path
import pytest
from elc_audit_engine.api.app import create_app


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    store_file = tmp_path / "test_store.json"
    monkeypatch.setenv("CASE_STORE_PATH", str(store_file))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_stage2_and_3_buttons_dom_integrity_for_webbrain():
    """驗證 static/index.html 內第 2 階與第 3 階的所有操作按鈕均具備唯一的 id 與 data-test-id，
    使 WebBrain（瀏覽器 AI Agent）在 Act 模式下能 100% 精確定位與點擊。"""
    html = Path("static/index.html").read_text(encoding="utf-8")

    # 預期的第 2 階按鈕 ID（已依需求移除載入預審、重新抽樣、單案卡片、隨機抽5案連動）
    stage2_btn_ids = [
        "btn-s-batch-report-top",
        "btn-s-run-audit",
        "btn-s-patient-entry",
        "btnBatchAudit",
        "btn-s-clear",
        "btn-s-batch-report",
        "btn-s-export-xml",
        "btn-s-apply-soap",
        "btn-s-save-evidence",
    ]

    # 預期的第 3 階按鈕 ID（已依需求移除載入預審、重新抽5案、單案申復卡片，加入 LLM 換 SOAP 按鈕）
    stage3_btn_ids = [
        "btn-a-batch-report-top",
        "btn-a-generate-draft",
        "btn-a-patient-entry",
        "btn-a-clear",
        "btn-a-batch-report",
        "btn-a-export-xml",
        "btn-a-download-json",
        "btn-a-download-xml",
        "btn-a-apply-soap",
    ]

    for bid in stage2_btn_ids:
        assert f'id="{bid}"' in html, f"第 2 階按鈕缺少 ID: {bid}"
        if bid != "btnBatchAudit":
            assert f'data-test-id="{bid}"' in html, f"第 2 階按鈕缺少 data-test-id: {bid}"

    for bid in stage3_btn_ids:
        assert f'id="{bid}"' in html, f"第 3 階按鈕缺少 ID: {bid}"
        assert f'data-test-id="{bid}"' in html, f"第 3 階按鈕缺少 data-test-id: {bid}"

    # 驗證佐證庫上傳與相簿庫元素存在於第 2 階與第 3 階
    vault_element_ids = [
        "vaultKeyLabel", "vaultBtnFile", "vaultBtnZip", "vaultImages",
        "aVaultKeyLabel", "aVaultBtnFile", "aVaultBtnZip", "aVaultImages",
    ]
    for vid in vault_element_ids:
        assert f'id="{vid}"' in html, f"缺少佐證庫元素 ID: {vid}"

    # 確認已刪除之按鈕確已自 DOM 中完全移除
    deleted_btn_ids = [
        "btn-s-import-monthly",
        "btn-s-sample-batch",
        "btn-s-preview-single",
        "btn-s-link-appeal",
        "btn-a-import-monthly",
        "btn-a-link-appeal",
        "btn-a-preview-single",
    ]
    for dbid in deleted_btn_ids:
        assert f'id="{dbid}"' not in html, f"已刪除按鈕仍存在於 DOM: {dbid}"


def test_stage2_button_api_endpoints(test_client):
    """驗證第 2 階（抽樣事前預審）所有按鈕關聯的後端 API 端點均能正常響應。"""
    # 1. 載入案件 / 清空清單按鈕
    clear_res = test_client.post("/api/sampling/cases/clear")
    assert clear_res.status_code in (200, 204)

    # 2. 批次報表按鈕 (HTML)
    rep_res = test_client.get("/api/sampling/batch-report?format=html")
    assert rep_res.status_code in (200, 404)  # 查無案件回傳 404，有案件回傳 200

    # 3. 抽樣 XML 導出按鈕
    xml_res = test_client.get("/api/sampling/export-batch-xml")
    assert xml_res.status_code in (200, 400, 404, 422)  # 無案件時 422/404，非 500

    # 4. 隨機抽 5 案連動至第 3 階申復庫
    link_res = test_client.post("/api/appeal/sample-from-stage2")
    assert link_res.status_code in (200, 400, 404)

    # 5. 第 2 階 SOAP 寫回資料庫端點
    soap_res = test_client.post(
        "/api/sampling/cases/SMP-001/soap",
        json={"soap": "S: Chief Complaint\nO: Normal\nA: DM\nP: Continue Metformin"}
    )
    assert soap_res.status_code in (200, 204)
    data = soap_res.get_json()
    assert data["status"] == "success"
    assert "DM" in data["soap"]


def test_stage3_button_api_endpoints(test_client):
    """驗證第 3 階（核減事後申復）所有按鈕關聯的後端 API 端點均能正常響應。"""
    # 1. 清空申復清單按鈕
    clear_res = test_client.post("/api/appeal/cases/clear")
    assert clear_res.status_code in (200, 204)

    # 2. 批次申復報表按鈕 (HTML)
    rep_res = test_client.get("/api/appeal/batch-report?format=html")
    assert rep_res.status_code in (200, 404)  # 查無案件時回 404

    # 3. 全批次導出申復 XML
    xml_res = test_client.get("/api/appeal/export-batch-xml")
    assert xml_res.status_code in (200, 400, 404, 422)

    # 4. 重新自第 2 階抽選 5 案連動
    link_res = test_client.post("/api/appeal/sample-from-stage2")
    assert link_res.status_code in (200, 400, 404)

    # 5. 第 3 階申復 SOAP 佐證寫回資料庫端點
    soap_res = test_client.post(
        "/api/appeal/cases/APP-001/soap",
        json={"soap": "① 案情摘要\n② 醫療必要性\n③ 規則依據\n④ 病歷佐證"}
    )
    assert soap_res.status_code in (200, 204)
    data = soap_res.get_json()
    assert data["status"] == "success"
    assert "病歷佐證" in data["soap"]
