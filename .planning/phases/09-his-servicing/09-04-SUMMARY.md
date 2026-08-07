# 09-04-SUMMARY.md — Package Builder (申復 XML 序列化)

## 執行成果摘要

Phase 9 Plan 04 成功完成 Package Builder 申復 XML 序列化器與背景 CLI 腳本：

1. **申復 XML 序列化器 (`src/elc_audit_engine/generators/appeal_xml.py`)**：
   - `build_appeal_xml()`：將 `appeal_{流水號}.json`（含 p1-p9）組裝為符合健保署申復格式之 ElementTree XML（tdata + ddata + pdata，不含 edata）。
   - 空值省略：`None` 或空字串欄位一律不輸出 XML 標籤（無資料不輸出標籤規則）。
   - 半形特殊字元全形轉換：`_to_fullwidth_specials()` 將 p8/p9 申復理由內之 `< > & ' "` 自動轉為全形 `＜ ＞ ＆ ＇ ＂`（符合官方【表8】規定，非依賴 XML escaping）。
   - Big5 編碼與 fail-fast：`write_appeal_xml()` 宣告 `<?xml version="1.0" encoding="Big5"?>` 寫檔；若遭遇 Big5 無法表示之字元時 fail-fast 拋出 `AppealXmlEncodingError`。

2. **背景 CLI 腳本 (`scripts/build_appeal_xml.py`)**：
   - 用法：`python scripts/build_appeal_xml.py <appeal_json_path> [output_xml_path]`。
   - 讀取 JSON 並輸出 XML，不新增 Flask API 端點、不涉及認證豁免清單與 zip 打包。
   - 錯誤處理以退出碼（`exit code 1`）乾淨表達，不噴錯 Traceback。

3. **自動化測試與文件**：
   - 新增 `tests/test_appeal_xml.py`（11 項測試全綠）。
   - 更新 README.md 紀錄 CLI 工具用法、edata 範圍說明與 Big5 / 全形轉換規則。

## 變更檔案清單

- `src/elc_audit_engine/generators/appeal_xml.py`: XML 序列化與全形轉換純函式。
- `src/elc_audit_engine/generators/__init__.py`: re-export `appeal_xml` 函式。
- `scripts/build_appeal_xml.py`: 背景 CLI 腳本。
- `tests/test_appeal_xml.py`: 結構組裝、空值省略、全形轉換、Big5 fail-fast 與 CLI 測試。
- `README.md`: Package Builder 工具說明與範圍紀錄。

## 檢驗

- `./.venv/bin/python -m pytest tests/test_appeal_xml.py -q`: 11 passed
- 全測試套件通過（363 passed / 2 skipped）。
