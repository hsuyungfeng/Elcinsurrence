"""Phase 31 Wave 0 共用測試輔助模組。

提供契約載入、確定性 WAV 分段生成、PCM 串接雜湊計算與隔離測試 App fixture。
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CONTRACT_FIXTURE_PATH = FIXTURES_DIR / "phase31_contract_v1.json"


def load_contract() -> dict[str, Any]:
    """讀取 Phase 31 契約 fixture (JSON)。"""
    with open(CONTRACT_FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def make_wav_chunk(seconds: float = 1.0, seed: int = 0, sample_rate: int = 16000) -> bytes:
    """產生確定性 16 kHz, mono, 16-bit PCM WAV 位元組。

    以 seed 產生不同頻率的正弦波，使不同分段之位元組與雜湊皆不同。
    """
    total_frames = int(seconds * sample_rate)
    freq = 440.0 + (seed * 37) % 1000
    frames = bytearray()
    for i in range(total_frames):
        val = int(10000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
        frames.extend(struct.pack("<h", val))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    return buf.getvalue()


def wav_sha256(data: bytes) -> str:
    """計算 WAV 檔本體位元組之 SHA-256 (64 位小寫 hex)。"""
    return sha256(data).hexdigest()


def pcm_sha256(list_of_wav_bytes: list[bytes]) -> str:
    """依序取出每段 WAV 之 PCM frames（不含 WAV 標頭）串接後計算 SHA-256。"""
    raw_pcm = bytearray()
    for wb in list_of_wav_bytes:
        with wave.open(io.BytesIO(wb), "rb") as wf:
            raw_pcm.extend(wf.readframes(wf.getnframes()))
    return sha256(raw_pcm).hexdigest()


@pytest.fixture
def phase31_app(tmp_path, monkeypatch):
    """建立隔離的 Phase 31 API app：暫存 CaseStore、暫存 DATA_DIR、固定測試金鑰。

    - ELC_API_KEYS: {"valid-key-123": "clinic_a"} (一般客戶端/診所金鑰)
    - ELC_AGENT_KEYS: {"agent-key-1": "agent_a"} (Agent 金鑰，測試 403 阻絕)
    - DATA_DIR: tmp_path / "data"
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "cases.sqlite3"
    audit_log_path = tmp_path / "audit" / "access.log"

    monkeypatch.setenv("CASES_DB_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setenv("DISABLE_AUTH", "0")

    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(settings, "CASES_DB_PATH", str(db_file))
    monkeypatch.setattr(settings, "AUDIT_LOG_PATH", str(audit_log_path))

    from elc_audit_engine import audit_log
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", str(audit_log_path))

    from elc_audit_engine.api import create_app
    from elc_audit_engine.case_store import CaseStore

    store = CaseStore(str(db_file))
    app = create_app(
        config={
            "TESTING": True,
            "DISABLE_AUTH": False,
            "ELC_API_KEYS": {"valid-key-123": "clinic_a"},
            "ELC_AGENT_KEYS": {"agent-key-1": "agent_a"},
            "ELC_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver"],
            "DATA_DIR": str(data_dir),
            "AUDIT_LOG_PATH": str(audit_log_path),
            "ELC_UPLOAD_DIR": str(data_dir / "uploads"),
            "ELC_RAW_DIR": str(data_dir / "raw"),
        },
        case_store=store,
        migrate_legacy=False,
    )
    app.case_store = store
    return app


@pytest.fixture
def phase31_client(phase31_app):
    """回傳 phase31_app 的 Flask 測試客戶端。"""
    return phase31_app.test_client()
