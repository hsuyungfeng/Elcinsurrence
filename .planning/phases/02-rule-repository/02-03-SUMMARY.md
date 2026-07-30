---
phase: 02-rule-repository
plan: 03
subsystem: rule-repository
tags: [python-docx, libreoffice, regex, docx-tree, chinese-nlp, pageindex-alternative]

# Dependency graph
requires:
  - phase: 02-rule-repository
    provides: "Plan 02-01 Wave 0 scaffolding (RuleResult contract, tests/test_docx_tree_coverage.py red test)"
provides:
  - "docx_tree package: doc_converter.py (LibreOffice batch .doc->.docx), patterns.py (8-depth regex hierarchy detection), extractor.py (ordered block extraction + tree building), tree_builder.py (34-file... actually 32-file orchestration)"
  - "data/db/docx_trees.json build artifact (32 source files, 1633 tree nodes) for Plan 04's rule_mapping build"
affects: ["02-04-rule-mapping-build"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Custom PageIndex-style tree index built from python-docx + regex + JSON (explicitly NOT the pageindex PyPI cloud SaaS package, per D2 offline-only constraint)"
    - "Regex-first hierarchy detection (not style-name-based) to handle 100%-Normal-style source documents"
    - "iter_inner_content() for document-order paragraph/table interleaving"

key-files:
  created:
    - src/elc_audit_engine/rule_repository/docx_tree/__init__.py
    - src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py
    - src/elc_audit_engine/rule_repository/docx_tree/patterns.py
    - src/elc_audit_engine/rule_repository/docx_tree/extractor.py
    - src/elc_audit_engine/rule_repository/docx_tree/tree_builder.py
    - src/elc_audit_engine/rule_repository/scripts/__init__.py
    - src/elc_audit_engine/rule_repository/scripts/build_docx_trees.py
    - tests/test_doc_converter.py
    - tests/test_patterns.py
  modified:
    - tests/test_docx_tree_coverage.py
    - .gitignore

key-decisions:
  - "Source file count is 32 (11 .doc + 21 native .docx), not the plan's stale '34' (23 native .docx) figure -- tree_builder.py asserts against the live glob count, matching the pre-existing test_docx_tree_coverage.py approach"
  - "Fixed a bug in test_docx_tree_coverage.py's test_flat_structure_doc_produces_nested_tree: it iterated `for t in trees` assuming dict values, but build_all_trees returns dict[str, dict] per the plan's own interface contract, so iteration yielded string keys and getattr() lookups always returned falsy defaults, making the test always fail regardless of implementation correctness. Changed to trees.get(target) with a fallback scan."
  - "data/converted_docx/ (LibreOffice conversion staging output) added to .gitignore as a regenerable build byproduct"

patterns-established:
  - "Build-time artifacts (docx_trees.json, converted_docx/) are gitignored and regenerated via one-shot scripts, not committed to version control"

requirements-completed: [REQ-rule-repository]

# Metrics
duration: 35min
completed: 2026-07-30
---

# Phase 2 Plan 3: Custom docx-tree indexer Summary

**Custom PageIndex-style hierarchical tree indexer (python-docx + regex + JSON, zero cloud dependency) processes all 32 source .doc/.docx files into a 1633-node tree JSON, replacing the unusable cloud-only `pageindex` PyPI package.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-30T06:34:00Z (approx, first Read of plan)
- **Completed:** 2026-07-30T07:09:17Z
- **Tasks:** 2/2
- **Files modified:** 11 (9 created, 2 modified)

## Accomplishments
- LibreOffice headless batch conversion of all 11 legacy `.doc` files to valid `.docx` (verified via `docx.Document()` round-trip open)
- 8-depth Traditional Chinese hierarchy regex detection (第X部/章/節/項, 一二三..., (一)(二)..., 1.2.3., 甲乙丙...) confirmed working as the **primary** detection mechanism against real 100%-Normal-style documents (2-2-7 手術, 牙醫) that have zero custom heading styles
- Document-order paragraph+table extraction via `iter_inner_content()`, with tables correctly attached to their nearest preceding heading node (verified against the 附表 table-heavy document: 7 top-level tables + nested tables under sub-headings, all correctly ordered)
- `build_all_trees()` orchestrates the full pipeline (convert -> glob native -> extract -> tree-build) with an internal coverage assertion that raises `AssertionError` listing missing filenames if any file is silently skipped
- Real build artifact produced: `data/db/docx_trees.json` (32 top-level keys, 1633 total tree nodes, 3.58 MB)
- Confirmed via grep: no `pageindex` import anywhere in the new code (only an explanatory comment in `__init__.py` documenting why it's deliberately not used)

## Task Commits

Each task was committed atomically:

1. **Task 1: LibreOffice .doc conversion + regex hierarchy patterns** - `1d035be` (feat)
2. **Task 2: Ordered block extraction + tree builder orchestration** - `1c076e1` (feat)

**Plan metadata:** (pending — see final commit below)

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/docx_tree/__init__.py` - Package docstring explaining why pageindex PyPI is not used
- `src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py` - `convert_doc_files()`: LibreOffice headless batch `.doc`->`.docx` conversion with `RuntimeError` on missing `soffice`
- `src/elc_audit_engine/rule_repository/docx_tree/patterns.py` - `HEADING_PATTERNS` (8 depth-tagged regex patterns), `detect_heading_depth()`
- `src/elc_audit_engine/rule_repository/docx_tree/extractor.py` - `extract_ordered_blocks()` (iter_inner_content-based), `build_tree_for_file()` (depth-stack tree builder)
- `src/elc_audit_engine/rule_repository/docx_tree/tree_builder.py` - `build_all_trees()`: full orchestration + coverage assertion
- `src/elc_audit_engine/rule_repository/scripts/build_docx_trees.py` - One-shot entrypoint writing `data/db/docx_trees.json`
- `tests/test_doc_converter.py` - Conversion count, valid-OOXML, and soffice-missing RuntimeError tests
- `tests/test_patterns.py` - Depth detection tests for section/list/body-text cases
- `tests/test_docx_tree_coverage.py` - Fixed dict-iteration bug in `test_flat_structure_doc_produces_nested_tree`
- `.gitignore` - Added `data/converted_docx/` as regenerable build byproduct

## Decisions Made
- Followed the test file's own precedent (already noted in a Wave 0 comment) of asserting file count against the **live glob count** rather than the plan's stale hardcoded "34" — actual is 32 (11 `.doc` + 21 native `.docx`, not 23)
- Fixed the pre-existing dict/iteration mismatch bug in `test_flat_structure_doc_produces_nested_tree` (Rule 1 — the test as originally written from Wave 0 would fail against ANY correct dict-returning implementation, since `for t in trees` over a dict yields keys not values)
- Added `data/converted_docx/` to `.gitignore` since it's LibreOffice's regenerable staging output, not source-of-truth

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broken dict-iteration test in test_docx_tree_coverage.py**
- **Found during:** Task 2 (verification run of `test_flat_structure_doc_produces_nested_tree`)
- **Issue:** The Wave 0-authored test iterated `for t in trees` where `trees` is `dict[str, dict]` per the documented interface contract — this yields dict *keys* (strings), not tree node values. `getattr(t, "source_path", "")` and `getattr(t, "source_file", None)` on a string always return the fallback defaults, so the `next(...)` lookup would always return `None` and the assertion would always fail, regardless of whether `build_all_trees` was implemented correctly.
- **Fix:** Changed to `trees.get(target)` (direct dict key lookup) with a fallback scan over `trees.items()` for basename/stem matching, matching the plan's explicit `dict[str, dict]` interface contract and the Task 2 acceptance criteria's own `result["2-2-7第二部第二章第七節手術-113.12.01"]` indexing example.
- **Files modified:** tests/test_docx_tree_coverage.py
- **Verification:** `uv run pytest tests/test_docx_tree_coverage.py -v` — both tests pass
- **Committed in:** 1c076e1 (Task 2 commit)

**2. [Rule 3 - Blocking-adjacent, out-of-scope cleanup] Added data/converted_docx/ to .gitignore**
- **Found during:** Task 2 (running the real build script produced an untracked directory)
- **Issue:** LibreOffice's conversion staging output directory appeared as untracked files after running `build_docx_trees.py`; it is regenerable build byproduct, not source data
- **Fix:** Added `data/converted_docx/` to `.gitignore`
- **Files modified:** .gitignore
- **Verification:** `git status --short` no longer lists the directory as untracked
- **Committed in:** 1c076e1 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug fix in test logic, 1 gitignore hygiene addition)
**Impact on plan:** Both fixes were necessary for the plan's own acceptance criteria to be achievable/verifiable as written. No scope creep — no architectural changes, no new features beyond what the plan specified.

## Issues Encountered
- Plan's stated "34 total files" (23 native .docx + 11 .doc) does not match the actual source directory contents (21 native .docx + 11 .doc = 32). This was already identified and documented in a Wave 0 comment in `tests/test_docx_tree_coverage.py` from Plan 02-01, so `tree_builder.py`'s internal coverage assertion follows the same "assert against live glob count" approach rather than hardcoding 34. No code change was needed to correct this — it was a pre-existing discrepancy in the plan document itself, not something introduced by this plan.
- Two test collection errors (`tests/test_rule_repository_interface.py`, `tests/test_rule_repository_sqlite.py`) and one test failure (`tests/test_rule_mapping_spotcheck.py::test_fixture_all_entries_verified`) exist in the full repo test suite. These are pre-existing Wave 0 red-state scaffolding from commit `cd30ebf` (Plan 02-01), explicitly documented in `02-01-SUMMARY.md` as intentionally red pending future plans (02-02, 02-04, 02-05) — out of scope for this plan per the scope boundary rule. No action taken.

## User Setup Required
None - no external service configuration required. LibreOffice (`soffice`) was already confirmed installed on this machine at plan-provisioning time.

## Next Phase Readiness
- `data/db/docx_trees.json` is ready as the candidate-node source for Plan 04's rule_mapping build (LLM-assisted mapping between medical order codes and docx tree article locations)
- `tree_builder.build_all_trees()` and `extractor.build_tree_for_file()` are stable public interfaces other plans can import
- No blockers identified for Plan 04

## Self-Check: PASSED

All 10 created/output files verified present on disk (docx_tree/* modules, scripts/build_docx_trees.py, tests/test_doc_converter.py, tests/test_patterns.py, data/db/docx_trees.json, this SUMMARY.md). Both task commits (`1d035be`, `1c076e1`) verified present in git log.

---
*Phase: 02-rule-repository*
*Completed: 2026-07-30*
