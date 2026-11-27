from __future__ import annotations

from pathlib import Path

from fliprr.config import TTSConfig
from fliprr.tts.engines import EdgeTTS, PiperTTS, SystemTTS, make_engine
from fliprr.tts.speaker import Speaker

__all__ = ["EdgeTTS", "PiperTTS", "Speaker", "SystemTTS", "make_engines"]


def make_engines(cfg: TTSConfig, data_dir: Path, log=print) -> list:  # noqa: ANN001
    """Main engine first, then the fallback. Engines that can't load are skipped."""
    engines = []
    for name in dict.fromkeys([cfg.engine, cfg.fallback]):
        if not name or name == "none":
            continue
        try:
            engines.append(make_engine(name, cfg, data_dir))
        except Exception as e:  # noqa: BLE001
            log(f"TTS «{name}» unavailable: {e}")
    return engines
