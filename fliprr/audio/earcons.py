"""Short synthesized sounds that tell you what the assistant is doing."""

from __future__ import annotations

import numpy as np

RATE = 24000

# (frequency Hz, seconds); 0 Hz = pause
_PATTERNS: dict[str, list[tuple[float, float]]] = {
    "wake": [(660, 0.07), (880, 0.10)],  # "I'm listening"
    "accept": [(880, 0.07)],  # request taken
    "done": [(880, 0.06), (660, 0.09)],  # finished
    "question": [(740, 0.06), (0, 0.05), (740, 0.06)],  # waiting for yes / no
    "error": [(330, 0.09), (0, 0.04), (247, 0.16)],
    "sleep": [(660, 0.08), (440, 0.14)],
    "awake": [(440, 0.08), (660, 0.14)],
}


def earcon(name: str, volume: float = 0.25, rate: int = RATE) -> np.ndarray:
    parts = []
    for freq, dur in _PATTERNS[name]:
        n = int(rate * dur)
        if freq <= 0:
            parts.append(np.zeros(n, np.float32))
            continue
        t = np.arange(n) / rate
        tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
        fade = min(n // 2, int(rate * 0.008))
        env = np.ones(n)
        env[:fade] = np.linspace(0, 1, fade)
        env[n - fade:] = np.linspace(1, 0, fade)
        parts.append((tone * env * volume / 1.25).astype(np.float32))
    parts.append(np.zeros(int(rate * 0.03), np.float32))
    return np.concatenate(parts)


NAMES = tuple(_PATTERNS)
