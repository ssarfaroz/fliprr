"""Local transcription with faster-whisper (CPU or NVIDIA GPU)."""

from __future__ import annotations

import time

import numpy as np

from fliprr.config import STTConfig
from fliprr.stt.base import Transcript, normalize_level, prompt_for


class WhisperTranscriber:
    name = "whisper"

    def __init__(self, cfg: STTConfig, log=print) -> None:  # noqa: ANN001
        from faster_whisper import WhisperModel

        self.cfg = cfg
        self.language = cfg.language or None
        self.prompt = prompt_for(cfg.language, cfg.initial_prompt)
        device, compute = self._resolve(cfg.device, cfg.compute_type)
        kwargs = {"cpu_threads": cfg.cpu_threads, "download_root": cfg.download_root or None}
        self.model = WhisperModel(cfg.model, device=device, compute_type=compute, **kwargs)
        self.device = device
        try:
            self._warm_up()
        except Exception as e:  # noqa: BLE001 — typically missing CUDA libraries
            if device == "cpu":
                raise
            log(f"GPU transcription failed ({e}); falling back to CPU")
            self.model = WhisperModel(cfg.model, device="cpu", compute_type="int8", **kwargs)
            self.device = "cpu"
            self._warm_up()

    @staticmethod
    def _resolve(device: str, compute_type: str) -> tuple[str, str]:
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:  # noqa: BLE001
                device = "cpu"
        if compute_type in ("auto", "default", ""):
            compute_type = "float16" if device == "cuda" else "int8"
        return device, compute_type

    def _warm_up(self) -> None:
        segments, _ = self.model.transcribe(np.zeros(16000, np.float32), language=self.language or "en", beam_size=1)
        list(segments)

    def transcribe(self, audio: np.ndarray, *, fast: bool = False) -> Transcript:
        started = time.perf_counter()
        segments, info = self.model.transcribe(
            normalize_level(audio),
            language=self.language,
            beam_size=1 if fast else self.cfg.beam_size,
            initial_prompt=self.prompt,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
            temperature=[0.0, 0.2, 0.4],
        )
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", "") or "",
            no_speech_prob=max((s.no_speech_prob for s in segments), default=0.0),
            avg_logprob=float(np.mean([s.avg_logprob for s in segments])) if segments else 0.0,
            seconds=time.perf_counter() - started,
        )
