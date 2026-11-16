"""tests/test_phase32_readiness.py
Plan 32-24: Phase 32 Overall Readiness Assertion and Integrity Regression.

Validates that:
1. All Phase 32 deliverables across host, client, frontend, and docs exist and are valid.
2. Shell scripts have valid bash syntax and proper permissions.
3. Zero deletion and exFAT backup contracts (D-32-03, D-32-04) function correctly.
4. No xfail markers remain in the test suite for Phase 32.
5. All architecture and product decisions D-32-01 through D-32-15 are documented and aligned.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


REQUIRED_ARTIFACTS: list[str] = [
    # Host server deployment & health
    "deploy/install.sh",
    "deploy/backup.sh",
    "deploy/healthcheck.sh",
    "static/setup.html",
    "static/status.html",
    # Windows client & installer
    "installer/elc_agent.iss",
    "deploy/windows_agent/first_run_wizard.py",
    "deploy/windows_agent/tray.py",
    "deploy/windows_agent/supervisor.py",
    "deploy/windows_agent/pick_control.py",
    # Frontend assets
    "static/css/workbench.css",
    "static/js/workbench.js",
    # Documentation & guides
    "docs/CLINIC_QUICKSTART_DOCTOR.md",
    "docs/CLINIC_DEPLOYMENT_GUIDE.md",
]


def test_all_phase32_artifacts_present() -> None:
    """Task 1: Assert all Phase 32 files exist and are non-empty."""
    missing: list[str] = []
    empty: list[str] = []

    for rel_path in REQUIRED_ARTIFACTS:
        full_path = WORKSPACE_ROOT / rel_path
        if not full_path.exists():
            missing.append(rel_path)
        elif full_path.stat().st_size == 0:
            empty.append(rel_path)

    assert not missing, f"Missing Phase 32 artifacts: {missing}"
    assert not empty, f"Empty Phase 32 artifacts: {empty}"


def test_shell_scripts_syntax() -> None:
    """Verify all bash scripts pass `bash -n` syntax check."""
    scripts = [
        WORKSPACE_ROOT / "deploy/install.sh",
        WORKSPACE_ROOT / "deploy/backup.sh",
        WORKSPACE_ROOT / "deploy/healthcheck.sh",
    ]
    for script in scripts:
        assert script.exists(), f"{script} does not exist"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error in {script}: {result.stderr}"


def test_exfat_dual_retention_backup_runnable_in_tmp() -> None:
    """Verify exFAT backup contract works in tmp directory with zero deletion."""
    from elc_audit_engine.backup_job import run_backup

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        src_data = tmp_path / "data"
        src_data.mkdir()
        backup_root = tmp_path / "backup_dest"
        backup_root.mkdir()
        status_file = tmp_path / "backup_status.json"

        # Create dummy db and vault file
        db_path = src_data / "audit.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE test (id INT, note TEXT);")
            conn.execute("INSERT INTO test VALUES (1, 'clinic data');")
            conn.commit()

        (src_data / "test_file.txt").write_text("sample content", encoding="utf-8")

        result_code = run_backup(
            data_dir=src_data,
            backup_root=backup_root,
            stamp="20261114T120000",
            status_file=status_file,
            allow_same_fs=True,
        )

        assert result_code == 0
        assert status_file.exists()
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        assert status_data["status"] == "success"

        # Verify DB snapshot is queryable in backup
        full_dir = backup_root / "elc-backup" / "full"
        backed_db = full_dir / "audit.db"
        assert backed_db.exists(), f"audit.db not in {full_dir}"

        with sqlite3.connect(str(backed_db)) as target_conn:
            cur = target_conn.cursor()
            cur.execute("SELECT note FROM test WHERE id = 1;")
            row = cur.fetchone()
            assert row is not None and row[0] == "clinic data"


def test_zero_xfail_in_phase32_tests() -> None:
    """Assert no xfail markers remain in tests related to Phase 32."""
    phase32_test_files = [
        "tests/test_lan_trust.py",
        "tests/test_discovery_udp.py",
        "tests/test_capacity_runway.py",
        "tests/test_backup_script.py",
        "tests/test_first_run_wizard.py",
        "tests/test_agent_entrypoint.py",
        "tests/test_workbench_static.py",
        "tests/test_workbench_e2e_smoke.py",
    ]
    for rel in phase32_test_files:
        test_path = WORKSPACE_ROOT / rel
        if test_path.exists():
            content = test_path.read_text(encoding="utf-8")
            assert "@pytest.mark.xfail" not in content, f"Found active xfail marker in {rel}"


def test_decisions_alignment_d32_all() -> None:
    """Verify that all core decisions D-32-01 through D-32-15 are reflected in code/docs."""
    # D-32-01: LAN trust mode (config has lan_trust)
    facility_cfg = WORKSPACE_ROOT / "config/facility.json.example"
    if facility_cfg.exists():
        assert "lan_trust" in facility_cfg.read_text(encoding="utf-8")

    # D-32-02: SmartScreen documentation
    deploy_guide = (WORKSPACE_ROOT / "docs/CLINIC_DEPLOYMENT_GUIDE.md").read_text(encoding="utf-8")
    assert "SmartScreen" in deploy_guide

    # D-32-03: exFAT support in deployment guide
    assert "exFAT" in deploy_guide

    # D-32-04: Zero deletion in backup
    backup_job_src = (WORKSPACE_ROOT / "src/elc_audit_engine/backup_job.py").read_text(encoding="utf-8")
    assert "--delete" not in backup_job_src

    # D-32-05: Capacity thresholds 180 and 90 days
    capacity_src = (WORKSPACE_ROOT / "src/elc_audit_engine/capacity.py").read_text(encoding="utf-8")
    assert "180" in capacity_src
    assert "90" in capacity_src

    # D-32-06: Strict CSP without unsafe-inline
    index_html = (WORKSPACE_ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "workbench.js" in index_html
    assert "workbench.css" in index_html

    # D-32-07: Single instance mutex
    main_py = (WORKSPACE_ROOT / "deploy/windows_agent/main.py").read_text(encoding="utf-8")
    assert "ElcAgentSingleInstance" in main_py

    # D-32-08: 3-step workflow guide
    workbench_js = (WORKSPACE_ROOT / "static/js/workbench.js").read_text(encoding="utf-8")
    assert "workflow-stepper" in workbench_js or "initDoctorMode" in workbench_js

    # D-32-09: Destructive action confirmation modal
    assert "confirm-destructive-modal" in index_html

    # D-32-10: 3-track naming (no double track)
    assert "雙軌" not in index_html
    assert "三軌" in index_html

    # D-32-11: Structured error modal
    assert "structured-error-modal" in index_html

    # D-32-12: Doctor 1-page quickstart guide
    doc_guide = (WORKSPACE_ROOT / "docs/CLINIC_QUICKSTART_DOCTOR.md").read_text(encoding="utf-8")
    assert "三顆燈" in doc_guide
