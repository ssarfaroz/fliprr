"""Command line: `fliprr` starts the assistant; subcommands help set it up."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from fliprr import __version__
from fliprr.config import Config, ConfigError, app_dir, load_config
from fliprr.ui import Console


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fliprr",
        description="Голосовое управление Claude Code и Claude без кнопок. "
        "Скажи «Клод Код, …» или «Клод, …».",
    )
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug output")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--version", action="version", version=f"fliprr {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("run", help="start listening (default)")
    p.add_argument("--project", help="folder for Claude Code (overrides config)")
    p.add_argument("--keyboard", action="store_true", help="also accept typed requests")
    sub.add_parser("devices", help="list microphones and speakers")
    p = sub.add_parser("test-mic", help="check the microphone, levels and recognition")
    p.add_argument("--seconds", type=float, default=20.0)
    p = sub.add_parser("say", help="speak a phrase with the configured voice")
    p.add_argument("text", nargs="+")
    p = sub.add_parser("transcribe", help="recognize speech in audio files")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("simulate", help="run the whole assistant on audio files instead of the microphone")
    p.add_argument("files", nargs="+")
    p.add_argument("--agents", choices=["claude", "echo"], default="echo",
                   help="echo = don't call Claude, just repeat the request")
    p.add_argument("--sound", action="store_true", help="play speech through the speakers")
    p.add_argument("--project", help="folder for Claude Code")
    p = sub.add_parser("init", help="create a config file")
    p.add_argument("--path", help=f"where to write it (default: {app_dir() / 'config.toml'})")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    sub.add_parser("doctor", help="check that everything is installed and working")

    args = parser.parse_args(argv)
    ui = Console(color=False if args.no_color else None, verbose=args.verbose)
    command = args.command or "run"

    if command == "init":
        return cmd_init(args, ui)
    try:
        cfg, path, warnings = load_config(args.config)
    except ConfigError as e:
        ui.error(f"config: {e}")
        return 2
    for w in warnings:
        ui.warn(f"config: {w}")
    if getattr(args, "project", None):
        cfg.claude_code.cwd = str(Path(args.project).expanduser().resolve())
    ui.debug(f"config: {path or 'defaults'}")

    try:
        if command == "run":
            return cmd_run(args, cfg, ui, path)
        if command == "devices":
            return cmd_devices(ui)
        if command == "test-mic":
            return cmd_test_mic(args, cfg, ui)
        if command == "say":
            return cmd_say(args, cfg, ui)
        if command == "transcribe":
            return cmd_transcribe(args, cfg, ui)
        if command == "simulate":
            return cmd_simulate(args, cfg, ui)
        if command == "doctor":
            from fliprr.doctor import run_doctor

            return run_doctor(cfg, ui, path)
    except KeyboardInterrupt:
        ui.state("пока!" if cfg.language == "ru" else "bye!")
        return 0
    except Exception as e:  # noqa: BLE001
        from fliprr.audio.devices import AudioUnavailable

        if isinstance(e, AudioUnavailable):
            ui.error(str(e))
            return 1
        raise
    parser.error(f"unknown command {command}")
    return 2


def cmd_run(args: argparse.Namespace, cfg: Config, ui: Console, path: Path | None) -> int:
    from fliprr.app import run_assistant
    from fliprr.audio.sources import MicrophoneSource

    if path is None:
        ui.info("Настройки по умолчанию (создать файл настроек: fliprr init)" if cfg.language == "ru"
                else "Using default settings (create a config file with: fliprr init)")
    ui.info("Ctrl+C — выход" if cfg.language == "ru" else "Ctrl+C to quit")
    asyncio.run(run_assistant(
        cfg, ui, lambda _a: MicrophoneSource(cfg.audio.input_device, cfg.audio.input_gain),
        keyboard=args.keyboard,
    ))
    return 0


def cmd_simulate(args: argparse.Namespace, cfg: Config, ui: Console) -> int:
    from fliprr.app import run_assistant
    from fliprr.audio.player import NullPlayer
    from fliprr.audio.sources import FileSource

    player = None if args.sound else NullPlayer()

    def source(assistant):  # noqa: ANN001, ANN202
        return FileSource(args.files, ready=lambda: assistant.idle or assistant.waiting_for_answer)

    if not args.sound and cfg.tts.engine != "none":
        cfg.tts.engine, cfg.tts.fallback = "none", "none"
    asyncio.run(run_assistant(cfg, ui, source, player=player, agents=args.agents, greet=False,
                              exit_when_done=True, restart_source=False))
    return 0


def cmd_devices(ui: Console) -> int:
    from fliprr.audio.devices import list_devices

    for d in list_devices():
        marks = []
        if d["default_input"]:
            marks.append("default mic")
        if d["default_output"]:
            marks.append("default speakers")
        kinds = []
        if d["inputs"]:
            kinds.append(f"in:{d['inputs']}")
        if d["outputs"]:
            kinds.append(f"out:{d['outputs']}")
        mark = f"  ← {', '.join(marks)}" if marks else ""
        print(f"{d['index']:3d}  {d['name']}  [{d['hostapi']}, {' '.join(kinds)}, {d['rate']} Hz]{mark}")
    print("\nУкажи микрофон в настройках: [audio] input_device = \"номер или часть названия\"")
    return 0


def cmd_say(args: argparse.Namespace, cfg: Config, ui: Console) -> int:
    from fliprr.audio.player import AudioPlayer
    from fliprr.speakable import to_speakable
    from fliprr.tts import Speaker, make_engines

    async def go() -> None:
        engines = make_engines(cfg.tts, cfg.data_path, ui.warn)
        if not engines:
            ui.error("no TTS engine available")
            return
        speaker = Speaker(engines, AudioPlayer(cfg.audio.output_device), log=ui.warn)
        speaker.start()
        text = to_speakable(" ".join(args.text))
        started = time.perf_counter()
        await speaker.say_and_wait(text)
        ui.info(f"[{engines[0].name}] {text} ({time.perf_counter() - started:.1f} s)")
        await speaker.close()

    asyncio.run(go())
    return 0


def cmd_transcribe(args: argparse.Namespace, cfg: Config, ui: Console) -> int:
    from fliprr.audio.segmenter import Segmenter
    from fliprr.audio.sources import read_audio
    from fliprr.audio.vad import FRAME, make_vad
    from fliprr.stt import is_hallucination, make_transcriber
    from fliprr.wake import WakeMatcher

    transcriber = make_transcriber(cfg.stt, ui.warn)
    wake = WakeMatcher(cfg.wake.max_prefix_words, cfg.wake.default_target,
                       cfg.wake.extra_claude_words, cfg.wake.extra_code_words)
    for file in args.files:
        audio = read_audio(file)
        vad = make_vad(cfg.audio.vad)
        seg = Segmenter(threshold=cfg.audio.vad_threshold, end_silence_ms=cfg.audio.end_silence_ms)
        utterances = []
        for i in range(0, len(audio) - FRAME + 1, FRAME):
            u = seg.push(audio[i:i + FRAME], vad(audio[i:i + FRAME]), i / 16000)
            if u:
                utterances.append(u)
        if (u := seg.flush(len(audio) / 16000)) is not None:
            utterances.append(u)
        print(f"{file}: {len(utterances)} utterance(s)")
        for u in utterances:
            tr = transcriber.transcribe(u.audio)
            match = wake.match(tr.text)
            note = "noise" if is_hallucination(tr.text, getattr(transcriber, "prompt", "")) else (
                f"→ {match.target}: {match.command!r}" if match else "not addressed")
            print(f"  [{u.started:6.2f}s +{u.duration:4.1f}s, stt {tr.seconds:.2f}s] {tr.text}   {note}")
    return 0


def cmd_test_mic(args: argparse.Namespace, cfg: Config, ui: Console) -> int:
    import threading

    from fliprr.audio.listener import Listener
    from fliprr.audio.segmenter import Segmenter
    from fliprr.audio.sources import MicrophoneSource
    from fliprr.audio.vad import make_vad
    from fliprr.stt import make_transcriber
    from fliprr.wake import WakeMatcher

    ui.info("Загружаю распознавание…" if cfg.language == "ru" else "Loading recognition…")
    transcriber = make_transcriber(cfg.stt, ui.warn)
    wake = WakeMatcher(cfg.wake.max_prefix_words, cfg.wake.default_target,
                       cfg.wake.extra_claude_words, cfg.wake.extra_code_words)
    source = MicrophoneSource(cfg.audio.input_device, cfg.audio.input_gain)
    utterances: list = []
    lock = threading.Lock()

    def on_utt(u):  # noqa: ANN001, ANN202
        with lock:
            utterances.append(u)

    listener = Listener(source, make_vad(cfg.audio.vad), Segmenter(threshold=cfg.audio.vad_threshold), on_utt)
    ui.info(f"🎤 {source.name} ({source.rate} Hz). Говори, например: «Клод Код, покажи статус гита»." if cfg.language == "ru"
            else f"🎤 {source.name} ({source.rate} Hz). Say e.g. “Claude Code, show git status”.")
    listener.start()
    end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < end:
            level = listener.level_db
            bar = "█" * max(0, min(40, int((level + 60) / 1.5)))
            speech = "речь" if listener.prob >= cfg.audio.vad_threshold else "    "
            sys.stdout.write(f"\r{level:6.1f} dBFS |{bar:<40}| {speech} ")
            sys.stdout.flush()
            with lock:
                pending, utterances[:] = list(utterances), []
            for u in pending:
                tr = transcriber.transcribe(u.audio)
                match = wake.match(tr.text)
                note = f"→ {match.target}: {match.command}" if match else "(без «Клод»)"
                sys.stdout.write("\r" + " " * 70 + "\r")
                print(f"«{tr.text}»  {note}  [{u.duration:.1f}s, распознано за {tr.seconds:.2f}s]")
            time.sleep(0.05)
    finally:
        listener.stop()
        print()
    ui.info("Если полоска почти не двигается, когда говоришь издалека — подними громкость микрофона в системе "
            "или [audio] input_gain." if cfg.language == "ru" else
            "If the bar barely moves when you speak from afar, raise the mic level or [audio] input_gain.")
    return 0


def cmd_init(args: argparse.Namespace, ui: Console) -> int:
    from fliprr.config_template import TEMPLATE

    path = Path(args.path).expanduser() if args.path else app_dir() / "config.toml"
    if path.exists() and not args.force:
        ui.error(f"{path} already exists (use --force to overwrite)")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.replace("{cwd}", str(Path.cwd()).replace("\\", "/")), encoding="utf-8")
    ui.info(f"Создан файл настроек: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
