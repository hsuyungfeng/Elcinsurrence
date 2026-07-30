---
phase: 02-rule-repository
plan: 01
subsystem: testing
tags: [dataclass, pytest, tdd, sqlite, docx, fixture, frozen-dataclass]

# Dependency graph
requires:
  - phase: 01-project-skeleton
    provides: "config/settings.py (RULE_SOURCE_DIR, DB_DIR), tests/conftest.py sys.path bootstrap, src/elc_audit_engine/rule_repository/ empty stub package"
provides:
  - "RuleResult frozen dataclass (D-07/D-08 contract) at src/elc_audit_engine/rule_repository/models.py"
  - "not_found() factory function"
  - "Finalized 20-code human spot-check fixture (tests/fixtures/rule_mapping_20_spotcheck.json), 01015C replaced"
  - "4 Wave-0 failing test scaffolds for Plans 02/03/05 to satisfy: test_rule_repository_sqlite.py, test_docx_tree_coverage.py, test_rule_mapping_spotcheck.py, test_rule_repository_interface.py"
  - "tests/conftest.py tmp_rule_db_path fixture"
affects: [02-02-sqlite-loaders, 02-03-docx-tree, 02-04-rule-mapping, 02-05-query-interface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RuleResult as the single locked return-type contract all later rule_repository plans implement against (no per-plan reinvention)"
    - "Wave-0 red-state test scaffolding: tests written and committed before implementation exists, asserting on ImportError/ModuleNotFoundError as the expected failure mode"
    - "Fixture-driven regression test (rule_mapping_20_spotcheck.json) decoupled from live LLM output — human sign-off flips verified:false to true in a later plan"

key-files:
  created:
    - src/elc_audit_engine/rule_repository/models.py
    - tests/test_rule_repository_models.py
    - tests/fixtures/rule_mapping_20_spotcheck.json
    - tests/test_rule_repository_sqlite.py
    - tests/test_docx_tree_coverage.py
    - tests/test_rule_mapping_spotcheck.py
    - tests/test_rule_repository_interface.py
  modified:
    - tests/conftest.py

key-decisions:
  - "Replaced invalid 01015C acceptance code with 20 CSV-verified-present codes (17 payment + 3 drug), all with substantive non-null 支付規定/給付規定 text spanning 檢查/處置/治療/手術/預防保健/藥品 categories"
  - "test_docx_tree_coverage.py asserts source-file count via live glob rather than a hardcoded '34' literal, since the actual on-disk count (11 .doc + 21 .docx = 32) diverges from the plan/research's stated 23 .docx figure"

patterns-established:
  - "Pattern: RuleResult(frozen=True) as immutable contract type — mutation raises dataclasses.FrozenInstanceError, enforced by test"
  - "Pattern: tmp_rule_db_path fixture returns an as-yet-nonexistent path so tests never touch data/db/rules.sqlite3"

requirements-completed: [REQ-rule-repository]

# Metrics
duration: 32min
completed: 2026-07-30
---

# Phase 2 Plan 1: Rule Repository Wave 0 Scaffolding Summary

**Locked the RuleResult dataclass contract (D-07/D-08), finalized the 20-code human spot-check fixture (01015C replaced with 20 verified-present codes), and wrote 4 intentionally-failing test files that Plans 02-05 must turn green.**

## Performance

- **Duration:** 32 min
- **Started:** 2026-07-30T05:34:22Z
- **Completed:** 2026-07-30T06:12:38Z
- **Tasks:** 2 completed
- **Files modified:** 8 (7 created, 1 modified)

## Accomplishments
- `RuleResult` frozen dataclass defined with all D-07/D-08 fields (code, source, name, payment_text, effective_from, effective_to, article_location, article_full_text, article_source, found) plus a `not_found()` module-level factory — 3/3 tests green
- 20-code human spot-check fixture finalized and written with verified-present codes only; `01015C` confirmed absent from both source CSVs and excluded
- 4 downstream test files created (SQLite queryability, docx tree coverage, 20-code spot-check regression, `get_rule()` interface contract) — all fail for the expected reason (missing implementation), none due to syntax/collection bugs unrelated to missing modules
- `tests/conftest.py` extended with `tmp_rule_db_path` fixture without breaking Phase 1's existing `test_config.py` suite (still 4/4 passing)

## Task Commits

Each task was committed atomically:

1. **Task 1: Define RuleResult contract + finalize 20-code fixture** - `acd6ff3` (feat)
2. **Task 2: Write Wave 0 failing test scaffolding** - `cd30ebf` (test)

**Plan metadata:** (this commit) `docs: complete 02-01 plan`

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/models.py` - `RuleResult` frozen dataclass + `not_found()` factory (D-07/D-08 contract)
- `tests/test_rule_repository_models.py` - 3 green tests: construction, not_found factory, frozen-instance mutation guard
- `tests/fixtures/rule_mapping_20_spotcheck.json` - 20-code candidate list (17 payment, 3 drug), all `verified: false`
- `tests/conftest.py` - added `tmp_rule_db_path(tmp_path)` fixture returning an as-yet-nonexistent temp SQLite path
- `tests/test_rule_repository_sqlite.py` - 4 tests against `elc_audit_engine.rule_repository.db`/`loaders` (not yet implemented; ImportError expected)
- `tests/test_docx_tree_coverage.py` - 2 tests against `elc_audit_engine.rule_repository.docx_tree.tree_builder` (not yet implemented; ModuleNotFoundError expected)
- `tests/test_rule_mapping_spotcheck.py` - 2 tests against the fixture JSON only (no rule_repository import; `test_fixture_has_20_entries` passes now, `test_fixture_all_entries_verified` fails until Plan 05's human checkpoint)
- `tests/test_rule_repository_interface.py` - 3 tests against `elc_audit_engine.rule_repository.get_rule` (not yet implemented; ImportError expected)

## Decisions Made
- Selected the final 20 spot-check codes from CONTEXT.md's draft candidates plus additional verified-present codes to reach exactly 20 with category diversity (檢查×8, 治療×4, 處置×2, 手術×1, 預防保健×2, 藥品×3), all independently re-verified present in the source CSVs this session with non-trivial rule text (78-1269 chars)
- Kept `test_docx_tree_coverage.py`'s file-count assertion dynamic (derived from `glob`) rather than hardcoding the plan's stated "34" total, since the actual on-disk count is 32 (11 `.doc` + 21 `.docx`, not 23 `.docx` as stated in 02-01-PLAN.md/02-RESEARCH.md) — see Deviations below

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected stale hardcoded file-count assumption in docx coverage test**
- **Found during:** Task 2 (writing `tests/test_docx_tree_coverage.py`)
- **Issue:** The plan's task spec and 02-RESEARCH.md both assert the source directory contains "34 total: 11 `.doc` + 23 `.docx`" files. Direct verification this session (`glob` count) shows 11 `.doc` + 21 `.docx` = 32 files actually present on disk — the `.docx` count in the plan/research is stale by 2 files. A test hardcoding `assert total_source_files == 34` would fail permanently even after Plan 03 lands a fully correct `tree_builder` implementation, since the true source-file count is 32.
- **Fix:** Changed the assertion to derive the expected count purely from the live `glob("*.doc") + glob("*.docx")` result (asserting it's `> 0` as a sanity check, then asserting `len(trees) == total_source_files`), matching the acceptance criteria's actual intent ("count of files returned equals count globbed from RULE_SOURCE_DIR") rather than a stale magic number. Documented via inline code comment.
- **Files modified:** `tests/test_docx_tree_coverage.py`
- **Verification:** Confirmed via `ls officialdocument/審查注意事項/*.doc | wc -l` (11) and `*.docx | wc -l` (21); test still ImportErrors at Wave 0 as expected (collection fails before the assertion line executes), so this fix only affects the test's *future* correctness once Plan 03 lands.
- **Committed in:** `cd30ebf` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 - bug fix on stale hardcoded literal)
**Impact on plan:** Necessary for Plan 03 to be able to actually turn this test green later; without the fix, Plan 03 would need to either fabricate 2 phantom files or this test would remain permanently red due to a data-accuracy bug inherited from planning documents, not implementation. No scope creep — the fix only touches the assertion's literal value, not the test's structure or intent.

## Issues Encountered
None beyond the deviation above.

## Worktree/Branch Note
This worktree's git branch (`worktree-agent-a8bdbe93edcf588f1`) was found stale at session start — pinned to an ancestor commit (`14815e6`) that predated all of Phase 1's completion and Phase 2's planning (the `.planning/phases/02-rule-repository/02-01-PLAN.md` file referenced in this task's prompt did not yet exist on that commit). Verified the branch had zero unique commits beyond the merge-base with `main`, then fast-forwarded (`git merge --ff-only main`) to bring the worktree in sync before starting execution. No divergent work was discarded; this was a pure fast-forward.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `RuleResult` contract is locked; Plans 02 (SQLite loaders), 03 (docx tree), 04 (rule_mapping build), and 05 (query interface) can now implement against a single, stable return type without inventing their own shapes.
- 20-code spot-check fixture is finalized and ready for Plan 05's human-verification checkpoint (fill `article_location`/`article_full_text`, flip `verified` to `true`).
- 4 Wave-0 test files are in place as concrete, unambiguous "definition of done" targets for Plans 02, 03, and 05 — each currently red for the correct, expected reason.
- No blockers for Wave 1 (Plan 02 — SQLite loaders) to begin.

## Self-Check: PASSED

All 8 created/modified files verified present on disk; both task commits (`acd6ff3`, `cd30ebf`) confirmed in `git log --oneline --all`.

---
*Phase: 02-rule-repository*
*Completed: 2026-07-30*
