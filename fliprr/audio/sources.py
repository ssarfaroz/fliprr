"""Audio inputs: the microphone, or audio files for testing without one.

Both yield 512-sample float32 frames at 16 kHz.
"""

from __future__ import annotations

import queue
import threading
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

from fliprr.audio.devices import AudioUnavailable, import_sounddevice, resolve_device
from fliprr.audio.resample import Resampler, resample
from fliprr.audio.vad import FRAME, SAMPLE_RATE


class MicrophoneSource:
    def __init__(self, device: str = "", gain: float = 1.0) -> None:
        sd = import_sounddevice()
        self.device = resolve_device(sd, device, "input")
        try:
            info = sd.query_devices(self.device, "input")
        except Exception as e:  # noqa: BLE001 — sounddevice.PortAudioError
            raise AudioUnavailable(f"no microphone found ({e}); see `fliprr devices`") from e
        self.name = info["name"]
        try:
            sd.check_input_settings(device=self.device, channels=1, samplerate=SAMPLE_RATE, dtype="float32")
            self.rate = SAMPLE_RATE
        except Exception:  # noqa: BLE001 — device can't do 16 kHz; resample ourselves
            self.rate = int(info["default_samplerate"])
        self.gain = gain
        self.overflows = 0
        self._resampler = Resampler(self.rate, SAMPLE_RATE)
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=1000)
        self._closed = threading.Event()
        self._stream = sd.InputStream(
            device=self.device,
            channels=1,
            samplerate=self.rate,
            dtype="float32",
            blocksize=int(self.rate * 0.032),
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            self.overflows += 1
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            self.overflows += 1

    def frames(self) -> Iterator[np.ndarray]:
        self._stream.start()
        pending = np.zeros(0, np.float32)
        try:
            while not self._closed.is_set():
                try:
                    chunk = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                chunk = self._resampler.process(chunk)
                if self.gain != 1.0:
                    chunk = np.clip(chunk * self.gain, -1.0, 1.0)
                pending = np.concatenate([pending, chunk])
                while len(pending) >= FRAME:
                    yield pending[:FRAME]
                    pending = pending[FRAME:]
        finally:
            self._stream.stop()
            self._stream.close()

    def close(self) -> None:
        self._closed.set()


def read_audio(path: str | Path) -> np.ndarray:
    """Read an audio file as 16 kHz mono float32 (WAV natively, others via PyAV)."""
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as wf:
            rate, width, channels = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
        if width == 2:
            data = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
        elif width == 4:
            data = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
        elif width == 1:
            data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise wave.Error(f"unsupported sample width {width}")
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return resample(data, rate, SAMPLE_RATE)
    except (wave.Error, EOFError):
        from faster_whisper.audio import decode_audio  # PyAV based, any format

        return decode_audio(str(path), sampling_rate=SAMPLE_RATE).astype(np.float32)


class FileSource:
    """Feeds audio files as if they were spoken into the microphone.

    ``ready`` (optional) is polled before each file after the first one, so a
    simulation can wait until the assistant is idle or asking a question.
    """

    def __init__(
        self,
        paths: list[str | Path],
        *,
        realtime: bool = False,
        gap_s: float = 1.5,
        ready: Callable[[], bool] | None = None,
        ready_timeout_s: float = 600.0,
    ) -> None:
        self.paths = [Path(p) for p in paths]
        self.realtime = realtime
        self.gap = np.zeros(int(gap_s * SAMPLE_RATE), np.float32)
        self.ready = ready
        self.ready_timeout_s = ready_timeout_s
        self._closed = threading.Event()
        self.name = "files"

    def frames(self) -> Iterator[np.ndarray]:
        silence = np.zeros(FRAME, np.float32)
        for n, path in enumerate(self.paths):
            if n and self.ready is not None:
                deadline = time.monotonic() + self.ready_timeout_s
                settle = 0
                while not self._closed.is_set() and time.monotonic() < deadline:
                    # require the condition to hold for ~0.5 s: a human reaction, and no races
                    settle = settle + 1 if self.ready() else 0
                    if settle >= 25:
                        break
                    yield silence
                    time.sleep(0.02)
            audio = np.concatenate([read_audio(path), self.gap])
            for i in range(0, len(audio) - FRAME + 1, FRAME):
                if self._closed.is_set():
                    return
                yield audio[i:i + FRAME]
                if self.realtime:
                    time.sleep(FRAME / SAMPLE_RATE)
        for _ in range(int(2.0 * SAMPLE_RATE / FRAME)):
            yield silence

    def close(self) -> None:
        self._closed.set()
