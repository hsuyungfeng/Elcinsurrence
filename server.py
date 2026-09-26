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
    # 安全預設（P0-1）：綁定 127.0.0.1、debug 關閉。
    # 原設定 host='0.0.0.0' + debug=True 等於無認證對全網卡開放，且
    # 例外會回顯堆疊；本服務會接觸病歷資料，不得如此。
    # 需對外提供時請置於反向代理／VPN 後，並以環境變數覆寫：
    #   ELC_SERVER_HOST=0.0.0.0 ELC_SERVER_PORT=5000 python server.py
    # 認證：before_request 依 api.security.AUTH_EXEMPT_ENDPOINTS 決定是否強制 X-API-Key
    # （案件清單、附件清單／刪除、PDF 下載必填；其餘選填，見該清單註解）。
    # ELC_API_KEYS 未設定時服務啟動即失敗（fail-fast）。
    # 對外部署另須設定 ELC_ALLOWED_HOSTS（Host header 白名單）。
    host = os.getenv('ELC_SERVER_HOST', '127.0.0.1')
    port = int(os.getenv('ELC_SERVER_PORT', '5000'))
    debug = os.getenv('ELC_SERVER_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
