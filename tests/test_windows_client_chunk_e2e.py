"""Phase 39: Windows Client 分段錄音與 VAD 自動錄音端到端整合測試.

涵蓋：
- T2.1: 正常 5 分段串接，每段帶獨立 RIFF WAV 標頭，驗證 full.wav 與 frame 數
- T2.1-ASR: 選用 sherpa-onnx 轉錄驗證（skipif 保護）
- T2.2: 弱網重送（等冪 duplicate=True）與亂序到達串接
- T2.3: 前綴音訊（pre-roll 3 秒）串接與 trigger_mode 標記
- T2.4: 邊界拒絕：seq >= total_chunks 或超過上限拒絕
- T2.5: 截斷或不完整 WAV 分段拒絕 (ChunkFormatError 422)
- T2.6: 循環上限控制（MAX_CHUNKS_PER_CYCLE 與 MAX_CYCLE_PCM_BYTES）
- T2.8: 心跳 (heartbeat) vad_listening 嚴格型別檢查
- T2.9: 循環建立 trigger_mode 與 preroll_sec 驗證
"""

from __future__ import annotations

import io
from pathlib import Path
import uuid
import wave

import pytest

from elc_audit_engine.cycles.chunks import cycle_artifacts
from elc_audit_engine.cycles.store import cycle_dir, get_cycle
from tests.phase31_support import make_wav_chunk, pcm_sha256, wav_sha256

pytest_plugins = ("tests.phase31_support",)

_AUTH_HEADER = {"X-API-Key": "valid-key-123"}


def _new_command_id() -> str:
    return uuid.uuid4().hex


def _new_machine_id() -> str:
    return f"win-{uuid.uuid4().hex[:8]}"


def _create_cycle_via_api(
    client,
    machine_id: str | None = None,
    command_id: str | None = None,
    trigger_mode: str = "manual",
    preroll_sec: float = 0.0,
) -> str:
    if machine_id is None:
        machine_id = _new_machine_id()
    if command_id is None:
        command_id = _new_command_id()
    payload = {
        "machine_id": machine_id,
        "command_id": command_id,
        "trigger_mode": trigger_mode,
        "preroll_sec": preroll_sec,
    }
    resp = client.post("/api/cycles", json=payload, headers=_AUTH_HEADER)
    assert resp.status_code == 201, f"Failed to create cycle: {resp.get_json()}"
    return resp.get_json()["cycle"]["cycle_id"]


def _upload_chunk_api(client, cycle_id: str, seq: int, wav_data: bytes):
    sha = wav_sha256(wav_data)
    data = {
        "seq": str(seq),
        "sha256": sha,
        "audio": (io.BytesIO(wav_data), f"chunk_{seq:06d}.wav", "audio/wav"),
    }
    return client.post(
        f"/api/cycles/{cycle_id}/chunks",
        data=data,
        content_type="multipart/form-data",
        headers=_AUTH_HEADER,
    )


def _finalize_api(client, cycle_id: str, total_chunks: int, audio_sha256: str, auto_generate: bool = False):
    payload = {
        "total_chunks": total_chunks,
        "audio_sha256": audio_sha256,
        "auto_generate": auto_generate,
    }
    return client.post(
        f"/api/cycles/{cycle_id}/finalize",
        json=payload,
        headers=_AUTH_HEADER,
    )


# ======================================================================
# T2.1: 正常分段串接 (5 段帶獨立 RIFF 標頭)
# ======================================================================


def test_e2e_normal_chunk_concatenation(phase31_app, phase31_client):
    """T2.1: 切為 5 段，每段帶獨立 RIFF 標頭，依序上傳後 finalize，驗證產出 full.wav 且 frame 數符合。"""
    store = phase31_app.case_store
    cid = _create_cycle_via_api(phase31_client)

    # 模擬 Client 端錄製 5 段音訊（各 0.6 秒，不同頻率）
    chunks = [make_wav_chunk(seconds=0.6, seed=i) for i in range(5)]
    for i, c in enumerate(chunks):
        assert len(c) % 2 == 0, f"Chunk {i} byte count must be even"

    chunk_frames = []
    for c in chunks:
        with wave.open(io.BytesIO(c), "rb") as wf:
            chunk_frames.append(wf.getnframes())

    # 上傳 0..4
    for i, c in enumerate(chunks):
        resp = _upload_chunk_api(phase31_client, cid, i, c)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["duplicate"] is False
        assert data["seq"] == i

    expected_full_sha = pcm_sha256(chunks)
    fin_resp = _finalize_api(phase31_client, cid, total_chunks=5, audio_sha256=expected_full_sha)
    assert fin_resp.status_code == 200
    fin_data = fin_resp.get_json()
    assert fin_data["upload_complete"] is True
    assert fin_data["audio_sha256"] == expected_full_sha

    # 檢查磁碟上的 full.wav
    artifacts = cycle_artifacts(store, cid)
    full_wav_path = Path(artifacts["audio_path"])
    assert full_wav_path.is_file()

    with wave.open(str(full_wav_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == sum(chunk_frames)


# ======================================================================
# T2.1-ASR: 選用 sherpa-onnx 轉錄驗證 (skipif 保護)
# ======================================================================


def _has_sherpa_model() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    model_dir = Path("/home/hsu/Desktop/Elcinsurrence/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
    return (model_dir / "model.int8.onnx").is_file() or (model_dir / "model.onnx").is_file()


@pytest.mark.skipif(not _has_sherpa_model(), reason="sherpa-onnx 或 SenseVoice 離線模型未就緒")
def test_e2e_optional_asr_transcription(phase31_app, phase31_client):
    """T2.1-ASR: 串接完成後觸發本機 sherpa-onnx 轉錄。"""
    cid = _create_cycle_via_api(phase31_client)
    chunks = [make_wav_chunk(seconds=1.0, seed=10 + i) for i in range(2)]

    for i, c in enumerate(chunks):
        _upload_chunk_api(phase31_client, cid, i, c)

    full_sha = pcm_sha256(chunks)
    resp = _finalize_api(phase31_client, cid, total_chunks=2, audio_sha256=full_sha, auto_generate=True)
    assert resp.status_code == 200
    assert resp.get_json()["pipeline_scheduled"] is True


# ======================================================================
# T2.2: 弱網重送與亂序抵達
# ======================================================================


def test_e2e_weak_network_retry_and_reordering(phase31_app, phase31_client):
    """T2.2: 第 2 段重送 (duplicate=True)，第 4 段先到、第 3 段後到，驗證正確依序串接。"""
    store = phase31_app.case_store
    cid = _create_cycle_via_api(phase31_client)
    chunks = [make_wav_chunk(seconds=0.5, seed=20 + i) for i in range(5)]
    chunk_frames = [int(0.5 * 16000)] * 5

    # 上傳 0, 1, 2
    for i in (0, 1, 2):
        r = _upload_chunk_api(phase31_client, cid, i, chunks[i])
        assert r.status_code == 201

    # 模擬第 2 段逾時 Client 重傳
    retry_r = _upload_chunk_api(phase31_client, cid, 2, chunks[2])
    assert retry_r.status_code == 200
    assert retry_r.get_json()["duplicate"] is True

    # 亂序抵達：第 4 段先送
    r4 = _upload_chunk_api(phase31_client, cid, 4, chunks[4])
    assert r4.status_code == 201

    # 嘗試在第 3 段缺段時 finalize，應拋 409 missing_chunks
    full_sha = pcm_sha256(chunks)
    premature_fin = _finalize_api(phase31_client, cid, total_chunks=5, audio_sha256=full_sha)
    assert premature_fin.status_code == 409
    assert premature_fin.get_json()["missing"] == [3]

    # 第 3 段補齊
    r3 = _upload_chunk_api(phase31_client, cid, 3, chunks[3])
    assert r3.status_code == 201

    # 正式 finalize
    fin = _finalize_api(phase31_client, cid, total_chunks=5, audio_sha256=full_sha)
    assert fin.status_code == 200

    artifacts = cycle_artifacts(store, cid)
    with wave.open(str(artifacts["audio_path"]), "rb") as wf:
        assert wf.getnframes() == sum(chunk_frames)


# ======================================================================
# T2.3: 前綴音訊（pre-roll 3 秒）串接
# ======================================================================


def test_e2e_preroll_prefix_concatenation(phase31_app, phase31_client):
    """T2.3: 模擬 Client 帶 3 秒 pre-roll 的 VAD 自動錄音循環。"""
    store = phase31_app.case_store
    cid = _create_cycle_via_api(
        phase31_client,
        trigger_mode="vad_auto",
        preroll_sec=3.0,
    )

    # 驗證循環視圖包含正確 trigger_mode 與 preroll_sec
    cview = get_cycle(store, cid)
    assert cview is not None
    assert cview["trigger_mode"] == "vad_auto"
    assert cview["preroll_sec"] == 3.0

    # chunk 0: pre-roll 3.0 秒；chunk 1..2: 正常各 1.0 秒
    preroll_chunk = make_wav_chunk(seconds=3.0, seed=30)
    active_chunk1 = make_wav_chunk(seconds=1.0, seed=31)
    active_chunk2 = make_wav_chunk(seconds=1.0, seed=32)
    chunks = [preroll_chunk, active_chunk1, active_chunk2]

    for i, c in enumerate(chunks):
        r = _upload_chunk_api(phase31_client, cid, i, c)
        assert r.status_code == 201

    full_sha = pcm_sha256(chunks)
    fin = _finalize_api(phase31_client, cid, total_chunks=3, audio_sha256=full_sha)
    assert fin.status_code == 200

    artifacts = cycle_artifacts(store, cid)
    with wave.open(str(artifacts["audio_path"]), "rb") as wf:
        expected_frames = int((3.0 + 1.0 + 1.0) * 16000)
        assert wf.getnframes() == expected_frames


# ======================================================================
# T2.4: 邊界拒絕 (seq 超出範圍)
# ======================================================================


def test_e2e_boundary_seq_out_of_range(phase31_app, phase31_client):
    """T2.4: 上傳超出 MAX_CHUNKS_PER_CYCLE 的 seq 遭拒絕 (413)。"""
    cid = _create_cycle_via_api(phase31_client)
    chunk_data = make_wav_chunk(seconds=0.5, seed=40)

    # seq 120 (預設 MAX_CHUNKS_PER_CYCLE=120)
    resp = _upload_chunk_api(phase31_client, cid, 120, chunk_data)
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "cycle_limit_exceeded"


# ======================================================================
# T2.5: 截斷或不完整 WAV 分段拒絕 (M4)
# ======================================================================


def test_e2e_truncated_chunk_rejection(phase31_app, phase31_client):
    """T2.5: 標頭宣告長度與實際位元組不符，或奇數位元組遭 ChunkFormatError 拒絕。"""
    cid = _create_cycle_via_api(phase31_client)
    valid_wav = make_wav_chunk(seconds=1.0, seed=50)

    # 1. 人為截斷 10 個位元組（標頭宣告的 data size 大於實際剩餘長度）
    truncated = valid_wav[:-10]
    sha_trunc = wav_sha256(truncated)
    data = {
        "seq": "0",
        "sha256": sha_trunc,
        "audio": (io.BytesIO(truncated), "chunk_000000.wav", "audio/wav"),
    }
    resp = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        data=data,
        content_type="multipart/form-data",
        headers=_AUTH_HEADER,
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "invalid_wav_format"

    # 2. 奇數位元組截斷（非 16-bit 對齊）
    odd_cut = valid_wav[:-1]
    sha_odd = wav_sha256(odd_cut)
    data_odd = {
        "seq": "0",
        "sha256": sha_odd,
        "audio": (io.BytesIO(odd_cut), "chunk_000000.wav", "audio/wav"),
    }
    resp2 = phase31_client.post(
        f"/api/cycles/{cid}/chunks",
        data=data_odd,
        content_type="multipart/form-data",
        headers=_AUTH_HEADER,
    )
    assert resp2.status_code == 422
    assert resp2.get_json()["error"] == "invalid_wav_format"


# ======================================================================
# T2.6: 循環上限控制 (M7)
# ======================================================================


def test_e2e_cycle_limits_exceeded(phase31_app, phase31_client, monkeypatch):
    """T2.6: 超過 MAX_CHUNKS_PER_CYCLE 或 MAX_CYCLE_PCM_BYTES 遭到拒絕且不產出 full.wav。"""
    from elc_audit_engine.cycles import chunks as chunks_mod

    cid = _create_cycle_via_api(phase31_client)
    chunk_data = make_wav_chunk(seconds=0.5, seed=60)
    _upload_chunk_api(phase31_client, cid, 0, chunk_data)

    # 模擬上限為 2
    monkeypatch.setattr(chunks_mod, "MAX_CHUNKS_PER_CYCLE", 2)
    fin_resp = _finalize_api(phase31_client, cid, total_chunks=5, audio_sha256="a" * 64)
    assert fin_resp.status_code == 413
    assert fin_resp.get_json()["error"] == "cycle_limit_exceeded"

    # 模擬位元組上限過小
    monkeypatch.setattr(chunks_mod, "MAX_CHUNKS_PER_CYCLE", 10)
    monkeypatch.setattr(chunks_mod, "MAX_CYCLE_PCM_BYTES", 100)
    fin_resp2 = _finalize_api(phase31_client, cid, total_chunks=1, audio_sha256="a" * 64)
    assert fin_resp2.status_code == 413
    assert fin_resp2.get_json()["error"] == "cycle_limit_exceeded"

    full_wav = cycle_dir(cid) / "full.wav"
    assert not full_wav.exists()


# ======================================================================
# T2.8: 心跳 (heartbeat) vad_listening 嚴格型別檢查 (H2)
# ======================================================================


def test_e2e_heartbeat_vad_listening_strict_type(phase31_app, phase31_client):
    """T2.8: vad_listening 必須為布林值，傳入 1 或 'true' 應回 422；chunks_pending 傳 bool 亦回 422。"""
    mid = str(uuid.uuid4())

    # 正常 boolean
    r1 = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": mid, "room_id": "room_1", "vad_listening": True, "chunks_pending": 0},
        headers=_AUTH_HEADER,
    )
    assert r1.status_code == 200

    r2 = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": mid, "room_id": "room_1", "vad_listening": False, "chunks_pending": 2},
        headers=_AUTH_HEADER,
    )
    assert r2.status_code == 200

    # 整數 1 (在 Python 裡 isinstance(1, bool) 是 False)
    r3 = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": mid, "room_id": "room_1", "vad_listening": 1},
        headers=_AUTH_HEADER,
    )
    assert r3.status_code == 422
    assert "vad_listening 需為布林值" in r3.get_json()["message"]

    # 字串 "true"
    r4 = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": mid, "room_id": "room_1", "vad_listening": "true"},
        headers=_AUTH_HEADER,
    )
    assert r4.status_code == 422
    assert "vad_listening 需為布林值" in r4.get_json()["message"]

    # chunks_pending 傳布林值 True (在 Python 裡 isinstance(True, int) 是 True，防禦性攔截)
    r5 = phase31_client.post(
        "/api/clients/heartbeat",
        json={"machine_id": mid, "room_id": "room_1", "chunks_pending": True},
        headers=_AUTH_HEADER,
    )
    assert r5.status_code == 422
    assert "chunks_pending 需為非負整數" in r5.get_json()["message"]


# ======================================================================
# T2.9: 循環建立 trigger_mode 與 preroll_sec 驗證 (H1)
# ======================================================================


def test_e2e_cycle_creation_trigger_mode_validation(phase31_app, phase31_client):
    """T2.9: trigger_mode 僅允許 'manual' 與 'vad_auto'；preroll_sec 必須為非負數。"""
    # 正常 manual
    r1 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id(), "trigger_mode": "manual", "preroll_sec": 0.0},
        headers=_AUTH_HEADER,
    )
    assert r1.status_code == 201

    # 正常 vad_auto
    r2 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id(), "trigger_mode": "vad_auto", "preroll_sec": 3.0},
        headers=_AUTH_HEADER,
    )
    assert r2.status_code == 201
    assert r2.get_json()["cycle"]["trigger_mode"] == "vad_auto"
    assert r2.get_json()["cycle"]["preroll_sec"] == 3.0

    # 預設值（不傳欄位）
    r3 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id()},
        headers=_AUTH_HEADER,
    )
    assert r3.status_code == 201
    assert r3.get_json()["cycle"]["trigger_mode"] == "manual"
    assert r3.get_json()["cycle"]["preroll_sec"] == 0.0

    # 非法 trigger_mode
    r4 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id(), "trigger_mode": "invalid_mode"},
        headers=_AUTH_HEADER,
    )
    assert r4.status_code == 422
    assert "不合法的 trigger_mode" in r4.get_json()["message"]

    # 負數 preroll_sec
    r5 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id(), "preroll_sec": -1.5},
        headers=_AUTH_HEADER,
    )
    assert r5.status_code == 422
    assert "preroll_sec 必須為非負數" in r5.get_json()["message"]

    # 字串 preroll_sec
    r6 = phase31_client.post(
        "/api/cycles",
        json={"machine_id": _new_machine_id(), "command_id": _new_command_id(), "preroll_sec": "not-a-number"},
        headers=_AUTH_HEADER,
    )
    assert r6.status_code == 422
    assert "preroll_sec 必須為非負數" in r6.get_json()["message"]
