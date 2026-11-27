"""Interruptible audio playback."""

from __future__ import annotations

import threading
import time

import numpy as np

from fliprr.audio.devices import AudioUnavailable, import_sounddevice, resolve_device
from fliprr.audio.resample import resample


class AudioPlayer:
    """Plays one clip at a time; ``stop()`` cuts it off within ~25 ms."""

    def __init__(self, device: str = "") -> None:
        self._sd = import_sounddevice()
        self.device = resolve_device(self._sd, device, "output")
        try:
            info = self._sd.query_devices(self.device, "output")
        except Exception as e:  # noqa: BLE001 — sounddevice.PortAudioError
            raise AudioUnavailable(f"no speakers found ({e}); see `fliprr devices`") from e
        self.name = info["name"]
        self.rate = int(info["default_samplerate"])
        self._channels = 1
        self._stop = threading.Event()
        self.playing = threading.Event()  # set while sound is coming out

    def play(self, audio: np.ndarray, rate: int) -> bool:
        """Blocking. Returns False if interrupted by ``stop()``."""
        if audio.size == 0:
            return True
        if rate != self.rate:
            audio = resample(audio, rate, self.rate)
        audio = np.ascontiguousarray(np.clip(audio, -1.0, 1.0), dtype=np.float32)
        self._stop.clear()
        self.playing.set()
        try:
            stream = self._open()
            with stream:
                block = 1024
                for i in range(0, len(audio), block):
                    if self._stop.is_set():
                        stream.abort()
                        return False
                    chunk = audio[i:i + block]
                    if self._channels == 2:
                        chunk = np.repeat(chunk[:, None], 2, axis=1)
                    stream.write(chunk)
            return not self._stop.is_set()
        finally:
            self.playing.clear()

    def _open(self):  # noqa: ANN202
        try:
            return self._sd.OutputStream(samplerate=self.rate, channels=self._channels, dtype="float32", device=self.device)
        except Exception:  # noqa: BLE001 — some devices refuse mono
            if self._channels == 2:
                raise
            self._channels = 2
            return self._sd.OutputStream(samplerate=self.rate, channels=2, dtype="float32", device=self.device)

    def stop(self) -> None:
        self._stop.set()


class NullPlayer:
    """No sound: records what would have been played (tests, `--no-sound`)."""

    def __init__(self, realtime: bool = False) -> None:
        self.realtime = realtime
        self.rate = 24000
        self.name = "none"
        self.clips: list[tuple[np.ndarray, int]] = []
        self._stop = threading.Event()
        self.playing = threading.Event()

    def play(self, audio: np.ndarray, rate: int) -> bool:
        self.clips.append((audio, rate))
        if not self.realtime:
            return True
        self._stop.clear()
        self.playing.set()
        try:
            end = time.monotonic() + len(audio) / rate
            while time.monotonic() < end:
                if self._stop.wait(0.02):
                    return False
            return True
        finally:
            self.playing.clear()

    def stop(self) -> None:
        self._stop.set()
