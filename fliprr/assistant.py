"""The conversation logic: who is being addressed, what to say, when to listen.

Flow: utterance → transcript → wake phrase? → local command or Claude request
→ streamed answer → speech → short follow-up window without the wake phrase.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from fliprr import intents as it
from fliprr.agents.chats import ChatStore
from fliprr.agents.session import TurnResult
from fliprr.audio.segmenter import Utterance
from fliprr.config import Config
from fliprr.i18n import t
from fliprr.speakable import SpeechChunker
from fliprr.stt.base import is_hallucination
from fliprr.text import shorten, words
from fliprr.wake import CHAT, CODE, WakeMatcher


@dataclass
class _Confirm:
    agent: Any
    future: asyncio.Future
    question: str
    hinted: bool = False


@dataclass
class _Turn:
    chunker: SpeechChunker
    budget: int
    spoken: list[str] = field(default_factory=list)
    raw: str = ""
    truncated: bool = False
    muted: bool = False


class Assistant:
    def __init__(
        self,
        cfg: Config,
        *,
        transcriber,  # noqa: ANN001 — Transcriber
        speaker,  # noqa: ANN001 — Speaker
        ui,  # noqa: ANN001 — Console
        chat_store: ChatStore | None = None,
        probe_audio: Callable[[float], np.ndarray] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.lang = cfg.language
        self.transcriber = transcriber
        self.speaker = speaker
        self.ui = ui
        self.chat_store = chat_store
        self.probe_audio = probe_audio
        self.clock = clock
        self.wake = WakeMatcher(
            max_prefix_words=cfg.wake.max_prefix_words,
            default_target=cfg.wake.default_target,
            extra_claude_words=cfg.wake.extra_claude_words,
            extra_code_words=cfg.wake.extra_code_words,
        )
        self.prompt = getattr(transcriber, "prompt", "")
        self.agents: dict[str, Any] = {}
        self.projects: dict[str, Path] = cfg.projects()
        self.current_project = self._project_name(cfg.project_dir())
        self.paused = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._utterances: asyncio.Queue[Utterance] = asyncio.Queue(maxsize=16)
        self._listening_for: tuple[str, float] | None = None
        self._followup: tuple[str, float] | None = None
        self._confirm: _Confirm | None = None
        self._confirm_lock = asyncio.Lock()
        self._turns: dict[str, _Turn] = {}
        self._last_answer: list[str] = []
        self._last_probe = 0.0
        self._transcribing = False
        self._stopping = asyncio.Event()
        self._background: set[asyncio.Task] = set()

    # -- wiring --------------------------------------------------------------------------

    def attach_agents(self, code, chat) -> None:  # noqa: ANN001
        self.agents = {CODE: code, CHAT: chat}

    def label(self, target: str) -> str:
        return t(self.lang, "label_code" if target == CODE else "label_chat")

    def post_utterance(self, utterance: Utterance) -> None:
        """Thread-safe: called by the listener thread."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._enqueue_utterance, utterance)

    def _enqueue_utterance(self, utterance: Utterance) -> None:
        if self._utterances.full():
            self._utterances.get_nowait()  # we're behind: drop the oldest
        self._utterances.put_nowait(utterance)

    @property
    def idle(self) -> bool:
        """Nothing running, nothing queued, nothing being said (used by simulations)."""
        return (
            self._utterances.empty()
            and not self._transcribing
            and not self.speaker.speaking
            and not any(a.busy or a.queued for a in self.agents.values())
        )

    @property
    def waiting_for_answer(self) -> bool:
        return (
            self._confirm is not None
            and not self._transcribing
            and not self.speaker.speaking
            and self._utterances.empty()
        )

    # -- main loop -------------------------------------------------------------------------

    async def run(self, *, greet: bool = True) -> None:
        self._loop = asyncio.get_running_loop()
        self.speaker.start()
        for agent in self.agents.values():
            agent.start()
            agent.warm_up()
        if greet:
            self.speaker.say(t(self.lang, "ready"))
        try:
            await self._stt_loop()
        finally:
            for agent in self.agents.values():
                await agent.close()
            await self.speaker.close()

    def stop(self) -> None:
        self._stopping.set()

    async def _stt_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                utterance = await asyncio.wait_for(self._utterances.get(), timeout=0.5)
            except asyncio.TimeoutError:
                await self._maybe_probe()
                continue
            self._transcribing = True
            try:
                transcript = await asyncio.to_thread(self.transcriber.transcribe, utterance.audio)
                self.ui.debug(f"stt {transcript.seconds:.2f}s for {utterance.duration:.1f}s audio")
                await self.on_transcript(transcript.text, started=utterance.started)
            except Exception as e:  # noqa: BLE001
                self.ui.error(f"speech recognition failed: {e}")
            finally:
                self._transcribing = False

    async def _maybe_probe(self) -> None:
        """While speaking, peek at the last seconds of audio for «Клод, стоп»."""
        if not (self.cfg.audio.barge_in and self.probe_audio and self.speaker.speaking):
            return
        now = self.clock()
        if now - self._last_probe < 2.0:
            return
        self._last_probe = now
        audio = self.probe_audio(3.5)
        if audio.size < 8000:
            return
        try:
            transcript = await asyncio.to_thread(self.transcriber.transcribe, audio, fast=True)
        except Exception:  # noqa: BLE001
            return
        kind = it.find_barge_in(transcript.text, self.wake.claude_kind)
        if kind and self.speaker.speaking:
            self.ui.heard(transcript.text, "barge-in")
            await self._stop(self._barge_target(transcript.text), mute_only=kind == it.MUTE, announce=False)

    def _barge_target(self, text: str) -> str:
        return CODE if any(self.wake.is_code_word(w) for w in words(text)) else CHAT

    # -- transcripts -----------------------------------------------------------------------

    async def on_transcript(self, text: str, *, typed: bool = False, started: float | None = None) -> None:
        """Handle one recognized utterance; ``started`` is when the speech began."""
        text = text.strip()
        if not text:
            return
        now = self.clock()
        wake = self.wake.match(text)
        if not typed:
            if is_hallucination(text, self.prompt):
                self.ui.debug(f"ignored (noise): {text}")
                return
            if self.speaker.overlapped(started):
                # The microphone also hears us. While we talk, only an explicit
                # «Клод…» at the start of a phrase, or «…Клод, стоп…», counts.
                ratio = self.speaker.echo_ratio(text)
                kind = it.find_barge_in(text, self.wake.claude_kind)
                if kind and ratio < 0.9:
                    await self._stop(self._barge_target(text), mute_only=kind == it.MUTE, announce=False)
                    return
                if wake is None or wake.index > 0 or ratio >= 0.4:
                    self.ui.debug(f"ignored (while speaking): {text}")
                    return

        if self.paused:
            if wake and (intent := it.parse_intent(wake.command, wake.target)) and intent.kind == it.RESUME:
                await self.handle_intent(wake.target, intent)
            else:
                self.ui.heard(text, "пауза" if self.lang == "ru" else "paused")
            return

        if self._confirm is not None:
            await self._on_confirm_transcript(text, wake)
            return

        if wake is not None:
            self.ui.heard(text)
            if wake.wake_only:
                self.speaker.stop()
                self._listening_for = (wake.target, now + self.cfg.wake.listen_timeout_s)
                self._followup = None
                self.speaker.earcon("wake")
                self.ui.state(("👂 слушаю → " if self.lang == "ru" else "👂 listening → ") + self.label(wake.target))
                return
            await self.dispatch(wake.target, wake.command)
            return

        if self._listening_for is not None and now < self._listening_for[1]:
            target = self._listening_for[0]
            self.ui.heard(text)
            await self.dispatch(target, text)
            return

        if self._followup is not None and now < self._followup[1] and not self.speaker.speaking:
            target = self._followup[0]
            agent = self.agents.get(target)
            if agent is not None and not agent.busy:
                self.ui.heard(text, "продолжение" if self.lang == "ru" else "follow-up")
                await self.dispatch(target, text)
                return

        if typed:
            await self.dispatch(self.cfg.wake.default_target, text)
            return
        self.ui.heard(text, "не мне" if self.lang == "ru" else "not addressed")

    async def _on_confirm_transcript(self, text: str, wake) -> None:  # noqa: ANN001
        confirm = self._confirm
        assert confirm is not None
        candidate = wake.command if wake is not None else text
        intent = it.parse_intent(candidate, wake.target) if wake is not None else None
        if intent is not None and intent.kind == it.STOP:
            self._resolve_confirm(it.NO)
            await self.handle_intent(wake.target, intent)
            return
        answer = it.parse_yes_no(candidate)
        if answer is not None:
            self.ui.heard(text)
            self._resolve_confirm(answer)
            return
        if wake is not None and not wake.wake_only:
            await self.dispatch(wake.target, wake.command)  # a new request; the question stays open
            return
        self.ui.heard(text, "?")
        if not confirm.hinted:
            confirm.hinted = True
            self.speaker.say(t(self.lang, "confirm_hint"))

    def _resolve_confirm(self, answer: str) -> None:
        if self._confirm is not None and not self._confirm.future.done():
            self._confirm.future.set_result(answer)

    # -- requests and commands --------------------------------------------------------------

    async def dispatch(self, target: str, command: str) -> None:
        """A request the user just made (voice or keyboard)."""
        self._listening_for = None
        self._followup = None
        if self.speaker.speaking:
            self.speaker.stop()  # the user is talking to us — stop talking
            if target in self._turns:
                self._turns[target].muted = True  # they've moved on from that answer
        intent = it.parse_intent(command, target, project_names=list(self.projects))
        if intent is not None:
            await self.handle_intent(target, intent)
            return
        await self.submit(target, command)

    async def submit(self, target: str, command: str) -> None:
        agent = self.agents[target]
        self.ui.command(self.label(target), command)
        self.speaker.earcon("accept")
        if agent.busy or agent.queued:
            self.speaker.say(t(self.lang, "queued"))
        agent.submit(command)

    async def handle_intent(self, target: str, intent: it.Intent) -> None:
        lang = self.lang
        say = self.speaker.say
        code, chat = self.agents.get(CODE), self.agents.get(CHAT)
        self.ui.state(f"⌘ {intent.kind}{': ' + intent.arg if intent.arg else ''}")
        kind = intent.kind
        if kind in (it.STOP, it.MUTE):
            await self._stop(target, mute_only=kind == it.MUTE, announce=kind == it.STOP)
            if intent.rest:
                await self.submit(target, intent.rest)
        elif kind == it.NEW_SESSION:
            if target == CODE:
                await self._abandon(code)
                code.restart(resume=None, continue_conversation=False)
                say(t(lang, "new_session"))
            else:
                if self.chat_store is not None:
                    self.chat_store.reset_current()
                await self._abandon(chat)
                chat.restart(resume=None)
                say(t(lang, "new_chat"))
            if intent.rest:
                await self.submit(target, intent.rest)
        elif kind == it.CONTINUE_LAST:
            await self._abandon(code)
            code.restart(resume=None, continue_conversation=True)
            say(t(lang, "continue_last"))
        elif kind == it.REPEAT:
            if self._last_answer:
                for sentence in self._last_answer:
                    say(sentence)
            else:
                say(t(lang, "nothing_to_repeat"))
        elif kind == it.SWITCH_PROJECT:
            path = self.projects[intent.arg]
            await self._abandon(code)
            code.restart(cwd=path, resume=None, continue_conversation=self.cfg.claude_code.continue_last)
            self.current_project = intent.arg
            say(t(lang, "project_switched", name=intent.arg))
        elif kind == it.LIST_PROJECTS:
            if self.projects:
                say(t(lang, "projects_list", names=", ".join(self.projects), current=self.current_project))
            else:
                say(t(lang, "no_projects", cwd=self.current_project))
        elif kind == it.OPEN_CHAT:
            await self._open_chat(intent)
        elif kind == it.LIST_CHATS:
            names = self.chat_store.names() if self.chat_store else []
            if len(names) > 1:
                say(t(lang, "chats_list", names=", ".join(names), current=self.chat_store.current))
            else:
                say(t(lang, "no_chats"))
        elif kind == it.PAUSE:
            self.speaker.stop()
            self.paused = True
            self._followup = self._listening_for = None
            say(t(lang, "paused"))
            self.speaker.earcon("sleep")
        elif kind == it.RESUME:
            self.paused = False
            self.speaker.earcon("awake")
            say(t(lang, "resumed"))
        elif kind == it.STATUS:
            busy = [a for a in self.agents.values() if a.busy]
            if busy:
                for agent in busy:
                    say(t(lang, "status_busy", task=shorten(agent.current_prompt, 80)))
                    if agent.queued:
                        say(t(lang, "status_queue", count=agent.queued))
            else:
                say(t(lang, "status_idle", project=self.current_project))
        elif kind == it.HELP:
            say(t(lang, "help"))
        elif kind == it.ACCEPT_EDITS:
            await code.set_permission_mode("acceptEdits")
            say(t(lang, "accept_edits_on"))
        elif kind == it.ASK_PERMISSIONS:
            mode = self.cfg.claude_code.permission_mode
            await code.set_permission_mode("default" if mode in ("acceptEdits", "bypassPermissions") else mode)
            say(t(lang, "accept_edits_off"))

    async def _stop(self, target: str, *, mute_only: bool, announce: bool) -> None:
        self.speaker.stop()
        for turn in self._turns.values():
            turn.muted = True
        if mute_only:
            return
        agent = self.agents.get(target)
        # «Клод, стоп» while only Claude Code is working stops Claude Code too.
        busy = [agent] if agent is not None and agent.busy else [a for a in self.agents.values() if a.busy]
        if self._confirm is not None:
            self._resolve_confirm(it.NO)
        stopped = False
        for a in busy:
            a.clear_queue()
            stopped = await a.interrupt() or stopped
        if stopped and announce:
            self.speaker.say(t(self.lang, "stopped"))

    async def _abandon(self, agent) -> None:  # noqa: ANN001
        """Drop what the agent is doing before switching its session or folder."""
        if self._confirm is not None and self._confirm.agent is agent:
            self._resolve_confirm(it.NO)
        agent.clear_queue()
        await agent.interrupt()

    async def _open_chat(self, intent: it.Intent) -> None:
        chat = self.agents[CHAT]
        await self._abandon(chat)
        store = self.chat_store
        name = intent.arg
        if store is not None:
            name = it.match_name(name, store.names()) or name
            existed = store.switch(name)
            chat.restart(resume=store.session_of(name))
        else:
            existed = False
            chat.restart(resume=None)
        self.speaker.say(t(self.lang, "chat_opened" if existed else "chat_created", name=name))
        if intent.rest:
            await self.submit(CHAT, intent.rest)

    def _project_name(self, path: Path) -> str:
        for name, p in self.projects.items():
            if p == path:
                return name
        return path.name or str(path)

    # -- AgentSink: events from Claude ------------------------------------------------------

    def _speak_mode(self, target: str) -> str:
        return self.cfg.claude_code.speak if target == CODE else "all"

    def on_turn_start(self, agent, prompt: str) -> None:  # noqa: ANN001
        budget = self.cfg.claude_code.max_speech_chars if agent.target == CODE else self.cfg.chat.max_speech_chars
        self._turns[agent.target] = _Turn(chunker=SpeechChunker(self.lang), budget=budget)

    def on_text(self, agent, delta: str) -> None:  # noqa: ANN001
        turn = self._turns.get(agent.target)
        if turn is None:
            return
        turn.raw += delta
        while "\n" in turn.raw:
            line, turn.raw = turn.raw.split("\n", 1)
            if line.strip():
                self.ui.agent(agent.label, line)
        if self._speak_mode(agent.target) == "all":
            for sentence in turn.chunker.feed(delta):
                self._speak(turn, sentence)

    def on_text_end(self, agent) -> None:  # noqa: ANN001
        turn = self._turns.get(agent.target)
        if turn is None:
            return
        if turn.raw.strip():
            self.ui.agent(agent.label, turn.raw.strip())
        turn.raw = ""
        if self._speak_mode(agent.target) == "all":
            for sentence in turn.chunker.flush():
                self._speak(turn, sentence)

    def on_tool(self, agent, name: str, data: dict[str, Any]) -> None:  # noqa: ANN001
        detail = str(data.get("command") or data.get("file_path") or data.get("pattern")
                     or data.get("url") or data.get("query") or data.get("description") or "")
        self.ui.tool(agent.label, name, shorten(detail, 140))
        if not self.cfg.claude_code.announce_tools or agent.target != CODE:
            return
        turn = self._turns.get(agent.target)
        if turn is None:
            return
        base = Path(str(data.get("file_path", ""))).name
        phrase = {
            "Bash": t(self.lang, "tool_bash"),
            "Edit": t(self.lang, "tool_edit", file=base),
            "MultiEdit": t(self.lang, "tool_edit", file=base),
            "Write": t(self.lang, "tool_write", file=base),
            "WebSearch": t(self.lang, "tool_search"),
            "Task": t(self.lang, "tool_agent"),
            "Agent": t(self.lang, "tool_agent"),
        }.get(name)
        if phrase:
            self._speak(turn, phrase)

    def on_result(self, agent, result: TurnResult) -> None:  # noqa: ANN001
        turn = self._turns.pop(agent.target, None)
        if turn is not None and turn.raw.strip():
            self.ui.agent(agent.label, turn.raw.strip())
        self.ui.result(agent.label, result.seconds, result.cost)
        if result.interrupted:
            return
        if result.is_error:
            key = "max_turns" if result.subtype == "error_max_turns" else "turn_failed"
            if result.errors:
                self.ui.error("; ".join(result.errors)[:500])
            self.speaker.earcon("error")
            self.speaker.say(t(self.lang, key))
            return
        if turn is not None:
            if self._speak_mode(agent.target) == "final" and result.text:
                chunker = SpeechChunker(self.lang)
                for sentence in chunker.feed(result.text) + chunker.flush():
                    self._speak(turn, sentence)
            if turn.spoken:
                self._last_answer = list(turn.spoken)
        self._spawn(self._open_followup(agent))

    def on_error(self, agent, kind: str, detail: str) -> None:  # noqa: ANN001
        self.ui.error(f"{agent.label}: {detail}")
        key = {"auth": "auth_error", "cli": "cli_error", "rate_limit": "rate_limit",
               "billing": "billing_error"}.get(kind, "turn_failed")
        self.speaker.earcon("error")
        self.speaker.say(t(self.lang, key))

    async def confirm(self, agent, question: str, details: str) -> str | None:  # noqa: ANN001
        """Ask a yes/no question out loud and wait for the spoken answer."""
        async with self._confirm_lock:
            if self.paused:
                return None
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._confirm = _Confirm(agent, future, question)
            self.ui.ask(question, details)
            try:
                self.speaker.say(question)
                self.speaker.earcon("question")
                idle = asyncio.ensure_future(self.speaker.wait_idle())
                await asyncio.wait({future, idle}, return_when=asyncio.FIRST_COMPLETED)
                idle.cancel()
                try:
                    answer = await asyncio.wait_for(asyncio.shield(future), self.cfg.claude_code.ask_timeout_s)
                except asyncio.TimeoutError:
                    answer = None
                    self.speaker.say(t(self.lang, "confirm_timeout"))
                self.ui.answer(str(answer))
                if answer in (it.YES, it.ALWAYS):
                    self.speaker.earcon("accept")
                return answer
            finally:
                self._confirm = None

    # -- helpers ------------------------------------------------------------------------------

    def _speak(self, turn: _Turn, sentence: str) -> None:
        if turn.muted or not sentence:
            return
        if turn.budget <= 0:
            if not turn.truncated:
                turn.truncated = True
                self.speaker.say(t(self.lang, "truncated"))
            return
        turn.budget -= len(sentence)
        turn.spoken.append(sentence)
        self.speaker.say(sentence)

    async def _open_followup(self, agent) -> None:  # noqa: ANN001
        await self.speaker.wait_idle()
        if agent.busy or agent.queued or self.paused:
            return
        self._followup = (agent.target, self.clock() + self.cfg.wake.followup_s)
        self.speaker.earcon("done")

    def _spawn(self, coro) -> None:  # noqa: ANN001
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
