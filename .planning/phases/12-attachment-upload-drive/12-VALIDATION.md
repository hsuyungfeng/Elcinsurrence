---
phase: 12
slug: attachment-upload-drive
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-11
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `rtk uv run pytest tests/test_attachment_store.py tests/test_appeal_attachment_integration.py` |
| **Full suite command** | `rtk uv run pytest` |
| **Estimated runtime** | ~10 seconds (quick), ~140 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run quick test command
- **After every plan wave:** Run full test suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | REQ-attachment-upload | T-12-01 | safe_filename 白名單防範路徑穿越 | unit | `rtk uv run pytest tests/test_attachment_store.py` | ❌ W0 | ⬜ pending |
| 12-01-02 | 01 | 1 | REQ-attachment-upload | T-12-02 | Magic Bytes + 開檔驗證拒絕偽造/損毀檔 | unit | `rtk uv run pytest tests/test_attachment_store.py` | ❌ W0 | ⬜ pending |
| 12-01-03 | 01 | 1 | REQ-attachment-upload | T-12-03 | 無實體檔案時誠實降級 p7=N | integration | `rtk uv run pytest tests/test_appeal_attachment_integration.py` | ❌ W0 | ⬜ pending |
| 12-01-04 | 01 | 1 | REQ-attachment-upload | T-12-04 | REST API 上傳與查詢端點整合 | API | `rtk uv run pytest tests/test_server_attachment_routes.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_attachment_store.py` — attachment_store 模組單元測試與安全防線測試
- [ ] `tests/test_appeal_attachment_integration.py` — has_attachment 真實驅動 generate/appeal_xml 測試
- [ ] `tests/test_server_attachment_routes.py` — /api/appeal/attachments/upload 端點整合測試

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真實超音波/X光照片可視覺瀏覽確認 | REQ-attachment-upload | 人工審查視覺體驗驗證 | 使用瀏覽器上傳 PNG/JPEG 影像檔後核對可於介面或系統資料夾檢視 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
