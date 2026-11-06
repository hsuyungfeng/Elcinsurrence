# Phase 13-02: ODT Filling & PDF Rendering Engine

## 執行摘要
本階段實作了核減明細表的 ODT 模板填充機制與 PDF 渲染轉換引擎，透過 `xml.etree.ElementTree` 安全處理特殊字元防範 XML Injection (T-13-01)，並利用 `subprocess` 與 `tempfile` 呼叫 LibreOffice 進行安全隔離的 PDF 轉換 (T-13-03, T-13-04)。

## 完成項目
- **13-02-01: ODT 模板填充實作**
  - 建立 `src/elc_audit_engine/generators/deduction_print/odt_fill.py`，支援動態搜尋原型列 (prototype row) 並複製擴增。
  - 實作防護機制 `set_cell_text` 透過 XML 樹節點屬性直接指派，防範 XML Injection。
  - 修改 `test_deduction_print.py` 中 `-k odt` 和 `-k security` 測試案例，確保 XML 安全處理與填充功能正常。
- **13-02-02: PDF 渲染引擎入口**
  - 建立 `src/elc_audit_engine/generators/deduction_print/__init__.py`，導出 `render_deduction_print` 與 `write_deduction_print`。
  - 套用 `tempfile.TemporaryDirectory` 與 `safe_filename` 以阻絕中間產物碰撞和路徑穿越漏洞。
  - 使用 `subprocess.run` 呼叫 LibreOffice `soffice --headless` 以非互動模式進行 PDF 轉換。
  - 更新 `src/elc_audit_engine/generators/__init__.py`，加入導出。
  - 修改 `test_deduction_print.py` 的 E2E 測試 (`-k e2e`)，自動套用真實版控 ODT 模板建立安全沙盒完成轉檔驗證。

## 測試狀態
所有 `test_deduction_print.py` 測試均已通過，包含 mapping, odt, security, e2e。
