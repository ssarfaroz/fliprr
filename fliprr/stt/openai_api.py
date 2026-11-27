"""Transcription through an OpenAI-compatible HTTP API.

Works with Groq (fast, free tier — default), OpenAI and local servers that
implement ``POST /audio/transcriptions``. Handy on slow computers.
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

from fliprr.config import STTConfig
from fliprr.stt.base import Transcript, normalize_level, prompt_for


class OpenAICompatibleTranscriber:
    name = "openai"

    def __init__(self, cfg: STTConfig) -> None:
        self.cfg = cfg
        self.url = cfg.api_base.rstrip("/") + "/audio/transcriptions"
        self.key = os.environ.get(cfg.api_key_env, "")
        if not self.key:
            raise RuntimeError(f"set the {cfg.api_key_env} environment variable to use stt.engine = \"openai\"")
        self.prompt = prompt_for(cfg.language, cfg.initial_prompt)

    def transcribe(self, audio: np.ndarray, *, fast: bool = False) -> Transcript:
        started = time.perf_counter()
        fields = {"model": self.cfg.api_model, "response_format": "json", "temperature": "0", "prompt": self.prompt}
        if self.cfg.language:
            fields["language"] = self.cfg.language
        body, content_type = _multipart(fields, "audio.wav", _wav_bytes(normalize_level(audio)))
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"transcription API error {e.code}: {detail}") from e
        return Transcript(text=(data.get("text") or "").strip(), seconds=time.perf_counter() - started)


def _wav_bytes(audio: np.ndarray, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _multipart(fields: dict[str, str], filename: str, payload: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(payload)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
