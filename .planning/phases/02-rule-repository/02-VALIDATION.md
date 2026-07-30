---
phase: 2
slug: rule-repository
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-30
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (established in Phase 1, `[dependency-groups] dev = ["pytest>=8.0"]`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` `testpaths = ["tests"]` (from Phase 1) |
| **Quick run command** | `uv run pytest tests/test_rule_repository*.py -x` |
| **Full suite command** | `uv run pytest tests/ -v` |
| **Estimated runtime** | ~5-15 seconds (small CSV row counts: 2,669 payment + 11,273 drug rows; SQLite batch insert is sub-second) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_rule_repository*.py -x` (fast, SQLite-only tests)
- **After every plan wave:** Run `uv run pytest tests/ -v` (full suite including docx tree + mapping spot-check)
- **Before `/gsd-verify-work`:** Full suite green + manual 20-code spot-check sign-off
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 0 | REQ-rule-repository | — | Coverage assertion catches silently-skipped `.doc`/`.docx` files (Pitfall 6) | integration | `uv run pytest tests/test_docx_tree_coverage.py -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 0 | REQ-rule-repository | — | Parameterized SQL queries only (no string-formatted SQL) | unit | `uv run pytest tests/test_rule_repository_sqlite.py -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | REQ-rule-repository | T-02-01 | Do not import/call installed `pageindex` cloud SDK (Pitfall 1) — code review + grep check for `pageindex` imports | integration | `uv run pytest tests/test_docx_tree_coverage.py -x` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | REQ-rule-repository | — | rule_mapping 20-code human-verified spot-check locked as regression fixture | manual-assisted | `uv run pytest tests/test_rule_mapping_spotcheck.py -x` | ❌ W0 | ⬜ pending |
| 02-01-05 | 01 | 1 | D-07/D-08 | — | `get_rule(code)` returns dataclass; unknown code returns not-found state, not exception | unit | `uv run pytest tests/test_rule_repository_interface.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_rule_repository_sqlite.py` — covers payment_rules/drug_rules queryability by code (e.g., 64140C, 06012C), parameterized-query usage
- [ ] `tests/test_docx_tree_coverage.py` — covers full-corpus docx tree coverage (23 native .docx + 11 legacy .doc→.docx converted via LibreOffice = 34 total files); asserts processed file count == source file count
- [ ] `tests/test_rule_mapping_spotcheck.py` — covers 20-code hit-rate acceptance against a human-curated fixture file (`tests/fixtures/rule_mapping_20_spotcheck.json`), not live LLM output
- [ ] `tests/test_rule_repository_interface.py` — covers D-07/D-08 single-entry-point contract (`get_rule`/`lookup_rule`)
- [ ] `tests/conftest.py` fixtures for a temp/test SQLite DB path (avoid polluting `data/db/` during test runs) — extend Phase 1's existing `tests/conftest.py` pattern

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 20-code rule_mapping 命中率人工核對 | REQ-rule-repository (acceptance criterion 3) | Requires human judgment to confirm each code's 條文位置/全文 is factually correct against source docx/CSV text — cannot be fully automated on first build | Planner/executor presents the 20-code candidate list (replacing `01015C`, which does not exist in either CSV) with proposed 條文位置/全文 for each; user reviews each against source document; confirmed results are written to `tests/fixtures/rule_mapping_20_spotcheck.json` and become the regression fixture asserted by `test_rule_mapping_spotcheck.py` |
| llama.cpp completion quality smoke test | D-04 (LLM-assisted rule_mapping build) | Live server response anomaly observed during research (Pitfall 5) — needs a human to inspect raw response before trusting batch logic | First task of the rule_mapping build step: send one real, correctly-formatted chat-completion request to `http://localhost:8080/v1/chat/completions` and manually confirm the response contains generated text, not schema-descriptor placeholders |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
