# AGENTs.md — LLM & Autonomous Agents Guidance

Welcome, LLM Agent. This document outlines the core architecture, non-negotiable operational principles, development environment, and safety boundaries for the **Elcinsurrence** (`elc-audit-engine`) codebase.

---

## 1. Project Overview & Three-Track Workflows

`Elcinsurrence` is an automated NHI (Taiwan National Health Insurance / 健保) outpatient audit, pre-submission checking, and appeal assistance engine.

### Three-Track Automation Architecture
1. **Stage 1: Monthly Pre-Audit Workflow (當月申報檔預審)**
   - **Purpose**: Full-volume audit of all outpatient cases in `TOTFA.zip` before official submission (days 1~5 of each month).
   - **Outcome**: Flag high-cost orders, rule non-compliances, and C-category payment standards; generate interactive HTML/JSON review cards.
   - **Entrypoint**: `POST /api/monthly/upload`, `src/elc_audit_engine/monthly_audit.py`.
2. **Stage 2: Sampling Pre-Audit & Packager Workflow (抽樣事前預審)**
   - **Purpose**: Evaluate medical record compliance before submitting抽審 to NHI.
   - **Outcome**: Read-only support assessment (`✅ 充分` / `⚠️ 薄弱` / `❌ 裸奔`) + 6-month historical timeline matching + EvidenceVault auto-mounting (`{id_card}-{fee_ym}`).
   - **Entrypoint**: `run_presubmission_check` in `src/elc_audit_engine/pipeline.py`.
   - **Constraint**: **Read-only, no side-effects, does NOT produce appeal drafts.**
3. **Stage 3: Appeal Post-processing Workflow (核減事後申復)**
   - **Purpose**: Process NHI deduction notices and generate formal 4-section appeal materials.
   - **Outcome**: 4-section appeal arguments (D10 standard) + export to Big5 XML (p1~p9) / ODT / PDF evidence packets.
   - **Entrypoint**: `run_case_pipeline` in `src/elc_audit_engine/pipeline.py`.

---

## 2. Hard Invariants & Non-Negotiable Constraints (BLOCKING)

Whenever modifying or analyzing this codebase, you MUST adhere to the following rules:

1. **Fake Data is Worse than No Data (絕對不可捏造)**
   - Never fabricate medical rules, citations, diagnosis codes, or conclusions.
   - Rules must be exact verbatim text extracted from the knowledge base / official docx tables.
   - In rule mapping, the LLM only **selects** candidates from predefined options (`choice-v2` scheme); it NEVER free-writes rule content.
   - Citations must match exact substrings of the patient SOAP record (`judger._verify_quote`).

2. **System Failure ≠ Business Conclusion (P1-1 / P0-2 原則)**
   - A failure in an LLM call or network timeout must NEVER masquerade as a clinical determination.
   - Distinguish the 3 non-conclusive states:
     - ❌ **裸奔 (`support_level == "裸奔"`)**: Record was examined and lacks required evidence (Clinical conclusion).
     - ⏳ **待判定 (`support_level is None and undetermined is True`)**: LLM failed, timed out, or crashed (System failure).
     - ❓ **查無規則 (`support_level is None and rule_found is False`)**: Order code has no matching NHI payment rule.
   - If an LLM call fails, the case state transitions to `failed`, NEVER to `reviewed`.

3. **`case_id` is the ONLY Global Primary Key**
   - `case_id` is a content-hash or globally unique ID (`SAMP-...` / `APP-...`). It is immutable and collision-proof.
   - `case_seq` (健保流水號) is only unique per fee-month/case-class and repeats across months.
   - **Never** use `case_seq` as a database primary key, storage key, or attachment key. Attachment directories, evidence packets, and lookups MUST use `case_id`.

4. **Zero PHI Leakage in Logs & Audit Trails**
   - Access logs (`data/audit/access.log`) must adhere strictly to 6 metadata fields: `ts`, `caller_id`, `method`, `path`, `status`.
   - Never log patient names, ID numbers, birth dates, or SOAP text. Attempting to pass prohibited fields raises `AuditFieldError`.

5. **Security & Authentication**
   - Batch PHI endpoints (`GET /api/sampling/cases`, `GET /api/appeal/cases`), attachments queries/deletions, and PDF downloads mandate `X-API-Key`.
   - `ELC_ALLOWED_HOSTS` whitelist protects against DNS rebinding.

---

## 3. Architecture & Codebase Map

- **`src/elc_audit_engine/`**:
  - **`api/`**: Modular Flask app created via factory pattern (`create_app`), separated into Blueprints:
    - `monthly`: `/api/monthly/*` (TOTFA upload, monthly batch pre-audit reports & clear endpoints, `GET /api/monthly/batch/<id>/package` ZIP download). Batch ID is `MONTHLY-YYYYMM` or `MONTHLY-YYYYMM-<機構代碼>` (Phase 29); uploads never overwrite the clinic's facility profile, and downloads require a confirmed profile (412 otherwise)
    - `sampling`: `/api/sampling/*` (Stage 2 pre-audit, closed-loop batch audit, batch XML export, unified batch report)
    - `appeal`: `/api/appeal/*` (Stage 3 appeal drafts, linkage from Stage 2, batch appeal XML export, unified batch report)
    - `emr_packaging`: `/api/emr/*` (11-code standard packaging, 500MB ZIP chunking, package listings & downloads)
    - `attachments`: `/api/appeal/attachments/*`
    - `print`: `/api/deduction/print`, `/api/appeal/evidence-packet/print`
    - `security`: Authentication, host whitelisting, and authorization hooks.
  - **`case_store/`**: SQLite-backed case repository with ACID transitions and collision detection (supports `kind='monthly'|'sampling'|'appeal'`).
  - **`attachment_store.py`**: SQLite-indexed attachment manager keyed by `case_id`.
  - **`evidence_vault.py`**: Local evidence vault keyed by `{id_card}-{fee_ym}` storing audio (`.opus`, `.flac`, `.wav`), images, and reports with regex boundary validation.
  - **`webbrain_bridge.py`**: Local WebBrain bridge (`ws://127.0.0.1:17374/extension`) for NHI Cloud 2.0 history extraction (`mode="ask"`), SOAP O-section lab injection, cross-hospital duplicate drug detection, and Stage 2/3 semantic button driving.
  - **`agent_desktop_bridge.py`**: Windows UIA automation interface executing Observe–Act–Verify loop, 3-tier fallback (ValuePattern -> Clipboard -> Copy Card), STALE_REF recovery, and HIS vendor profiles (Vision, Yaosheng, Minger, Chihshi).
  - **`bridge_queue.py`**: SQLite CAS atomic task queue managing jobs for `15`, `00`, `07`, `09`, `HIS_PUSH`, `WB_EXTRACT_MED`, `WB_UI_VERIFY`.
  - **`installer/build_clinic_installer.py`**: Single-click clinic workstation client installer script generator (`clinic_installer.iss`, `start_clinic_client.bat`).
  - **`unified_review_report.py`**: Unified review report generator aligning Stage 2 and Stage 3 batch views with the MONTHLY-YYYYMM report format.
  - **`reconciliation/`**: Automatic month-start `TOTFA.zip` reconciliation against daily clinic outpatient voice SOAP records (`soap_reconciler.py`), populating SOAP into `CaseStore` for Stages 2 & 3.
  - **`packagers/`**: NHI EMR batch packaging engine (`emr_batch_packager.py`) generating 11-code filenames, A/B/C/D 4-tier classification, A-tier PDF outline bookmarks, and 500MB ZIP chunking at 450MB threshold.
  - **`pipeline.py`**: Pipeline coordinators (`run_presubmission_check` and `run_case_pipeline`).
  - **`rule_repository/`**: SQLite rule store, docx tree indices, and LLM mapping scripts.
  - **`parsers/`**: Parsers for XML declarations (TOTFA), deduction notifications, and outpatient SOAP text.
  - **`generators/`**: Builders for appeal drafts, Big5 XML (`appeal_xml.py`, `sampling_xml.py`), tracking tables, ODT/PDF templates, and evidence packets.

- **`server.py`**: WSGI entrypoint (`server:app`) delegating to `elc_audit_engine.api.create_app()`. Production runs it via gunicorn under systemd (see §6); `python server.py` is development-only (Flask dev server, debug-capable).
- **`deploy/`**: Production service files — `gunicorn.conf.py`, systemd user units (`elc-audit-engine.service`, healthcheck `.service`/`.timer`), `healthcheck.sh`, env template, and `README.md` (LAN guidance).
- **`scripts/`**: CLI builders for appeal print, XML, deduction sheets, and evidence packets.

---

## 4. Herdr Multi-Agent Collaborative Architecture

When operating within the Herdr terminal workspace manager (`HERDR_ENV=1`), tasks are coordinated across specialized agents pinned to panes in workspace `w7`:

| Terminal Pane | Assigned Agent | Model & Capabilities | Core Responsibilities |
| :--- | :--- | :--- | :--- |
| **`w7:p1`** | **Antigravity (Agy)** | `inherit` / `gemini-2.5-pro` (Central Agent) | **執行中樞、階段規劃與測試審核**<br>• GSD 階段規劃 (`/gsd-plan-phase`、`/gsd-execute-phase`)<br>• 跨 Agent 任務指派與進度監控<br>• 全套件整合測試、API 契約檢查與最終代碼合規驗收 |
| **`w7:p2`** | **Claude** | Claude Code CLI (Executor) | **執行核心代碼實作與打包邏輯編寫**<br>• 健保 11 碼標準檔名編碼與資料屬性分類邏輯 (`emr_batch_packager.py`)<br>• A 類高畫質 PDF 書籤生成器與 500MB ZIP 動態分包實作<br>• 診間 HIS 雙向回寫與資料庫同步功能維護 |
| **`w7:p3`** | **Hermes** | Hermes Agent / Qwen3.8-27B-FP8 | **待命狀態，負責邊界案例測試與本地模型推理比對**<br>• Qwen3.8-27B-FP8 本地大模型臨床推理與 SOAP 比對建議檢驗<br>• 異常輸入、缺欄位降級、中文檔名阻斷等邊界壓力測試<br>• 離線環境推論穩定度確認 |

---

## 5. Execution & Testing Conventions

- **Environment Manager**: `uv`
  - Sync dependencies: `uv sync`
  - Run server (production, managed): `systemctl --user restart elc-audit-engine.service` — do NOT start a second instance on port 5000
  - Run server (dev only, foreground): `uv run python server.py`
  - Run tests: `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests`
  - Dependency pitfall: the user's global `~/.config/uv/uv.toml` sets `constraint-dependencies = ["pydantic<2.11"]`, which silently downgrades pydantic on `uv add`/`uv lock`. Lock with `uv lock --no-config` (or `--no-config` on `uv add`) so only the intended package changes; verify with `git diff uv.lock`.
- **Testing Guardrails**:
  - Never write to production databases (`data/db/cases.sqlite3`) in tests.
  - Use fixtures from `tests/conftest.py` (e.g., `make_api_app`) which create temporary isolated databases.
- **Herdr Environment**:
  - When running inside Herdr (`HERDR_ENV=1`), coordinate long-running jobs or agent tasks across assigned panes (`claude-executor` for coding/execution, `hermes-test` for tests, server panes for runtimes).

---

## 6. Deployment & Service Stability (systemd)

The production server is a **systemd user service** (not a manual terminal process).

| Item | Value |
| :--- | :--- |
| Service | `elc-audit-engine.service` (gunicorn 26.2.0, `server:app`, 1 worker × 8 threads) |
| Restart | `Restart=always`, `RestartSec=3`; start-limit 10 failures / 300 s |
| Crash record | `logs/crash.log` (written on every stop: `result`, `exit_code`, `exit_status`) |
| Logs | `logs/access.log`, `logs/error.log` (gunicorn + Python tracebacks), `logs/healthcheck.log` |
| Health | `GET /api/health` (auth-exempt). `elc-audit-engine-healthcheck.timer` runs `deploy/healthcheck.sh` every 60 s; restarts after 3 consecutive failures |
| Config | `~/.config/elc-audit-engine/env` (mode 600; template `deploy/elc-audit-engine.env.example`) — **never commit** |
| Units | `~/.config/systemd/user/` (copies of `deploy/*.service|*.timer`). Re-copy and `systemctl --user daemon-reload` after editing `deploy/` |
| Boot | Linger enabled for user `hsu` → starts at boot without login |
| Bind | `ELC_SERVER_HOST=127.0.0.1` (local only). Do not change to `0.0.0.0` without the LAN steps below |

**Operations**
- Status / restart / logs: `systemctl --user status|restart elc-audit-engine.service`, `journalctl --user -u elc-audit-engine.service -f`
- Crash forensics: `cat logs/crash.log logs/error.log`
- Verify: `curl http://127.0.0.1:5000/api/health` → `{"status":"ok"}`

**LAN exposure checklist (required before serving other machines)**
1. Keep gunicorn on `127.0.0.1`; put Caddy/Nginx with TLS in front.
2. Set `ELC_ALLOWED_HOSTS` to the LAN hostname/IP (no port).
3. Replace the development key `clinic:dev-key-for-local-dev-001` with strong per-client keys.
4. Ensure `DISABLE_AUTH` is unset.
5. Firewall: allow only the LAN subnet; do not open port 5000.
6. Back up `data/` and `logs/`; `data/` contains patient-related data.

**Known open items**
- Nine pre-existing test failures (monthly SOAP pregen ×7, `test_monthly_report_ux`, `test_sampling_evidence_preview`) reproduce on the original code; not caused by deployment changes. Track separately.
- `logs/healthcheck.log` may show one `failed (1/3)` line at service start (startup race); harmless below the threshold.
- Uncommitted: `pyproject.toml`, `uv.lock` (gunicorn added), `.gitignore` (`logs/`), `deploy/`, `AGENTs.md`.
