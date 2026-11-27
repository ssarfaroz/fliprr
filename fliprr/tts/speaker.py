"""Queued, interruptible speech output.

Sentences are synthesized one ahead of playback so there are no gaps, and
``stop()`` silences everything immediately (current clip and queue).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from fliprr.audio.earcons import RATE as EARCON_RATE
from fliprr.audio.earcons import earcon
from fliprr.text import keys, overlap_ratio, script_of

# Room reverb and output latency after the last sample was handed to the device.
ECHO_TAIL_S = 0.35


class Speaker:
    def __init__(
        self,
        engines: list,
        player,  # noqa: ANN001 — AudioPlayer | NullPlayer
        *,
        earcons: bool = True,
        earcon_volume: float = 0.25,
        log: Callable[[str], None] | None = None,
        synth_timeout_s: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engines = engines
        self.player = player
        self.earcons_enabled = earcons
        self.earcon_volume = earcon_volume
        self.log = log or (lambda _msg: None)
        self.synth_timeout_s = synth_timeout_s
        self.clock = clock
        self._items: asyncio.Queue = asyncio.Queue()
        self._audio: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._gen = 0
        self._pending = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._disabled_until: dict[int, float] = {}
        self._tasks: list[asyncio.Task] = []
        self.recent: deque[tuple[float, str]] = deque(maxlen=40)
        self._played: deque[tuple[float, float]] = deque(maxlen=40)  # (start, end) of spoken clips
        self._current_start: float | None = None

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        if not self._tasks:
            self._tasks = [asyncio.create_task(self._synth_loop()), asyncio.create_task(self._play_loop())]

    async def close(self) -> None:
        self.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    # -- public API ----------------------------------------------------------------

    @property
    def speaking(self) -> bool:
        return self._pending > 0

    def say(self, text: str) -> None:
        text = text.strip()
        if not text or not self.engines:
            return
        self._enqueue(("text", text))

    def earcon(self, name: str) -> None:
        if self.earcons_enabled:
            self._enqueue(("audio", (earcon(name, self.earcon_volume, EARCON_RATE), EARCON_RATE, "")))

    async def say_and_wait(self, text: str) -> None:
        self.say(text)
        await self.wait_idle()

    async def wait_idle(self) -> None:
        await self._idle.wait()

    def stop(self) -> None:
        """Silence now: drop queued speech and cut off the current clip."""
        self._gen += 1
        for q in (self._items, self._audio):
            while not q.empty():
                q.get_nowait()
                self._done()
        self.player.stop()

    def overlapped(self, started: float | None = None) -> bool:
        """Was our voice (or its echo tail) in the air when an utterance began?

        Speech that began after we had finished talking is the user's, even
        if it repeats our words («Скажи “Клод, проснись”» → «Клод, проснись»).
        Earcons don't count: a beep doesn't turn into words.
        """
        started = self.clock() if started is None else started
        if self._current_start is not None and started >= self._current_start - 0.3:
            return True
        return any(s - 0.3 <= started <= e + ECHO_TAIL_S for s, e in self._played)

    @property
    def last_spoken(self) -> str:
        return self.recent[-1][1] if self.recent else ""

    def echo_ratio(self, text: str) -> float:
        """How much of ``text`` sounds like what we said in the last minute (0…1)."""
        now = self.clock()
        recent = [t for ts, t in self.recent if now - ts < 60]
        if not recent or len(keys(text)) < 2:
            return 0.0
        return overlap_ratio(text, set(keys(" ".join(recent))))

    def is_echo(self, text: str, started: float | None = None) -> bool:
        """Did the microphone just hear our own voice?"""
        return self.overlapped(started) and self.echo_ratio(text) >= 0.6

    # -- internals -----------------------------------------------------------------

    def _enqueue(self, item: tuple) -> None:
        self._pending += 1
        self._idle.clear()
        self._items.put_nowait((self._gen, *item))

    def _done(self) -> None:
        self._pending = max(0, self._pending - 1)
        if self._pending == 0:
            self._idle.set()

    async def _synth_loop(self) -> None:
        while True:
            gen, kind, payload = await self._items.get()
            if gen != self._gen:
                self._done()
                continue
            if kind == "audio":
                audio, rate, text = payload
            else:
                text = payload
                audio, rate = await self._synthesize(text)
                if gen != self._gen or audio is None:
                    self._done()
                    continue
            await self._audio.put((gen, audio, rate, text))

    async def _play_loop(self) -> None:
        while True:
            gen, audio, rate, text = await self._audio.get()
            try:
                if gen == self._gen:
                    start = self.clock()
                    if text:
                        self.recent.append((start, text))
                        self._current_start = start
                    await asyncio.to_thread(self.player.play, audio, rate)
                    if text:
                        self._played.append((start, self.clock()))
            except Exception as e:  # noqa: BLE001
                self.log(f"playback failed: {e}")
            finally:
                self._current_start = None
                self._done()

    async def _synthesize(self, text: str) -> tuple[np.ndarray | None, int]:
        lang = script_of(text)
        now = time.monotonic()
        for engine in self.engines:
            if self._disabled_until.get(id(engine), 0) > now:
                continue
            try:
                audio, rate = await asyncio.wait_for(engine.synthesize(text, lang), self.synth_timeout_s)
                if audio is not None and audio.size:
                    return audio, rate
            except Exception as e:  # noqa: BLE001 — try the next engine
                self.log(f"TTS «{engine.name}» failed: {e!r}")
                # Don't retry a broken engine (e.g. no internet) for every sentence.
                self._disabled_until[id(engine)] = now + 60
        return None, 0
