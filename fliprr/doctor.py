"""`fliprr doctor`: check every piece and say what to fix."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from fliprr.config import Config
from fliprr.ui import Console


def run_doctor(cfg: Config, ui: Console, config_path: Path | None) -> int:
    problems = 0

    def ok(msg: str) -> None:
        ui.info(f"✔ {msg}")

    def bad(msg: str, fix: str = "") -> None:
        nonlocal problems
        problems += 1
        ui.error(msg + (f"\n    → {fix}" if fix else ""))

    ok(f"Python {sys.version.split()[0]}")
    ui.info(f"  config: {config_path or 'defaults (fliprr init creates a file)'}")
    ui.info(f"  data:   {cfg.data_path}")
    project = cfg.project_dir()
    if project.is_dir():
        ok(f"Claude Code folder: {project}")
    else:
        bad(f"Claude Code folder does not exist: {project}", "set [claude_code] cwd")

    # audio
    try:
        from fliprr.audio.devices import import_sounddevice

        sd = import_sounddevice()
        try:
            dev_in = sd.query_devices(kind="input")
            ok(f"microphone: {dev_in['name']}")
        except Exception as e:  # noqa: BLE001
            bad(f"no microphone found ({e})", "connect a microphone; see `fliprr devices`")
        try:
            dev_out = sd.query_devices(kind="output")
            ok(f"speakers: {dev_out['name']}")
        except Exception as e:  # noqa: BLE001
            bad(f"no speakers found ({e})")
    except Exception as e:  # noqa: BLE001
        bad(str(e))

    # VAD
    try:
        from fliprr.audio.vad import SileroVAD

        SileroVAD()
        ok("speech detector (Silero VAD)")
    except Exception as e:  # noqa: BLE001
        bad(f"Silero VAD unavailable: {e}", "pip install faster-whisper onnxruntime")

    # STT
    if cfg.stt.engine == "whisper":
        try:
            from faster_whisper.utils import download_model

            try:
                download_model(cfg.stt.model, local_files_only=True, cache_dir=cfg.stt.download_root or None)
                ok(f"speech recognition: faster-whisper «{cfg.stt.model}» (downloaded)")
            except Exception:  # noqa: BLE001
                ok(f"speech recognition: faster-whisper «{cfg.stt.model}» (downloads on first start)")
        except ImportError:
            bad("faster-whisper is not installed", "pip install faster-whisper")
    else:
        import os

        if os.environ.get(cfg.stt.api_key_env):
            ok(f"speech recognition via {cfg.stt.api_base}")
        else:
            bad(f"{cfg.stt.api_key_env} is not set", f"set the {cfg.stt.api_key_env} environment variable")

    # TTS
    from fliprr.tts import make_engines

    engines = make_engines(cfg.tts, cfg.data_path, lambda m: bad(m))
    if engines:
        ok("text-to-speech: " + ", ".join(e.name for e in engines))

    # Claude Code CLI
    cli = cfg.claude_code.cli_path or _bundled_cli() or shutil.which("claude")
    if not cli:
        bad("Claude Code CLI not found", "pip install claude-agent-sdk (bundles it) or install Claude Code")
    else:
        try:
            out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
            ok(f"Claude Code {out.stdout.strip() or out.stderr.strip()} ({cli})")
        except Exception as e:  # noqa: BLE001
            bad(f"Claude Code CLI failed to run: {e}")
        ui.info("  login: the first request tells you if Claude Code needs `claude` → /login")

    if problems:
        ui.warn(f"{problems} problem(s) found")
        return 1
    ok("all good — run `fliprr`")
    return 0


def _bundled_cli() -> str | None:
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    base = Path(claude_agent_sdk.__file__).parent / "_bundled"
    for name in ("claude.exe", "claude"):
        if (base / name).is_file():
            return str(base / name)
    return None
