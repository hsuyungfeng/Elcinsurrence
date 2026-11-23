"""本機 sherpa-onnx 離線語音辨識與說者分離後端（Phase 34）。

採用 SenseVoice int8（ONNX Runtime，純 CPU 約 42.8× 即時速度、0% 重複迴圈）＋
OpenCC（`s2twp` 轉台灣繁體）＋ 診所專科熱詞校正，並可選擇性啟用
pyannote-segmentation-3-0 ＋ 3D-Speaker 離線說者分離（預設 ``num_clusters=2``，
將診間 1 對 1 對話聚類為醫師／病患雙說者，避免自動門檻過度切分）。

設計原則：
- **延遲載入**：僅在執行轉錄時 import ``sherpa_onnx``／``opencc``；未安裝或缺少模型時
  拋出 ``ASRUnavailableError``（系統故障語意，絕不靜默回傳空字串）。
- **可注入測試點**：提供 ``recognizer_factory``、``diarizer_factory``、``audio_loader``
  與 ``text_converter``，單元測試零外部模型依賴。
- **PHI-safe logging**：僅記錄模型、耗時、段數與說者數，絕不輸出逐字稿內容。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from elc_audit_engine.asr.transcriber import (
    ASRTranscriptionError,
    ASRUnavailableError,
    HotwordConfig,
    TranscriptionResult,
    _decode_audio_16k,
    apply_hotword_replacements,
    load_hotword_config,
)

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = Path(os.path.expanduser("~/.cache/elc-sherpa"))
_DEFAULT_SENSEVOICE_DIR = _DEFAULT_CACHE_ROOT / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
_DEFAULT_PYANNOTE_DIR = _DEFAULT_CACHE_ROOT / "sherpa-onnx-pyannote-segmentation-3-0"
_DEFAULT_EMBEDDING_MODEL = _DEFAULT_CACHE_ROOT / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

_SAMPLE_RATE = 16000
_DEFAULT_MAX_CHUNK_SEC = 25.0
_DEFAULT_MAX_GAP_SEC = 1.0
_DEFAULT_NUM_CLUSTERS = 2

_RECOGNIZER_CACHE: dict[tuple[str, int, str], Any] = {}
_DIARIZER_CACHE: dict[tuple[str, str, int, int], Any] = {}


@dataclass(frozen=True)
class SherpaModelPaths:
    """sherpa-onnx 本機模型路徑設定。"""

    sensevoice_dir: Path
    pyannote_dir: Path
    embedding_model: Path


def resolve_sherpa_paths(
    *,
    sensevoice_dir: str | Path | None = None,
    pyannote_dir: str | Path | None = None,
    embedding_model: str | Path | None = None,
) -> SherpaModelPaths:
    """解析 sherpa-onnx 本機模型路徑（參數優先 → 環境變數 → 預設快取目錄）。"""
    sv = Path(sensevoice_dir or os.environ.get("ELC_SHERPA_SENSEVOICE_DIR") or _DEFAULT_SENSEVOICE_DIR)
    pyan = Path(pyannote_dir or os.environ.get("ELC_SHERPA_PYANNOTE_DIR") or _DEFAULT_PYANNOTE_DIR)
    emb = Path(embedding_model or os.environ.get("ELC_SHERPA_EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL)
    return SherpaModelPaths(sensevoice_dir=sv, pyannote_dir=pyan, embedding_model=emb)


def merge_diar_segments(
    segments: list[Any],
    *,
    max_sec: float = _DEFAULT_MAX_CHUNK_SEC,
    max_gap: float = _DEFAULT_MAX_GAP_SEC,
    min_sec: float = 0.15,
) -> list[tuple[int, float, float]]:
    """合併同說者相鄰語段並切分超長語段（確保單段 ≤ max_sec 符合 SenseVoice 視窗）。"""
    merged: list[tuple[int, float, float]] = []
    for seg in segments:
        spk = int(getattr(seg, "speaker", 0))
        st = float(getattr(seg, "start", 0.0))
        ed = float(getattr(seg, "end", 0.0))
        if ed - st < min_sec:
            continue
        if (
            merged
            and merged[-1][0] == spk
            and (st - merged[-1][2]) <= max_gap
            and (ed - merged[-1][1]) <= max_sec
        ):
            merged[-1] = (spk, merged[-1][1], ed)
        else:
            cur_s = st
            while cur_s < ed:
                cur_e = min(ed, cur_s + max_sec)
                if cur_e - cur_s >= min_sec:
                    merged.append((spk, cur_s, cur_e))
                cur_s = cur_e
    return merged


def _slice_fixed_chunks(
    num_samples: int,
    *,
    sample_rate: int = _SAMPLE_RATE,
    max_sec: float = _DEFAULT_MAX_CHUNK_SEC,
) -> list[tuple[int, float, float]]:
    """不啟用說者分離時，依固定視窗切段供 SenseVoice 批次轉錄。"""
    dur = num_samples / float(sample_rate)
    chunks: list[tuple[int, float, float]] = []
    cur = 0.0
    while cur < dur:
        end = min(dur, cur + max_sec)
        if end - cur >= 0.15:
            chunks.append((-1, cur, end))
        cur = end
    return chunks


def _load_sensevoice_recognizer(sensevoice_dir: Path, num_threads: int, language: str) -> Any:
    key = (str(sensevoice_dir), num_threads, language)
    if key in _RECOGNIZER_CACHE:
        return _RECOGNIZER_CACHE[key]
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise ASRUnavailableError(
            "sherpa-onnx 未安裝，無法執行 SenseVoice 本機轉錄（請安裝：uv sync --extra asr-sherpa）"
        ) from exc

    model_file = sensevoice_dir / "model.int8.onnx"
    if not model_file.is_file():
        model_file = sensevoice_dir / "model.onnx"
    tokens_file = sensevoice_dir / "tokens.txt"
    if not (model_file.is_file() and tokens_file.is_file()):
        raise ASRUnavailableError(
            f"找不到 SenseVoice ONNX 模型檔（預期於 {sensevoice_dir} 內含 model.int8.onnx 與 tokens.txt）"
        )
    try:
        rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=num_threads,
            language=language,
            use_itn=True,
            provider="cpu",
        )
    except Exception as exc:
        raise ASRUnavailableError(f"sherpa-onnx SenseVoice 初始化失敗：{exc}") from exc
    _RECOGNIZER_CACHE[key] = rec
    return rec


def _load_diarizer(pyannote_dir: Path, embedding_model: Path, num_threads: int, num_clusters: int) -> Any:
    key = (str(pyannote_dir), str(embedding_model), num_threads, num_clusters)
    if key in _DIARIZER_CACHE:
        return _DIARIZER_CACHE[key]
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise ASRUnavailableError(
            "sherpa-onnx 未安裝，無法執行離線說者分離（請安裝：uv sync --extra asr-sherpa）"
        ) from exc

    seg_file = pyannote_dir / "model.onnx"
    if not seg_file.is_file():
        seg_file = pyannote_dir / "model.int8.onnx"
    if not seg_file.is_file():
        raise ASRUnavailableError(f"找不到 pyannote 分段模型檔：{pyannote_dir}")
    if not embedding_model.is_file():
        raise ASRUnavailableError(f"找不到說者特徵模型檔：{embedding_model}")

    try:
        cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_file)),
                num_threads=num_threads,
                provider="cpu",
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(embedding_model),
                num_threads=num_threads,
                provider="cpu",
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_clusters,
                threshold=0.55,
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not cfg.validate():
            raise ASRUnavailableError("sherpa-onnx OfflineSpeakerDiarizationConfig 驗證失敗")
        diarizer = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    except ASRUnavailableError:
        raise
    except Exception as exc:
        raise ASRUnavailableError(f"sherpa-onnx 說者分離初始化失敗：{exc}") from exc
    _DIARIZER_CACHE[key] = diarizer
    return diarizer


def _default_s2twp_converter() -> Callable[[str], str]:
    try:
        import opencc

        cc = opencc.OpenCC("s2twp")
        return cc.convert
    except ImportError as exc:
        raise ASRUnavailableError(
            "opencc 未安裝，無法執行台灣繁體轉換（請安裝：uv sync --extra asr-sherpa）"
        ) from exc


def transcribe_audio_sherpa(
    audio_path: str | Path,
    *,
    diarize: bool = False,
    num_clusters: int = _DEFAULT_NUM_CLUSTERS,
    cpu_threads: int | None = None,
    language: str = "zh",
    model_paths: SherpaModelPaths | None = None,
    hotword_config: HotwordConfig | None = None,
    recognizer_factory: Callable[[Path, int, str], Any] | None = None,
    diarizer_factory: Callable[[Path, Path, int, int], Any] | None = None,
    audio_loader: Callable[[Path], Any] | None = None,
    text_converter: Callable[[str], str] | None = None,
) -> TranscriptionResult:
    """使用本機 sherpa-onnx（SenseVoice int8 + OpenCC + 可選雙人說者分離）轉錄音檔。

    Args:
        audio_path: 本機音檔路徑（.wav / .opus 等）。
        diarize: 是否啟用離線說者分離（預設 False；啟用時輸出 `[Speaker N]` 標籤）。
        num_clusters: 說者分離聚類人數（預設 2：醫師／病患；設 -1 改由門檻自動判定）。
        cpu_threads: CPU 執行緒數（預設讀 `ELC_ASR_THREADS` 或 8）。
        language: SenseVoice 語言提示（預設 `"zh"`）。
        model_paths: 本機模型路徑（未提供則自動由環境變數／預設快取解析）。
        hotword_config: 診所熱詞與同音替換表（未提供則載入 `config/asr_hotwords.json`）。
        recognizer_factory / diarizer_factory / audio_loader / text_converter: 測試注入點。
    """
    path = Path(audio_path)
    if not path.is_file():
        raise ASRTranscriptionError("音檔不存在，無法執行本機語音轉錄")

    eff_threads = cpu_threads or int(os.environ.get("ELC_ASR_THREADS", "8"))
    paths = model_paths or resolve_sherpa_paths()
    hw_cfg = hotword_config if hotword_config is not None else load_hotword_config()
    convert = text_converter if text_converter is not None else _default_s2twp_converter()

    rec_factory = recognizer_factory or _load_sensevoice_recognizer
    recognizer = rec_factory(paths.sensevoice_dir, eff_threads, language)

    diarizer = None
    if diarize:
        d_factory = diarizer_factory or _load_diarizer
        diarizer = d_factory(paths.pyannote_dir, paths.embedding_model, eff_threads, num_clusters)

    loader = audio_loader or _decode_audio_16k
    t0 = time.monotonic()
    try:
        audio = loader(path)
        num_samples = len(audio)
        duration = num_samples / float(_SAMPLE_RATE)

        if diarize and diarizer is not None:
            raw_segs = diarizer.process(audio).sort_by_start_time()
            chunks = merge_diar_segments(list(raw_segs))
        else:
            chunks = _slice_fixed_chunks(num_samples)

        lines: list[str] = []
        batch_size = 16
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            streams = []
            for spk, st, ed in batch:
                st_idx = max(0, int(st * _SAMPLE_RATE))
                ed_idx = min(num_samples, int(ed * _SAMPLE_RATE))
                stream = recognizer.create_stream()
                stream.accept_waveform(_SAMPLE_RATE, audio[st_idx:ed_idx])
                streams.append((spk, stream))
            recognizer.decode_streams([st_obj for _, st_obj in streams])
            for spk, st_obj in streams:
                raw_txt = (getattr(st_obj.result, "text", "") or "").strip()
                if not raw_txt:
                    continue
                fixed = apply_hotword_replacements(convert(raw_txt), hw_cfg.replacements)
                if diarize and spk >= 0:
                    lines.append(f"[Speaker {spk}] {fixed}")
                else:
                    lines.append(fixed)
    except ASRUnavailableError:
        raise
    except Exception as exc:
        raise ASRTranscriptionError(f"sherpa-onnx 語音轉錄失敗：{type(exc).__name__}") from exc

    elapsed = round(time.monotonic() - t0, 2)
    transcript = "\n".join(lines)
    model_label = "sherpa-onnx-sensevoice-int8+diar" if diarize else "sherpa-onnx-sensevoice-int8"

    # PHI-safe logging：只記錄元資料，絕不輸出逐字稿內容
    logger.info(
        "Local sherpa-onnx ASR completed: model=%s diarize=%s num_clusters=%d duration_s=%.1f elapsed_s=%.2f segments=%d",
        model_label,
        diarize,
        num_clusters if diarize else 0,
        duration,
        elapsed,
        len(lines),
    )
    return TranscriptionResult(
        transcript=transcript,
        model=model_label,
        duration_s=round(duration, 2),
        elapsed_s=elapsed,
        segment_count=len(lines),
    )
