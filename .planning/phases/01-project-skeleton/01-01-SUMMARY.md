---
phase: 01-project-skeleton
plan: 01
subsystem: project-scaffold
tags: [uv, config, skeleton]
dependency-graph:
  requires: []
  provides: [uv-project, config-settings-module, package-skeleton]
  affects: [phase-02-rule-repository, phase-03-parsers, phase-04-record-aggregator, phase-05-comparator, phase-06-07-generators]
tech-stack:
  added: [uv, flask, python-dotenv, pandas, python-docx, pageindex, chromadb, requests, pytest]
  patterns:
    - "config/settings.py env-var-overridable module constants (mirrors DrtoolboxLocalServer)"
    - "src/ layout package with empty subsystem stub sub-packages, one per future phase"
key-files:
  created:
    - pyproject.toml
    - .python-version
    - .gitignore (updated)
    - config/settings.py
    - config/llama_config.json
    - .env.example
    - src/elc_audit_engine/__init__.py
    - src/elc_audit_engine/parsers/__init__.py
    - src/elc_audit_engine/rule_repository/__init__.py
    - src/elc_audit_engine/record_aggregator/__init__.py
    - src/elc_audit_engine/comparator/__init__.py
    - src/elc_audit_engine/generators/__init__.py
    - data/.gitkeep
    - data/db/.gitkeep
    - data/rag/.gitkeep
    - data/output/.gitkeep
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_config.py
    - uv.lock
  modified: []
decisions:
  - "Added [dependency-groups] dev = [pytest>=8.0] to pyproject.toml — not specified in plan text but required for `uv run pytest` to resolve inside the project venv (Rule 3 blocking-issue fix)"
  - "gitignore data/db/ pattern changed to data/db/*  + !data/db/.gitkeep (plan text only specified this exception for data/rag/, but data/db/.gitkeep needs the same treatment to stay tracked)"
metrics:
  duration: "~25 minutes"
  completed: 2026-07-29
---

# Phase 1 Plan 1: uv 專案骨架、Config 載入機制、Package 結構 Summary

uv-managed Python 3.12 project skeleton with a DrtoolboxLocalServer-mirrored `config/settings.py` env-var-override module (LLAMA_CPP_BASE_URL, DATA_DIR, DB_DIR, RAG_DIR, OUTPUT_DIR, RULE_SOURCE_DIR) plus D2-locked `llama_config.json` (Ornith-1.0-9B, n_ctx 32768), a `src/elc_audit_engine/` package with 5 empty subsystem stub sub-packages for Phase 2-7, and a 4-test config test suite (all passing).

## What Was Built

**Task 1 — uv project init + directory skeleton** (commit `d9db5a4`)
- `pyproject.toml`: `elc-audit-engine` v0.1.0, Python >=3.12, `src/` layout via `[tool.setuptools.packages.find]`, dependencies `flask`, `python-dotenv`, `pandas`, `python-docx`, `pageindex`, `chromadb`, `requests`
- `.python-version` pinned to `3.12`
- `src/elc_audit_engine/` package + 5 empty stub sub-packages (`parsers`, `rule_repository`, `record_aggregator`, `comparator`, `generators`), each with a one-line Chinese docstring naming its owning future phase
- `data/{db,rag,output}/.gitkeep` — directory structure tracked, contents gitignored (except `data/output/`)
- `tests/__init__.py`
- `.gitignore` extended with Python/uv section (`__pycache__/`, `*.pyc`, `.venv/`, `.env`, `*.egg-info/`) and runtime-data section (`data/db/*`, `!data/db/.gitkeep`, `data/rag/*`, `!data/rag/.gitkeep`, `logs/`)
- `uv sync` generated `uv.lock` and `.venv/` (96 packages resolved)

**Task 2 — Config loading mechanism + llama.cpp connection settings** (commit `dc867ab`)
- `config/settings.py`: `load_dotenv()` at import time, `PROJECT_ROOT` derived from `__file__`, env-overridable `DATA_DIR`/`DB_DIR`/`RAG_DIR`/`OUTPUT_DIR`/`RULE_SOURCE_DIR`/`LLAMA_CPP_BASE_URL`/`LLAMA_CONFIG_PATH`, and `load_llama_config()` which raises `FileNotFoundError` (fail-fast) if the config file is missing
- `config/llama_config.json`: D2-locked values — `model.name = "Ornith-1.0-9B"`, `model.quantization = "Q6_K_XL"`, `model.path = "/home/hsu/llama.cpp/models/Ornith-1.0-9B-UD-Q6_K_XL.gguf"`, `inference.n_ctx = 32768`, `server.host = "localhost"`, `server.port = 8080`
- `.env.example`: path-override placeholders + `DO NOT COMMIT REAL TOKENS/SECRETS` convention section

**Task 3 — Config test suite (TDD)** (commit `9bab385`)
- `tests/conftest.py`: `sys.path.insert(0, PROJECT_ROOT)` mirroring DrtoolboxLocalServer's conftest pattern
- `tests/test_config.py`: 4 tests — module importability + `PROJECT_ROOT` existence, `LLAMA_CPP_BASE_URL` default value, `load_llama_config()` returns D2-locked values, `load_llama_config()` raises `FileNotFoundError` on a monkeypatched missing path
- All 4 tests pass: `uv run pytest tests/test_config.py -v` → `4 passed`

## Verification

- `uv run python -c "print('ok')"` → `ok`
- `uv run python -c "import elc_audit_engine; from config import settings; print(settings.LLAMA_CPP_BASE_URL)"` → `http://localhost:8080`
- `uv run pytest tests/ -v` → 4/4 passed
- `find . -maxdepth 2 -type d | grep -E "^\./(config|src|data|tests)$"` → all four present
- `git status --short` → clean working tree after final commit (no untracked/uncommitted files)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `uv run pytest` resolved a global pytest instead of the project venv**
- **Found during:** Task 3, first test run
- **Issue:** `pyproject.toml` declared no `pytest` dependency, so `uv run pytest` fell through to a system-wide `/home/hsu/.local/bin/pytest` running under `/usr/bin/python3`, which does not have `python-dotenv` installed — collection failed with `ModuleNotFoundError: No module named 'dotenv'`
- **Fix:** Added `[dependency-groups]` with `dev = ["pytest>=8.0"]` to `pyproject.toml`, then `uv sync --group dev`. Verified both `uv run pytest ...` and `uv run --group dev pytest ...` now resolve pytest from `.venv/bin/python3` and pass
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Commit:** `9bab385`

**2. [Rule 1 - Bug] `data/db/.gitkeep` was silently gitignored**
- **Found during:** Task 1, staging step
- **Issue:** The plan's action text specified `.gitignore` rule `data/db/` (blanket directory ignore) plus `data/rag/*` + `!data/rag/.gitkeep` (exception for the marker file), but gave no equivalent exception for `data/db/.gitkeep` — the blanket `data/db/` rule silently excluded it from tracking, contradicting the plan's own acceptance criteria ("`.gitkeep` present in `data/`, `data/db/`, `data/rag/`")
- **Fix:** Changed the `data/db/` gitignore rule to the same `data/db/*` + `!data/db/.gitkeep` pattern used for `data/rag/`, so the marker file stays tracked while db contents remain ignored
- **Files modified:** `.gitignore`
- **Commit:** `d9db5a4`

**3. [Rule 1 - Bug] `src/elc_audit_engine.egg-info/` build artifact was about to be committed**
- **Found during:** Task 1, staging step
- **Issue:** `uv sync` built the local package in editable/dev mode, generating `src/elc_audit_engine.egg-info/` (PKG-INFO, SOURCES.txt, etc.), which `git add src/` picked up as new files
- **Fix:** Unstaged and deleted the `egg-info` directory, added `*.egg-info/` to `.gitignore` so it stays untracked on subsequent builds
- **Files modified:** `.gitignore`
- **Commit:** `d9db5a4`

No architectural deviations (Rule 4) were needed.

## Known Stubs

The five subsystem sub-packages (`parsers`, `rule_repository`, `record_aggregator`, `comparator`, `generators`) are intentionally empty placeholder packages containing only a docstring — this is explicit Phase 1 scope per the plan (`REQ-project-skeleton`), not an unintentional stub. Each docstring names the future phase that will implement it (Phase 2 for `rule_repository`, Phase 3 for `parsers`, Phase 4 for `record_aggregator`, Phase 5 for `comparator`, Phase 6-7 for `generators`).

## Threat Flags

None — this plan's config/settings surface matches the `<threat_model>` in `01-01-PLAN.md` exactly (T-01-01 through T-01-04), no new trust-boundary-crossing surface was introduced beyond what was already registered (local-filesystem config reads, env-var overrides, no network/remote input).

## Self-Check: PASSED

- FOUND: pyproject.toml
- FOUND: .python-version
- FOUND: config/settings.py
- FOUND: config/llama_config.json
- FOUND: .env.example
- FOUND: src/elc_audit_engine/__init__.py
- FOUND: tests/conftest.py
- FOUND: tests/test_config.py
- FOUND: uv.lock
- FOUND commit d9db5a4 (Task 1)
- FOUND commit dc867ab (Task 2)
- FOUND commit 9bab385 (Task 3)
