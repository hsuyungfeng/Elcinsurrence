"""Gunicorn 設定：正式 WSGI 伺服器（取代 Flask 開發伺服器）。

- 綁定位址由環境變數決定：預設 127.0.0.1:5000（僅本機）。
  要開放區域網路時設 ELC_SERVER_HOST=0.0.0.0，且必須同時設定
  ELC_API_KEYS 與 ELC_ALLOWED_HOSTS（見 deploy/README.md）。
- 單一 worker + 多執行緒：SQLite（CaseStore）與本機 LLM 呼叫不宜多程序寫入。
- 日誌寫入 logs/，崩潰（worker 例外、啟動失敗）同時輸出至 error log。
"""

import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_log_dir = os.path.join(_root, "logs")
os.makedirs(_log_dir, exist_ok=True)

bind = "{}:{}".format(
    os.getenv("ELC_SERVER_HOST", "127.0.0.1"),
    os.getenv("ELC_SERVER_PORT", "5000"),
)

workers = 1
worker_class = "gthread"
threads = int(os.getenv("ELC_SERVER_THREADS", "8"))

# LLM 判定與文件產出可能耗時數分鐘，預設逾時放寬。
timeout = int(os.getenv("ELC_SERVER_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5

# 定期回收 worker，限制長時間執行的記憶體累積。
max_requests = 2000
max_requests_jitter = 100

accesslog = os.path.join(_log_dir, "access.log")
errorlog = os.path.join(_log_dir, "error.log")
loglevel = os.getenv("ELC_SERVER_LOGLEVEL", "info")
# 將 worker 內 print()／未捕捉的 stdout/stderr 也寫入 error.log，避免崩潰訊息遺失。
capture_output = True
access_log_format = '%(t)s %(h)s "%(r)s" %(s)s %(L)ss'

# 程序名稱（ps／systemd 顯示用）。
proc_name = "elc-audit-engine"
