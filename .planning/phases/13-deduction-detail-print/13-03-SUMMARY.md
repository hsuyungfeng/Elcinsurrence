---
phase: 13-deduction-detail-print
plan: 03
subsystem: api
tags: [cli, api, pdf, print, deduction]

# Dependency graph
requires:
  - phase: 13-02
    provides: [deduction print ODT fill and PDF generation]
provides:
  - CLI script for generating deduction print PDFs
  - API endpoint for generating deduction print PDFs
affects: [frontend, users]

# Tech tracking
tech-stack:
  added: []
  patterns: [CLI entrypoint, Flask API endpoint, Audit Log integration]

key-files:
  created: [scripts/build_deduction_print.py]
  modified: [server.py, tests/test_deduction_print.py]

key-decisions:
  - "Added `--case-id` and `--json` support to the CLI for flexible testing."
  - "Used `_AUTH_EXEMPT_ENDPOINTS` for the new `generate_deduction_print` API to match existing business API rules but retained audit log integration."
  - "Mocked `write_deduction_print` in API tests to avoid requiring LibreOffice dependencies during standard test execution."

patterns-established:
  - "Pattern 1: CLI wrapping around PDF generation using argparse"
  - "Pattern 2: API wrapping around PDF generation handling both `records` payload and `case_id` fetching"

requirements-completed: [REQ-deduction-print]

# Metrics
duration: 15min
completed: 2026-08-11
---

# Phase 13 Plan 03: CLI & API Servicing Summary

**Implemented user-facing CLI and API endpoint to trigger deduction details PDF generation**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-11T13:11:17Z
- **Completed:** 2026-08-11T13:26:17Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Implemented `scripts/build_deduction_print.py` CLI supporting `--csv`, `--json`, and `--case-id` inputs
- Added `POST /api/deduction/print` Flask endpoint in `server.py` supporting direct `records` array or `case_id` references
- Added integration test `test_api_deduction_print` in `tests/test_deduction_print.py`

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立 CLI 工具** - `pending` (feat)
2. **Task 2: 實作 API 端點並接入 Audit Log** - `pending` (feat)

**Plan metadata:** `pending` (docs)

## Files Created/Modified
- `scripts/build_deduction_print.py` - CLI tool to build deduction print
- `server.py` - Flask API routing and logic
- `tests/test_deduction_print.py` - Integrated test for the new endpoint

## Decisions Made
- Allowed the API to receive either a full `records` list or a `case_id` to allow flexibility for the frontend depending on what data they hold locally vs on server.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Deduction Print is complete, ready for full milestone conclusion.

---
*Phase: 13-deduction-detail-print*
*Completed: 2026-08-11*
