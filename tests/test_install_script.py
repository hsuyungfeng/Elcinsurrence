"""Tests for install script (Phase 32 Plan 32-15, D1/C6)."""

import os
from pathlib import Path
import re
import subprocess
import pytest


def test_install_script_syntax_and_safety():
    script = Path("deploy/install.sh")
    if not script.exists():
        pytest.fail("deploy/install.sh does not exist")

    # Syntax check
    p = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert p.returncode == 0, f"Bash syntax error: {p.stderr}"

    # No curl pipe to bash
    content = script.read_text(encoding="utf-8")
    assert not re.search(r"curl[^\n]*\|\s*(ba)?sh", content)


def test_install_script_render_units(tmp_path):
    script = Path("deploy/install.sh")
    if not script.exists():
        pytest.fail("deploy/install.sh does not exist")

    out_dir = tmp_path / "systemd"
    env = os.environ.copy()
    env["ELC_INSTALL_ROOT"] = "/opt/elc-test"

    p = subprocess.run(
        ["bash", str(script), "--render-units", str(out_dir)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    service_file = out_dir / "elc-audit-engine.service"
    assert service_file.exists()
    content = service_file.read_text(encoding="utf-8")
    assert "WorkingDirectory=/opt/elc-test" in content
    assert "/home/hsu/Desktop" not in content


def test_install_script_write_env_idempotent(tmp_path):
    script = Path("deploy/install.sh")
    if not script.exists():
        pytest.fail("deploy/install.sh does not exist")

    env_file = tmp_path / "env"
    p1 = subprocess.run(["bash", str(script), "--write-env", str(env_file)], capture_output=True, text=True)
    assert p1.returncode == 0
    content1 = env_file.read_text(encoding="utf-8")
    assert "ELC_SERVER_HOST=0.0.0.0" in content1
    assert "ELC_API_KEYS" not in content1

    # Modify a key and run again -> must not overwrite existing value
    env_file.write_text(content1 + "\nCUSTOM_TEST_KEY=preserved\n", encoding="utf-8")
    p2 = subprocess.run(["bash", str(script), "--write-env", str(env_file)], capture_output=True, text=True)
    assert p2.returncode == 0
    assert "CUSTOM_TEST_KEY=preserved" in env_file.read_text(encoding="utf-8")


def test_install_script_dry_run_outputs_urls():
    script = Path("deploy/install.sh")
    env = os.environ.copy()
    env["ELC_INSTALL_ROOT"] = "/tmp/elc-dry"

    p = subprocess.run(
        ["bash", str(script), "--dry-run", "--yes"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    out = p.stdout
    assert "http://" in out
    assert "/setup" in out
    assert "/status" in out
