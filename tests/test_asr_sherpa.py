"""sherpa-onnx SenseVoice int8 + OpenCC + 可選雙人說者分離（num_clusters=2）測試（Phase 34）。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from elc_audit_engine.asr import (
    ASRTranscriptionError,
    ASRUnavailableError,
    HotwordConfig,
    SherpaModelPaths,
    merge_diar_segments,
    transcribe_audio,
    transcribe_audio_sherpa,
)


def test_merge_diar_segments_merges_same_speaker_and_splits_long():
    segs = [
        SimpleNamespace(speaker=0, start=0.0, end=4.0),
        SimpleNamespace(speaker=0, start=4.6, end=9.0),  # gap 0.6s <= 1.0s -> merge
        SimpleNamespace(speaker=1, start=9.5, end=40.0),  # 30.5s -> split at 25s
        SimpleNamespace(speaker=1, start=40.1, end=40.15),  # < 0.15s -> drop
    ]
    merged = merge_diar_segments(segs, max_sec=25.0, max_gap=1.0)
    assert merged == [
        (0, 0.0, 9.0),
        (1, 9.5, 34.5),
        (1, 34.5, 40.0),
    ]


def test_transcribe_audio_sherpa_without_diarization_converts_and_applies_hotwords(tmp_path, caplog):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    class _FakeStream:
        def __init__(self):
            self.result = SimpleNamespace(text="")

        def accept_waveform(self, sr, samples):
            self.sr = sr
            self.samples = samples

    class _FakeRecognizer:
        def create_stream(self):
            return _FakeStream()

        def decode_streams(self, streams):
            for st in streams:
                st.result = SimpleNamespace(text="病患王大明右肩概化性肌腱發炎合併賓骨問題")

    caplog.set_level(logging.INFO)
    res = transcribe_audio_sherpa(
        wav,
        diarize=False,
        hotword_config=HotwordConfig(
            prompt_prefix="",
            hotwords=("鈣化性肌腱炎",),
            replacements={"概化性肌腱發炎": "鈣化性肌腱炎", "賓骨": "髕骨"},
        ),
        recognizer_factory=lambda *args: _FakeRecognizer(),
        audio_loader=lambda _: [0.0] * 16000 * 5,
        text_converter=lambda s: s,
    )

    assert res.model == "sherpa-onnx-sensevoice-int8"
    assert res.duration_s == 5.0
    assert res.segment_count == 1
    assert "鈣化性肌腱炎" in res.transcript
    assert "髕骨" in res.transcript
    assert "[Speaker" not in res.transcript

    # PHI-safe logging：日誌絕不可包含病患姓名或症狀原文
    for rec in caplog.records:
        assert "王大明" not in rec.getMessage()
        assert "肌腱炎" not in rec.getMessage()


def test_transcribe_audio_sherpa_with_diarization_defaults_to_two_speakers(tmp_path):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    diar_calls: dict = {}

    class _FakeDiarResult:
        def sort_by_start_time(self):
            return [
                SimpleNamespace(speaker=0, start=0.0, end=2.0),
                SimpleNamespace(speaker=1, start=2.5, end=4.5),
            ]

    class _FakeDiarizer:
        def process(self, audio):
            return _FakeDiarResult()

    def _diar_factory(pyan_dir, emb_model, threads, num_clusters):
        diar_calls["num_clusters"] = num_clusters
        return _FakeDiarizer()

    class _FakeStream:
        def __init__(self):
            self.result = SimpleNamespace(text="")

        def accept_waveform(self, sr, samples):
            pass

    class _FakeRecognizer:
        def __init__(self):
            self.idx = 0

        def create_stream(self):
            return _FakeStream()

        def decode_streams(self, streams):
            texts = ["請問哪裡不舒服", "右膝蓋上下樓梯會痛"]
            for st in streams:
                st.result = SimpleNamespace(text=texts[self.idx])
                self.idx += 1

    res = transcribe_audio_sherpa(
        wav,
        diarize=True,
        recognizer_factory=lambda *args: _FakeRecognizer(),
        diarizer_factory=_diar_factory,
        audio_loader=lambda _: [0.0] * 16000 * 5,
        text_converter=lambda s: s,
    )

    assert diar_calls["num_clusters"] == 2
    assert res.model == "sherpa-onnx-sensevoice-int8+diar"
    assert res.transcript == "[Speaker 0] 請問哪裡不舒服\n[Speaker 1] 右膝蓋上下樓梯會痛"


def test_transcribe_audio_defaults_to_sherpa_backend(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import sherpa_backend

    called: dict = {}

    def _fake_sherpa(path, **kwargs):
        called["path"] = Path(path)
        called["kwargs"] = kwargs
        return SimpleNamespace(transcript="ok", model="sherpa", duration_s=1.0, elapsed_s=0.1, segment_count=1)

    monkeypatch.delenv("ELC_ASR_BACKEND", raising=False)
    monkeypatch.setattr(sherpa_backend, "transcribe_audio_sherpa", _fake_sherpa)
    res = transcribe_audio(wav)
    assert res.transcript == "ok"
    assert called["kwargs"]["diarize"] is False
    assert called["kwargs"]["num_clusters"] == 2


def test_transcribe_audio_dispatches_to_sherpa_backend(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import sherpa_backend

    called: dict = {}

    def _fake_sherpa(path, **kwargs):
        called["path"] = Path(path)
        called["kwargs"] = kwargs
        return SimpleNamespace(transcript="ok", model="sherpa", duration_s=1.0, elapsed_s=0.1, segment_count=1)

    monkeypatch.setattr(sherpa_backend, "transcribe_audio_sherpa", _fake_sherpa)
    res = transcribe_audio(wav, backend="sherpa", diarize=True, num_clusters=2)
    assert res.transcript == "ok"
    assert called["kwargs"]["diarize"] is True
    assert called["kwargs"]["num_clusters"] == 2


def test_invalid_backend_raises_transcription_error(tmp_path):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    with pytest.raises(ASRTranscriptionError, match="不支援的 ASR 後端"):
        transcribe_audio(wav, backend="invalid_engine")


def test_missing_sherpa_onnx_raises_unavailable_error(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import sherpa_backend

    monkeypatch.setattr(sherpa_backend, "_RECOGNIZER_CACHE", {})
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    with pytest.raises(ASRUnavailableError):
        transcribe_audio_sherpa(
            wav,
            model_paths=SherpaModelPaths(tmp_path, tmp_path, tmp_path / "emb.onnx"),
            text_converter=lambda s: s,
        )


def test_missing_opencc_raises_unavailable_error(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    monkeypatch.setitem(sys.modules, "opencc", None)
    with pytest.raises(ASRUnavailableError, match="opencc"):
        transcribe_audio_sherpa(
            wav,
            recognizer_factory=lambda *args: object(),
            audio_loader=lambda _: [],
        )
