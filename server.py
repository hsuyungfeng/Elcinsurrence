"""Elcinsurrence Web Dashboard Backend API Server (Flask).

支援兩大核心獨立工作流：
1. 抽樣事前預審工作流 (/api/sampling/*)
   - 上傳 CSV 抽樣清單
   - 審核原有病歷並評估「醫令支持度」（充分/薄弱/裸奔）
   - 產出「病歷補強報告」供抽審送出前先補強

2. 核減事後申復工作流 (/api/appeal/*)
   - 導入核減明細 (刪減醫令)
   - 啟動針對刪減醫令之多源證據補強（整合門診 SOAP、檢驗、影像、雲端病歷）
   - 生成 4 段式申復理由草稿 (≤2000字) 與申復 XML 欄位

WSGI／開發伺服器入口。路由與邏輯位於 `elc_audit_engine.api`（app factory＋
blueprints，review IN-04）；本檔只負責建立 app，匯入 `server` 會依環境變數
載入 API key、開啟 CaseStore 並遷移舊版匯入快照。

    gunicorn server:app            # 或
    python server.py
"""

import os

from elc_audit_engine.api import create_app

app = create_app()


if __name__ == '__main__':
    # 區域網路部署（Phase 32-A）：院內信任模式下 host 需為 0.0.0.0 才能讓
    # 診間電腦連入；存取控制由 api.security 的 before_request 以**來源位址**
    # 把關（僅放行 loopback 與伺服器所在子網，其餘回 403），不再使用金鑰。
    # 預設仍為 127.0.0.1，由部署腳本（deploy/install.sh）明示設定對外綁定。
    # debug 一律關閉：例外回顯堆疊會洩漏路徑與程式結構。
    host = os.getenv('ELC_SERVER_HOST', '127.0.0.1')
    port = int(os.getenv('ELC_SERVER_PORT', '5000'))
    debug = os.getenv('ELC_SERVER_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
