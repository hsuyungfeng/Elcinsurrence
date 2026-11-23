"""本機離線語音辨識（ASR）套件（Phase 33–34）。

支援雙後端（皆 100% 本機離線、絕不外送雲端，符合 D2 紅線）：
- ``sherpa``（Phase 34）：sherpa-onnx SenseVoice int8 ＋ OpenCC `s2twp` ＋ 專科熱詞
  ＋ 可選雙人說者分離（`num_clusters=2`），純 CPU 約 42.8× 即時速度、0% 重複迴圈。
- ``whisper``（Phase 33）：faster-whisper `large-v3-turbo` ＋ Silero VAD ＋ 專科熱詞表。
"""

from .sherpa_backend import (
    SherpaModelPaths,
    merge_diar_segments,
    resolve_sherpa_paths,
    transcribe_audio_sherpa,
)
from .transcriber import (
    ASRTranscriptionError,
    ASRUnavailableError,
    HotwordConfig,
    TranscriptionResult,
    apply_hotword_replacements,
    build_initial_prompt,
    load_hotword_config,
    transcribe_audio,
)

__all__ = [
    "ASRTranscriptionError",
    "ASRUnavailableError",
    "HotwordConfig",
    "SherpaModelPaths",
    "TranscriptionResult",
    "apply_hotword_replacements",
    "build_initial_prompt",
    "load_hotword_config",
    "merge_diar_segments",
    "resolve_sherpa_paths",
    "transcribe_audio",
    "transcribe_audio_sherpa",
]
