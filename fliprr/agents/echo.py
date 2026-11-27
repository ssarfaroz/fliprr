"""A stand-in agent that just repeats the request (simulations without Claude)."""

from __future__ import annotations

import asyncio
from typing import Any

from fliprr.agents.session import TurnResult


class EchoAgent:
    def __init__(self, target: str, label: str, sink, lang: str = "ru", delay_s: float = 0.0) -> None:  # noqa: ANN001
        self.target = target
        self.label = label
        self.sink = sink
        self.lang = lang
        self.delay_s = delay_s
        self.busy = False
        self.current_prompt = ""
        self.prompts: list[str] = []
        self.restarts: list[dict[str, Any]] = []
        self.permission_modes: list[str] = []
        self.interrupted = 0
        self._pending = 0
        self._tasks: set[asyncio.Task] = set()

    @property
    def queued(self) -> int:
        return self._pending

    def start(self) -> None:
        pass

    def warm_up(self) -> None:
        pass

    def submit(self, prompt: str) -> None:
        self.prompts.append(prompt)
        self._pending += 1
        task = asyncio.get_running_loop().create_task(self._respond(prompt))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _respond(self, prompt: str) -> None:
        while self.busy:
            await asyncio.sleep(0.01)
        self._pending -= 1
        self.busy = True
        self.current_prompt = prompt
        try:
            self.sink.on_turn_start(self, prompt)
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            reply = ("Ты сказал: " if self.lang == "ru" else "You said: ") + prompt
            self.sink.on_text(self, reply)
            self.sink.on_text_end(self)
            self.sink.on_result(self, TurnResult(reply, False, "success", self.delay_s, None, "echo", False))
        finally:
            self.busy = False
            self.current_prompt = ""

    def restart(self, **changes: Any) -> None:
        self.restarts.append(changes)

    async def interrupt(self) -> bool:
        self.interrupted += 1
        return self.busy

    def clear_queue(self) -> int:
        return 0

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_modes.append(mode)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
