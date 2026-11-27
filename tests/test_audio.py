import numpy as np
import pytest

from fliprr.audio.earcons import NAMES, earcon
from fliprr.audio.resample import Resampler, resample
from fliprr.audio.segmenter import Segmenter
from fliprr.audio.vad import FRAME, EnergyVAD, SileroVAD


def tone(freq, seconds, rate, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.mark.parametrize("src", [48000, 44100, 22050, 16000])
def test_streaming_resampler_keeps_frequency_and_length(src):
    x = tone(1000, 2.0, src)
    r = Resampler(src, 16000)
    rng = np.random.default_rng(0)
    out, i = [], 0
    while i < len(x):
        n = int(rng.integers(50, 4000))
        out.append(r.process(x[i:i + n]))
        i += n
    y = np.concatenate(out)
    assert abs(len(y) - 32000) <= 2
    seg = y[4000:20000]
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    assert abs(np.argmax(spectrum) * 16000 / len(seg) - 1000) < 2
    assert 0.45 < np.max(np.abs(seg)) < 0.52


def test_resampler_removes_frequencies_above_nyquist():
    y = Resampler(48000, 16000).process(tone(10000, 1.0, 48000))
    assert np.max(np.abs(y[200:])) < 0.01


def test_one_shot_resample_length():
    assert len(resample(tone(440, 1.0, 24000), 24000, 48000)) == 48000
    assert len(resample(tone(440, 1.0, 22050), 22050, 16000)) == 16000


def feed(segmenter, probs, now0=0.0):
    out = []
    for i, p in enumerate(probs):
        u = segmenter.push(np.full(FRAME, 0.1, np.float32), p, now0 + i * 0.032)
        if u is not None:
            out.append(u)
    return out


def test_segmenter_basic_utterance():
    seg = Segmenter(min_speech_ms=200, end_silence_ms=320, pre_roll_ms=96)
    probs = [0.0] * 10 + [0.9] * 20 + [0.0] * 15
    (u,) = feed(seg, probs)
    # pre-roll (3 frames incl. the 2 start frames) + speech + kept silence tail
    assert 20 * FRAME <= len(u.audio) <= (20 + 3 + 10) * FRAME
    assert u.speech_ms == pytest.approx(20 * 32, abs=1)


def test_segmenter_ignores_blips_and_bridges_short_pauses():
    seg = Segmenter(min_speech_ms=300, end_silence_ms=500)
    assert feed(seg, [0.0] * 5 + [0.9] * 3 + [0.0] * 30) == []  # 96 ms blip
    probs = [0.9] * 15 + [0.0] * 8 + [0.9] * 15 + [0.0] * 20  # 256 ms pause inside
    assert len(feed(seg, probs)) == 1


def test_segmenter_hysteresis_and_max_length():
    seg = Segmenter(threshold=0.5, end_silence_ms=320, max_utterance_s=1.0)
    # 0.4 is above neg threshold (0.35): still speech, never ends by silence
    utts = feed(seg, [0.9] * 12 + [0.4] * 40)
    assert len(utts) == 1 and len(utts[0].audio) == pytest.approx(1.0 * 16000, abs=FRAME * 3)


def test_segmenter_flush():
    seg = Segmenter(min_speech_ms=100)
    feed(seg, [0.9] * 10)
    assert seg.in_speech
    assert seg.flush(1.0) is not None
    assert not seg.in_speech


def test_energy_vad_tracks_noise_floor():
    vad = EnergyVAD()
    rng = np.random.default_rng(0)
    noise = [rng.standard_normal(FRAME).astype(np.float32) * 0.003 for _ in range(60)]
    assert max(vad(f) for f in noise[30:]) < 0.5
    speech = tone(300, FRAME / 16000, 16000, amp=0.2)
    assert vad(speech) > 0.9


def test_silero_vad_streaming():
    vad = SileroVAD()
    silence = np.zeros(FRAME, np.float32)
    assert vad(silence) < 0.2
    vad.reset()
    assert 0.0 <= vad(tone(200, FRAME / 16000, 16000)) <= 1.0


def test_earcons():
    for name in NAMES:
        clip = earcon(name, volume=0.3)
        assert clip.dtype == np.float32 and 0.05 < len(clip) / 24000 < 0.5
        assert np.max(np.abs(clip)) <= 0.3 + 1e-6
