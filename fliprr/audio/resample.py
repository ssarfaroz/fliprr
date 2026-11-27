"""Streaming sample-rate conversion (numpy only).

Microphones usually run at 44.1/48 kHz; speech recognition wants 16 kHz.
A windowed-sinc low-pass followed by linear interpolation is plenty for speech.
"""

from __future__ import annotations

import numpy as np


class Resampler:
    def __init__(self, src_rate: int, dst_rate: int, taps: int = 63) -> None:
        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        self.step = self.src_rate / self.dst_rate
        self.passthrough = self.src_rate == self.dst_rate
        n = taps | 1
        fc = 0.45 * min(self.src_rate, self.dst_rate) / self.src_rate  # cycles/sample
        t = np.arange(n) - (n - 1) / 2
        h = 2 * fc * np.sinc(2 * fc * t) * np.blackman(n)
        self._h = (h / h.sum()).astype(np.float32)
        self._hist = np.zeros(n - 1, np.float32)
        self._buf = np.zeros(0, np.float32)  # filtered samples not consumed yet
        self._t = 0.0  # position of the next output sample within _buf

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        if self.passthrough:
            return x
        if x.size == 0:
            return x
        xx = np.concatenate([self._hist, x])
        self._hist = xx[-(len(self._h) - 1):]
        y = np.convolve(xx, self._h, mode="valid").astype(np.float32)
        buf = np.concatenate([self._buf, y])
        last = len(buf) - 1
        if last < 1 or self._t > last:
            self._buf = buf
            return np.zeros(0, np.float32)
        count = int(np.floor((last - self._t) / self.step)) + 1
        pos = self._t + np.arange(count) * self.step
        i0 = pos.astype(np.int64)
        frac = (pos - i0).astype(np.float32)
        i1 = np.minimum(i0 + 1, last)
        out = buf[i0] * (1.0 - frac) + buf[i1] * frac
        self._t += count * self.step
        drop = min(int(self._t), last)
        self._buf = buf[drop:]
        self._t -= drop
        return out.astype(np.float32)


def resample(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """One-shot resampling of a whole clip."""
    if src_rate == dst_rate:
        return np.asarray(x, dtype=np.float32).reshape(-1)
    r = Resampler(src_rate, dst_rate)
    # Pad so the filter delay does not cut off the tail.
    pad = np.zeros(len(r._h), np.float32)
    out = r.process(np.concatenate([np.asarray(x, np.float32).reshape(-1), pad]))
    # Compensate the FIR group delay ((taps-1)/2 input samples).
    delay = int(round((len(r._h) - 1) / 2 / r.step))
    expected = int(round(len(x) * dst_rate / src_rate))
    return out[delay:delay + expected]
