---
phase: 12
plan: 01
subsystem: attachment_store
tags:
  - attachment
  - upload
  - security
  - dynamic-p7
requires:
  - REQ-attachment-upload
provides:
  - attachment-store-module
  - attachment-api-routes
  - dynamic-has-attachment-driver
affects:
  - src/elc_audit_engine/attachment_store.py
  - src/elc_audit_engine/generators/appeal.py
  - server.py
  - config/settings.py
tech-stack:
  added:
    - pillow_heif
  patterns:
    - magic-bytes-validation
    - safe-path-sanitization
    - zero-phi-audit-logging
key-files:
  created:
    - src/elc_audit_engine/attachment_store.py
    - tests/test_attachment_store.py
    - tests/test_appeal_attachment_integration.py
    - tests/test_server_attachment_routes.py
  modified:
    - config/settings.py
    - src/elc_audit_engine/generators/appeal.py
    - server.py
key-decisions:
  - "ATTACHMENTS_DIR configured with default data/attachments, overrideable by env var"
  - "Strict validation enforced via Magic Bytes and image verification for PNG/JPEG/HEIC/PDF"
  - "Dynamic query to attachment_store.has_attachment when build_appeal_draft receives no explicit has_attachment parameter"
requirements-completed:
  - REQ-attachment-upload
duration: 5 min
completed: 2026-08-11T12:47:00Z
---

# Phase 12 Plan 01: Attachment Store & API Integration Summary

## One-liner
Implemented the secure attachment storage module, dynamic `has_attachment`/`p7` flag driver, and Flask REST endpoints for evidence image uploads.

## Key Accomplishments
1. **Attachment Store Engine (`src/elc_audit_engine/attachment_store.py`)**:
   - Built safe file validation checking Magic Bytes (`PNG`, `JPEG`, `PDF`) and `pillow_heif` verification (`HEIC`).
   - Enforced 10MB file size limit and path sanitization with `safe_paths.safe_filename()`.
   - Maintained case-level metadata store (`meta.json`) for efficient listing and management.

2. **Dynamic `p7_attachment` Integration (`src/elc_audit_engine/generators/appeal.py`)**:
   - Modified `build_appeal_draft` to dynamically check physical attachment presence via `attachment_store.has_attachment(case_seq, order_seq)` when `has_attachment` is not explicitly provided.
   - Preserved `p7_attachment` ("Y"/"N") accuracy in JSON output.

3. **REST API Endpoints (`server.py`)**:
   - Added `POST /api/appeal/attachments/upload` (multipart/form-data with zero-PHI audit logging).
   - Added `GET /api/appeal/attachments/<case_seq>` for retrieving attachments list.
   - Added `DELETE /api/appeal/attachments/<case_seq>/<attachment_id>` for file deletion.
   - Added endpoint permissions to `_AUTH_EXEMPT_ENDPOINTS`.

4. **Scaffolding and Verification**:
   - Created `tests/test_attachment_store.py`, `tests/test_appeal_attachment_integration.py`, and `tests/test_server_attachment_routes.py`.
   - Verified 100% test pass rate for all new test cases.

## Self-Check: PASSED
