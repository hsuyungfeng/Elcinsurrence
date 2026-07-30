---
phase: 02-rule-repository
plan: 06
subsystem: rag
tags: [chromadb, embeddings, onnx, d-09, non-blocking]

requires:
  - phase: 02-rule-repository
    provides: "data/db/docx_trees.json (Plan 03: 32 files, 1633 tree nodes)"
provides:
  - "flatten_tree_nodes() — pure function extracting non-empty full_text nodes from a docx tree"
  - "build_chroma_collection() — non-blocking ChromaDB ingestion (D-09 infrastructure)"
  - "Populated local persistent ChromaDB collection at data/rag/ (165 chunks ingested)"
affects: [phase-5-three-way-comparator]

tech-stack:
  added: []
  patterns:
    - "Non-blocking build step: broad try/except around ChromaDB client/ingestion, returns {status: skipped, reason} instead of raising — write-only infrastructure that must never fail core acceptance criteria"
    - "Chunk id disambiguation: duplicate node paths (from repeated boilerplate clauses) get a numeric ::dupN suffix to satisfy ChromaDB's globally-unique-id requirement"

key-files:
  created:
    - src/elc_audit_engine/rule_repository/embeddings/__init__.py
    - src/elc_audit_engine/rule_repository/embeddings/chroma_store.py
    - src/elc_audit_engine/rule_repository/scripts/build_chroma_index.py
    - tests/test_chroma_store.py
  modified: []

key-decisions:
  - "Used ChromaDB's default local ONNX (all-MiniLM-L6-v2) embedding function rather than llama.cpp's /v1/embeddings — RESEARCH.md confirmed the live server does not support that endpoint under its current launch flags"
  - "Disambiguated duplicate chunk ids with a numeric suffix (Rule 1 fix) — node path can legitimately collide on repeated boilerplate text within a document, which would otherwise silently overwrite chunks or raise a ChromaDB uniqueness error"

patterns-established:
  - "Pattern: D-09 / low-priority infrastructure plans wrap all external-dependency calls (network, embedding model download) in a broad except, returning a status dict rather than propagating — keeps non-blocking guarantees explicit and testable"

requirements-completed: [REQ-rule-repository]

duration: 45min
completed: 2026-07-30
---

# Phase 2 Plan 6: ChromaDB Embeddings (D-09) Summary

**Non-blocking ChromaDB ingestion pipeline built and run for real: 165 chunks from the 32-file docx tree corpus embedded into a local persistent collection at `data/rag/`, using ChromaDB's default ONNX embedder.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-07-30T15:49:00Z
- **Completed:** 2026-07-30T16:10:00Z (session resumed after mid-run interruption; SUMMARY completed by orchestrator after verifying committed work)
- **Tasks:** 1 completed
- **Files modified:** 4 (all new)

## Accomplishments
- `flatten_tree_nodes()` recursively extracts every non-empty-`full_text` node from a Plan 03 docx tree into a flat chunk list with stable `{doc}::{path}` ids
- `build_chroma_collection()` ingests all documents' chunks into a local `PersistentClient` collection in batches of 500, wrapped in a broad non-blocking exception handler
- Real run completed successfully: `{'status': 'ok', 'chunks_ingested': 165, 'reason': None}`, exit code 0 — `data/rag/` now contains a populated ChromaDB collection (`chroma.sqlite3` + embedding store)
- 3/4 tests pass unconditionally (flatten logic + non-blocking contract on a broken persist_dir); 1 network-dependent best-effort test correctly skippable

## Task Commits

1. **Task 1 (RED): failing test for chroma_store ingestion pipeline** - `adb7ac6` (test)
2. **Task 1 (GREEN): D-09 ChromaDB persistent collection ingestion** - `e8ace14` (feat)

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/embeddings/__init__.py` - empty package marker
- `src/elc_audit_engine/rule_repository/embeddings/chroma_store.py` - `flatten_tree_nodes()` + `build_chroma_collection()` (non-blocking)
- `src/elc_audit_engine/rule_repository/scripts/build_chroma_index.py` - one-shot entrypoint, run for real this session
- `tests/test_chroma_store.py` - 4 tests (3 unconditional, 1 network-dependent skip-guarded)

## Decisions Made
- ChromaDB's bundled ONNX all-MiniLM-L6-v2 embedder used instead of llama.cpp's `/v1/embeddings`, per RESEARCH.md's confirmed finding that the live server doesn't support that endpoint under its current launch configuration
- Duplicate chunk-id disambiguation (numeric `::dupN` suffix) added as a Rule 1 fix — node `path` (derived from ancestor titles + text) can legitimately repeat for boilerplate clauses appearing verbatim more than once in the same source document

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Disambiguated colliding chunk ids before ChromaDB ingestion**
- **Found during:** Task 1 (real build run against the full 32-file corpus)
- **Issue:** ChromaDB's `collection.add()` requires globally-unique `ids` within a single call. The chunk id scheme (`{doc}::{node_path}`) can legitimately collide when the same boilerplate clause text appears more than once within a document, producing duplicate paths.
- **Fix:** Added a `seen_id_counts` disambiguation pass immediately before ingestion — the first occurrence of any id keeps its original form; subsequent occurrences get a `::dup{N}` suffix.
- **Files modified:** `src/elc_audit_engine/rule_repository/embeddings/chroma_store.py`
- **Verification:** Full 32-file build run completed with `chunks_ingested: 165` and no ChromaDB uniqueness errors.
- **Committed in:** `e8ace14` (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 - bug fix on id collision)
**Impact on plan:** Necessary for the real ingestion run to succeed at all — without it, `collection.add()` would raise on the first duplicate id, and the broad non-blocking except would have (correctly, but unnecessarily) swallowed it as a "skipped" result instead of actually ingesting. No scope creep — fix is isolated to id generation.

## Issues Encountered
None beyond the deviation above. Session was interrupted mid-flow by an account spend-limit error after both TDD commits and the real build run had already completed and were confirmed clean (`git status` empty in the worktree); the orchestrator resumed, independently re-verified the committed state (tests green, real artifact present with correct chunk count, non-blocking exception handling present via grep), and completed this SUMMARY.md directly rather than re-spawning a fresh executor.

## User Setup Required
None - no external service configuration required. (ChromaDB's one-time ONNX model download succeeded automatically during this session's real build run — no manual pre-staging was needed.)

## Next Phase Readiness
- D-09 ChromaDB infrastructure exists and is populated (165 chunks, `data/rag/`), ready for Phase 5 (three-way comparator) to build actual free-text/similar-case query logic on top of it — this plan intentionally implements ingestion only, no query API, per CONTEXT.md's deferred scope.
- This was explicitly a non-blocking, low-priority task — REQ-rule-repository's three core acceptance criteria (SQLite, docx tree, rule_mapping) do not depend on this plan and are tracked separately (Plans 02, 03, 04).

---
*Phase: 02-rule-repository*
*Completed: 2026-07-30*
