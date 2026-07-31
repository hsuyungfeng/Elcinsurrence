---
phase: 02-rule-repository
plan: 05
subsystem: query-interface
tags: [public-api, sqlite, d-07, d-08, human-checkpoint]

requires:
  - phase: 02-rule-repository
    provides: "RuleResult contract (Plan 01), payment_rules/drug_rules (Plan 02), rule_mapping (Plan 04)"
provides:
  - "get_rule(code) — the single public D-07/D-08 query entry point for downstream phases"
  - "20-code human-verified spot-check fixture, locked as a permanent regression test"
affects: [phase-3-parsers, phase-4-record-aggregator, phase-5-three-way-comparator]

tech-stack:
  added: []
  patterns:
    - "Public single-entry-point interface: downstream callers use only get_rule(code), never touch db.py/models.py directly"
    - "Never-raises contract: all SQLite errors degrade to not_found(), ValueError from a table-allowlist violation is the one exception intentionally NOT caught (indicates a programming bug in this module, not a data/runtime issue)"

key-files:
  created: []
  modified:
    - src/elc_audit_engine/rule_repository/__init__.py
    - src/elc_audit_engine/rule_repository/db.py
    - tests/fixtures/rule_mapping_20_spotcheck.json

key-decisions:
  - "Added \"rule_mapping\" to db.py's query_by_code table allowlist — Plan 04 created the rule_mapping schema and upsert helper but never added it to the allowlist, which would have made get_rule()'s rule_mapping lookup raise ValueError at runtime"
  - "Human spot-check conducted via a published Artifact review page (not raw terminal output) — user requested visual review since Traditional Chinese regulatory text is hard to scan in a terminal; all 20 codes confirmed correct in a single review pass"

patterns-established:
  - "Pattern: this project's human-verification checkpoints render as published Artifact pages when reviewing dense/CJK text, not terminal dumps — worth reusing for any future manual-review gate"

requirements-completed: [REQ-rule-repository]

duration: "~20min (Task 1+3 development; Task 2 checkpoint review time not counted as build duration)"
completed: 2026-07-31
---

# Phase 2 Plan 5: get_rule() Query Interface + Human Spot-Check Summary

**`get_rule(code)` implemented as the sole D-07/D-08 public entry point (zero LLM/network calls, never raises); all 20 human spot-check codes confirmed correct via a published review artifact, closing REQ-rule-repository's third and final acceptance criterion. Phase 2 is complete.**

## Performance

- **Duration:** ~20 min active development (Tasks 1 and 3); Task 2's human review was a separate interactive step
- **Started:** 2026-07-31T (continuing directly from Plan 04's merge)
- **Completed:** 2026-07-31T
- **Tasks:** 3 completed (1 auto, 1 human checkpoint, 1 auto)
- **Files modified:** 3

## Accomplishments
- `get_rule(code, db_path=None) -> RuleResult` implemented: looks up `payment_rules`/`drug_rules` first (returns `not_found()` immediately if the code exists in neither), then enriches with `rule_mapping` if present — a code existing in the base tables but missing a `rule_mapping` row correctly returns `found=True` with `article_source=None`, not an error
- Fixed a real integration gap: `rule_mapping` was missing from `db.py`'s `query_by_code` table allowlist (Plan 04 created the schema/upsert helper but never added the allowlist entry) — would have caused every `get_rule()` call to raise `ValueError` at runtime had this not been caught here
- All 3 `test_rule_repository_interface.py` tests green (previously red since Plan 01)
- 20-code human spot-check completed: presented via a published Artifact review page (Traditional Chinese regulatory text, requested by user over raw terminal output) — user confirmed **all 20/20 correct** in a single review pass
- `tests/fixtures/rule_mapping_20_spotcheck.json` locked: real `article_location`/`article_full_text` snapshots from `get_rule()`, `verified: true` for all 20 entries
- Full test suite green: 34 passed, 1 skipped (network-dependent ChromaDB test, expected) — **zero failing tests in the entire Phase 2 test suite**

## Task Commits

1. **Task 1: Implement get_rule() single query interface** - `11f3ea8` (feat)
2. **Task 2: Human 20-code spot-check** - checkpoint, no code commit (review conducted via published Artifact, user confirmed all 20 correct)
3. **Task 3: Lock verified fixture as regression test** - `76e4776` (test)

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/__init__.py` - `get_rule()` implementation, replacing the Phase-1 empty stub
- `src/elc_audit_engine/rule_repository/db.py` - added `"rule_mapping"` to `_ALLOWED_TABLES` and `_SELECT_BY_CODE_QUERIES`
- `tests/fixtures/rule_mapping_20_spotcheck.json` - all 20 entries now carry real, human-verified article data with `verified: true`

## Decisions Made
- `rule_mapping` added to the `query_by_code` allowlist — a genuine cross-plan integration gap discovered while implementing this plan's `get_rule()`, not present in either Plan 04's or this plan's original spec text; caught by actually running the interface tests rather than assuming Plan 04's schema work implied allowlist coverage.
- Human spot-check delivered as a published Artifact page rather than terminal text, per explicit user request ("let me see on the screen") — this is now a reusable pattern for any future manual-review checkpoint in this project involving dense Traditional Chinese regulatory text.

## Deviations from Plan

None — plan executed as written. The `rule_mapping` allowlist fix is a bug fix surfaced during implementation of Task 1's stated behavior (test 1 in the plan's `<behavior>` section already implied the allowlist must work), not a deviation from the plan's design.

## Issues Encountered
- During spot-check data preparation, confirmed two drug-code entries (A046933100, AB49742100) have source-CSV `給付規定` text that itself ends in "…" — an apparent upstream data-truncation issue in the original CSV, not a bug in this pipeline. Flagged explicitly in the review artifact; user's "all 20 correct" verdict accounts for this (the available text, though partial, is a plausible and non-hallucinated excerpt of the real drug regulation). Documented here for future phases (Phase 3-5) that may consume this same CSV data directly.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness

**Phase 2 (規則庫建置 / Rule Repository) is COMPLETE.** All 3 REQ-rule-repository acceptance criteria are automated-and-passing:
1. SQLite `payment_rules`/`drug_rules` queryable — Plan 02
2. Docx tree index covers all 34 source files — Plan 03
3. `rule_mapping` precompiled cache with 20-code human-verified spot-check — Plans 01/04/05

`get_rule(code)` is the stable public interface Phase 3 (解析器), Phase 4 (病歷彙整器), and Phase 5 (三方比對器) should call against. Downstream callers should treat `found=True` with `article_source=None` (code exists but no cached article match) as a distinct, valid state from `found=False` (code doesn't exist) — this maps directly onto constraints.md C5's error-handling fallback chain for "規則庫查無醫令" scenarios.

Ready to advance to Phase 3.

---
*Phase: 02-rule-repository*
*Completed: 2026-07-31*
