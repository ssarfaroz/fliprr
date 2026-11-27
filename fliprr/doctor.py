"""`fliprr doctor`: check every piece and say what to fix."""

from __future__ import annotations

import sys
from pathlib import Path

from fliprr import claude_cli
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

    # Claude Code CLI and login
    cli = claude_cli.find_cli(cfg)
    if not cli:
        bad("Claude Code CLI not found", "pip install claude-agent-sdk (bundles it) or install Claude Code")
    else:
        try:
            ok(f"Claude Code {claude_cli.version(cli)} ({cli})")
        except Exception as e:  # noqa: BLE001
            bad(f"Claude Code CLI failed to run: {e}")
        status = claude_cli.auth_status(cli)
        if status is None:
            ui.warn("couldn't check the Claude login; the first request will tell")
        elif status.get("loggedIn"):
            ok(f"logged in to Claude ({status.get('authMethod', '?')})")
        else:
            bad("not logged in to Claude", "run: fliprr login")

    if problems:
        ui.warn(f"{problems} problem(s) found")
        return 1
    ok("all good — run `fliprr`")
    return 0
