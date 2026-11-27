"""Text-to-speech engines. Each returns (float32 mono audio, sample rate).

* ``edge``   — Microsoft Edge neural voices via edge-tts: free, natural, needs internet.
* ``piper``  — Piper neural voices: fully offline, voices download on first use (~60 MB).
* ``system`` — the voice built into the OS (macOS `say`, Windows SAPI, Linux espeak-ng).
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from fliprr.config import TTSConfig


class TTSError(RuntimeError):
    pass


def decode_audio_bytes(data: bytes, rate: int = 24000) -> np.ndarray:
    """Decode MP3/OGG/WAV bytes to mono float32 with PyAV."""
    import av

    chunks: list[np.ndarray] = []
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        rate, width, channels = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise TTSError(f"unexpected WAV sample width {width}")
    audio = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


class EdgeTTS:
    name = "edge"

    def __init__(self, cfg: TTSConfig) -> None:
        import edge_tts  # noqa: F401 — fail early if missing

        self.cfg = cfg

    async def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        import edge_tts

        voice = self.cfg.voice if lang == "ru" else (self.cfg.voice_en or self.cfg.voice)
        communicate = edge_tts.Communicate(text, voice, rate=self.cfg.rate, volume=self.cfg.volume)
        mp3 = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                mp3 += chunk["data"]
        if not mp3:
            raise TTSError("edge-tts returned no audio")
        return decode_audio_bytes(bytes(mp3), 24000), 24000


class PiperTTS:
    name = "piper"

    def __init__(self, cfg: TTSConfig, data_dir: Path) -> None:
        from piper import PiperVoice  # noqa: F401 — fail early if missing

        self.cfg = cfg
        self.dir = data_dir / "piper"
        self._voices: dict[str, object] = {}

    def _voice(self, name: str):  # noqa: ANN202
        if name not in self._voices:
            from piper import PiperVoice

            path = self.dir / f"{name}.onnx"
            if not path.is_file():
                from piper.download_voices import download_voice

                self.dir.mkdir(parents=True, exist_ok=True)
                download_voice(name, self.dir)
            self._voices[name] = PiperVoice.load(str(path))
        return self._voices[name]

    def _synth(self, text: str, name: str) -> tuple[np.ndarray, int]:
        from piper import SynthesisConfig

        voice = self._voice(name)
        rate = 1.0
        if self.cfg.rate.endswith("%"):
            try:
                rate = 1.0 + float(self.cfg.rate[:-1]) / 100
            except ValueError:
                pass
        chunks = list(voice.synthesize(text, SynthesisConfig(length_scale=1.0 / max(0.5, rate))))
        if not chunks:
            raise TTSError("piper returned no audio")
        audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        return audio, chunks[0].sample_rate

    async def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        name = self.cfg.piper_voice if lang == "ru" else (self.cfg.piper_voice_en or self.cfg.piper_voice)
        return await asyncio.to_thread(self._synth, text, name)


_WINDOWS_SCRIPT = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:FLIPRR_VOICE) { try { $s.SelectVoice($env:FLIPRR_VOICE) } catch {} }
elseif ($env:FLIPRR_CULTURE) {
  try { $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]$env:FLIPRR_CULTURE) } catch {}
}
$s.SetOutputToWaveFile($env:FLIPRR_OUT)
$s.Speak([Console]::In.ReadToEnd())
$s.Dispose()
"""


class SystemTTS:
    name = "system"

    def __init__(self, cfg: TTSConfig) -> None:
        self.cfg = cfg
        if sys.platform == "darwin":
            self.kind = "say"
        elif sys.platform == "win32":
            self.kind = "powershell"
        else:
            self.kind = shutil.which("espeak-ng") or shutil.which("espeak") or ""
            if not self.kind:
                raise TTSError("no system voice: install espeak-ng (sudo apt install espeak-ng)")

    async def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        fd, out = tempfile.mkstemp(suffix=".wav", prefix="fliprr-")
        os.close(fd)
        try:
            env = dict(os.environ)
            if self.kind == "say":
                voice = self.cfg.system_voice or ("Milena" if lang == "ru" else "")
                attempts = [self._say_cmd(out, voice)]
                if voice and not self.cfg.system_voice:
                    attempts.append(self._say_cmd(out, ""))  # Russian voice not installed
            elif self.kind == "powershell":
                attempts = [["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_SCRIPT]]
                env.update(FLIPRR_OUT=out, FLIPRR_VOICE=self.cfg.system_voice,
                           FLIPRR_CULTURE="ru-RU" if lang == "ru" else "en-US")
            else:
                attempts = [[self.kind, "-v", "ru" if lang == "ru" else "en", "-w", out, "--stdin"]]
            error = b""
            for cmd in attempts:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE, env=env,
                )
                _, error = await asyncio.wait_for(proc.communicate(text.encode("utf-8")), timeout=60)
                if proc.returncode == 0 and os.path.getsize(out):
                    return read_wav(out)
            raise TTSError(f"system TTS failed: {error.decode(errors='replace')[:200]}")
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass

    @staticmethod
    def _say_cmd(out: str, voice: str) -> list[str]:
        cmd = ["say", "--file-format=WAVE", "--data-format=LEI16@22050", "-o", out, "-f", "-"]
        return cmd[:1] + ["-v", voice] + cmd[1:] if voice else cmd


def make_engine(name: str, cfg: TTSConfig, data_dir: Path):  # noqa: ANN201
    if name == "edge":
        return EdgeTTS(cfg)
    if name == "piper":
        return PiperTTS(cfg, data_dir)
    if name == "system":
        return SystemTTS(cfg)
    raise ValueError(f"unknown TTS engine {name!r} (edge, piper, system, none)")
