"""Microphone and speaker code against a fake sounddevice module."""

import threading
import time

import numpy as np
import pytest

from fliprr.audio import devices, player as player_mod, sources
from fliprr.audio.vad import FRAME


class FakeSD:
    def __init__(self, native_rate=48000, supports_16k=False):
        self.native_rate = native_rate
        self.supports_16k = supports_16k
        self.output_writes = []
        self.default = type("D", (), {"device": (0, 1)})()

    def query_devices(self, device=None, kind=None):
        devs = [
            {"name": "USB Mic Array", "max_input_channels": 2, "max_output_channels": 0,
             "default_samplerate": self.native_rate, "hostapi": 0},
            {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2,
             "default_samplerate": 44100, "hostapi": 0},
        ]
        if kind == "input":
            return devs[0 if device is None else device]
        if kind == "output":
            return devs[1 if device is None else device]
        return devs

    def query_hostapis(self):
        return [{"name": "FakeAPI"}]

    def check_input_settings(self, device=None, channels=1, samplerate=None, dtype=None):
        if samplerate == 16000 and not self.supports_16k:
            raise ValueError("Invalid sample rate")

    def InputStream(self, device, channels, samplerate, dtype, blocksize, callback):  # noqa: N802
        sd = self

        class Stream:
            def __init__(self):
                self.running = False

            def start(self):
                self.running = True
                t = np.arange(samplerate * 2) / samplerate
                signal = (0.3 * np.sin(2 * np.pi * 500 * t)).astype(np.float32)

                def run():
                    for i in range(0, len(signal) - blocksize + 1, blocksize):
                        if not self.running:
                            return
                        callback(signal[i:i + blocksize, None], blocksize, None, None)

                threading.Thread(target=run, daemon=True).start()

            def stop(self):
                self.running = False

            def close(self):
                pass

        sd.input_rate = samplerate
        return Stream()

    def OutputStream(self, samplerate, channels, dtype, device):  # noqa: N802
        sd = self

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, chunk):
                sd.output_writes.append(len(chunk))
                time.sleep(0.001)

            def abort(self):
                sd.aborted = True

        sd.output_rate = samplerate
        return Stream()


@pytest.fixture
def fake_sd(monkeypatch):
    sd = FakeSD()
    monkeypatch.setattr(sources, "import_sounddevice", lambda: sd)
    monkeypatch.setattr(player_mod, "import_sounddevice", lambda: sd)
    monkeypatch.setattr(devices, "import_sounddevice", lambda: sd)
    return sd


def test_microphone_resamples_to_16k_frames(fake_sd):
    mic = sources.MicrophoneSource("usb", gain=2.0)
    assert mic.rate == 48000 and fake_sd.input_rate == 48000
    frames = []
    for frame in mic.frames():
        frames.append(frame)
        if len(frames) == 40:  # ~1.3 s
            mic.close()
    audio = np.concatenate(frames)
    assert all(len(f) == FRAME for f in frames)
    assert 0.55 < np.max(np.abs(audio[2000:])) <= 0.61  # gain 2 × 0.3
    spectrum = np.abs(np.fft.rfft(audio[2000:18000]))
    assert abs(np.argmax(spectrum) * 16000 / 16000 - 500) < 3


def test_microphone_uses_16k_when_supported(fake_sd):
    fake_sd.supports_16k = True
    assert sources.MicrophoneSource().rate == 16000


def test_device_lookup(fake_sd):
    assert devices.resolve_device(fake_sd, "", "input") is None
    assert devices.resolve_device(fake_sd, "1", "output") == 1
    assert devices.resolve_device(fake_sd, "mic", "input") == 0
    with pytest.raises(devices.AudioUnavailable):
        devices.resolve_device(fake_sd, "webcam", "input")
    listed = devices.list_devices()
    assert listed[0]["default_input"] and listed[1]["default_output"]


def test_player_resamples_and_can_be_stopped(fake_sd):
    p = player_mod.AudioPlayer()
    assert p.play(np.zeros(24000, np.float32), 24000)
    assert fake_sd.output_rate == 44100
    assert sum(fake_sd.output_writes) == 44100
    fake_sd.output_writes.clear()
    threading.Timer(0.02, p.stop).start()
    assert p.play(np.zeros(24000 * 5, np.float32), 24000) is False
    assert sum(fake_sd.output_writes) < 44100 * 5
    assert not p.playing.is_set()
