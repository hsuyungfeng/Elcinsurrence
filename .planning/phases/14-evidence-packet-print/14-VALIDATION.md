---
phase: 14
slug: evidence-packet-print
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-11
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | pyproject.toml |
| **Quick run command** | `rtk uv run pytest tests/test_evidence_packet_builder.py tests/test_evidence_packet_pdf.py` |
| **Full suite command** | `rtk uv run pytest` |
| **Estimated runtime** | ~140 seconds |

---

## Sampling Rate

- **After every task commit:** Run `rtk uv run pytest tests/test_evidence_packet_builder.py tests/test_evidence_packet_pdf.py`
- **After every plan wave:** Run `rtk uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 0 | REQ-evidence-packet-print | — | Test scaffold creation | unit | `rtk uv run pytest tests/test_evidence_packet_builder.py` | ❌ W0 | ⬜ pending |
| 14-01-02 | 01 | 1 | REQ-evidence-packet-print | T-14-02 | Image scaling & EXIF rotation | unit | `rtk uv run pytest tests/test_evidence_packet_builder.py` | ❌ W0 | ⬜ pending |
| 14-01-03 | 01 | 1 | REQ-evidence-packet-print | T-14-01 | DOCX section building (Cover/Audit/Summary/Draft) | unit | `rtk uv run pytest tests/test_evidence_packet_builder.py` | ❌ W0 | ⬜ pending |
| 14-02-01 | 02 | 2 | REQ-evidence-packet-print | T-14-03 / T-14-04 | PDF export via soffice & pypdf concatenation | e2e | `rtk uv run pytest tests/test_evidence_packet_pdf.py` | ❌ W0 | ⬜ pending |
| 14-02-02 | 02 | 2 | REQ-evidence-packet-print | T-14-03 | CLI tool execution | integration | `rtk uv run pytest tests/test_evidence_packet_pdf.py` | ❌ W0 | ⬜ pending |
| 14-03-01 | 03 | 3 | REQ-evidence-packet-print | T-14-03 | Flask API route & audit logging | integration | `rtk uv run pytest tests/test_evidence_packet_pdf.py` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

- [ ] `tests/test_evidence_packet_builder.py` — unit stubs for DOCX builder & image processor
- [ ] `tests/test_evidence_packet_pdf.py` — integration stubs for PDF exporter, CLI, and Flask API

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 審核軌跡＋佐證包列印排版美觀度檢查 | REQ-evidence-packet-print | 檢查 A4 PDF 跨頁斷頁、圖片縮放比例與顏色徽章 | 開啟 `data/output/申復佐證包_*.pdf` 進行視覺檢查 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-11
