# Phase 30 Plan 08 Summary: Windows Executable Packaging, Main Entrypoint & Fail-Closed Integrity Verification

## Execution Overview
- **Plan**: `30-08` (Wave 3)
- **Status**: Completed (Linux-verifiable components)
- **Requirements**: D-30-06, D-30-07, D-30-08, D-30-09

## Key Implementations

### 1. Configuration Storage & Security (`deploy/windows_agent/config.py`)
- `AgentSettings` dataclass stores client settings under `%LOCALAPPDATA%\ElcAgent\config.json`.
- `agent_key` and `operator_key` have `repr=False` to prevent leaking credentials in log outputs or representations (T-30-39).
- Atomic writes implemented using `.tmp` and `os.replace` to prevent corrupted configs.

### 2. Main Entrypoint & Startup Flow (`deploy/windows_agent/main.py`)
- `run_startup_flow()`:
  - First attempts `last_server_url` (unauthenticated probe first); if valid and authenticated, returns immediately without triggering subnet scanning (D-30-08).
  - On discovery of candidates, requires user confirmation before sending any credentials (D-30-09, T-30-40).
  - Falls back to manual entry with RFC 1918 IPv4 validation (`validate_manual_server_url`).
- `--selftest` mode:
  - Evaluates local settings readability, local `agent-desktop` binary existence, and local `CalibrationStore` readiness.
  - Returns exit code 2 with clean Chinese message if `agent-desktop` executable is missing.
  - Returns exit code 0 and indicates "尚未校正" if not calibrated; never writes to HIS (T-30-43).
  - Employs zero network calls (verified by tests).
- `--run` mode:
  - Runs startup connection flow.
  - If calibration is not ready, launches calibration wizard before polling.
  - Implements exponential backoff on server unavailability (2.0s doubled up to 300.0s) (T-30-42).
- Module-level imports do not load `tkinter` (lazy GUI import preserved for headless Linux).

### 3. Portable Packaging & Fail-Closed Integrity (`deploy/windows_agent/ElcAgent.spec`, `scripts/build_windows_agent.py`)
- `deploy/windows_agent/ElcAgent.spec`:
  - One-folder mode (`exclude_binaries=True`, `COLLECT`).
  - Includes `config.template.json` and `bin/`.
  - Excludes heavy ML/audio dependencies (e.g. whisper, llama_cpp, torch) and unit tests.
- `scripts/build_windows_agent.py`:
  - `build_manifest()`: Strictly discards `calibration/` directories, `config.json` containing keys, `.env` files, and any `*.json` other than `config.template.json` (T-30-37).
  - `verify_sha256()`: Fail-closed verification against `AGENT_DESKTOP_SHA256` environment variable; missing hash or mismatch raises `BuildIntegrityError` (T-30-38).
  - `make_zip()`: Builds one-folder zip where all items reside under top-level `ElcAgent/` directory (D-30-07).

## Assumptions, O-items & Threat Disposition Status

1. **ASSUMPTION O4 (Non-blocking)**:
   - UDP discovery probing is disabled by default; fallback sequence relies on cached URL -> subnet /24 probing -> manual input.
2. **ASSUMPTION O6 (Non-blocking)**:
   - In accordance with user decision, `agent-desktop.exe` binary is downloaded pre-compiled from GitHub Releases and verified against a pinned SHA256 (fail-closed if missing or mismatch). Live binary compilation/downloading is deferred to Windows machine validation in 30-09.
3. **T-30-41 (Unsigned exe - Accepted)**:
   - Disposition: Accept. Code signing certificates for Windows exe are excluded from Phase 30 scope since deployment is within internal clinic LAN workstations.

## Verification & Test Results
- `tests/test_agent_entrypoint.py`: 16 tests passed.
  - Settings: load defaults, round-trip, repr credential concealment.
  - Startup flow: cached URL skip, rejected candidate safety, manual entry validation, authenticated probe.
  - Selftest & Run: binary missing exit code 2, uncalibrated exit code 0 without HIS write, zero network requests, wizard callback, exponential backoff.
  - Packaging: manifest exclusions, sha256 fail-closed, missing sha256 fail-closed, spec verification, zip structure.
- Regression suite:
  ```bash
  .venv/bin/pytest tests/test_agent_entrypoint.py tests/test_agent_discovery.py tests/test_calibration_wizard.py tests/test_windows_agent.py --no-cov -x
  # 57 passed in 0.34s
  ```
- Lazy import check passed:
  ```bash
  python3 -c "import sys; sys.path.insert(0, '/home/hsu/Desktop/Elcinsurrence'); from deploy.windows_agent import main; assert 'tkinter' not in sys.modules"
  ```
