# AGENTs.md — LLM & Autonomous Agents Guidance

Welcome, LLM Agent. This document outlines the core architecture, non-negotiable operational principles, development environment, and safety boundaries for the **Elcinsurrence** (`elc-audit-engine`) codebase.

---

## 1. Project Overview & Dual Workflows

`Elcinsurrence` is an automated NHI (Taiwan National Health Insurance / 健保) outpatient audit and appeal assistance engine.

### Dual-Workflow Architecture
1. **Sampling Pre-audit Workflow (抽樣事前預審)**
   - **Purpose**: Evaluate medical record compliance before submitting抽審 to NHI.
   - **Outcome**: Read-only support assessment (`✅ 充分` / `⚠️ 薄弱` / `❌ 裸奔`) + gap identification & reinforcement suggestions.
   - **Entrypoint**: `run_presubmission_check` in `src/elc_audit_engine/pipeline.py`.
   - **Constraint**: **Read-only, no side-effects, does NOT produce appeal drafts.**
2. **Appeal Post-processing Workflow (核減事後申復)**
   - **Purpose**: Process NHI deduction notices and generate formal appeal materials.
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
    - `monthly`: `/api/monthly/*` (TOTFA upload, monthly batch pre-audit reports & clear endpoints)
    - `sampling`: `/api/sampling/*` (Stage 2 pre-audit, closed-loop batch audit, batch XML export, unified batch report)
    - `appeal`: `/api/appeal/*` (Stage 3 appeal drafts, linkage from Stage 2, batch appeal XML export, unified batch report)
    - `attachments`: `/api/appeal/attachments/*`
    - `print`: `/api/deduction/print`, `/api/appeal/evidence-packet/print`
    - `security`: Authentication, host whitelisting, and authorization hooks.
  - **`case_store/`**: SQLite-backed case repository with ACID transitions and collision detection (supports `kind='monthly'|'sampling'|'appeal'`).
  - **`attachment_store.py`**: SQLite-indexed attachment manager keyed by `case_id`.
  - **`evidence_vault.py`**: Local evidence vault keyed by `record_no-YYMM` storing images, audio, lab reports, and medical records.
  - **`unified_review_report.py`**: Unified review report generator aligning Stage 2 and Stage 3 batch views with the MONTHLY-YYYYMM report format.
  - **`pipeline.py`**: Pipeline coordinators (`run_presubmission_check` and `run_case_pipeline`).
  - **`rule_repository/`**: SQLite rule store, docx tree indices, and LLM mapping scripts.
  - **`parsers/`**: Parsers for XML declarations (TOTFA), deduction notifications, and outpatient SOAP text.
  - **`generators/`**: Builders for appeal drafts, Big5 XML (`appeal_xml.py`, `sampling_xml.py`), tracking tables, ODT/PDF templates, and evidence packets.

- **`server.py`**: Lightweight development entrypoint delegating to `elc_audit_engine.api.create_app()`.
- **`scripts/`**: CLI builders for appeal print, XML, deduction sheets, and evidence packets.

---

## 4. Execution & Testing Conventions

- **Environment Manager**: `uv`
  - Sync dependencies: `uv sync`
  - Run server: `uv run python server.py`
  - Run tests: `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests`
- **Testing Guardrails**:
  - Never write to production databases (`data/db/cases.sqlite3`) in tests.
  - Use fixtures from `tests/conftest.py` (e.g., `make_api_app`) which create temporary isolated databases.
- **Herdr Environment**:
  - When running inside Herdr (`HERDR_ENV=1`), coordinate long-running jobs or agent tasks across assigned panes (`claude-executor` for coding/execution, `hermes-test` for tests, server panes for runtimes).
