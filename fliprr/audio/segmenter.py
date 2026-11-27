"""Cut the continuous microphone stream into utterances using VAD scores."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from fliprr.audio.vad import FRAME_MS


@dataclass
class Utterance:
    audio: np.ndarray  # float32 mono, 16 kHz
    started: float  # monotonic time of the first speech frame
    ended: float  # monotonic time when the utterance was closed
    speech_ms: float

    @property
    def duration(self) -> float:
        return len(self.audio) / 16000


class Segmenter:
    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_ms: int = 300,
        end_silence_ms: int = 900,
        max_utterance_s: float = 30.0,
        pre_roll_ms: int = 300,
        start_frames: int = 2,
        tail_ms: int = 250,
    ) -> None:
        self.threshold = threshold
        self.neg_threshold = max(0.05, threshold - 0.15)
        self.min_speech_frames = max(1, round(min_speech_ms / FRAME_MS))
        self.end_silence_frames = max(1, round(end_silence_ms / FRAME_MS))
        self.max_frames = max(1, round(max_utterance_s * 1000 / FRAME_MS))
        self.start_frames = max(1, start_frames)
        self.tail_frames = max(0, round(tail_ms / FRAME_MS))
        self._preroll: deque[np.ndarray] = deque(maxlen=max(self.start_frames, round(pre_roll_ms / FRAME_MS)))
        self.reset()

    def reset(self) -> None:
        self._preroll.clear()
        self._frames: list[np.ndarray] = []
        self._in_speech = False
        self._run = 0  # consecutive speech frames before start
        self._silence = 0
        self._speech_frames = 0
        self._started = 0.0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def push(self, frame: np.ndarray, prob: float, now: float) -> Utterance | None:
        if not self._in_speech:
            self._preroll.append(frame)
            self._run = self._run + 1 if prob >= self.threshold else 0
            if self._run >= self.start_frames:
                self._in_speech = True
                self._frames = list(self._preroll)
                self._preroll.clear()
                self._speech_frames = self._run
                self._silence = 0
                self._started = now - self._run * FRAME_MS / 1000
            return None

        self._frames.append(frame)
        if prob >= self.threshold:
            self._speech_frames += 1
            self._silence = 0
        elif prob < self.neg_threshold:
            self._silence += 1
        if self._silence >= self.end_silence_frames or len(self._frames) >= self.max_frames:
            return self._finish(now)
        return None

    def flush(self, now: float) -> Utterance | None:
        return self._finish(now) if self._in_speech else None

    def _finish(self, now: float) -> Utterance | None:
        frames = self._frames
        trailing = self._silence
        if trailing > self.tail_frames:
            frames = frames[: len(frames) - (trailing - self.tail_frames)]
        speech_frames = self._speech_frames
        started = self._started
        self.reset()
        if speech_frames < self.min_speech_frames or not frames:
            return None
        return Utterance(
            audio=np.concatenate(frames).astype(np.float32),
            started=started,
            ended=now,
            speech_ms=speech_frames * FRAME_MS,
        )
