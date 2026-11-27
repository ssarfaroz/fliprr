"""Background thread: audio source → VAD → utterances."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from fliprr.audio.segmenter import Segmenter, Utterance
from fliprr.audio.vad import FRAME_MS


class Listener(threading.Thread):
    def __init__(
        self,
        source,  # noqa: ANN001 — MicrophoneSource | FileSource
        vad: Callable[[np.ndarray], float],
        segmenter: Segmenter,
        on_utterance: Callable[[Utterance], None],
        *,
        playing: threading.Event | None = None,
        barge_in: bool = True,
        on_error: Callable[[BaseException], None] | None = None,
        ring_s: float = 6.0,
    ) -> None:
        super().__init__(name="fliprr-listener", daemon=True)
        self.source = source
        self.vad = vad
        self.segmenter = segmenter
        self.on_utterance = on_utterance
        self.playing = playing
        self.barge_in = barge_in
        self.on_error = on_error
        self.level_db = -120.0
        self.prob = 0.0
        self.finished = threading.Event()
        self._ring: deque[np.ndarray] = deque(maxlen=max(1, int(ring_s * 1000 / FRAME_MS)))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._mute_until = 0.0

    def run(self) -> None:
        try:
            for frame in self.source.frames():
                if self._stop_event.is_set():
                    break
                now = time.monotonic()
                with self._lock:
                    self._ring.append(frame)
                self.level_db = 20 * np.log10(float(np.sqrt(np.mean(frame * frame))) + 1e-6)
                if self.playing is not None and self.playing.is_set() and not self.barge_in:
                    # half-duplex: ignore our own voice and a short echo tail
                    self.segmenter.reset()
                    self._mute_until = now + 0.4
                    continue
                if now < self._mute_until:
                    continue
                self.prob = self.vad(frame)
                utterance = self.segmenter.push(frame, self.prob, now)
                if utterance is not None:
                    self.on_utterance(utterance)
            tail = self.segmenter.flush(time.monotonic())
            if tail is not None:
                self.on_utterance(tail)
        except BaseException as e:  # noqa: BLE001
            if self.on_error is not None:
                self.on_error(e)
            else:
                raise
        finally:
            self.finished.set()

    def recent_audio(self, seconds: float) -> np.ndarray:
        n = max(1, int(seconds * 1000 / FRAME_MS))
        with self._lock:
            frames = list(self._ring)[-n:]
        return np.concatenate(frames) if frames else np.zeros(0, np.float32)

    def stop(self) -> None:
        self._stop_event.set()
        self.source.close()
