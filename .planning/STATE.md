---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: milestone
current_phase: 32
status: Phase 32 文件與程式層級完成；外部實機驗收未完成
stopped_at: null
last_updated: "2026-11-16T14:00:00.000Z"
last_activity: 2026-11-16 — Phase 32.1 CSP style-src 嚴格化（'self'）與 Ruff 規則回復（移除 F841/B007/F811 放寬）完成
progress:
  total_phases: 32
  completed_phases: 31
  total_plans: 24
  completed_plans: 24
  percent: 100
---

# STATE.md — elc-audit-engine

## 目前位置 (Current Position)

- **Phase 32**：院內免驗證客戶端一體化與醫師上手（Fable 5.2 改進計畫落實）
- **狀態**：24/24 Plans 的程式與文件已完成並合併至 `main`（最新提交 `86a605c`）。**外部實機驗收尚未進行**，Phase 32 不應視為完全驗收通過。
- **最近裁示**：D-32-27 撤回管理設定僅限本機的限制（取代 D-32-19、D-32-25）。

## 已完成成果 (Completed Work)

- **第一期交付（提交 `01e1a13`，per D-32-15）**：
  - A1–A8 院內信任模式：以來源 IP 網段判定存取（取代 API Key）、跨站寫入防護（Origin／Sec-Fetch-Site）、Host 標頭形式檢查防 DNS rebinding。
  - B1 快捷列接進執行檔；B2 無主控台模式；C1 移除寫死診所 IP。
- **Phase 32 程式與文件（提交 `a01a3be`、`607329b`、`86a605c` 等）**：
  - 網段自動偵測（讀實際遮罩、排除 VPN／虛擬介面）、跨站 GET 拒絕（D-32-18）。
  - 管理寫入限制已依 D-32-27 撤回（原 D-32-19 不再適用）。
  - 容量預警 180／90 天、只增不刪的備份、SoapVoice 守護程序、首次啟動精靈、E8 前端拆檔、醫師模式導引、雙手冊。
- **測試**：工作區全套件 `1649 passed、2 skipped、1 deselected`（2026-11-16 重跑，含 D-32-27 改動）。

## 未結與承接項目 (Pending & Deferred Items)

- **Windows 實機人工驗收**：依 `31-WINDOWS-MANUAL-VERIFY.md` 的 12 項逐一測試（Phase 31 與 32 共同承接）。**尚未執行。**
- **Phase 30 的 30-09 探針重跑**：由 32-24 承接，尚未實際執行。
- **Ubuntu 一鍵安裝驗證**：`deploy/install.sh` 需在乾淨 Ubuntu Server VM 上實測。
- **Windows 打包驗證**：ElcAgent 與 `soapvoice_client.spec`（D-32-26）需在 Windows 環境建置。
- **CSP `style-src` 嚴格化（Phase 32.1 完成）**：原 292 處估計更正為實測 17 處（靜態 4 處全轉 class 獨立成檔，Python 產出 13 處為自包含離線檔不受 app CSP 約束），HTTP CSP `style-src` 已收緊為 `'self'`。
- **Phase 33（醫師工作台 E1–E7／E9）**：目錄 `.planning/phases/33*` 尚未建立。開始前需先對照 Phase 32 已完成的 E1、E2、E5、E6、E7，避免重複。
- **已確認裁示**：D-32-28（2GB 容量上限僅作警示，只刪已上傳資料）已於 2026-11-16 由使用者確認。D-32-24 的剩餘風險說明已寫入 `docs/CLINIC_DEPLOYMENT_GUIDE.md` 第一節。

## 外部阻塞 (External Blockers)

- 無 Windows 原生 PE 建置環境（本機為 Linux，PyInstaller 建置依賴 Windows 實機或 CI）。
- 無乾淨 Ubuntu Server VM（install.sh 實機驗證依賴獨立主機）。

## 已知風險 (Known Risks)

- CI 的 ruff 檢查放寬已於 Phase 32.1 回復（移除 F841、B007 與 tests/** F811 豁免，修復 22 處未用變數與迴圈變數，以行級 noqa 標註 fixture shadowing，全專案 `ruff check .` 通過）。
- `config/facility.json` 含現場執行期變更，依交接規定不納入 git 提交，目前以未追蹤／未提交狀態保留。
- 同網段任何裝置皆可修改管理設定（D-32-27 已接受之取捨，僅限院內網路）。
- `Wavesample/`（約 227MB 訓練資料）位於專案目錄內，已被 `.gitignore` 排除，但建議移出。
