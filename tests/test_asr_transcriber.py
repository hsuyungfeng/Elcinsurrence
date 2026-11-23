"""本機 faster-whisper ASR 轉錄器測試（Phase 33，零真實模型下載）。"""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest

from elc_audit_engine.asr import (
    ASRTranscriptionError,
    ASRUnavailableError,
    HotwordConfig,
    apply_hotword_replacements,
    build_initial_prompt,
    load_hotword_config,
    transcribe_audio,
)


def test_load_default_hotword_config():
    cfg = load_hotword_config()
    assert "鈣化性肌腱炎" in cfg.hotwords
    assert cfg.replacements.get("概化性肌腱發炎") == "鈣化性肌腱炎"


def test_load_missing_hotword_config_returns_safe_default(tmp_path):
    cfg = load_hotword_config(tmp_path / "nonexistent.json")
    assert cfg.hotwords == ()
    assert cfg.replacements == {}
    assert "繁體中文" in cfg.prompt_prefix


def test_build_initial_prompt_and_deterministic_replacements():
    cfg = HotwordConfig(
        prompt_prefix="門診轉錄。",
        hotwords=("髕骨外翻", "鈣化性肌腱炎"),
        replacements={"概化性肌腱發炎": "鈣化性肌腱炎", "賓骨": "髕骨"},
    )
    prompt = build_initial_prompt(cfg)
    assert "髕骨外翻、鈣化性肌腱炎" in prompt
    fixed = apply_hotword_replacements("右肩概化性肌腱發炎合併賓骨問題", cfg.replacements)
    assert fixed == "右肩鈣化性肌腱炎合併髕骨問題"


def test_transcribe_audio_enforces_vad_no_loop_and_phi_safe_logging(tmp_path, caplog):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    captured: dict = {}
    secret_phrase = "病患陳小明主訴右肩概化性肌腱發炎"

    class _FakeModel:
        def transcribe(self, path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return iter([SimpleNamespace(text=secret_phrase)]), SimpleNamespace(duration=42.5)

    caplog.set_level(logging.INFO)
    result = transcribe_audio(
        wav,
        model_name="large-v3-turbo",
        model_factory=lambda *args: _FakeModel(),
    )

    assert captured["kwargs"]["vad_filter"] is True
    assert captured["kwargs"]["condition_on_previous_text"] is False
    assert captured["kwargs"]["language"] == "zh"
    assert "鈣化性肌腱炎" in captured["kwargs"]["initial_prompt"]
    assert "鈣化性肌腱炎" in result.transcript
    assert "概化性肌腱發炎" not in result.transcript
    assert result.duration_s == 42.5
    assert result.segment_count == 1

    # PHI-safe logging：日誌絕不可包含逐字稿文字
    for rec in caplog.records:
        assert "陳小明" not in rec.getMessage()
        assert "肌腱炎" not in rec.getMessage()


def test_transcribe_missing_audio_raises_error(tmp_path):
    with pytest.raises(ASRTranscriptionError):
        transcribe_audio(tmp_path / "missing.wav", model_factory=lambda *args: None)


def test_missing_faster_whisper_raises_unavailable_error(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import transcriber

    monkeypatch.setattr(transcriber, "_MODEL_CACHE", {})
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    with pytest.raises(ASRUnavailableError):
        transcribe_audio(wav, backend="whisper")


def test_decode_audio_16k_missing_av_raises_unavailable_error(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import transcriber

    monkeypatch.setitem(sys.modules, "av", None)
    with pytest.raises(ASRUnavailableError):
        transcriber._decode_audio_16k(wav)


def test_decode_audio_16k_calls_av_open_without_metadata_errors(tmp_path, monkeypatch):
    wav = tmp_path / "visit.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")

    from elc_audit_engine.asr import transcriber

    open_kwargs: dict = {}

    class _FakeArray:
        def reshape(self, *_):
            return self

        def astype(self, _):
            return self

        def __truediv__(self, _):
            return [0.25, -0.25]

    class _FakeFrame:
        def to_ndarray(self):
            return _FakeArray()

    class _FakeResampler:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def resample(self, frame):
            return [_FakeFrame()]

    class _FakeContainer:
        def decode(self, audio=0):
            return [object()]

        def close(self):
            pass

    def _fake_open(path, **kwargs):
        open_kwargs.update(kwargs)
        return _FakeContainer()

    fake_av = SimpleNamespace(
        open=_fake_open,
        audio=SimpleNamespace(resampler=SimpleNamespace(AudioResampler=_FakeResampler)),
    )
    fake_np = SimpleNamespace(
        float32="float32",
        concatenate=lambda chunks: chunks[0],
        zeros=lambda n, dtype=None: [],
    )
    monkeypatch.setitem(sys.modules, "av", fake_av)
    monkeypatch.setitem(sys.modules, "numpy", fake_np)

    out = transcriber._decode_audio_16k(wav)
    assert "metadata_errors" not in open_kwargs
    assert out == [0.25, -0.25]
