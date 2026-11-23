"""本機離線語音辨識（ASR）套件（Phase 33）。

採用 faster-whisper（預設 large-v3-turbo）搭配 Silero VAD 與診所專科熱詞表，
所有語音推論 100% 留在本機，絕不外送雲端（D2 紅線）。
"""

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
    "TranscriptionResult",
    "apply_hotword_replacements",
    "build_initial_prompt",
    "load_hotword_config",
    "transcribe_audio",
]
