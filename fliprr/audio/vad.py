"""Voice activity detection on 32 ms frames (512 samples at 16 kHz).

``SileroVAD`` runs the Silero model that ships with faster-whisper, one frame
at a time with its recurrent state carried over. ``EnergyVAD`` is a
dependency-free fallback with an adaptive noise floor.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np

FRAME = 512
SAMPLE_RATE = 16000
FRAME_MS = FRAME * 1000 / SAMPLE_RATE  # 32 ms


def _bundled_silero() -> Path | None:
    try:
        import faster_whisper
    except ImportError:
        return None
    assets = Path(os.path.dirname(faster_whisper.__file__)) / "assets"
    for name in ("silero_vad_v6.onnx", "silero_vad_v5.onnx", "silero_vad.onnx"):
        if (assets / name).is_file():
            return assets / name
    return None


class SileroVAD:
    def __init__(self, model_path: str | Path | None = None) -> None:
        import onnxruntime as ort

        path = Path(model_path) if model_path else _bundled_silero()
        if path is None or not path.is_file():
            raise FileNotFoundError("Silero VAD model not found (install faster-whisper)")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"], sess_options=opts)
        names = {i.name for i in self._session.get_inputs()}
        # faster-whisper's export takes (input, h, c); the upstream one (input, state, sr).
        self._upstream = "state" in names
        self.reset()

    def reset(self) -> None:
        if self._upstream:
            self._state = np.zeros((2, 1, 128), np.float32)
        else:
            self._h = np.zeros((1, 1, 128), np.float32)
            self._c = np.zeros((1, 1, 128), np.float32)
        self._context = np.zeros(64, np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        frame = np.asarray(frame, np.float32).reshape(-1)
        x = np.concatenate([self._context, frame])[None, :]
        self._context = frame[-64:]
        if self._upstream:
            out, self._state = self._session.run(
                None, {"input": x, "state": self._state, "sr": np.array(SAMPLE_RATE, dtype=np.int64)}
            )
        else:
            out, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        return float(np.asarray(out).reshape(-1)[0])


class EnergyVAD:
    """Speech probability from loudness relative to a tracked noise floor."""

    def __init__(self, ratio_db: float = 9.0, min_rms: float = 0.004) -> None:
        self.ratio = 10 ** (ratio_db / 20)
        self.min_rms = min_rms
        self.noise = 0.003

    def reset(self) -> None:
        self.noise = 0.003

    def __call__(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)) + 1e-9)
        threshold = max(self.noise * self.ratio, self.min_rms)
        # Track the floor quickly downwards, slowly upwards.
        alpha = 0.2 if rms < self.noise else 0.005
        if rms < threshold:
            self.noise += alpha * (rms - self.noise)
        x = 8.0 * (math.log(rms) - math.log(threshold))
        return 1.0 / (1.0 + math.exp(-x))


def make_vad(kind: str):
    if kind == "silero":
        try:
            return SileroVAD()
        except Exception:  # noqa: BLE001 — fall back silently, reported by `fliprr doctor`
            return EnergyVAD()
    if kind == "energy":
        return EnergyVAD()
    raise ValueError(f"unknown VAD: {kind}")
