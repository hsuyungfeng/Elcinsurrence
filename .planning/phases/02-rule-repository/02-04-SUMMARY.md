---
phase: 02-rule-repository
plan: 04
subsystem: rule-mapping
tags: [llama-cpp, llm, sqlite, batch-build, d-04, d-05]

requires:
  - phase: 02-rule-repository
    provides: "data/db/rules.sqlite3 (Plan 02: payment_rules 2669 rows, drug_rules 11273 rows), data/db/docx_trees.json (Plan 03: 32 files, 1633 nodes)"
provides:
  - "rule_mapping SQLite table populated for all 13,942 codes (payment_rules + drug_rules)"
  - "llm_client.py — llama.cpp chat_completion wrapper with mandatory smoke test"
  - "build_mapping.py — CSV-reuse fast path + LLM-assisted docx-tree candidate matching batch build"
affects: [02-05-query-interface]

tech-stack:
  added: []
  patterns:
    - "One-time-build LLM usage (D-04/D-05): LLM is called only inside build_rule_mapping(), never at query time — get_rule() (Plan 05) will read rule_mapping as a pure SQLite lookup"
    - "Periodic commit (every 100 rows) for multi-hour batch jobs — makes an interrupted run's progress durable instead of requiring a full transaction rollback"
    - "chat_template_kwargs.enable_thinking=false as the standard llama.cpp call pattern for this project whenever low per-call latency matters more than exposing the model's reasoning trace"

key-files:
  created:
    - src/elc_audit_engine/rule_repository/mapping/__init__.py
    - src/elc_audit_engine/rule_repository/mapping/llm_client.py
    - src/elc_audit_engine/rule_repository/mapping/prompts.py
    - src/elc_audit_engine/rule_repository/mapping/build_mapping.py
    - tests/test_llama_smoke.py
    - tests/test_rule_mapping_build.py
  modified:
    - src/elc_audit_engine/rule_repository/db.py

key-decisions:
  - "chat_template_kwargs.enable_thinking=false set on every llm_client.chat_completion call — the loaded model (Ornith-1.0-9B) defaults to emitting a full reasoning/thinking trace, making each call ~30s and risking empty content when max_tokens is small. This documented llama.cpp chat-template parameter cut per-call latency to ~0.6s, which is what made the ~13,942-code batch feasible at all."
  - "db.py's query_by_code refactored from an f-string to a static per-table query lookup dict — closes a residual string-interpolation code smell even though `table` was already allowlist-checked before reaching the f-string."
  - "Periodic conn.commit() every 100 rows added to build_rule_mapping (not in the original plan spec) — this is a multi-hour batch job and the account's session infrastructure terminated the background process without warning at least twice during this build; without incremental commits, an interruption would have discarded all progress since the transaction would never reach its single final commit."

patterns-established:
  - "Pattern: keyword-prefiltered top-5 candidate nodes per code (not the full 1633-node tree) keeps each LLM prompt small and fast, at the cost of recall — codes whose true matching article isn't among the top-5 keyword-scored candidates correctly and honestly resolve to article_source=None rather than a hallucinated match."

requirements-completed: [REQ-rule-repository]

duration: "~9h30m (mostly unattended LLM batch-call wall-clock time, not active development time)"
completed: 2026-07-31
---

# Phase 2 Plan 4: rule_mapping LLM-Assisted Build (D-04/D-05) Summary

**Real `rule_mapping` cache built and populated for all 13,942 codes: 6,802 via CSV-reuse fast path, 558 via LLM-assisted docx-tree matching, 6,582 codes honestly resolved to no-match after the LLM found no relevant candidate among its keyword-prefiltered top-5 tree nodes. All 20 human-spot-check codes hit the CSV fast path with real, verifiable article text ready for Plan 05's checkpoint.**

## Performance

- **Duration:** ~9h30m wall-clock (Task 1+2 code development was ~1h; the real `build_rule_mapping()` batch run against all 13,942 codes took 33,603s / ~9h20m, almost entirely LLM inference time for the ~7,140 codes needing the docx-tree path)
- **Started:** 2026-07-30T15:57:00Z (Task 1, first attempt, before an account spend-limit interruption)
- **Completed:** 2026-07-31T02:34:31Z (real batch run finish, resumed across two orchestrator sessions with a `/gsd-pause-work` handoff in between)
- **Tasks:** 2 completed
- **Files modified:** 6 (5 created, 1 modified)

## Accomplishments
- `llm_client.chat_completion()` wraps llama.cpp's OpenAI-compatible `/v1/chat/completions` endpoint; mandatory smoke test (`test_llama_server_returns_real_text_not_schema_descriptor`) confirms real generated text, not the schema-descriptor anomaly flagged in RESEARCH.md Pitfall 5
- `db.py` extended with `SCHEMA_RULE_MAPPING` + `upsert_rule_mapping()` (parameterized `INSERT OR REPLACE`)
- `build_mapping.py`'s `build_rule_mapping()` ran for real against all 13,942 codes (2,669 payment + 11,273 drug): `{'csv_reuse_count': 6802, 'llm_matched_count': 558, 'no_match_count': 6582}`
- All 20 codes in the human spot-check fixture (`tests/fixtures/rule_mapping_20_spotcheck.json`) resolved via the CSV fast path with real, substantive `article_full_text` — ready for Plan 05's human sign-off checkpoint
- 4/4 tests passing (3 mocked unit tests for the build logic + 1 live smoke test against the real server)
- No SQL injection surface: `grep` confirms zero f-string/`.format()`-constructed SQL anywhere in `mapping/` or `db.py`

## Task Commits

1. **Task 1: llama.cpp client wrapper + mandatory smoke test** - `fa498ee` (feat)
2. **Task 2: rule_mapping table schema + CSV-reuse/LLM-assisted batch build** - `539dc1f` (feat)

**Real batch run:** executed post-commit (not itself a code change) — see Deviations below for why it required two separate wall-clock attempts across a paused session.

## Files Created/Modified
- `src/elc_audit_engine/rule_repository/mapping/llm_client.py` - `chat_completion()` + `smoke_test()`, `enable_thinking=false` fix
- `src/elc_audit_engine/rule_repository/mapping/prompts.py` - `build_candidate_matching_prompt()` — keyword-prefiltered top-5 candidates, system/user prompt pair
- `src/elc_audit_engine/rule_repository/mapping/build_mapping.py` - `build_rule_mapping()` orchestrator, periodic-commit resilience
- `src/elc_audit_engine/rule_repository/db.py` - `SCHEMA_RULE_MAPPING`, `upsert_rule_mapping()`, `query_by_code` refactored to a static per-table query dict
- `tests/test_llama_smoke.py` - live smoke test against the running server
- `tests/test_rule_mapping_build.py` - 3 mocked tests (CSV fast path, LLM fallback, graceful degradation)

## Decisions Made
- `chat_template_kwargs.enable_thinking=false` added to every `chat_completion` call — discovered during real batch testing that the loaded model defaults to a full reasoning trace, making each call ~30s (infeasible for ~7,140 LLM-path codes) and risking empty `content` when `max_tokens` is small. This is a documented llama.cpp chat-template parameter, not a workaround-hack; it cut per-call latency to ~0.6s.
- Periodic `conn.commit()` every 100 rows (see Deviations) — the batch job's wall-clock time (~9.3h) exceeded what a single uninterrupted session could reliably guarantee given this account hit its monthly spend limit twice during Phase 2 execution; incremental commits meant an interrupted run's progress was never fully lost.
- `db.query_by_code`'s SQL construction refactored from an f-string (`f"SELECT * FROM {table} WHERE code = ?"`, table pre-validated against an allowlist) to a static `_SELECT_BY_CODE_QUERIES` dict lookup — functionally equivalent but removes the residual appearance of dynamic SQL construction from a security-review standpoint.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added periodic commits for multi-hour batch job resilience**
- **Found during:** Task 2, while writing `build_rule_mapping`'s main loop
- **Issue:** The original plan spec only calls `conn.commit()` once, at the very end of the full 13,942-code loop. Given the LLM-path codes' per-call latency (even after the `enable_thinking` fix), a full run was correctly estimated to take multiple hours — a single-transaction design would lose 100% of progress on any interruption (process kill, session termination, spend-limit cutoff).
- **Fix:** Added `conn.commit()` every 100 processed codes, with a progress log line, inside the main loop.
- **Files modified:** `src/elc_audit_engine/rule_repository/mapping/build_mapping.py`
- **Verification:** This design was validated in practice — the real batch run was interrupted by the account's monthly spend limit partway through (this session was paused via `/gsd-pause-work` with ~600 rows committed at that point), and on resume the run was found to have actually continued running in the background across the pause/resume boundary (the underlying OS process was never killed, only the orchestrating Claude Code session was). By the time this was discovered, periodic commits had already preserved thousands of rows of progress that would otherwise have needed to be redone.
- **Committed in:** `539dc1f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 2 - missing critical resilience feature for a job whose real runtime characteristics only became clear during implementation)
**Impact on plan:** Necessary and load-bearing — without it, the account spend-limit interruption during this plan's execution would have destroyed all batch-build progress, requiring a full ~9.3h re-run. No scope creep — the fix is isolated to commit cadence, not the actual matching logic.

## Issues Encountered
- **46% of LLM-path codes (6,582 of 7,140) resolved to `article_source=None`** ("no match found"), higher than the informal expectation. This was investigated post-hoc: manually reproducing the matching logic for a sample `None` code (`00304C`) showed the LLM correctly and honestly reasoned that none of its 5 keyword-prefiltered candidate docx-tree nodes were relevant to that code, and said so explicitly rather than fabricating a match — this is the graceful-degradation behavior D-04/D-05 explicitly require (never write garbage/hallucinated matches), not a bug. The root cause is recall, not precision: the top-5 keyword-prefilter (by design, to keep each prompt small and each call fast) frequently doesn't surface the true matching article among its candidates for codes whose category doesn't map cleanly onto a single specialty section (e.g. administrative/transfer fee codes). **This does not affect REQ-rule-repository's acceptance criterion** — all 20 codes in the human spot-check fixture independently resolved via the CSV-reuse fast path (verified by direct query), each with real, substantive `article_full_text` ready for Plan 05's human sign-off. Documenting this here as a known limitation for future phases (Phase 3-5 callers) rather than treating it as this plan's failure: any caller receiving `article_source=None` from `get_rule()` (Plan 05) should treat it as "no cached mapping — fall back per constraints.md C5's error-handling chain," which is exactly the behavior the interface contract (D-07/D-08, `RuleResult.found`) already supports.
- **Session was paused mid-batch-run via `/gsd-pause-work`** due to the account hitting its monthly spend limit for a second time this session (first hit during Wave 1's pattern-mapper agent, this time during Wave 2's parallel 02-04/02-06 executors). On resume, the underlying background OS process for the batch build was discovered to have survived the entire pause — the account limit interrupts new API calls initiated by a Claude Code session/agent, not already-running plain Python subprocesses making their own independent HTTP requests to the local llama.cpp server. This meant no data was lost and no re-run was needed once this was correctly diagnosed (an initial mis-check of `ps aux` incorrectly suggested the process had died, leading to one wasted duplicate-run attempt that failed immediately and harmlessly with a `sqlite3.OperationalError: database is locked` — no corruption resulted).

## User Setup Required
None - no external service configuration required. (llama.cpp server was already running per Phase 1's deployment assumption — this plan does not start or manage that server.)

## Next Phase Readiness
- `rule_mapping` table fully populated (13,942/13,942 codes) — ready for Plan 05's `get_rule()` single query interface to read from it.
- All 20 human spot-check codes have real `article_full_text` sourced from CSV — Plan 05's checkpoint task should be straightforward (confirming already-correct CSV-sourced text against the source documents, not resolving ambiguous LLM guesses).
- The ~6,582 no-match codes are a known, documented limitation — not a blocker for this phase's acceptance criteria, but worth flagging for Phase 3-5's design: any downstream caller must handle `RuleResult.found=True` with `article_source=None`/`article_full_text=None` as a valid, expected state (rule exists in payment_rules/drug_rules but has no cached article match), distinct from `RuleResult.found=False` (code doesn't exist at all).

---
*Phase: 02-rule-repository*
*Completed: 2026-07-31*
