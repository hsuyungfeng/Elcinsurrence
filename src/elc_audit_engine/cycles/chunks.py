"""Phase 31: 循環音訊分段儲存、雜湊驗證與 finalize 串接 (D-31-19 ~ D-31-23, D-31-27 ~ D-31-30).

核心規範：
- 分段以 (cycle_id, seq) 去重：相同雜湊重送 duplicate=true，不同雜湊抛 ChunkConflictError
- 重算 sha256，不符抛 ChunkHashMismatchError
- 單段上限 4 MiB，格式限定 16 kHz mono 16-bit PCM WAV
- finalize 檢查 0..total-1 齊全並比對 PCM 串接 sha256，產生 full.wav 並設定 upload_complete
- 永不刪除任何正式分段檔（D-31-29），僅清理自己產生的 .tmp 暫存檔
"""

from __future__ import annotations

import datetime
import hashlib
import io
import logging
import os
from pathlib import Path
import uuid
import wave
from typing import Any, Dict, Optional, Sequence

from elc_audit_engine.cycles.store import cycle_dir

logger = logging.getLogger(__name__)

MAX_CHUNK_SIZE_BYTES = 4 * 1024 * 1024  # 4 MiB


class ChunkConflictError(Exception):
    """同 seq 但雜湊不同之衝突。"""


class ChunkHashMismatchError(Exception):
    """宣告之雜湊與實際檔案重算雜湊不符。"""


class ChunkFormatError(Exception):
    """音訊格式不符（非 16 kHz mono 16-bit PCM WAV）。"""


class ChunkStateError(Exception):
    """循環狀態不允許上傳分段或 finalize。"""


class MissingChunksError(Exception):
    """finalize 時缺少分段。"""

    def __init__(self, missing: Sequence[int]):
        super().__init__(f"缺少分段：{list(missing)}")
        self.missing = list(missing)


class AudioHashMismatchError(Exception):
    """PCM 串接雜湊與宣告之 audio_sha256 不符。"""


class ChunkSizeExceededError(Exception):
    """分段檔案大小超過上限 (4 MiB)。"""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def validate_wav_chunk(data: bytes) -> None:
    """驗證資料為 16 kHz, 1 channel, 16-bit (2 bytes) PCM WAV。"""
    if len(data) > MAX_CHUNK_SIZE_BYTES:
        raise ChunkSizeExceededError(f"分段大小 {len(data)} 超過上限 4 MiB")

    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            comptype = wf.getcomptype()
            if nchannels != 1 or sampwidth != 2 or framerate != 16000 or comptype != "NONE":
                raise ChunkFormatError(
                    f"不支援的 WAV 格式 (channels={nchannels}, width={sampwidth}, rate={framerate}, comp={comptype})"
                )
    except wave.Error as exc:
        raise ChunkFormatError(f"無效的 WAV 檔案：{exc}") from exc


def store_chunk(
    store,
    *,
    cycle_id: str,
    seq: int,
    declared_sha256: str,
    data: bytes,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """儲存單一分段音訊並在資料庫內記錄（交易內去重防競爭）。

    回傳：{"cycle_id": str, "seq": int, "sha256": str, "duplicate": bool}
    """
    if seq < 0:
        raise ValueError("seq 必須大於或等於 0")

    # 1. 格式與大小驗證
    validate_wav_chunk(data)

    # 2. 雜湊比對
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha.lower() != declared_sha256.lower():
        raise ChunkHashMismatchError(
            f"分段雜湊不符：宣告={declared_sha256}, 實際={actual_sha}"
        )

    # 3. 先寫入暫存檔
    c_dir = cycle_dir(cycle_id)
    c_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = c_dir / f"chunk_{seq:06d}.wav.tmp.{uuid.uuid4().hex[:8]}"

    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        conn = store._connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()

                # 4. 驗證循環存在與狀態
                cur.execute("SELECT state FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
                c_row = cur.fetchone()
                if not c_row:
                    raise LookupError(f"Cycle not found: {cycle_id}")

                cycle_state = c_row["state"]
                if cycle_state not in ("RECORDING", "AWAITING_DRAFT"):
                    raise ChunkStateError(
                        f"循環狀態為 {cycle_state}，無法接收分段上傳"
                    )

                # 5. 去重檢查
                cur.execute(
                    "SELECT sha256, path FROM cycle_chunks WHERE cycle_id = ? AND seq = ?",
                    (cycle_id, seq),
                )
                existing = cur.fetchone()
                if existing:
                    existing_sha = existing["sha256"]
                    # 暫存檔無用直接清除
                    tmp_path.unlink(missing_ok=True)
                    if existing_sha.lower() == actual_sha.lower():
                        return {
                            "cycle_id": cycle_id,
                            "seq": seq,
                            "sha256": existing_sha,
                            "duplicate": True,
                        }
                    else:
                        raise ChunkConflictError(
                            f"分段 (cycle_id={cycle_id}, seq={seq}) 已存在但雜湊不同"
                        )

                # 6. 新分段：原子移動暫存檔為正式檔並寫入 DB
                target_path = c_dir / f"chunk_{seq:06d}.wav"
                os.replace(tmp_path, target_path)

                now = _now_iso()
                cur.execute(
                    """
                    INSERT INTO cycle_chunks (
                        cycle_id, seq, sha256, size_bytes, path, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cycle_id, seq, actual_sha, len(data), str(target_path), now),
                )
                cur.execute("UPDATE recording_cycles SET updated_at = ? WHERE cycle_id = ?", (now, cycle_id))

                return {
                    "cycle_id": cycle_id,
                    "seq": seq,
                    "sha256": actual_sha,
                    "duplicate": False,
                }
        finally:
            conn.close()
    finally:
        # 確保任何例外情況下 .tmp 檔被清理
        if tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def finalize_cycle_audio(
    store,
    *,
    cycle_id: str,
    total_chunks: int,
    audio_sha256: str,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """確認分段齊全、驗證 PCM 串接雜湊、產出 full.wav 並設定 upload_complete。

    回傳：{"cycle_id": str, "total_chunks": int, "audio_sha256": str, "upload_complete": True}
    """
    if total_chunks <= 0:
        raise ValueError("total_chunks 必須大於 0")

    conn = store._connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()

            cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
            c_row = cur.fetchone()
            if not c_row:
                raise LookupError(f"Cycle not found: {cycle_id}")

            # 冪等檢查
            if bool(c_row["upload_complete"]):
                if (
                    c_row["total_chunks"] == total_chunks
                    and (c_row["audio_sha256"] or "").lower() == audio_sha256.lower()
                ):
                    return {
                        "cycle_id": cycle_id,
                        "total_chunks": total_chunks,
                        "audio_sha256": audio_sha256,
                        "upload_complete": True,
                    }

            cycle_state = c_row["state"]
            if cycle_state not in ("RECORDING", "AWAITING_DRAFT"):
                raise ChunkStateError(
                    f"循環狀態為 {cycle_state}，無法執行 finalize"
                )

            # 查詢所有已接收分段
            cur.execute(
                "SELECT seq, sha256, path FROM cycle_chunks WHERE cycle_id = ? ORDER BY seq ASC",
                (cycle_id,),
            )
            rows = cur.fetchall()
            received_seqs = {r["seq"] for r in rows}
            expected_seqs = set(range(total_chunks))
            missing = sorted(list(expected_seqs - received_seqs))
            if missing:
                raise MissingChunksError(missing=missing)

            # 讀取每段 PCM frames 串接
            seq_to_row = {r["seq"]: r for r in rows}
            raw_pcm = bytearray()
            for s in range(total_chunks):
                chunk_file = Path(seq_to_row[s]["path"])
                with wave.open(str(chunk_file), "rb") as wf:
                    raw_pcm.extend(wf.readframes(wf.getnframes()))

            computed_sha = hashlib.sha256(raw_pcm).hexdigest()
            if computed_sha.lower() != audio_sha256.lower():
                raise AudioHashMismatchError(
                    f"PCM 串接雜湊不符：計算值={computed_sha}, 宣告值={audio_sha256}"
                )

            # 寫入 full.wav (tmp + replace)
            c_dir = cycle_dir(cycle_id)
            c_dir.mkdir(parents=True, exist_ok=True)
            full_tmp = c_dir / f"full.wav.tmp.{uuid.uuid4().hex[:8]}"
            full_target = c_dir / "full.wav"

            try:
                with wave.open(str(full_tmp), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(raw_pcm)

                with open(full_tmp, "rb") as f:
                    os.fsync(f.fileno())

                os.replace(full_tmp, full_target)
            finally:
                if full_tmp.exists():
                    try:
                        full_tmp.unlink(missing_ok=True)
                    except OSError:
                        pass

            now = _now_iso()
            cur.execute(
                """
                UPDATE recording_cycles
                SET total_chunks = ?,
                    audio_sha256 = ?,
                    upload_complete = 1,
                    audio_path = ?,
                    updated_at = ?
                WHERE cycle_id = ?
                """,
                (total_chunks, audio_sha256, str(full_target), now, cycle_id),
            )

            return {
                "cycle_id": cycle_id,
                "total_chunks": total_chunks,
                "audio_sha256": audio_sha256,
                "upload_complete": True,
            }
    finally:
        conn.close()


def cycle_artifacts(store, cycle_id: str) -> Dict[str, Any]:
    """查詢循環之成果檔案路徑。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT audio_path, transcript_path FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
        c_row = cur.fetchone()
        if not c_row:
            raise LookupError(f"Cycle not found: {cycle_id}")

        cur.execute("SELECT path FROM cycle_chunks WHERE cycle_id = ? ORDER BY seq ASC", (cycle_id,))
        chunk_rows = cur.fetchall()
        chunk_paths = [r["path"] for r in chunk_rows]

        return {
            "audio_path": c_row["audio_path"],
            "chunk_paths": chunk_paths,
            "transcript_path": c_row["transcript_path"],
        }
    finally:
        conn.close()
