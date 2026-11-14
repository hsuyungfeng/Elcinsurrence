"""Phase 32 Plan 10: D4 增量備份任務 (backup_job.py).

(D-32-04, D-32-07, D-32-11)
備份規則保證：
1. 完整一份 (full/) ＋ 每日增量 (incr/$STAMP/)，只增不刪。
2. SQLite 以 sqlite3.connect().backup() 取得一致性快照，不直接複製運作中資料庫；排除 -wal, -shm, -journal。
3. 每個複製檔案均經 sha256 與來源雜湊驗證，不符即失敗且不寫出 manifest。
4. 不依賴硬連結、符號連結或 Unix 權限，相容 exFAT 媒體。
5. 每次備份產生一份包含當前所有檔案指標之 manifest JSON。
6. 目的端不可與來源位於同一裝置（以 st_dev 檢查，防誤寫入主機磁碟）。
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

_EXFAT_FORBIDDEN = set('\\:*?"<>|')


def _sanitize_for_exfat(relpath: str) -> str:
    """替換或百分比編碼 exFAT 不合法字元。"""
    res = []
    for ch in relpath:
        if ch in _EXFAT_FORBIDDEN:
            res.append(f"%{ord(ch):02X}")
        else:
            res.append(ch)
    return "".join(res)


def sha256_file(path: Union[str, Path]) -> str:
    """計算檔案之 SHA-256 雜湊值（hex digest）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def plan_incremental(
    source_index: Dict[str, Dict[str, Any]],
    previous_manifest: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """計算增量備份計畫。

    比對來源檔案索引與前次 manifest：
    - 若無前次 manifest：mode="full"，全部檔案皆需複製，location="full"
    - 若有前次 manifest：mode="incremental"，僅複製新檔或 sha256 變更檔
      未變更者保留前次 location，來源已刪除者不列入本次 manifest
    """
    if previous_manifest is None:
        to_copy = {k: v for k, v in source_index.items()}
        manifest_files = {}
        for relpath, meta in source_index.items():
            manifest_files[relpath] = {
                "sha256": meta["sha256"],
                "size": meta["size"],
                "location": "full",
            }
        return {
            "mode": "full",
            "to_copy": to_copy,
            "manifest_files": manifest_files,
        }

    # 取得前次 manifest 的檔案對照表
    prev_files = previous_manifest.get("files", {}) if isinstance(previous_manifest, dict) else {}

    to_copy = {}
    manifest_files = {}

    for relpath, meta in source_index.items():
        prev_meta = prev_files.get(relpath)
        sha = meta["sha256"]
        sz = meta["size"]

        if prev_meta is None or prev_meta.get("sha256") != sha:
            to_copy[relpath] = meta
            manifest_files[relpath] = {
                "sha256": sha,
                "size": sz,
                "location": None,  # 由執行期填入 incr/$STAMP
            }
        else:
            # 未變更：沿用前次 location
            manifest_files[relpath] = {
                "sha256": sha,
                "size": sz,
                "location": prev_meta.get("location", "full"),
            }

    return {
        "mode": "incremental",
        "to_copy": to_copy,
        "manifest_files": manifest_files,
    }


def _write_status_json(status_file: Path, data: Dict[str, Any]) -> None:
    """原子化寫入狀態 JSON 檔。"""
    status_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(status_file))


def run_backup(
    data_dir: Optional[Union[str, Path]] = None,
    backup_root: Optional[Union[str, Path]] = None,
    stamp: Optional[str] = None,
    status_file: Optional[Union[str, Path]] = None,
    allow_same_fs: Optional[bool] = None,
) -> int:
    """執行完整或增量備份任務。回傳 0 表示成功，非 0 表示失敗。"""
    data_path = Path(data_dir or os.environ.get("ELC_DATA_DIR", "data")).resolve()
    raw_root = backup_root or os.environ.get("ELC_BACKUP_ROOT", "")
    if not raw_root:
        logger.error("ELC_BACKUP_ROOT is not set")
        return 1
    backup_root_path = Path(raw_root).resolve()

    stamp_str = stamp or os.environ.get("ELC_BACKUP_STAMP") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    status_path = Path(status_file or os.environ.get("ELC_BACKUP_STATUS_FILE", "logs/backup-status.json")).resolve()

    if allow_same_fs is None:
        allow_same_fs = os.environ.get("ELC_BACKUP_ALLOW_SAME_FS") == "1"

    # 1. 檢查目的端路徑
    if not backup_root_path.exists():
        err_msg = f"備份目的端目錄不存在: {backup_root_path}"
        logger.error(err_msg)
        _write_status_json(status_path, {
            "last_backup_at": stamp_str,
            "snapshot": stamp_str,
            "mode": "unknown",
            "free_bytes": 0,
            "verified_files": 0,
            "error": err_msg,
        })
        return 1

    if not os.access(str(backup_root_path), os.W_OK):
        err_msg = f"備份目的端目錄不可寫: {backup_root_path}"
        logger.error(err_msg)
        _write_status_json(status_path, {
            "last_backup_at": stamp_str,
            "snapshot": stamp_str,
            "mode": "unknown",
            "free_bytes": 0,
            "verified_files": 0,
            "error": err_msg,
        })
        return 1

    # 2. 檢查是否與資料目錄為同一檔案系統 (防寫入主機系統碟)
    if not allow_same_fs and data_path.exists():
        try:
            if os.stat(str(data_path)).st_dev == os.stat(str(backup_root_path)).st_dev:
                err_msg = "備份目的端不得與資料目錄位於同一裝置（請掛載外接磁碟）"
                logger.error(err_msg)
                _write_status_json(status_path, {
                    "last_backup_at": stamp_str,
                    "snapshot": stamp_str,
                    "mode": "unknown",
                    "free_bytes": 0,
                    "verified_files": 0,
                    "error": err_msg,
                })
                return 1
        except OSError as exc:
            logger.warning("st_dev check encountered OSError: %s", exc)

    free_bytes = shutil.disk_usage(str(backup_root_path)).free

    # 3. 準備備份目錄與 manifests
    elc_backup_dir = backup_root_path / "elc-backup"
    manifests_dir = elc_backup_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    previous_manifest: Optional[Dict[str, Any]] = None
    existing_manifests = sorted(manifests_dir.glob("*.json"))
    if existing_manifests:
        latest_manifest_path = existing_manifests[-1]
        try:
            previous_manifest = json.loads(latest_manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse previous manifest %s: %s", latest_manifest_path, exc)

    # 4. 建立來源檔案索引與 SQLite 一致性快照
    source_index: Dict[str, Dict[str, Any]] = {}
    sqlite_snapshots: Dict[str, Path] = {}

    if data_path.exists():
        for root_str, _, files in os.walk(str(data_path)):
            root_p = Path(root_str)
            for fname in files:
                # 排除暫存日誌與鎖定檔案
                if fname.endswith(("-wal", "-shm", "-journal", ".tmp")):
                    continue
                file_p = root_p / fname
                try:
                    rel_parts = file_p.relative_to(data_path).parts
                    relpath = "/".join(rel_parts)
                except ValueError:
                    continue

                if fname.endswith((".sqlite3", ".db")):
                    # 使用 SQLite backup API 寫入暫存快照
                    snap_dir = Path(tempfile.gettempdir()) / "elc_backup_snaps"
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    snap_p = snap_dir / f"snap_{stamp_str}_{fname}"
                    try:
                        with sqlite3.connect(str(file_p)) as src_conn, sqlite3.connect(str(snap_p)) as dst_conn:
                            src_conn.backup(dst_conn)
                        sha = sha256_file(snap_p)
                        sz = snap_p.stat().st_size
                        source_index[relpath] = {"sha256": sha, "size": sz, "source_path": snap_p}
                        sqlite_snapshots[relpath] = snap_p
                    except Exception as exc:
                        logger.error("SQLite backup failed for %s: %s", file_p, exc)
                        _write_status_json(status_path, {
                            "last_backup_at": stamp_str,
                            "snapshot": stamp_str,
                            "mode": "unknown",
                            "free_bytes": free_bytes,
                            "verified_files": 0,
                            "error": f"資料庫快照失敗: {fname} ({exc})",
                        })
                        return 1
                else:
                    sha = sha256_file(file_p)
                    sz = file_p.stat().st_size
                    source_index[relpath] = {"sha256": sha, "size": sz, "source_path": file_p}

    # 5. 計算增量計畫
    plan = plan_incremental(source_index, previous_manifest)
    mode = plan["mode"]
    to_copy = plan["to_copy"]
    manifest_files = plan["manifest_files"]

    # 6. 設定目標路徑（full.partial / incr/$STAMP.partial）
    if mode == "full":
        target_partial = elc_backup_dir / "full.partial"
        target_final = elc_backup_dir / "full"
        loc_prefix = "full"
    else:
        target_partial = elc_backup_dir / "incr" / f"{stamp_str}.partial"
        target_final = elc_backup_dir / "incr" / stamp_str
        loc_prefix = f"incr/{stamp_str}"

    if target_final.exists():
        err_msg = f"備份目標已存在，拒絕覆寫: {target_final}"
        logger.error(err_msg)
        _write_status_json(status_path, {
            "last_backup_at": stamp_str,
            "snapshot": stamp_str,
            "mode": mode,
            "free_bytes": free_bytes,
            "verified_files": 0,
            "error": err_msg,
        })
        return 1

    target_partial.mkdir(parents=True, exist_ok=True)

    # 7. 複製檔案並即時校驗雜湊
    verified_files = 0
    for relpath, meta in to_copy.items():
        src_file = meta["source_path"]
        expected_sha = meta["sha256"]

        safe_relpath = _sanitize_for_exfat(relpath)
        dst_file = target_partial / safe_relpath
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        shutil.copyfile(str(src_file), str(dst_file))
        actual_sha = sha256_file(dst_file)

        if actual_sha != expected_sha:
            err_msg = f"備份檔驗證失敗: {relpath} 雜湊不符 (期望 {expected_sha}, 實際 {actual_sha})"
            logger.error(err_msg)
            _write_status_json(status_path, {
                "last_backup_at": stamp_str,
                "snapshot": stamp_str,
                "mode": mode,
                "free_bytes": free_bytes,
                "verified_files": verified_files,
                "error": err_msg,
            })
            return 1

        verified_files += 1
        if manifest_files[relpath]["location"] is None:
            manifest_files[relpath]["location"] = f"{loc_prefix}/{safe_relpath}"

    # 8. 完成複製：將 .partial 重新命名為正式名稱
    os.rename(str(target_partial), str(target_final))

    # 9. 寫出本次 manifest JSON
    manifest_data = {
        "stamp": stamp_str,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verified_files": verified_files,
        "files": manifest_files,
    }
    manifest_tmp = manifests_dir / f"{stamp_str}.json.tmp"
    manifest_final = manifests_dir / f"{stamp_str}.json"
    manifest_tmp.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(manifest_tmp), str(manifest_final))

    # 10. 寫出 backup-status.json
    end_free_bytes = shutil.disk_usage(str(backup_root_path)).free
    status_data = {
        "last_backup_at": stamp_str,
        "snapshot": stamp_str,
        "mode": mode,
        "free_bytes": end_free_bytes,
        "verified_files": verified_files,
        "status": "success",
    }
    _write_status_json(status_path, status_data)
    logger.info("Backup %s (%s) completed successfully. Verified %d files.", stamp_str, mode, verified_files)
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    code = run_backup()
    sys.exit(code)


if __name__ == "__main__":
    main()
