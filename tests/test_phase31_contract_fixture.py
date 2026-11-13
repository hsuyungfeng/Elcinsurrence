"""Phase 31 契約 fixture 自我一致性與測試輔助驗證。"""

from __future__ import annotations

import io
from hashlib import sha256
import wave

from tests.phase31_support import (
    phase31_app,  # noqa: F401
    load_contract,
    make_wav_chunk,
    pcm_sha256,
    wav_sha256,
)
from tests.phase31_support import phase31_app  # noqa: F401

EXPECTED_STATES = {
    "RECORDING",
    "AWAITING_DRAFT",
    "AWAITING_CONFIRM",
    "DRAFT_UNUSABLE",
    "CONFIRMED",
    "ARCHIVING",
    "ARCHIVE_FAILED",
    "ARCHIVED",
    "ABANDONED",
}


def test_contract_version_and_states():
    """Test 1: fixture 的 contract 為 elc-p31-ipc/1，cycle_states 恰為九個狀態。"""
    contract = load_contract()
    assert contract["contract"] == "elc-p31-ipc/1"
    states = contract["cycle_states"]
    assert len(states) == 9
    assert set(states) == EXPECTED_STATES


def test_transitions_validity():
    """Test 2: transitions 中每個目標狀態都屬於 cycle_states；ARCHIVED 與 ABANDONED 無轉出。"""
    contract = load_contract()
    all_states = set(contract["cycle_states"])
    transitions = contract["transitions"]

    for src_state, target_states in transitions.items():
        assert src_state in all_states, f"Unknown source state {src_state}"
        for tgt in target_states:
            assert tgt in all_states, f"Target state {tgt} from {src_state} not in cycle_states"

    assert transitions.get("ARCHIVED") == [], "ARCHIVED must have no outgoing transitions"
    assert transitions.get("ABANDONED") == [], "ABANDONED must have no outgoing transitions"


def test_heartbeat_response_has_no_forbidden_keys():
    """Test 3: heartbeat 範例回應遞迴檢查不含 heartbeat_forbidden_keys。"""
    contract = load_contract()
    forbidden = set(contract["heartbeat_forbidden_keys"])
    heartbeat_resp = contract["server"]["heartbeat"]["response_200"]

    def _check_keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in forbidden, f"Forbidden key '{k}' found in heartbeat response"
                _check_keys(v)
        elif isinstance(obj, list):
            for item in obj:
                _check_keys(item)

    _check_keys(heartbeat_resp)


def test_make_wav_chunk_and_pcm_sha256():
    """Test 4: make_wav_chunk 回傳合法 16kHz mono 16-bit WAV，pcm_sha256 計算一致。"""
    chunk1 = make_wav_chunk(seconds=1.0, seed=1)
    chunk2 = make_wav_chunk(seconds=0.5, seed=2)

    assert len(chunk1) > 44
    assert len(chunk2) > 44
    assert wav_sha256(chunk1) != wav_sha256(chunk2)

    # 驗證 WAV 標頭與格式
    with wave.open(io.BytesIO(chunk1), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames1 = wf.readframes(wf.getnframes())

    with wave.open(io.BytesIO(chunk2), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames2 = wf.readframes(wf.getnframes())

    expected_combined_pcm = frames1 + frames2
    expected_pcm_hash = sha256(expected_combined_pcm).hexdigest()

    calc_hash = pcm_sha256([chunk1, chunk2])
    assert calc_hash == expected_pcm_hash


def test_phase31_app_isolation(phase31_app, tmp_path):
    """Test 5: phase31_app fixture 建立的 app 其 DATA_DIR 指向 tmp_path，不寫入專案 data/。"""
    app_data_dir = phase31_app.config.get("DATA_DIR")
    assert app_data_dir is not None
    assert str(tmp_path) in app_data_dir

    from config import settings
    assert str(tmp_path) in str(settings.DATA_DIR)
