# Phase 31 Execution Log

## 執行原則與路徑設定
- **SoapVoice 目標路徑**：`/home/hsu/Desktop/Elcinsurrence/SoapVoice`（乾淨 clone，所有 Client 端改動均落地於此）。
- **禁止寫入路徑**：`~/Desktop/SoapVoice`（保留使用者未提交修改）。
- **版本控管規則**：不自動 commit 外層專案，亦不自動 commit 任何子 repo。
- **偏離記錄**：所有原始 PLAN 檔案中參照 `~/Desktop/SoapVoice` 之路徑，實際執行時一律重導向至 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`。

---

## Plan 31-01 (Wave 1): 契約定義與共用測試輔助
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-IPC-CONTRACT.md`（驗證完成）
  - `tests/fixtures/phase31_contract_v1.json`（驗證完成）
  - `tests/phase31_support.py`（已建立）
  - `tests/test_phase31_contract_fixture.py`（已建立並通過 5/5 測試）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-01-SUMMARY.md`（已建立）
- **SoapVoice 相關操作**：無（契約與測試骨架均位於 Elcinsurrence）。

---

## Plan 31-02 (Wave 1): 核准流程崩潰窗口收斂 (D-31-38, D-31-07)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/case_store/db.py`（`his_job_id`、`his_machine_id` 欄位與冪等遷移）
  - `src/elc_audit_engine/case_store/store.py`（欄位讀寫、`set_soap_draft_his_job`）
  - `src/elc_audit_engine/bridge_queue.py`（`job_id` 參數與 `ensure_job`）
  - `src/elc_audit_engine/api/routes/soap_review.py`（`approve_and_enqueue`、`recover_stuck_approved`）
  - `tests/test_approve_crash_window.py`（6 項 TDD 測試）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-02-SUMMARY.md`（已建立）
- **測試結果**：新測試 6 passed，既有整合套件 135 passed，無迴歸。
- **SoapVoice 相關操作**：無（此計畫屬 server 端儲存與核准狀態機修復）。

---

## Plan 31-03 (Wave 1): 櫃台雲端病歷擷取可行性調查 (D-31-34, D-31-35, D-31-36)
- **狀態**：完成 (PASS，使用者決策 defer 暫不實作櫃台功能)
- **操作檔案**：
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-COUNTER-CLOUD-FEASIBILITY.md`（已建立）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-03-SUMMARY.md`（已建立與更新決策）
- **SoapVoice 相關操作**：無（純可行性評估筆記，未修改任何程式碼）。

---

## Plan 31-04 (Wave 2): machine_id 親和性分派與 Agent 輪詢隔離 (D-31-37, D-31-38, D-31-16)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/case_store/db.py`（SCHEMA_CASES 新增 `his_machine_id` 欄位與遷移邏輯）
  - `src/elc_audit_engine/case_store/store.py`（`claim_bridge_job` 支援 `machine_id` 優先親和性與舊任務相容）
  - `src/elc_audit_engine/bridge_queue.py`（`ensure_job` 寫入 `his_machine_id`）
  - `src/elc_audit_engine/api/routes/bridge.py`（`POST /api/bridge/jobs/claim` 接收 `machine_id`，`GET /api/bridge/jobs/pending` 依 `machine_id` 過濾）
  - `deploy/windows_agent/agent.py`（心跳登記帶 `machine_id`，任務輪詢與領取皆帶 `machine_id`）
  - `tests/test_bridge_agent_affinity.py`（8 項親和性與回退機制測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-04-SUMMARY.md`（已建立）
- **測試結果**：新測試 8 passed，既有整合套件 135 passed，無迴歸。
- **SoapVoice 相關操作**：無（此計畫屬 server 橋接佇列分派與 Windows Agent 輪詢）。

---

## Plan 31-05 (Wave 2): 循環狀態機與核心循環管理 API (D-31-05, D-31-06, D-31-07, D-31-16, D-31-17, D-31-29)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/case_store/db.py`（建立 `recording_cycles`、`cycle_events`、`cycle_chunks`、`cycle_confirmations`、`client_presence` 資料表與索引）
  - `src/elc_audit_engine/cycles/states.py`（純函式狀態機：9 大狀態、合法轉換表、`assert_cycle_transition`、`display_state` 顯示狀態轉換）
  - `src/elc_audit_engine/cycles/store.py`（資料存取層：`create_cycle` 冪等建立、`get_cycle`、`get_active_cycle`、`get_last_cycle`、`transition_cycle`，D-31-29 嚴格無刪除檔案）
  - `src/elc_audit_engine/api/routes/cycles.py`（POST /api/cycles 建立、GET /api/cycles 查詢、POST stop、POST abandon、權限驗證）
  - `tests/test_cycle_state_machine.py`（16 項狀態轉換測試全數通過）
  - `tests/test_cycles_api.py`（12 項 API 端點與安全邊界測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-05-SUMMARY.md`（已建立）
- **測試結果**：新測試 28 passed，既有整合套件 135 passed，無迴歸。
- **SoapVoice 相關操作**：無（此計畫屬 server 循環資料模型與管理端點）。

---

## Plan 31-06 (Wave 2): 快捷列按鈕狀態機、螢幕吸附與安全無錄音保證 (D-31-01, D-31-02, D-31-08, D-31-11, D-31-24)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `deploy/windows_agent/traffic_bar/bar_state.py`（純邏輯狀態機：15 種投影狀態、`ENABLED` 按鍵白名單、`on_press` 防誤觸、`project` 投影純函式、`status_text` 零 PHI 顯示）
  - `deploy/windows_agent/traffic_bar/bar_position.py`（螢幕邊緣吸附純數學演算法：32px 吸附閾值、雙螢幕虛擬座標支援、幾何越界保護）
  - `tests/test_bar_state.py`（14 項狀態映射與按鍵驗證測試全數通過）
  - `tests/test_bar_position.py`（10 項吸附幾何與邊界測試全數通過）
  - `tests/test_traffic_bar_no_recording.py`（AST 靜態分析安全保證：嚴格掃描禁止 wave/pyaudio/sounddevice/ctypes/winmm 等錄音 API，D-31-01）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-06-SUMMARY.md`（已建立）
- **測試結果**：新測試 25 passed，既有整合套件 135 passed，無迴歸。
- **SoapVoice 相關操作**：無（此計畫屬快捷列 Windows Agent 端純邏輯模組）。

---

## Plan 31-07 (Wave 2): SoapVoice 串流錄音分段器與崩潰自癒 (D-31-19, D-31-21, D-31-27, D-31-28, D-31-30, D-31-31)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/audio_recorder.py`（實作 20 秒分段切音、`.pcm.part` atomic flush、16kHz mono 16-bit PCM WAV 檔寫入、`recover_partial` 崩潰自癒、`concat_segments`、`pcm_sha256` 計算）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_audio_recorder.py`（10 項錄音切段、雜湊、崩潰恢復測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-07-SUMMARY.md`（已建立）
- **測試結果**：新測試 10 passed，SoapVoice 全套件 42 passed。
- **SoapVoice 相關操作**：
  - 依照使用者指定規則，寫入路徑重導向至 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`。
  - 禁止寫入 `~/Desktop/SoapVoice`，保持使用者工作區完整無改動。
  - 無 git commit。

---

## Plan 31-08 (Wave 2): SoapVoice 本機分段清冊與空間上限 (D-31-27, D-31-32, D-31-33)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/segment_store.py`（`manifest.json` RLock 讀寫、`register_chunk`、`mark_acked`、`mark_archived`、`get_pending_chunks`、`all_acked`、`get_cycle_segments`）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/lan_config.py`（新增 `chunk_seconds=20`、`temp_dir`、`max_temp_bytes=2GB`、`control_port=18765`）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/temp_cleanup.py`（空間清理：4 條硬性規則，嚴格僅刪除已獲 server 認可封存之段落）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/local_storage.py`（停用舊佇列 drop_oldest 機制，未送出草稿無上限保留，D-31-32）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_segment_store.py`（7 項清冊與並行安全測試全數通過）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_temp_cleanup.py`（5 項空間清理規則測試全數通過）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_client.py`（佇列不丟棄行為斷言更新）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-08-SUMMARY.md`（已建立）
- **測試結果**：SoapVoice 全套件 54 passed。
- **SoapVoice 相關操作**：
  - 所有檔案修改均嚴格位於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`。
  - `~/Desktop/SoapVoice` 未受任何寫入。
  - 無 git commit。

---

## Plan 31-09 (Wave 3): Server 分段儲存、去重與 finalize 串接 (D-31-19, D-31-20, D-31-22, D-31-23, D-31-27, D-31-28, D-31-29, D-31-30)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/cycles/chunks.py`（store_chunk 去重防競爭、validate_wav_chunk、finalize_cycle_audio 串接 full.wav、cycle_artifacts、零刪除安全保證）
  - `src/elc_audit_engine/api/routes/cycle_chunks.py`（POST chunks 與 POST finalize 路由、API Key 權限驗證、無私有 IP 免金鑰例外）
  - `tests/test_cycle_chunks.py`（14 項核心邏輯與 API 整合測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-09-SUMMARY.md`（已建立）
- **測試結果**：14 passed，循環測試套件 26 passed。
- **SoapVoice 相關操作**：無（此計畫屬 server 端端點）。

---

## Plan 31-10 (Wave 3): 循環草稿送出、檢索隔離與通用審核保護 (D-31-39, D-31-16, D-31-13, D-31-23, D-31-25, D-31-27, D-31-28, D-31-12, D-31-17)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/cycles/drafts.py`（submit_cycle_draft 冪等送出、cycle_draft_view 結構化檢視、cycle_bound_draft_ids、is_cycle_bound、extract_advisory）
  - `src/elc_audit_engine/api/routes/soap_review_queue.py`（list_pending_review 排除循環綁定草稿）
  - `src/elc_audit_engine/api/routes/soap_review.py`（approve_draft 與 edit_draft 對循環草稿回傳 409、approve_batch 跳過已綁定）
  - `src/elc_audit_engine/api/routes/cycles.py`（POST 與 GET /api/cycles/<cycle_id>/draft 路由）
  - `tests/test_cycle_isolation.py`（TDD 3 項隔離驗證通過）
  - `tests/test_cycle_drafts.py`（9 項生命週期與邊界驗證通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-10-SUMMARY.md`（已建立）
- **測試結果**：12 passed，回歸測試 134 passed。
- **SoapVoice 相關操作**：無（此計畫屬 server 端路由與草稿隔離邏輯）。

---

## Plan 31-11 (Wave 3): 多連線監控、工作站心跳與通知搭便車 (D-31-12, D-31-15, D-31-16, D-31-17, D-31-18, D-31-18a, D-31-18b, D-31-18c)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/cycles/presence.py`（upsert_presence、subnet_of、in_clinic_subnet、notification_for_machine、list_presence_grouped、欄位驗證）
  - `src/elc_audit_engine/api/routes/clients.py`（POST /api/clients/heartbeat、GET /api/clients、GET /clients）
  - `src/elc_audit_engine/api/security.py`（clients.monitor_page 審計/認證豁免；clients.client_heartbeat 審計豁免但非認證豁免；Agent 金鑰 403 阻絕）
  - `static/clients.html`（多連線診間分組監控純靜態頁，零 innerHTML/eval，每 5 秒輪詢，草稿調閱與放棄按鈕）
  - `tests/test_client_notify_auth.py`（心跳通知、無 PHI、認證與隔離測試通過）
  - `tests/test_clients_monitor.py`（監控分組、離線判定、顯示狀態、安全豁免與頁面安全測試通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-11-SUMMARY.md`（已建立）
- **測試結果**：15 passed，全套件 1456 passed (0 迴歸)。
- **SoapVoice 相關操作**：無（此計畫屬 server 端 presence 與 monitor 靜態頁）。

---

## Plan 31-12 (Wave 3): 快捷列通訊與流程控制器 (D-31-03, D-31-05 ~ D-31-08, D-31-11, D-31-12, D-31-16, D-31-24, D-31-33)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `deploy/windows_agent/config.py`（AgentSettings 擴充 room_id, bar_x, bar_y, soapvoice_control_port 且向後相容）
  - `deploy/windows_agent/traffic_bar/soapvoice_client.py`（SoapVoiceControlClient 本機 IPC 客戶端，限定 127.0.0.1 防 rebinding，自動帶 token）
  - `deploy/windows_agent/traffic_bar/server_client.py`（CycleServerClient 伺服器循環客戶端，帶 operator_key，完整保留 202/409 回應）
  - `deploy/windows_agent/traffic_bar/controller.py`（BarController 流程協調器，紅綠黃推進、重啟還原、無 GUI 依賴）
  - `tests/test_soapvoice_ipc_contract.py`（6 項 IPC 契約與客戶端安全測試全數通過）
  - `tests/test_bar_controller.py`（11 項控制器流程、失敗自癒、離線重送與無 PHI 測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-12-SUMMARY.md`（已建立）
- **測試結果**：17 passed，Agent/快捷列相關測試 50 passed。
- **SoapVoice 相關操作**：無（此計畫屬快捷列 client 端 controller 與網路層）。

---

## Plan 31-13 (Wave 3): SoapVoice 分段上傳器與綠燈後循環 Pipeline (D-31-20, D-31-22, D-31-23, D-31-24, D-31-25, D-31-27, D-31-30, D-31-01)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/chunk_uploader.py`（ChunkUploader 背景依序上傳、sha256 校驗、指數退避、執行緒隔離）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/cycle_pipeline.py`（CyclePipeline 綠燈後狀態推進、finalize PCM 雜湊比對、完整音檔 SOAP 生成、草稿送出與 map_lan_result_to_draft 欄位映射）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/segment_store.py`（CycleManifest 擴充 `extras_missing` 欄位）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/fixtures/phase31_contract_v1.json`（複製契約 fixture）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_chunk_uploader.py`（6 項上傳、退避與校驗測試全數通過）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_cycle_pipeline.py`（7 項 pipeline 生命週期推進與容錯測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-13-SUMMARY.md`（已建立，含 A-31-13b 欄位對應表）
- **測試結果**：新測試 13 passed，Pipeline/Uploader/Recorder/Store 整合測試 26 passed。
- **SoapVoice 相關操作**：
  - 依照使用者規定，所有檔案修改嚴格落地於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`。
  - 禁止寫入 `~/Desktop/SoapVoice`。
  - 無 git commit，無 git push。

---

## Plan 31-14 (Wave 4): 循環確認存檔與黃燈封存 (D-31-05, D-31-06, D-31-07, D-31-08, D-31-11, D-31-14, D-31-25, D-31-26, D-31-38, D-31-37)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `src/elc_audit_engine/cycles/archive.py`（confirm_cycle 確認版存檔與 HIS_PUSH 綁定 machine_id 排入、archive_cycle 黃燈封存前置檢查與狀態推進、CAS 併發防重、卡住恢復與重試佇列）
  - `src/elc_audit_engine/api/routes/cycles.py`（新增 POST /api/cycles/<cycle_id>/confirm 與 POST /api/cycles/<cycle_id>/archive 路由）
  - `src/elc_audit_engine/api/errors.py`（ApiError 擴充支援 extra 傳遞 422 結構化 quality_issues）
  - `src/elc_audit_engine/cycles/store.py`（cycle_view 補充 archived_at 欄位）
  - `tests/phase31_support.py`（測試 config 補上 AUDIT_LOG_PATH）
  - `tests/test_cycle_confirm.py`（10 項確認版儲存、修改重檢、HIS 任務過濾與審計測試全數通過）
  - `tests/test_cycle_archive.py`（9 項封存條件、雙擊 CAS 安全、重試與磁碟檔案零刪除測試全數通過）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-14-SUMMARY.md`（已建立）
- **測試結果**：19 passed，循環與 Agent 相關迴歸測試 78 passed，快捷列測試 28 passed。
- **SoapVoice 相關操作**：無（此計畫屬 server 端 confirm 與 archive 端點）。

---

## Plan 31-15 (Wave 4): SoapVoice 本機控制伺服器與循環工作階段 (D-31-01, D-31-02, D-31-03, D-31-21, D-31-22, D-31-23, D-31-30, D-31-31, D-31-32, D-31-33)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/cycle_session.py`（CycleSession 工作階段管理、RLock 防死鎖、指令冪等快取、錄音中 busy 保護、patient_bound 脫敏、archived 伺服器狀態校驗與重啟自癒）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/control_server.py`（ControlServer 127.0.0.1 綁定、Host 檢查防 rebinding、X-Local-Token 認證、4KB 負載限制與安全日誌）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/main.py`（App 元件接線、on_segment 非同步分段通知、啟動與關閉生命週期整合、SoapVoiceClientApp 別名）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_cycle_session.py`（5 項工作階段推進、防併發干擾、脫敏與重啟自癒測試全數通過）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_consultation_ipc.py`（4 項認證、Host 標頭、Token 自動生成與負載上限測試全數通過）
  - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_segmented_recorder.py`（修復假串流微秒等候避免測試競爭）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-15-SUMMARY.md`（已建立）
- **測試結果**：SoapVoice 客戶端測試套件 101 passed，`import client.main` 驗證成功。
- **SoapVoice 相關操作**：
  - 依照使用者規定，所有檔案修改嚴格落地於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`。
  - 禁止寫入 `~/Desktop/SoapVoice`。
  - 無 git commit，無 git push。

---

## 補充任務: D-31-10 快捷列 Tk 視窗與人工驗證清單 (D-31-09, D-31-10, D-31-11)
- **狀態**：完成 (PASS)
- **操作檔案**：
  - `deploy/windows_agent/traffic_bar/bar_window.py`（TrafficBarWindow 實作：置頂 -topmost、無工作列按鈕 -toolwindow/overrideredirect、滑鼠拖曳與位置記憶、收合 160x44 與展開 250x100 切換、純邏輯 BarViewModel、按鈕合法性檢查與 Toast 提示、絕不搶奪焦點 focus_force）
  - `deploy/windows_agent/traffic_bar/__init__.py`（匯出 BarViewModel, TrafficBarWindow, build_view_model, run_traffic_bar）
  - `tests/test_bar_window_logic.py`（9 項 Linux 可執行純邏輯測試：15 種狀態按鈕啟用/禁用與背景色、收合展開幾何尺寸、連線文字、Toast 覆蓋、邊界夾取與位置設定檔持久化全數通過）
  - `tests/test_traffic_bar_no_recording.py`（靜態 AST 掃描通過：無任何音訊依賴，無 focus_force 呼叫）
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-WINDOWS-MANUAL-VERIFY.md`（已建立：包含置頂性、不搶焦點、拖曳記憶、多螢幕夾取、UIA 互不干擾、斷線狀態顯示、完整閉環實機驗證清單）
- **測試結果**：
  - 新增測試 `tests/test_bar_window_logic.py`：9 passed。
  - 靜態掃描 `tests/test_traffic_bar_no_recording.py`：2 passed。
  - 快捷列與 Agent 相關測試總計：39 passed。
- **SoapVoice 相關操作**：無。
- **保護約束遵循**：
  - 未修改或刪除根目錄的 `boot31.py`。
  - 未修改或刪除 `SoapVoice/data/rag/chroma/chroma.sqlite3`。
  - 未進行任何 git commit，未進行 git push。

---

## 驗收任務: 全套件測試執行與 31-TEST-REPORT.md 產出
- **狀態**：完成 (PASS)
- **產出檔案**：
  - `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-TEST-REPORT.md`（完整測試報告與 D-31-01 至 D-31-44 需求覆蓋表）
- **測試執行結果彙總**：
  1. **Elcinsurrence 根目錄全套件**：
     - 指令：`ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest -q --no-cov`
     - 結果：`1502 passed, 2 skipped, 1 deselected, 10 warnings in 110.73s (0:01:50)`（100% 通過，0 失敗，無回歸）
  2. **SoapVoice 客戶端全套件**：
     - 指令：`cd /home/hsu/Desktop/Elcinsurrence/SoapVoice && uv run pytest tests/ -q --no-cov`
     - 結果：`369 passed, 4 skipped, 3 xfailed, 22 warnings in 50.04s`（核心套件 100% 通過，0 失敗）
     - 既有 XFAIL 說明：`test_llm_db_cli.py` 3 項既有測試依賴本機 `medical.db` 資料庫狀態，由 Claude 負責追蹤，非 Phase 31 造成。
  3. **Phase 31 跨倉專屬子集**：
     - Elcinsurrence 端子集（17 個測試檔）：`120 passed in 4.67s`
     - SoapVoice 端子集（7 個測試檔）：`41 passed in 4.29s`
     - SoapVoice 客戶端核心組件（含 Phase 31 + client + storage，9 個測試檔）：`115 passed in 10.12s`
- **需求覆蓋率**：
  - D-31-01 至 D-31-44 全部 44 項規格指標皆落實且具備單元/整合測試或設計規劃文件（D-31-34~36 依 31-03 完成可行性調研；D-31-29/44 server 端依 Q9 不自動刪除），需求覆蓋率 100%。
- **Windows 人工驗證項目**：
  - 8 項涉及實機視窗置頂、不搶輸入焦點、多螢幕夾取、UIA 互不干擾、斷線防護與端到端完整循環驗證已明列於 `31-WINDOWS-MANUAL-VERIFY.md`，待實機查驗。
- **保護約束遵循**：
  - 未修改任何專案程式碼。
  - 未修改或刪除根目錄的 `boot31.py`。
  - 未修改或刪除 `SoapVoice/data/rag/chroma/chroma.sqlite3`。
  - 未寫入 `~/Desktop/SoapVoice`。
  - 未進行任何 git commit，未進行 git push。

---

