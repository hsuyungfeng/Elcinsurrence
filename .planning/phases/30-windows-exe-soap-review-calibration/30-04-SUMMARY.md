# Phase 30 Plan 04: SoapVoice Recording Ingestion & Contract Summary

**Completed:** 2026-11-09
**Status:** Completed

## Implementation Summary
- Created `tests/fixtures/soapvoice_recording_v1.json` defining canonical contract schema version 1 with [S] [O] [A] [P] text and metadata.
- Implemented `parse_soap_txt` in `src/elc_audit_engine/api/routes/soap_recording.py` parsing `[S]`, `[O]`, `[A]`, `[P]` with fail-closed missing section detection.
- Implemented `validate_recording_payload` validating `session_id`, `visit_date`, `patient_ref`, `soap`, and audio metadata (max 25MB, wav).
- Implemented `POST /api/soap/recordings` in `soap_recording.py` with:
  - Idempotency via `soap_recording_sessions` SQLite table.
  - Safe audio persistence at `<data_dir>/recordings/<session_id>.wav` (no client-provided filename used).
  - Draft creation via shared `_create_draft_record` helper.
  - Cleanup of newly created audio file on draft creation failure (zero orphans).
  - PHI-safe logging (no raw SOAP text in logs).
- Updated `src/elc_audit_engine/api/security.py`:
  - Enforced O3 decision: `POST /api/soap/recordings` is exempt from API key ONLY for requests from RFC 1918 private subnets (`10/8`, `172.16/12`, `192.168/16`, `127.0.0.1`).
  - Requests from non-private IPs strictly require API key authentication (401 on failure).
  - Agent keys are blocked with 403 on this endpoint.
- Updated `src/elc_audit_engine/case_store/db.py` and `store.py` with `soap_recording_sessions` table and queries.
- Registered `soap_recording_bp` in `routes/__init__.py`.
- Created `tests/test_soap_recording_contract.py` (19 tests) and verified compatibility with `test_soap_review_api.py` (5 tests). All 24 tests passed.
