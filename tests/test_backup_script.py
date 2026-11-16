"""Tests for backup script and backup_job.py (Phase 32 Plan 32-10, D-32-11)."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import pytest

from elc_audit_engine.backup_job import plan_incremental, run_backup


def test_backup_script_full_and_incremental(tmp_path):
    # Setup source data directory
    src_data = tmp_path / "data"
    src_data.mkdir()
    db_path = src_data / "cases.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE test (id INT, val TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'initial')")
        conn.commit()

    (src_data / "a.txt").write_text("hello a", encoding="utf-8")
    (src_data / "b.txt").write_text("hello b", encoding="utf-8")

    backup_root = tmp_path / "backup_dest"
    backup_root.mkdir()
    status_file = tmp_path / "backup_status.json"

    env = os.environ.copy()
    env["ELC_DATA_DIR"] = str(src_data)
    env["ELC_BACKUP_ROOT"] = str(backup_root)
    env["ELC_BACKUP_STAMP"] = "20261101T020000"
    env["ELC_BACKUP_STATUS_FILE"] = str(status_file)
    env["ELC_BACKUP_ALLOW_SAME_FS"] = "1"

    script = Path("deploy/backup.sh")
    if not script.exists():
        pytest.fail("deploy/backup.sh does not exist")

    # First run -> Full backup
    p1 = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert p1.returncode == 0, f"STDOUT: {p1.stdout}\nSTDERR: {p1.stderr}"
    assert (backup_root / "elc-backup" / "full").exists()
    assert (backup_root / "elc-backup" / "manifests" / "20261101T020000.json").exists()

    status_data1 = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_data1["mode"] == "full"
    assert status_data1["status"] == "success"

    # Modify a.txt and run second incremental backup
    (src_data / "a.txt").write_text("hello a modified", encoding="utf-8")
    env["ELC_BACKUP_STAMP"] = "20261102T020000"
    p2 = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert p2.returncode == 0, f"STDOUT: {p2.stdout}\nSTDERR: {p2.stderr}"
    assert (backup_root / "elc-backup" / "incr" / "20261102T020000" / "a.txt").exists()
    assert not (backup_root / "elc-backup" / "incr" / "20261102T020000" / "b.txt").exists()

    status_data2 = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_data2["mode"] == "incremental"
    assert status_data2["verified_files"] == 1


def test_backup_hash_mismatch_failure(tmp_path, monkeypatch):
    """驗證寫入檔案雜湊不符時立即中止、不寫出 manifest、並記錄錯誤。"""
    src_data = tmp_path / "data_mismatch"
    src_data.mkdir()
    (src_data / "file.txt").write_text("source content", encoding="utf-8")

    backup_root = tmp_path / "backup_dest_mismatch"
    backup_root.mkdir()
    status_file = tmp_path / "status_mismatch.json"

    # Monkeypatch shutil.copyfile 寫入錯誤內容以模擬傳輸位元損壞
    orig_copyfile = shutil.copyfile

    def corrupted_copyfile(src, dst, *args, **kwargs):
        orig_copyfile(src, dst, *args, **kwargs)
        with open(dst, "ab") as f:
            f.write(b"corrupted_bytes")

    monkeypatch.setattr(shutil, "copyfile", corrupted_copyfile)

    ret = run_backup(
        data_dir=src_data,
        backup_root=backup_root,
        stamp="20261101T999999",
        status_file=status_file,
        allow_same_fs=True,
    )

    assert ret != 0
    # manifest 嚴禁寫出
    assert not (backup_root / "elc-backup" / "manifests" / "20261101T999999.json").exists()
    # 狀態 JSON 必須含有錯誤訊息
    assert status_file.exists()
    st = json.loads(status_file.read_text(encoding="utf-8"))
    assert "備份檔驗證失敗" in st.get("error", "")


def test_backup_same_fs_rejected_without_override(tmp_path):
    """驗證當目的端與資料目錄在同一檔案系統且未設定 allow_same_fs 時拒絕備份。"""
    src_data = tmp_path / "data_same"
    src_data.mkdir()
    backup_root = tmp_path / "backup_same"
    backup_root.mkdir()
    status_file = tmp_path / "status_same.json"

    ret = run_backup(
        data_dir=src_data,
        backup_root=backup_root,
        stamp="20261101T000000",
        status_file=status_file,
        allow_same_fs=False,
    )

    assert ret != 0
    assert status_file.exists()
    st = json.loads(status_file.read_text(encoding="utf-8"))
    assert "備份目的端不得與資料目錄位於同一裝置" in st.get("error", "")


def test_plan_incremental_logic():
    """單元測試 plan_incremental 增量判定。"""
    source_index = {
        "doc1.pdf": {"sha256": "h1", "size": 100},
        "doc2.pdf": {"sha256": "h2", "size": 200},
        "new.pdf": {"sha256": "h3", "size": 300},
    }
    prev_manifest = {
        "files": {
            "doc1.pdf": {"sha256": "h1", "size": 100, "location": "full/doc1.pdf"},
            "doc2.pdf": {"sha256": "old_h2", "size": 190, "location": "full/doc2.pdf"},
            "deleted.pdf": {"sha256": "h_del", "size": 50, "location": "full/deleted.pdf"},
        }
    }

    plan = plan_incremental(source_index, prev_manifest)
    assert plan["mode"] == "incremental"
    # doc1 未變更，doc2 變更，new 為新檔
    assert "doc1.pdf" not in plan["to_copy"]
    assert "doc2.pdf" in plan["to_copy"]
    assert "new.pdf" in plan["to_copy"]
    assert plan["manifest_files"]["doc1.pdf"]["location"] == "full/doc1.pdf"


def test_backup_no_deletion_or_hardlinks():
    for f in [Path("deploy/backup.sh"), Path("src/elc_audit_engine/backup_job.py")]:
        if not f.exists():
            pytest.fail(f"{f} does not exist yet")
        content = f.read_text(encoding="utf-8")
        forbidden = [
            "--delete", "rm -rf", "-delete", "rmtree",
            "os.remove", "unlink(", "os.link", "symlink", "--link-dest"
        ]
        for item in forbidden:
            assert item not in content, f"Forbidden backup pattern {item} found in {f}"
