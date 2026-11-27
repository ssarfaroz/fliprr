"""Assemble the pieces: audio in → assistant → Claude → audio out."""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable
from typing import Any

from fliprr.agents.chats import ChatStore
from fliprr.agents.echo import EchoAgent
from fliprr.assistant import Assistant
from fliprr.audio.listener import Listener
from fliprr.audio.segmenter import Segmenter
from fliprr.audio.vad import EnergyVAD, make_vad
from fliprr.config import Config
from fliprr.i18n import t
from fliprr.stt import make_transcriber
from fliprr.tts import Speaker, make_engines
from fliprr.wake import CHAT, CODE


def build_agents(cfg: Config, assistant: Assistant, store: ChatStore, ui, kind: str = "claude"):  # noqa: ANN001, ANN201
    lang = cfg.language
    if kind == "echo":
        return (EchoAgent(CODE, t(lang, "label_code"), assistant, lang),
                EchoAgent(CHAT, t(lang, "label_chat"), assistant, lang))

    from fliprr.agents import ClaudeSession, SessionSpec, make_chat_options, make_code_options

    code = ClaudeSession(
        CODE, t(lang, "label_code"),
        SessionSpec(cwd=cfg.project_dir(), continue_conversation=cfg.claude_code.continue_last),
        make_code_options(cfg, ui.debug), assistant, lang=lang, ask_permissions=True, log=ui.warn,
    )
    chat_dir = cfg.data_path / "chat"
    chat_dir.mkdir(parents=True, exist_ok=True)
    resume = store.session_of(store.current) if cfg.chat.resume else None
    chat = ClaudeSession(
        CHAT, t(lang, "label_chat"), SessionSpec(cwd=chat_dir, resume=resume),
        make_chat_options(cfg, ui.debug), assistant, lang=lang, ask_permissions=False, log=ui.warn,
        on_session_id=lambda sid: store.remember(store.current, sid),
    )
    return code, chat


async def run_assistant(
    cfg: Config,
    ui,  # noqa: ANN001
    make_source: Callable[[Assistant], Any],
    *,
    player=None,  # noqa: ANN001
    agents: str = "claude",
    keyboard: bool = False,
    greet: bool = True,
    exit_when_done: bool = False,
    restart_source: bool = True,
) -> Assistant:
    data = cfg.data_path
    data.mkdir(parents=True, exist_ok=True)

    ui.state("Загружаю распознавание речи…" if cfg.language == "ru" else "Loading speech recognition…")
    transcriber = await asyncio.to_thread(make_transcriber, cfg.stt, ui.warn)
    vad = make_vad(cfg.audio.vad)
    if cfg.audio.vad == "silero" and isinstance(vad, EnergyVAD):
        ui.warn("Silero VAD unavailable, using the simple energy detector")
    if player is None:
        from fliprr.audio.player import AudioPlayer

        player = AudioPlayer(cfg.audio.output_device)
    engines = make_engines(cfg.tts, data, ui.warn)
    if not engines and cfg.tts.engine != "none":
        ui.warn("no text-to-speech engine works — answers will only be printed")
    speaker = Speaker(engines, player, earcons=cfg.audio.earcons, earcon_volume=cfg.audio.earcon_volume, log=ui.warn)
    store = ChatStore(data / "chats.json")
    assistant = Assistant(cfg, transcriber=transcriber, speaker=speaker, ui=ui, chat_store=store)
    assistant.attach_agents(*build_agents(cfg, assistant, store, ui, agents))
    assistant._loop = asyncio.get_running_loop()

    errors: list[BaseException] = []

    def new_listener() -> Listener:
        source = make_source(assistant)
        segmenter = Segmenter(
            threshold=cfg.audio.vad_threshold, min_speech_ms=cfg.audio.min_speech_ms,
            end_silence_ms=cfg.audio.end_silence_ms, max_utterance_s=cfg.audio.max_utterance_s,
            pre_roll_ms=cfg.audio.pre_roll_ms,
        )
        vad.reset()
        listener = Listener(source, vad, segmenter, assistant.post_utterance, playing=player.playing,
                            barge_in=cfg.audio.barge_in, on_error=errors.append)
        assistant.probe_audio = listener.recent_audio
        ui.state(f"🎤 {getattr(source, 'name', 'audio')}")
        return listener

    listener = new_listener()
    run_task = asyncio.create_task(assistant.run(greet=greet))
    listener.start()
    ui.state(f"Claude Code → {cfg.project_dir()}")
    tasks = [asyncio.create_task(_keyboard(assistant))] if keyboard else []

    try:
        while not run_task.done():
            await asyncio.wait({run_task}, timeout=0.5)
            if not listener.finished.is_set():
                continue
            if errors:
                ui.error(f"audio input stopped: {errors[-1]}")
            if exit_when_done:
                await _wait_idle(assistant)
                assistant.stop()
                break
            if not restart_source:
                assistant.stop()
                break
            errors.clear()
            await asyncio.sleep(3)
            try:
                listener = new_listener()
                listener.start()
            except Exception as e:  # noqa: BLE001 — microphone unplugged etc.
                ui.error(f"can't open the microphone: {e}")
        await run_task
    finally:
        listener.stop()
        for task in tasks:
            task.cancel()
        if not run_task.done():
            assistant.stop()
            await asyncio.gather(run_task, return_exceptions=True)
    return assistant


async def _wait_idle(assistant: Assistant, settle_s: float = 1.5) -> None:
    quiet_since = None
    loop = asyncio.get_running_loop()
    while True:
        if assistant.idle:
            quiet_since = quiet_since or loop.time()
            if loop.time() - quiet_since >= settle_s:
                return
        else:
            quiet_since = None
        await asyncio.sleep(0.1)


async def _keyboard(assistant: Assistant) -> None:
    """Typed lines are handled like speech (handy at the desk)."""
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[str | None] = asyncio.Queue()

    def read() -> None:  # a daemon thread: a pending readline() must not block exit
        for line in sys.stdin:
            loop.call_soon_threadsafe(lines.put_nowait, line)
        loop.call_soon_threadsafe(lines.put_nowait, None)

    threading.Thread(target=read, name="fliprr-keyboard", daemon=True).start()
    while (line := await lines.get()) is not None:
        if line.strip():
            await assistant.on_transcript(line.strip(), typed=True)
