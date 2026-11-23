"""本機 faster-whisper 語音轉錄器（Phase 33）。

設計原則：
- **延遲載入**：僅在呼叫 ``transcribe_audio`` 時 import ``faster_whisper``；
  未安裝選配依賴時拋出 ``ASRUnavailableError``（系統故障語意，絕不靜默回空字）。
- **防重複迴圈**：強制 ``vad_filter=True`` 與 ``condition_on_previous_text=False``
  （已於 8 支真實門診錄音實測驗證，徹底消除重複迴圈）。
- **專科熱詞**：從 ``config/asr_hotwords.json`` 載入診所專詞注入 ``initial_prompt``，
  並套用確定性同音專詞校正表。
- **PHI-safe logging**：日誌只記錄模型、耗時與段數，絕不輸出任何逐字稿內容。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import settings

logger = logging.getLogger(__name__)

_DEFAULT_HOTWORDS_PATH = Path(settings.PROJECT_ROOT) / "config" / "asr_hotwords.json"
_DEFAULT_PROMPT_PREFIX = "以下為台灣門診醫師與病患的繁體中文對話，包含醫學術語，請以繁體中文轉錄。"


class ASRUnavailableError(RuntimeError):
    """本機 ASR 引擎（faster-whisper）未安裝或無法初始化（系統故障，非業務結論）。"""


class ASRTranscriptionError(RuntimeError):
    """音檔無法讀取或轉錄過程失敗（系統故障，非業務結論）。"""


@dataclass(frozen=True)
class HotwordConfig:
    """診所專科熱詞與同音校正設定。"""

    prompt_prefix: str
    hotwords: tuple[str, ...]
    replacements: dict[str, str]


@dataclass(frozen=True)
class TranscriptionResult:
    """語音轉錄結構化結果（不含任何遠端呼叫）。"""

    transcript: str
    model: str
    duration_s: float
    elapsed_s: float
    segment_count: int


def load_hotword_config(path: str | Path | None = None) -> HotwordConfig:
    """讀取熱詞設定檔；缺檔時回傳安全預設，JSON 損毀時 fail-fast。"""
    resolved = Path(path) if path else Path(os.environ.get("ELC_ASR_HOTWORDS_PATH") or _DEFAULT_HOTWORDS_PATH)
    if not resolved.is_file():
        return HotwordConfig(
            prompt_prefix=_DEFAULT_PROMPT_PREFIX,
            hotwords=(),
            replacements={},
        )
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ASRTranscriptionError(f"無法讀取 ASR 熱詞設定檔 {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise ASRTranscriptionError(f"ASR 熱詞設定檔格式錯誤（須為 JSON 物件）: {resolved}")

    prefix = str(data.get("prompt_prefix") or _DEFAULT_PROMPT_PREFIX).strip()
    raw_words = data.get("hotwords") or []
    words = tuple(str(w).strip() for w in raw_words if str(w).strip())
    raw_repl = data.get("replacements") or {}
    replacements = {
        str(k).strip(): str(v).strip()
        for k, v in raw_repl.items()
        if str(k).strip() and str(v).strip()
    }
    return HotwordConfig(prompt_prefix=prefix, hotwords=words, replacements=replacements)


def build_initial_prompt(cfg: HotwordConfig) -> str:
    """將熱詞表組裝為 Whisper initial_prompt（精簡格式，避免佔用過多提示預算）。"""
    if not cfg.hotwords:
        return cfg.prompt_prefix
    return f"{cfg.prompt_prefix}常見詞彙：{'、'.join(cfg.hotwords)}。"


def apply_hotword_replacements(text: str, replacements: dict[str, str]) -> str:
    """套用確定性同音專詞校正（長詞優先，避免部分覆寫）。"""
    if not text or not replacements:
        return text
    out = text
    for wrong in sorted(replacements, key=len, reverse=True):
        out = out.replace(wrong, replacements[wrong])
    return out


_MODEL_CACHE: dict[tuple[str, str, str, int], Any] = {}


def _load_whisper_model(model_name: str, device: str, compute_type: str, cpu_threads: int) -> Any:
    key = (model_name, device, compute_type, cpu_threads)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ASRUnavailableError(
            "faster-whisper 未安裝，無法執行本機語音轉錄（請安裝選配依賴：uv sync --extra asr）"
        ) from exc
    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
        )
    except Exception as exc:
        raise ASRUnavailableError(f"faster-whisper 模型初始化失敗（{model_name}）：{exc}") from exc
    _MODEL_CACHE[key] = model
    return model


def _decode_audio_16k(path: Path) -> Any:
    """以 PyAV 將任意音檔解碼為 16 kHz mono float32 陣列（相容 PyAV 19+，避開 faster-whisper 舊參數 bug）。"""
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise ASRUnavailableError(
            "音訊解碼套件（av / numpy）未安裝，無法執行本機語音轉錄（請安裝：uv sync --extra asr-sherpa）"
        ) from exc

    container = av.open(str(path))
    try:
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
    finally:
        container.close()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe_audio(
    audio_path: str | Path,
    *,
    backend: str | None = None,
    diarize: bool = False,
    num_clusters: int = 2,
    model_name: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    cpu_threads: int | None = None,
    hotword_config: HotwordConfig | None = None,
    model_factory: Callable[[str, str, str, int], Any] | None = None,
) -> TranscriptionResult:
    """本機語音轉錄統一入口：預設 `sherpa`（SenseVoice int8 + OpenCC + 可選說者分離），`whisper` 為備援。

    Args:
        audio_path: 本機音檔路徑（.wav / .opus 等 PyAV 支援格式）。
        backend: `"sherpa"`（預設）或 `"whisper"`（重雜訊／口音備援）；未提供時讀環境變數
            ``ELC_ASR_BACKEND``（預設 `"sherpa"`；若明確注入 Whisper `model_factory` 則走 Whisper 路徑）。
        diarize: 僅 ``backend="sherpa"`` 生效，是否啟用離線說者分離（預設 False）。
        num_clusters: 說者分離聚類人數（預設 2：醫師／病患）。
        model_name: Whisper 模型名（預設讀 ``ELC_ASR_MODEL`` 或 ``large-v3-turbo``）。
        device: 推論裝置（預設 ``cpu``）。
        compute_type: 量化型別（預設 ``int8``）。
        cpu_threads: CPU 執行緒數（預設讀 ``ELC_ASR_THREADS`` 或 8）。
        hotword_config: 注入的熱詞設定；未提供則自動載入 ``config/asr_hotwords.json``。
        model_factory: Whisper 測試用模型工廠注入點（零真實模型依賴）。
    """
    eff_backend = (backend or os.environ.get("ELC_ASR_BACKEND") or "sherpa").strip().lower()
    if model_factory is None and eff_backend == "sherpa":
        from elc_audit_engine.asr.sherpa_backend import transcribe_audio_sherpa

        return transcribe_audio_sherpa(
            audio_path,
            diarize=diarize,
            num_clusters=num_clusters,
            cpu_threads=cpu_threads,
            hotword_config=hotword_config,
        )
    if eff_backend not in ("whisper", "sherpa"):
        raise ASRTranscriptionError(f"不支援的 ASR 後端：{eff_backend!r}（僅支援 'sherpa' 或 'whisper'）")

    path = Path(audio_path)
    if not path.is_file():
        raise ASRTranscriptionError("音檔不存在，無法執行本機語音轉錄")

    eff_model = model_name or os.environ.get("ELC_ASR_MODEL", "large-v3-turbo")
    eff_device = device or os.environ.get("ELC_ASR_DEVICE", "cpu")
    eff_compute = compute_type or os.environ.get("ELC_ASR_COMPUTE_TYPE", "int8")
    eff_threads = cpu_threads or int(os.environ.get("ELC_ASR_THREADS", "8"))

    hw_cfg = hotword_config if hotword_config is not None else load_hotword_config()
    initial_prompt = build_initial_prompt(hw_cfg)

    factory = model_factory or _load_whisper_model
    model = factory(eff_model, eff_device, eff_compute, eff_threads)

    t0 = time.monotonic()
    try:
        audio_input: Any = str(path) if model_factory is not None else _decode_audio_16k(path)
        segments_iter, info = model.transcribe(
            audio_input,
            language="zh",
            initial_prompt=initial_prompt,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 250},
            beam_size=3,
            condition_on_previous_text=False,
        )
        lines: list[str] = []
        for seg in segments_iter:
            txt = (getattr(seg, "text", "") or "").strip()
            if txt:
                lines.append(txt)
    except ASRUnavailableError:
        raise
    except Exception as exc:
        raise ASRTranscriptionError(f"本機語音轉錄失敗：{type(exc).__name__}") from exc

    elapsed = round(time.monotonic() - t0, 2)
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    transcript = apply_hotword_replacements("\n".join(lines), hw_cfg.replacements)

    # PHI-safe logging：只記錄元資料，絕不記錄逐字稿內容
    logger.info(
        "Local ASR completed: model=%s duration_s=%.1f elapsed_s=%.2f segments=%d",
        eff_model,
        duration,
        elapsed,
        len(lines),
    )
    return TranscriptionResult(
        transcript=transcript,
        model=eff_model,
        duration_s=round(duration, 2),
        elapsed_s=elapsed,
        segment_count=len(lines),
    )
