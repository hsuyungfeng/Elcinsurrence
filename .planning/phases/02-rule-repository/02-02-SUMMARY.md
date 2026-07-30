---
phase: 02-rule-repository
plan: 02
subsystem: database
tags: [sqlite, csv, etl, roc-calendar, gregorian-calendar, parameterized-sql]

# Dependency graph
requires:
  - phase: 02-rule-repository (Plan 01, Wave 0)
    provides: "RuleResult dataclass contract, tests/test_rule_repository_sqlite.py (red-state scaffold), tests/conftest.py tmp_rule_db_path fixture"
provides:
  - "src/elc_audit_engine/rule_repository/db.py: SQLite schema (payment_rules/drug_rules DDL) + get_connection/init_schema/query_by_code"
  - "src/elc_audit_engine/rule_repository/loaders/dates.py: parse_flexible_date() disambiguating 8-digit Gregorian vs 7-digit ROC dates"
  - "src/elc_audit_engine/rule_repository/loaders/payment_loader.py + drug_loader.py: CSV -> SQLite loaders"
  - "src/elc_audit_engine/rule_repository/scripts/build_sqlite.py: one-shot build entrypoint"
  - "Real data/db/rules.sqlite3 populated with 2669 payment_rules + 11273 drug_rules rows"
affects: [02-04-rule-mapping, 02-05-query-interface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "String-length-based date format disambiguation (7 digits = ROC RRRMMDD, 8 digits = Gregorian YYYYMMDD) rather than per-CSV configuration flags"
    - "Table-name allowlist checked before f-string interpolation into FROM clause, with all user-supplied values (code) going through ? placeholders exclusively"
    - "INSERT OR REPLACE + executemany batch insert pattern for CSV-to-SQLite loaders"
    - "glob-based CSV path resolution (no hardcoded filenames) to tolerate upstream filename drift"

key-files:
  created:
    - src/elc_audit_engine/rule_repository/db.py
    - src/elc_audit_engine/rule_repository/loaders/dates.py
    - src/elc_audit_engine/rule_repository/loaders/payment_loader.py
    - src/elc_audit_engine/rule_repository/loaders/drug_loader.py
    - src/elc_audit_engine/rule_repository/loaders/__init__.py
    - src/elc_audit_engine/rule_repository/scripts/__init__.py
    - src/elc_audit_engine/rule_repository/scripts/build_sqlite.py
    - tests/test_rule_repository_dates.py
  modified: []

key-decisions:
  - "Implemented the sentinel 'no date' list exactly as specified in the plan (empty string, \"null\", \"0\", \"99991231\") without adding extra special-casing for the year-2910 far-future values actually observed in the data (payment CSV's 29101231, drug CSV's 9991231) — both parse correctly via the normal Gregorian/ROC formula to 2910-12-31, so no additional sentinel was needed"
  - "Added scripts/__init__.py (not explicitly listed in plan's files_modified) so `python -m elc_audit_engine.rule_repository.scripts.build_sqlite` resolves as a package-relative module invocation"

patterns-established:
  - "Pattern: payment_rules and drug_rules share an identical column schema (code, name, payment_text, effective_from, effective_to) so downstream query code (Plan 05) can treat both tables uniformly"
  - "Pattern: query_by_code() as the single parameterized read path — table name allowlist-checked, code value always via ? placeholder"

requirements-completed: [REQ-rule-repository]

# Metrics
duration: 25min
completed: 2026-07-30
---

# Phase 2 Plan 2: Rule Repository SQLite Structured-Rule Layer Summary

**SQLite `payment_rules`/`drug_rules` tables built from CSV via glob-resolved loaders with ROC/Gregorian-aware date parsing, populating a real 2,669-row + 11,273-row `data/db/rules.sqlite3`.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-30T06:32:00Z
- **Completed:** 2026-07-30T06:57:01Z
- **Tasks:** 2 completed
- **Files modified:** 8 created

## Accomplishments
- `parse_flexible_date()` correctly disambiguates 8-digit Gregorian (`20160401` -> `2016-04-01`) from 7-digit ROC (`1121001` -> `2023-10-01`) dates by string length, with sentinel "no date" values (empty, `"null"`, `"0"`, `"99991231"`) returning `None` and unrecognized formats emitting a `warnings.warn` (not silently swallowed)
- `db.py` provides schema creation (`payment_rules`/`drug_rules`, identical column shapes) and a `query_by_code()` helper that is parameterized end-to-end: table name checked against a hardcoded allowlist before entering the f-string FROM clause, and the `code` value always passed via a `?` placeholder
- `payment_loader.py`/`drug_loader.py` load the real CSVs end-to-end: 2,669 payment rows and 11,273 drug rows, matching the plan's exact expected counts
- `build_sqlite.py` one-shot script actually run against the real source CSVs, populating `data/db/rules.sqlite3` (verified via direct sqlite3 query: `(2669,)` payment rows, `(11273,)` drug rows)
- `tests/test_rule_repository_sqlite.py` (written red in Plan 01) now fully green: 4/4 passing
- Spot-checked both required codes: `64140C` (payment) returns a full non-null `payment_text`; `AC10398100` (drug) returns `effective_from == "2023-10-01"`

## Task Commits

Each task was committed atomically:

1. **Task 1: Date parsing helper + SQLite schema/connection management** - `9781ae8` (feat)
2. **Task 2: Payment + drug CSV loaders and build script** - `5e6b2c7` (feat)

**Plan metadata:** (this commit) `docs: complete 02-02 plan`

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/loaders/dates.py` - `parse_flexible_date()`: length-based ROC/Gregorian disambiguation, sentinel handling, `warnings.warn` on unrecognized input
- `src/elc_audit_engine/rule_repository/db.py` - `SCHEMA_PAYMENT`/`SCHEMA_DRUG` DDL, `get_connection()` (auto-creates parent dir, sets `row_factory`), `init_schema()`, `query_by_code()` (allowlisted table + parameterized code)
- `src/elc_audit_engine/rule_repository/loaders/payment_loader.py` - `load_payment_csv(db_path, csv_path) -> int`, maps `診療項目代碼/中文項目名稱/支付規定/生效起日/生效迄日` to schema columns, Gregorian dates
- `src/elc_audit_engine/rule_repository/loaders/drug_loader.py` - `load_drug_csv(db_path, csv_path) -> int`, maps `藥品代號/藥品中文名稱/給付規定/有效起日/有效迄日` to schema columns, ROC dates
- `src/elc_audit_engine/rule_repository/loaders/__init__.py` - re-exports `load_payment_csv`/`load_drug_csv` to satisfy the `from elc_audit_engine.rule_repository import loaders` import contract
- `src/elc_audit_engine/rule_repository/scripts/build_sqlite.py` - one-shot entrypoint: glob-resolves both CSVs, calls both loaders, prints row-count summary
- `src/elc_audit_engine/rule_repository/scripts/__init__.py` - empty package marker (Rule 3 auto-fix, see Deviations)
- `tests/test_rule_repository_dates.py` - 4 self-contained tests for `dates.py`/`db.py`, independent of Plan 01's Wave 0 scaffolding

## Decisions Made
- Implemented sentinel date handling exactly per the plan's literal list rather than inventing extra cases for the year-2910 "far future" values actually observed in the real CSVs (`29101231` in payment, `9991231` in drug) — both already parse correctly to `2910-12-31` under the standard formula, so no additional logic was warranted
- Added `scripts/__init__.py` so the plan's own acceptance-criteria command (`python -m elc_audit_engine.rule_repository.scripts.build_sqlite`) resolves as a proper package submodule

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added missing `scripts/__init__.py`**
- **Found during:** Task 2, immediately before running the build script
- **Issue:** The plan's `files_modified` list didn't include a package marker for the new `scripts/` directory; without it, `python -m elc_audit_engine.rule_repository.scripts.build_sqlite` would fail to resolve as a package submodule under some import configurations
- **Fix:** Added an empty `src/elc_audit_engine/rule_repository/scripts/__init__.py`
- **Files modified:** `src/elc_audit_engine/rule_repository/scripts/__init__.py`
- **Verification:** `uv run python -m elc_audit_engine.rule_repository.scripts.build_sqlite` ran successfully and printed `payment_rules: 2669 rows, drug_rules: 11273 rows`
- **Committed in:** `5e6b2c7` (Task 2 commit)

**2. [Environment] Worktree was pinned to a pre-Phase-1 commit; fast-forwarded to main**
- **Found during:** Initial setup, before Task 1
- **Issue:** The spawned worktree's branch (`worktree-agent-a5a89c402f03273d8`) was at commit `14815e6`, which predates all of Phase 1 and Phase 2's planning artifacts (no `.planning/`, `src/`, `tests/`, or `config/` directories existed). This is the same class of issue documented in Plan 01's summary for a different worktree.
- **Fix:** Verified zero unique commits on the worktree branch relative to `main` (`git log worktree-agent-... ^main` empty) and that the worktree's HEAD was an ancestor of `main` (merge-base equals worktree HEAD), then ran `git merge --ff-only main` — a pure fast-forward with no discarded work.
- **Files modified:** None (git ref update only)
- **Verification:** Post-merge, `src/elc_audit_engine/rule_repository/models.py`, `tests/test_rule_repository_sqlite.py`, `config/settings.py`, and all `.planning/` plan files were present and readable.
- **Committed in:** N/A (fast-forward merge, no new commit created)

---

**Total deviations:** 2 (1 Rule 3 blocking fix, 1 environment/worktree-sync fix)
**Impact on plan:** Both necessary to execute the plan at all. No scope creep — neither changes the plan's design or behavior, only unblocks execution.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `data/db/rules.sqlite3` is populated for real (not just in tests) with both `payment_rules` (2,669 rows) and `drug_rules` (11,273 rows), ready for Plan 04 (rule_mapping build, needs SQLite codes to iterate over) and Plan 05 (single query interface).
- `db.query_by_code()` and the loaders are the stable, parameterized read/write surface Plan 05 should build its `get_rule()` interface on top of.
- All SQL in `loaders/` and `db.py` verified parameterized (`?` placeholders only); table-name allowlist in place as defense-in-depth per the threat model.
- No blockers for Plan 03 (docx tree extraction, running in parallel) or subsequent waves.

## Self-Check: PASSED

All 8 created files verified present on disk (individually checked via `[ -f ... ]`); both task commits (`9781ae8`, `5e6b2c7`) confirmed present via `git log --oneline --all`; real `data/db/rules.sqlite3` confirmed present on disk and populated (2669/11273 rows) via direct sqlite3 query.

---
*Phase: 02-rule-repository*
*Completed: 2026-07-30*
