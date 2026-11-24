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
   - If an LLM call fails (`OrderJudgment.llm_failed is True`), the case state transitions to `failed`, NEVER to `reviewed`. Conversely, an official rule row with `payment_text IS NULL` (no published restriction text) is a valid manual-review business outcome (`reviewed`), NOT an LLM failure (Phase 36).

3. **`case_id` is the ONLY Global Primary Key**
   - `case_id` is a content-hash or globally unique ID (`SAMP-...` / `APP-...`). It is immutable and collision-proof.
   - `case_seq` (健保流水號) is only unique per fee-month/case-class and repeats across months.
   - **Never** use `case_seq` as a database primary key, storage key, or attachment key. Attachment directories, evidence packets, and lookups MUST use `case_id`.

4. **Zero PHI Leakage in Logs & Audit Trails**
   - Access logs (`data/audit/access.log`) must adhere strictly to 6 metadata fields: `ts`, `caller_id`, `method`, `path`, `status`.
   - Never log patient names, ID numbers, birth dates, or SOAP text. Attempting to pass prohibited fields raises `AuditFieldError`.

5. **Security & Authentication (LAN trust, D-32-06 / D-32-27)**
   - `X-API-Key` authentication has been removed. Access is decided by source address: loopback or a trusted intranet subnet (`ELC_TRUSTED_SUBNETS`; auto-detected at runtime if unset). Other sources receive `403`.
   - The `Host` header must be well-formed (anti DNS rebinding); malformed hosts receive `400`. `ELC_ALLOWED_HOSTS` is not used.
   - Cross-site requests (`Sec-Fetch-Site: cross-site`) are rejected with `403`, including GET.
   - Admin settings (auto-accept, facility, setup) may be modified from the trusted intranet (D-32-27).
   - Accepted residual risk (D-32-24): any device in the trusted subnet can read patient data.
   - Access audit logs record the source address as `caller_id` (`lan:<ip>`, PHI-free).

6. **Rules Sync Safety & Zero Auto-Deletion (Phase 35–37)**
   - Never auto-delete existing NHI payment/drug rules or silently drop codes absent from a newer CSV. `analyze_stale_payment_codes()` MUST recommend `"upsert"` whenever `stale_count > 0`.
   - `replace=True` full-table replacement is gated by 4 layers requiring explicit confirmation token `REPLACE_RULES`: (1) `sync_latest_rules()` function top (before `pick_latest`, lock, and sidecar checks), (2) `POST /api/rules/sync` returning `422` before any lock/sidecar/write, (3) CLI `--replace --confirm REPLACE_RULES`, and (4) frontend `advanced-only` button with `prompt()` confirmation.
   - `sync_latest_rules` uses an exclusive `O_EXCL` `.lock` file and rejects active SQLite sidecars (`-wal`, `-shm`, `-journal`) with `409`; NEVER auto-delete `.lock` or sidecar files in code.
   - **Database git policy**: Public NHI rules DB `data/db/rules.sqlite3` (5,752 payment / 11,472 drug rows, **zero PHI**) is tracked in git for out-of-the-box deployment; `data/db/cases.sqlite3` (contains patient PHI) and `data/db/rules.sqlite3.bak.*` MUST remain strictly gitignored.

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
    - `rules`: `/api/rules/status`, `/api/rules/upload` (65 MB single-route override in `api/security.py`), `/api/rules/sync` (`upsert` default; `replace: true` requires `confirm == "REPLACE_RULES"` else `422`)
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
  - **`packagers/`**: NHI EMR batch packaging engine (`emr_batch_packager.py`) generating 11-code filenames, A/B/C/D 4-tier classification, A-tier HTML SOAP document (`StructuredSoapHtmlBuilder`: anchored sections; the former PDF builder produced blank pages and is no longer used, 2026-11-17), and 500MB ZIP chunking at 450MB threshold.
  - **`pipeline.py`**: Pipeline coordinators (`run_presubmission_check` and `run_case_pipeline`).
  - **`asr/`**: Local offline dual-backend speech recognition (`sherpa_backend.py` as **default** `sherpa-onnx` SenseVoice int8 + OpenCC `s2twp` + optional `num_clusters=2` speaker diarization, 66.2× realtime & 0% repetition on 8-WAV benchmark; `transcriber.py` unified dispatcher with `ELC_ASR_BACKEND=sherpa|whisper`, optional low-density auto-fallback `ELC_ASR_WHISPER_FALLBACK=1` with 8-gram repetition `<0.15` guard, and `faster-whisper` + PyAV 19 compatible decoder for heavy-noise/Taiwanese dialect recall; shared `config/asr_hotwords.json` specialty hotwords; lazy-loaded optional extras `asr-sherpa` / `asr`; strict fail-closed `ASRUnavailableError` & PHI-safe logging; full 8-WAV head-to-head metrics in `compare.md` §5).
  - **`comparator/`**: Three-way evidence judger (`judger.py`), reinforcement narratives (`narratives.py`), bilingual & clinical SOAP generation (`soap_advice.py` with `validate_soap_quality(..., profile="template"|"clinical")`, single targeted placeholder retry, empty `summary_zh` backfill, and two-step clinical `pending` bypass guard), and local ICD-10 semantic mismatch validator (`icd10_validator.py` — advisory warnings only, never silently rewrites codes).
  - **`services/rule_summary.py` & Report Rule Display (Phase 38 user-confirmed UX)**: Stage 1 (`monthly_report_html.py`) and Stage 2/3 (`services/report_renderer.py`) directly expand full verbatim `payment_text` (no summary truncation), while collapsible `<details class="rule-fulltext">` (`📜 檢視完整給付規定條文`) is collapsed by default, displays ONLY official `article_full_text` with `article_location` provenance (never repeating `payment_text`), and is omitted when a code has no individual official article (e.g. `64140C`). `rule_summary.py` remains available as a standalone deterministic utility.
  - **`rule_repository/`**: SQLite rule store (`data/db/rules.sqlite3`, zero PHI, tracked in git: 5,752 payment / 11,472 drug / 8,302 official full-text `rule_mapping`), unified placeholder-to-SQL-`NULL` CSV loaders (`loaders/_csv_table.py`), deterministic zero-LLM official full-text builder (`mapping/build_fulltext_mapping.py` parsing `完整給付規定1140221.odt`, 21 official `.docx` files, and CSV `備註`), readonly quality & 8-category stale-code analyzer (`audit_csv.py`, CLI `--stale-vs-db`), atomic locked sync pipeline (`scripts/sync_latest_rules.py` auto-rebuilding `rule_mapping` with missing-dir preservation, `O_EXCL` `.lock`, sidecar `409` check, filename-timestamp backup rotation max 5, `REPLACE_CONFIRM_TOKEN`), docx tree indices, and legacy LLM mapping scripts.
  - **`docs/CLINIC_SERVER_OPS_QUICKCARD.md`**: One-page non-engineer clinic server operations quickcard (verified by `tests/test_ops_quickcard_doc.py`).
  - **`parsers/`**: Parsers for XML declarations (TOTFA), deduction notifications, and outpatient SOAP text.
  - **`generators/`**: Builders for appeal drafts, Big5 XML (`appeal_xml.py`, `sampling_xml.py`), tracking tables, ODT/PDF templates, and evidence packets.

- **`server.py`**: WSGI entrypoint (`server:app`) delegating to `elc_audit_engine.api.create_app()` (Flask `MAX_CONTENT_LENGTH = 26 MB` aligned with `/api/soap/recordings` 25 MB `.wav`/`.opus` contract; non-recording uploads retain 10 MB per-route limits).
- **`deploy/`**: Production service files — `gunicorn.conf.py`, systemd user units (`elc-audit-engine.service`, `elc-llama-server.service` for 128K Gemma 4 E4B `Q4_K_M` + `mmproj-BF16`, healthcheck `.service`/`.timer`, `elc-backup.*`), `healthcheck.sh`, env template, and `README.md` (LAN guidance).
- **`scripts/`**: CLI builders for appeal print, XML, deduction sheets, and evidence packets.

---

## 4. Herdr Multi-Agent Collaborative Architecture

When operating within the Herdr terminal workspace manager (`HERDR_ENV=1`), tasks are coordinated across specialized agents pinned to panes in workspace `w7`:

| Terminal Pane | Assigned Agent | Model & Capabilities | Core Responsibilities |
| :--- | :--- | :--- | :--- |
| **`w7:p6`** | **Antigravity (agy)** | Executor | **執行代碼與文件修改（依計畫逐項實作）**<br>• 只按計畫檔（如 `.planning/phases/32.1-*/32.1-PLAN.md`）修改，不自行擴大範圍<br>• 不得自行提交（commit）；完成後回報改動清單與待決疑問 |
| **`w7:p3`** | **Hermes** | Tester | **測試與驗收，不修改程式**<br>• 全套件測試、`ruff check .`、瀏覽器 console 檢查（如 CSP 違規）<br>• 回報原始輸出與數字，不得以「應該通過」代替實測 |
| **`w7:p1`** | **Claude Code** | Coordinator / Final check | **規劃、派工、最終核對**<br>• 撰寫計畫檔、派工給 agy、收取 Hermes 測試結果<br>• 獨立重跑測試與 ruff、審查 diff、核對文件數字<br>• 提交（commit）與推送，須經使用者確認 |

**標準流程**：Claude 規劃 → agy 執行 → Hermes 測試 → Claude 最終核對 → 使用者確認後提交。
任一環節發現問題，退回上一棒，不得跳過測試或核對直接提交。

---

## 5. Execution & Testing Conventions

- **Environment Manager**: `uv`
  - Sync dependencies: `uv sync`
  - Run server (production, managed): `systemctl --user restart elc-audit-engine.service` — do NOT start a second instance on port 5000
  - Run server (dev only, foreground): `uv run python server.py`
  - Run tests: `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests`
  - Dependency pitfall: the user's global `~/.config/uv/uv.toml` sets `constraint-dependencies = ["pydantic<2.11"]`, which silently downgrades pydantic on `uv add`/`uv lock`. Lock with `uv lock --no-config` (or `--no-config` on `uv add`) so only the intended package changes; verify with `git diff uv.lock`.
- **Testing Guardrails**:
  - Never write to production databases (`data/db/cases.sqlite3`, `data/db/rules.sqlite3`) or `data/audit/access.log` in tests.
  - `tests/conftest.py` enforces global autouse isolation (`_isolate_prod_runtime_paths`) redirecting `CASES_DB_PATH` and `AUDIT_LOG_PATH` away from `data/`; always use `make_api_app` / `tmp_path` fixtures for isolated databases.
- **Herdr Environment**:
  - When running inside Herdr (`HERDR_ENV=1`), coordinate long-running jobs or agent tasks across assigned panes: `agy` (`w7:p6`) for execution, `hermes` (`w7:p3`) for testing, and `claude` (`w7:p1`) for planning and final check. See §4 for the handoff flow.
  - Pane IDs and agent names may change when panes are recreated; confirm with `herdr agent list` before sending work.

---

## 5b. Windows Probe (MockHIS) Invariants

Applies to `deploy/windows_agent/mock_his/`. These were learned the hard way on WinBoat (2026-11-11):

1. **MockHIS must expose native controls.** Tkinter children are invisible to UI Automation (the snapshot only shows the title bar). Keep the Win32 EDIT/STATIC implementation; do not revert to Tkinter.
2. **Snapshot shape (agent-desktop 2.6).** Parse `data.tree` recursively; refs are `ref_id`; text fields appear as role `textfield`, and their `name` is the field label. There is no `get-value` command: read with `get <REF> --property value` and parse `data.value`. Write with `set-value`.
3. **Launch with `pythonw`.** A `python.exe` console window also matches `--app python` and triggers `AMBIGUOUS_TARGET`.
4. **Fail closed.** The probe acts only on windows whose title contains `MockHIS`, and never on shell windows (檔案總管, Windows PowerShell, 命令提示字元, Terminal) even if the title contains `MockHIS` (2026-11-17). Do not widen this without an explicit request.
5. **`--test-vendor` is for demo-data test VMs only.** Never ship it in a handoff bundle, and never run it against a real HIS.
6. **Handoff bundles** must not contain `JHISX/`, `*.mdb`, or any patient-related data. Keep the SHA-256 in the operator guide in sync with the zip.

## 6. Deployment & Service Stability (systemd)

The production server is a **systemd user service** (not a manual terminal process).

| Item | Value |
| :--- | :--- |
| Service | `elc-audit-engine.service` (gunicorn 26.2.0, `server:app`, 1 worker × 8 threads) |
| Local LLM | `elc-llama-server.service` (`llama serve`, Gemma 4 E4B `Q4_K_M` + `mmproj-BF16`, `127.0.0.1:8080`, `--ctx-size 131072 --kv-unified --offline -ngl 99`) |
| Restart | `Restart=always`, `RestartSec=3`; start-limit 10 failures / 300 s |
| Crash record | `logs/crash.log` (written on every stop: `result`, `exit_code`, `exit_status`) |
| Logs | `logs/access.log`, `logs/error.log` (gunicorn + Python tracebacks), `logs/healthcheck.log` |
| Health | `GET /api/health` (auth-exempt). `elc-audit-engine-healthcheck.timer` runs `deploy/healthcheck.sh` every 60 s; restarts after 3 consecutive failures |
| Config | `~/.config/elc-audit-engine/env` (mode 600; template `deploy/elc-audit-engine.env.example`) — **never commit** |
| Units | `~/.config/systemd/user/` (copies of `deploy/*.service|*.timer`). Re-copy and `systemctl --user daemon-reload` after editing `deploy/` |
| Boot | Linger enabled for user `hsu` → starts at boot without login |
| Bind | Production: `ELC_SERVER_HOST=0.0.0.0`，為院內區域網路服務的有意設定（使用者已於 2026-11-16 確認）。本機開發／測試仍用 `127.0.0.1`。 |

**Operations**
- Status / restart / logs: `systemctl --user status|restart elc-audit-engine.service`, `journalctl --user -u elc-audit-engine.service -f`
- Crash forensics: `cat logs/crash.log logs/error.log`
- Verify: `curl http://127.0.0.1:5000/api/health` → `{"status":"ok"}`

**LAN exposure checklist (required before serving other machines)**
1. Bind is `0.0.0.0` by design for the clinic LAN. No TLS reverse proxy is in place; accepted as an intranet-only deployment.
2. Host header is checked by format (`lan_trust.is_allowed_host`, anti DNS rebinding). No `ELC_ALLOWED_HOSTS` list is used.
3. `X-API-Key` / `ELC_API_KEYS` were removed under D-32-06; no per-client key setup is needed.
4. Ensure `DISABLE_AUTH` is unset.
5. Firewall: **ufw 目前為不活動（2026-11-16 確認）**。Port 5000 listens on all interfaces; enable ufw with LAN-only rules before relying on the LAN trust model.
6. Back up `data/` and `logs/`; `data/` contains patient-related data.

**Known open items**
- Full suite passes: **1,766 passed, 3 skipped, 1 deselected, 0 failed** (2026-11-23, Phase 38). No known pre-existing failures.
- `deploy/install.sh` includes `elc-llama-server.service` plus `--check-asr-models` / `--check-llama-cache` health checks; clean Ubuntu Server VM end-to-end verification and Windows 12-item manual verification remain pending.
- `logs/healthcheck.log` may show one `failed (1/3)` line at service start (startup race); harmless below the threshold.
- Deployment files and public NHI rules DB (`data/db/rules.sqlite3`, zero PHI) are committed; `config/facility.json`, `data/db/cases.sqlite3` (PHI), `E4Btest.md`, and `Wavesample/` stay local-only (gitignored).

---

## 7. Next To Do & Prioritized Backlog (Post-Phase 38, 2026-11-24)

Read `.planning/.continue-here.md` and `.planning/STATE.md` before starting any new phase. Current open work, ordered by clinic rollout priority:

### P0 — On-Site / Real-Environment Rollout Verification (Highest Value)
1. **Windows Workstation 12-Item Manual Verification (Phase 31–38 carryover)**:
   - Execute `deploy/release-20261116/31-WINDOWS-MANUAL-VERIFY.md` item-by-item on a real Windows clinic PC against HIS (Vision / Yaosheng / Minger / Chihshi).
2. **Windows Client Packaging Build**:
   - Build `deploy/windows_agent/ElcAgent.spec` (with ASR excludes from Phase 34) and `soapvoice_client.spec` (D-32-26) on Windows, verify SHA-256 and zero-PHI handoff checklist (§5b).
3. **Clean Ubuntu Server VM One-Click Install Verification**:
   - Run `deploy/install.sh` end-to-end on a fresh Ubuntu Server VM, verify `elc-audit-engine.service`, `elc-llama-server.service`, `--check-asr-models`, `--check-llama-cache`, and enable `ufw` LAN-only firewall rules before clinic LAN exposure.

### P1 — Local Engineering Hardening (Can Be Done Anytime on Dev Host)
4. **Rules Backup Pinning & Sync Throttling (`sync_latest_rules.py`)**:
   - Flagged during Phase 37 Tester audit: rapid repeated `POST /api/rules/sync` calls can rotate out an important baseline under `max_backups=5`. Add a protected pinned-backup directory (exempt from rotation) and/or short cooldown throttling, plus record sync `mode` (`upsert`/`replace`) in PHI-free `access.log` `detail`.
5. **Unify Stage 1 & Stage 2/3 Rule-Block HTML Renderer Helper**:
   - Flagged during Phase 38 Checker audit: `monthly_report_html.py` and `services/report_renderer.py` currently duplicate identical `_rule_fulltext_html` logic; extract a single shared helper in `services/report_assets.py` (or `services/rule_html.py`) to prevent future drift.
6. **Clinic HIS Shared-Folder / Read-Only DB Connector (Non-Docker)**:
   - Host has 20 GiB RAM (~4.9 GiB free with Gemma 4 E4B 128K loaded) and no Docker (do NOT deploy Appwrite). When clinic HIS DB schema/share details are confirmed, implement a lightweight read-only Linux `cifs ro` mount or direct Python read-only DB connector (`pyodbc`/`pymssql`/`psycopg`/`mdbtools`).
7. **Legacy Binary `.doc` Official Rules Extraction (Optional)**:
   - Phase 38 covers `完整給付規定1140221.odt` + all 21 `.docx` + `261119` `備註` (8,302 mapped codes). If deeper coverage of the 11 legacy Word 97 `.doc` files under `officialdocument/審查注意事項/` (e.g., `2-2-1檢查`, `2-2-3注射`, `3第三部牙醫`, `5居家照護`) is needed, convert once via LibreOffice `soffice --headless --convert-to docx` and feed into `build_fulltext_mapping.py`.
8. **Rules DB Git Size Hygiene (Optional)**:
   - `data/db/rules.sqlite3` is currently ~54.5 MB (GitHub recommends ≤50 MB; hard limit 100 MB). Consider Git LFS or generating it on fresh hosts via `sync_latest_rules` (1.27 s cold build from tracked CSVs + `officialdocument/`).

### P2 — Externally Blocked
9. **Phase 10 — NHI VPN / `NHI_EIIAPI` Real Machine Integration**:
   - Blocked on external clinic NHI VPN access, SAM card reader, and `doctor-toolbox` integration permissions.
