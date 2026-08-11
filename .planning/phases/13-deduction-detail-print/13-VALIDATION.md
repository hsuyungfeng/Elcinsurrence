---
phase: 13
slug: deduction-detail-print
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-11
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | pyproject.toml |
| **Quick run command** | `rtk uv run pytest tests/test_deduction_print.py` |
| **Full suite command** | `rtk uv run pytest` |
| **Estimated runtime** | ~140 seconds |

---

## Sampling Rate

- **After every task commit:** Run `rtk uv run pytest tests/test_deduction_print.py`
- **After every plan wave:** Run `rtk uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 0 | REQ-deduction-print | — | Test scaffold creation | unit | `rtk uv run pytest tests/test_deduction_print.py` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | REQ-deduction-print | T-13-01 | Field mapping & SHA256 integrity | unit | `rtk uv run pytest tests/test_deduction_print.py` | ❌ W0 | ⬜ pending |
| 13-02-01 | 02 | 2 | REQ-deduction-print | T-13-01 | XML escaping & dynamic row expansion | integration | `rtk uv run pytest tests/test_deduction_print.py` | ❌ W0 | ⬜ pending |
| 13-02-02 | 02 | 2 | REQ-deduction-print | T-13-03 | PDF generation via LibreOffice & pypdf check | e2e | `rtk uv run pytest tests/test_deduction_print.py` | ❌ W0 | ⬜ pending |
| 13-03-01 | 03 | 3 | REQ-deduction-print | T-13-04 | CLI & API service integration | integration | `rtk uv run pytest tests/test_deduction_print.py` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `tests/test_deduction_print.py` — unit, integration, and E2E stubs for REQ-deduction-print

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 實體列印版面視覺與對帳排版確認 | REQ-deduction-print | 檢查 PDF 表格邊框、字型與跨頁斷頁美觀度 | 使用 PDF 閱讀器開啟 `data/output/核減明細_*.pdf` 並進行視覺檢查 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-11
