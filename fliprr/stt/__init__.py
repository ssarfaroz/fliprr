from __future__ import annotations

from fliprr.config import STTConfig
from fliprr.stt.base import Transcriber, Transcript, is_hallucination, prompt_for

__all__ = ["Transcriber", "Transcript", "is_hallucination", "make_transcriber", "prompt_for"]


def make_transcriber(cfg: STTConfig, log=print) -> Transcriber:  # noqa: ANN001
    if cfg.engine == "whisper":
        from fliprr.stt.whisper_local import WhisperTranscriber

        return WhisperTranscriber(cfg, log=log)
    if cfg.engine == "openai":
        from fliprr.stt.openai_api import OpenAICompatibleTranscriber

        return OpenAICompatibleTranscriber(cfg)
    raise ValueError(f"unknown stt.engine: {cfg.engine!r} (use whisper or openai)")
