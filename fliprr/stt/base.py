"""Speech-to-text interfaces and shared helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from fliprr.text import normalize

# Biasing Whisper with the assistant names makes «Клод Код» come out right
# far more often than `hotwords` does (measured on synthetic and real speech).
DEFAULT_PROMPTS = {
    "ru": "Разговор с ассистентом Клод (Claude) и Клод Код (Claude Code).",
    "en": "A conversation with the assistants Claude and Claude Code.",
    "": "Claude, Claude Code. Клод, Клод Код.",
}

# Phrases Whisper is known to invent on silence and noise (it learned them
# from subtitles). An utterance consisting of one of these is dropped.
_HALLUCINATIONS = [
    "субтитры", "продолжение следует", "спасибо за просмотр", "редактор субтитров",
    "корректор", "подписывайтесь на канал", "ставьте лайки", "dimatorzok", "amara org",
    "до новых встреч", "thank you for watching", "thanks for watching", "subtitles by",
    "please subscribe", "transcribed by", "переведено", "смотрите продолжение",
]
_REPEAT_RE = re.compile(r"\b(\w+(?:\s+\w+){0,3})(?:\s+\1\b){3,}")


@dataclass
class Transcript:
    text: str
    language: str = ""
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    seconds: float = 0.0  # time spent transcribing


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio: np.ndarray, *, fast: bool = False) -> Transcript: ...


def prompt_for(language: str, override: str = "") -> str:
    if override:
        return override
    return DEFAULT_PROMPTS.get(language, DEFAULT_PROMPTS[""])


def is_hallucination(text: str, prompt: str = "") -> bool:
    norm = normalize(text)
    if not norm:
        return True
    if any(h in norm for h in _HALLUCINATIONS):
        return True
    if prompt:
        p = normalize(prompt)
        # The prompt leaking back as the transcript.
        if norm == p or (len(norm) > 12 and norm in p):
            return True
    if _REPEAT_RE.search(norm):
        return True
    return False


def normalize_level(audio: np.ndarray, target_peak: float = 0.5) -> np.ndarray:
    """Quiet far-field speech: bring the peak up (never above ~-6 dBFS)."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-4:
        return audio
    gain = min(target_peak / peak, 20.0)
    return (audio * gain).astype(np.float32) if gain > 1.0 else audio
