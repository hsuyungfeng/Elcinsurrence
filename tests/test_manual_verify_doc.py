"""Tests for Windows manual verification documentation accuracy (Phase 32 Plan 32-03, B10)."""

from pathlib import Path


def test_windows_manual_verify_doc_accuracy():
    doc_path = Path(".planning/phases/31-windows-client-traffic-light-bar-multi-session/31-WINDOWS-MANUAL-VERIFY.md")
    assert doc_path.exists(), "31-WINDOWS-MANUAL-VERIFY.md must exist"

    content = doc_path.read_text(encoding="utf-8")

    # 1. Must not reference the outdated agent_settings.json
    assert "agent_settings.json" not in content, "Document should not reference agent_settings.json"

    # 2. Must not reference the old agent module entrypoint
    assert "python -m deploy.windows_agent.agent" not in content, "Document should not launch agent module directly"

    # 3. Must reference actual config.json and ElcAgent.exe
    assert r"ElcAgent\config.json" in content or "ElcAgent/config.json" in content
    assert "ElcAgent.exe" in content

    # 4. Must reference log location for headless troubleshooting
    assert r"ElcAgent\logs\agent.log" in content or "ElcAgent/logs/agent.log" in content
