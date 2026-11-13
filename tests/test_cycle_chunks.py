"""Tests for server chunk upload and finalize (Phase 31 Plan 31-09)."""

import io
import threading
import time
import pytest
import wave

from elc_audit_engine.cycles.chunks import (
    AudioHashMismatchError,
    ChunkConflictError,
    ChunkFormatError,
    ChunkHashMismatchError,
    ChunkStateError,
    MissingChunksError,
    cycle_artifacts,
    finalize_cycle_audio,
    store_chunk,
)
from elc_audit_engine.cycles.store import create_cycle, cycle_dir, transition_cycle
from tests.phase31_support import make_wav_chunk, pcm_sha256, wav_sha256
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401


# ======================================================================
# Task 1: Core store_chunk & finalize_cycle_audio Tests
# ======================================================================


def _create_test_cycle(store, cycle_id: str = "c0000000000000000000000000000001", state: str = "RECORDING"):
    cycle, _ = create_cycle(store, command_id="cmd111111111111111111111111111111", machine_id="m1")
    if state != "RECORDING":
        transition_cycle(store, cycle["cycle_id"], state, actor="test")
    return cycle["cycle_id"]


def test_store_chunk_new_segment(tmp_path, phase31_app):
    """Test 1: store_chunk 新段 → 檔案存在、回傳 duplicate=False、sha256 等於 wav_sha256。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data = make_wav_chunk(seconds=0.5, seed=1)
    sha = wav_sha256(data)

    res = store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha, data=data, actor="tester")
    assert res["cycle_id"] == cid
    assert res["seq"] == 0
    assert res["sha256"] == sha
    assert res["duplicate"] is False

    chunk_file = cycle_dir(cid) / "chunk_000000.wav"
    assert chunk_file.is_file()
    assert chunk_file.read_bytes() == data


def test_store_chunk_duplicate_idempotent(tmp_path, phase31_app):
    """Test 2: 同 seq 同內容 → duplicate=True，檔案修改時間不變。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data = make_wav_chunk(seconds=0.5, seed=2)
    sha = wav_sha256(data)

    res1 = store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha, data=data)
    assert res1["duplicate"] is False

    chunk_file = cycle_dir(cid) / "chunk_000000.wav"
    mtime_before = chunk_file.stat().st_mtime_ns

    time.sleep(0.01)
    res2 = store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha, data=data)
    assert res2["duplicate"] is True
    assert chunk_file.stat().st_mtime_ns == mtime_before


def test_store_chunk_conflict_different_hash(tmp_path, phase31_app):
    """Test 3: 同 seq 不同內容 → 拋 ChunkConflictError，原檔內容不變。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data1 = make_wav_chunk(seconds=0.5, seed=3)
    sha1 = wav_sha256(data1)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha1, data=data1)

    data2 = make_wav_chunk(seconds=0.5, seed=4)
    sha2 = wav_sha256(data2)

    with pytest.raises(ChunkConflictError):
        store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha2, data=data2)

    chunk_file = cycle_dir(cid) / "chunk_000000.wav"
    assert chunk_file.read_bytes() == data1


def test_store_chunk_declared_hash_mismatch(tmp_path, phase31_app):
    """Test 4: 宣告 sha256 與內容不符 → 拋 ChunkHashMismatchError，不留下任何檔案。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data = make_wav_chunk(seconds=0.5, seed=5)
    bad_sha = "0000" * 16

    with pytest.raises(ChunkHashMismatchError):
        store_chunk(store, cycle_id=cid, seq=0, declared_sha256=bad_sha, data=data)

    c_dir = cycle_dir(cid)
    if c_dir.exists():
        assert len(list(c_dir.glob("*.wav"))) == 0
        assert len(list(c_dir.glob("*.tmp*"))) == 0


def test_store_chunk_invalid_format(tmp_path, phase31_app):
    """Test 5: 非 WAV 或非 16 kHz mono 16-bit → 拋 ChunkFormatError。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    # 1. 隨意二進位資料
    bad_data = b"not_a_wav_file_at_all"
    with pytest.raises(ChunkFormatError):
        store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(bad_data), data=bad_data)

    # 2. 立體聲 (2 channels) WAV
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00\x00\x00" * 100)
    stereo_data = buf.getvalue()
    with pytest.raises(ChunkFormatError):
        store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(stereo_data), data=stereo_data)


def test_store_chunk_invalid_cycle_state(tmp_path, phase31_app):
    """Test 6: 循環狀態為 AWAITING_CONFIRM 時 store_chunk → ChunkStateError。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    # 轉移至 AWAITING_DRAFT -> AWAITING_CONFIRM
    transition_cycle(store, cid, "AWAITING_DRAFT", actor="test")
    transition_cycle(store, cid, "AWAITING_CONFIRM", actor="test")

    data = make_wav_chunk(seconds=0.5, seed=6)
    with pytest.raises(ChunkStateError):
        store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(data), data=data)


def test_finalize_cycle_audio_lifecycle(tmp_path, phase31_app):
    """Test 7: finalize_cycle_audio 缺段、雜湊錯、成功串接與冪等性。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    # 準備 3 段音訊 (seq 0, 1, 2)
    chunk0 = make_wav_chunk(seconds=0.3, seed=10)
    chunk1 = make_wav_chunk(seconds=0.3, seed=11)
    chunk2 = make_wav_chunk(seconds=0.3, seed=12)

    # 先只上傳 seq 0 與 seq 2 (缺 seq 1)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(chunk0), data=chunk0)
    store_chunk(store, cycle_id=cid, seq=2, declared_sha256=wav_sha256(chunk2), data=chunk2)

    correct_audio_sha = pcm_sha256([chunk0, chunk1, chunk2])

    # 1. 缺 seq 1
    with pytest.raises(MissingChunksError) as exc_info:
        finalize_cycle_audio(store, cycle_id=cid, total_chunks=3, audio_sha256=correct_audio_sha)
    assert exc_info.value.missing == [1]

    # 補上 seq 1
    store_chunk(store, cycle_id=cid, seq=1, declared_sha256=wav_sha256(chunk1), data=chunk1)

    # 2. 全到齊但 audio_sha256 不符
    with pytest.raises(AudioHashMismatchError):
        finalize_cycle_audio(store, cycle_id=cid, total_chunks=3, audio_sha256="ff" * 32)

    # 3. 正確 finalize
    fin_res = finalize_cycle_audio(store, cycle_id=cid, total_chunks=3, audio_sha256=correct_audio_sha)
    assert fin_res["upload_complete"] is True
    assert fin_res["total_chunks"] == 3
    assert fin_res["audio_sha256"] == correct_audio_sha

    # 驗證 full.wav 存在且 frames 數為總和
    full_path = cycle_dir(cid) / "full.wav"
    assert full_path.is_file()
    with wave.open(str(full_path), "rb") as wf:
        total_frames = wf.getnframes()
        expected_frames = 16000 * 0.3 * 3
        assert abs(total_frames - expected_frames) < 10

    # 4. 重送相同參數冪等成功
    fin_res_repeat = finalize_cycle_audio(store, cycle_id=cid, total_chunks=3, audio_sha256=correct_audio_sha)
    assert fin_res_repeat["upload_complete"] is True


def test_cycle_artifacts(tmp_path, phase31_app):
    """Test 8: cycle_artifacts 回傳 audio_path, chunk_paths, transcript_path。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data = make_wav_chunk(seconds=0.2, seed=20)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(data), data=data)
    finalize_cycle_audio(store, cycle_id=cid, total_chunks=1, audio_sha256=pcm_sha256([data]))

    arts = cycle_artifacts(store, cid)
    assert arts["audio_path"] == str(cycle_dir(cid) / "full.wav")
    assert len(arts["chunk_paths"]) == 1
    assert arts["chunk_paths"][0] == str(cycle_dir(cid) / "chunk_000000.wav")
    assert arts["transcript_path"] is None


def test_store_chunk_concurrency(tmp_path, phase31_app):
    """Test 9: 兩個執行緒同時以相同 (cycle_id, seq) 呼叫 store_chunk → 恰一個 duplicate=False。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)

    data = make_wav_chunk(seconds=0.2, seed=30)
    sha = wav_sha256(data)

    results: list[dict] = []
    errors: list[Exception] = []

    def worker():
        try:
            r = store_chunk(store, cycle_id=cid, seq=0, declared_sha256=sha, data=data)
            results.append(r)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    assert len(results) == 2
    duplicates = [r["duplicate"] for r in results]
    assert duplicates.count(False) == 1
    assert duplicates.count(True) == 1


# ======================================================================
# Task 2: HTTP API Routes Tests
# ======================================================================


def test_api_chunks_lifecycle_and_validation(phase31_client, phase31_app):
    """Test api_1: POST chunks 新段 201、重送 200 duplicate、衝突 409、雜湊不符 422、過大 413、seq 不合法 422。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)
    headers = {"X-API-Key": "valid-key-123"}

    data = make_wav_chunk(seconds=0.2, seed=40)
    sha = wav_sha256(data)

    # 1. 新段 → 201
    resp1 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "0", "sha256": sha, "audio": (io.BytesIO(data), "chunk_000000.wav")},
        content_type="multipart/form-data",
    )
    assert resp1.status_code == 201
    body1 = resp1.get_json()
    assert body1["duplicate"] is False
    assert body1["sha256"] == sha

    # 2. 重送 → 200 duplicate: true
    resp2 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "0", "sha256": sha, "audio": (io.BytesIO(data), "chunk_000000.wav")},
        content_type="multipart/form-data",
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["duplicate"] is True

    # 3. 同 seq 不同內容 → 409
    data_diff = make_wav_chunk(seconds=0.2, seed=41)
    sha_diff = wav_sha256(data_diff)
    resp3 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "0", "sha256": sha_diff, "audio": (io.BytesIO(data_diff), "chunk_000000.wav")},
        content_type="multipart/form-data",
    )
    assert resp3.status_code == 409

    # 4. 雜湊不符 → 422
    resp4 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "1", "sha256": "00" * 32, "audio": (io.BytesIO(data), "chunk_000001.wav")},
        content_type="multipart/form-data",
    )
    assert resp4.status_code == 422

    # 5. seq 非整數或為負數 → 422
    resp5a = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "-1", "sha256": sha, "audio": (io.BytesIO(data), "chunk.wav")},
        content_type="multipart/form-data",
    )
    assert resp5a.status_code == 422

    resp5b = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "abc", "sha256": sha, "audio": (io.BytesIO(data), "chunk.wav")},
        content_type="multipart/form-data",
    )
    assert resp5b.status_code == 422


def test_api_chunks_auth_and_no_private_ip_exemption(phase31_client, phase31_app):
    """Test api_2: 無 key → 401；Agent 金鑰 → 403；私有 IP 無 key → 401。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)
    data = make_wav_chunk(seconds=0.1, seed=50)
    sha = wav_sha256(data)

    def mk_payload():
        return {"seq": "0", "sha256": sha, "audio": (io.BytesIO(data), "chunk_000000.wav")}

    # 1. 無 key → 401
    r1 = phase31_client.post(f"/api/cycles/{cid}/chunks", data=mk_payload(), content_type="multipart/form-data")
    assert r1.status_code == 401

    # 2. Agent 金鑰 → 403
    r2 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers={"X-API-Key": "agent-key-1"},
        data=mk_payload(),
        content_type="multipart/form-data",
    )
    assert r2.status_code == 403

    # 3. 私有 IP 且無 key → 401 (不套用 /api/soap/recordings 的私有 IP 免 key 例外)
    r3 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        environ_base={"REMOTE_ADDR": "192.168.1.20"},
        data=mk_payload(),
        content_type="multipart/form-data",
    )
    assert r3.status_code == 401


def test_api_finalize(phase31_client, phase31_app):
    """Test api_3: POST finalize 缺段 → 409 含 missing；成功 → 200 upload_complete:true。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)
    headers = {"X-API-Key": "valid-key-123"}

    c0 = make_wav_chunk(seconds=0.2, seed=60)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(c0), data=c0)

    # 要求 2 段但只上傳了 seq 0
    full_sha = pcm_sha256([c0])
    r_missing = phase31_client.post(
        f"/api/cycles/{cid}/finalize",
        headers=headers,
        json={"total_chunks": 2, "audio_sha256": full_sha},
    )
    assert r_missing.status_code == 409
    body = r_missing.get_json()
    assert body["error"] == "missing_chunks"
    assert body["missing"] == [1]

    # 正確 finalize (total_chunks=1)
    r_ok = phase31_client.post(
        f"/api/cycles/{cid}/finalize",
        headers=headers,
        json={"total_chunks": 1, "audio_sha256": full_sha},
    )
    assert r_ok.status_code == 200
    assert r_ok.get_json()["upload_complete"] is True


def test_api_not_found_cycle(phase31_client, phase31_app):
    """Test api_4: 不存在或格式錯誤的 cycle_id → 404。"""
    headers = {"X-API-Key": "valid-key-123"}

    # 格式錯誤
    r1 = phase31_client.post("/api/cycles/invalid_id/chunks", headers=headers)
    assert r1.status_code == 404

    # 不存在
    r2 = phase31_client.post("/api/cycles/0123456789abcdef0123456789abcdef/finalize", headers=headers, json={"total_chunks": 1, "audio_sha256": "00"*32})
    assert r2.status_code == 404


def test_api_caplog_no_audio_or_phi(phase31_client, phase31_app, caplog):
    """Test api_5: 回應與日誌不含音訊位元組或病人欄位。"""
    store = phase31_app.case_store
    cid = _create_test_cycle(store)
    headers = {"X-API-Key": "valid-key-123"}

    data = make_wav_chunk(seconds=0.1, seed=70)
    sha = wav_sha256(data)

    resp = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        headers=headers,
        data={"seq": "0", "sha256": sha, "audio": (io.BytesIO(data), "chunk_000000.wav")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201

    resp_text = resp.get_data(as_text=True)
    assert "RIFF" not in resp_text
    assert "WAVE" not in resp_text

    for record in caplog.records:
        msg = record.getMessage()
        assert "RIFF" not in msg
        assert "WAVE" not in msg
