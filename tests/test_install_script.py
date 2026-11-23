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

    llama_service = out_dir / "elc-llama-server.service"
    assert llama_service.exists()
    llama_content = llama_service.read_text(encoding="utf-8")
    assert "WorkingDirectory=/opt/elc-test" in llama_content
    assert "--ctx-size 131072" in llama_content


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


def test_install_script_check_asr_models_4_files(tmp_path):
    """--check-asr-models 驗證 4 項必備模型檔（含 pyannote model.int8.onnx 擇一）。"""
    script = Path("deploy/install.sh")
    cache_dir = tmp_path / "elc-sherpa"
    env = os.environ.copy()
    env["ELC_SHERPA_CACHE_DIR"] = str(cache_dir)
    for k in ("ELC_SHERPA_SENSEVOICE_DIR", "ELC_SHERPA_PYANNOTE_DIR", "ELC_SHERPA_EMBEDDING_MODEL"):
        env.pop(k, None)

    # 1. 空目錄 → 非 0
    p_miss = subprocess.run(["bash", str(script), "--check-asr-models"], env=env, capture_output=True, text=True)
    assert p_miss.returncode != 0
    assert "tokens.txt" in p_miss.stderr

    # 2. 補齊 4 檔（pyannote 用 model.int8.onnx 擇一）→ 0
    sv = cache_dir / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
    pyan = cache_dir / "sherpa-onnx-pyannote-segmentation-3-0"
    sv.mkdir(parents=True)
    pyan.mkdir(parents=True)
    (sv / "model.int8.onnx").write_bytes(b"onnx")
    (sv / "tokens.txt").write_text("a 0\n", encoding="utf-8")
    (pyan / "model.int8.onnx").write_bytes(b"onnx")
    (cache_dir / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx").write_bytes(b"onnx")

    p_ok = subprocess.run(["bash", str(script), "--check-asr-models"], env=env, capture_output=True, text=True)
    assert p_ok.returncode == 0
    assert "[OK]" in p_ok.stdout


def test_install_script_check_llama_cache_handles_symlinks(tmp_path):
    """--check-llama-cache 檢查 HF snapshots/ 下有效 symlink，失效 symlink 或缺失回非 0。"""
    script = Path("deploy/install.sh")
    hf_hub = tmp_path / "hub"
    snap = hf_hub / "models--unsloth--gemma-4-E4B-it-GGUF" / "snapshots" / "abc123"
    blobs = hf_hub / "models--unsloth--gemma-4-E4B-it-GGUF" / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir(parents=True)

    env = os.environ.copy()
    env["ELC_HF_HUB_DIR"] = str(hf_hub)

    # 1. 失效（dangling）symlink → 非 0
    dangling = snap / "gemma-4-E4B-it-Q4_K_M.gguf"
    dangling.symlink_to(blobs / "nonexistent_blob")
    p_bad = subprocess.run(["bash", str(script), "--check-llama-cache"], env=env, capture_output=True, text=True)
    assert p_bad.returncode != 0

    # 2. 補上實際 blob 目標 → 0
    (blobs / "nonexistent_blob").write_bytes(b"gguf")
    p_ok = subprocess.run(["bash", str(script), "--check-llama-cache"], env=env, capture_output=True, text=True)
    assert p_ok.returncode == 0
    assert "OK:" in p_ok.stdout
