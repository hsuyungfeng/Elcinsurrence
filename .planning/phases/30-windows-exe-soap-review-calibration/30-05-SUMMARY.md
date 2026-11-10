# Phase 30 Plan 05: Auto-Accept Toggle & Automatic Approval Branch Summary

**Completed:** 2026-11-09
**Status:** Completed

## Implementation Summary
- Created `soap_settings` SQLite table in `db.py` and added `get_setting` / `set_setting` to `store.py`.
- Added endpoints in `src/elc_audit_engine/api/routes/soap_review.py`:
  - `GET /api/soap/settings/auto-accept`: Returns enabled state (default `false`).
  - `PUT /api/soap/settings/auto-accept`: Updates enabled state with validation of `reason_code` (`DEFAULT`, `CLINIC_POLICY`) and access restrictions (Agent key rejected with 403, optional `ELC_SOAP_ADMIN_CALLERS` whitelist).
  - Every toggle operation logs audit event `soap_auto_accept_toggle` with `old`, `new`, `changed`, `reason_code`, and `caller` (zero PHI).
- Refactored `_approve_draft_record` as a shared core function across manual approval and auto-accept:
  - Validates `content_hash`.
  - Checks state eligibility (`validated` or `failed`).
  - Checks idempotency (`find_pushed_soap_draft`).
  - Enqueues `HIS_PUSH` job via CAS state progression.
  - Logs `soap_auto_accept_approve` (or `soap_review_approve`).
- Added `_maybe_auto_accept` hook in both `create_draft` (`soap_review.py`) and `receive_recording` (`soap_recording.py`):
  - If setting is ON and draft is `validated`, automatically approves and enqueues `HIS_PUSH`.
  - If draft state is `quality_failed`, it remains in `quality_failed` without queuing.
- Created `tests/test_auto_accept_toggle.py` (15 tests passing) and confirmed zero regressions across `test_soap_review_api.py` and `test_soap_recording_contract.py` (39 tests total passing).

## Open Item & Behavior Notes
- **O10 (Admin Callers)**: Implemented via environment variable `ELC_SOAP_ADMIN_CALLERS` (comma-separated caller names). When unset, any authenticated non-agent caller can toggle; when set, only callers in the whitelist can toggle. Agent keys are unconditionally forbidden (403).
- **Task 2 Test 2 Behavior**: When toggle is switched to OFF after a draft has already been queued for `HIS_PUSH`, existing queued jobs in `bridge_queue` are preserved and not revoked.
