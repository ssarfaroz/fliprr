"""A long-lived Claude session driven by voice, on top of the Claude Agent SDK.

The SDK runs the real Claude Code (bundled CLI) as a subprocess, so the
Claude Code mode has the same tools, settings, CLAUDE.md and login as Claude
Code in a terminal. Each session is owned by one worker task: requests are
processed in order, and the SDK client is connected and disconnected inside
that task (the SDK requires it).
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    CLINotFoundError,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
)

from fliprr.agents.permissions import describe_permission
from fliprr.intents import ALWAYS, NO, YES


@dataclass
class SessionSpec:
    cwd: Path
    resume: str | None = None
    continue_conversation: bool = False
    permission_mode: str | None = None


@dataclass
class TurnResult:
    text: str
    is_error: bool
    subtype: str
    seconds: float
    cost: float | None
    session_id: str
    interrupted: bool
    errors: list[str] = field(default_factory=list)


class AgentSink(Protocol):
    """What the session reports to (implemented by the assistant)."""

    def on_turn_start(self, agent: ClaudeSession, prompt: str) -> None: ...
    def on_text(self, agent: ClaudeSession, delta: str) -> None: ...
    def on_text_end(self, agent: ClaudeSession) -> None: ...
    def on_tool(self, agent: ClaudeSession, name: str, data: dict[str, Any]) -> None: ...
    def on_result(self, agent: ClaudeSession, result: TurnResult) -> None: ...
    def on_error(self, agent: ClaudeSession, kind: str, detail: str) -> None: ...
    async def confirm(self, agent: ClaudeSession, question: str, details: str) -> str | None: ...


OptionsFactory = Callable[[SessionSpec, Any], ClaudeAgentOptions]

_ERROR_KINDS = {"authentication_failed": "auth", "billing_error": "billing", "rate_limit": "rate_limit"}


class ClaudeSession:
    def __init__(
        self,
        target: str,
        label: str,
        spec: SessionSpec,
        make_options: OptionsFactory,
        sink: AgentSink,
        *,
        lang: str = "ru",
        ask_permissions: bool = True,
        log: Callable[[str], None] | None = None,
        on_session_id: Callable[[str], None] | None = None,
    ) -> None:
        self.target = target
        self.label = label
        self.spec = spec
        self.make_options = make_options
        self.sink = sink
        self.lang = lang
        self.ask_permissions = ask_permissions
        self.log = log or (lambda _m: None)
        self.on_session_id = on_session_id
        self.session_id: str | None = spec.resume
        self.busy = False
        self.current_prompt = ""
        self.turn_started = 0.0
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._client: ClaudeSDKClient | None = None
        self._task: asyncio.Task | None = None
        self._streamed_chars = 0
        self._text_blocks: set[int] = set()

    # -- control (safe to call from any task) --------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"fliprr-{self.target}")

    def warm_up(self) -> None:
        self._queue.put_nowait(("connect", None))

    def submit(self, prompt: str) -> None:
        self._queue.put_nowait(("prompt", prompt))

    @property
    def queued(self) -> int:
        return sum(1 for kind, _ in list(self._queue._queue) if kind == "prompt")  # type: ignore[attr-defined]

    def clear_queue(self) -> int:
        kept, dropped = [], 0
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item[0] == "prompt":
                dropped += 1
            else:
                kept.append(item)
        for item in kept:
            self._queue.put_nowait(item)
        return dropped

    def restart(self, **changes: Any) -> None:
        """Reconnect with a changed spec (new session, other folder, resume…)."""
        self._queue.put_nowait(("restart", changes))

    async def interrupt(self) -> bool:
        if not (self.busy and self._client is not None):
            return False
        try:
            await self._client.interrupt()
        except Exception as e:  # noqa: BLE001
            self.log(f"{self.label}: interrupt failed: {e}")
            return False
        return True

    async def set_permission_mode(self, mode: str) -> None:
        self.spec.permission_mode = mode
        if self._client is not None:
            try:
                await self._client.set_permission_mode(mode)  # type: ignore[arg-type]
            except Exception as e:  # noqa: BLE001 — applies on next connect anyway
                self.log(f"{self.label}: could not change permission mode now: {e}")

    async def close(self) -> None:
        if self._task is None:
            return
        await self.interrupt()
        self.clear_queue()
        self._queue.put_nowait(("close", None))
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=8)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    # -- worker ------------------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            kind, payload = await self._queue.get()
            if kind == "close":
                await self._disconnect()
                return
            if kind == "restart":
                await self._disconnect()
                self.spec = dataclasses.replace(self.spec, **payload)
                self.session_id = self.spec.resume
                continue
            if kind == "connect":
                try:
                    await self._ensure_connected()
                except Exception as e:  # noqa: BLE001 — reported on first real use
                    self.log(f"{self.label}: warm-up failed: {e}")
                continue
            await self._turn(payload)

    async def _ensure_connected(self) -> None:
        if self._client is not None:
            return
        spec = self.spec
        if self.session_id and not spec.resume:
            # reconnecting after an error: keep the conversation
            spec = dataclasses.replace(spec, resume=self.session_id, continue_conversation=False)
        options = self.make_options(spec, self._can_use_tool if self.ask_permissions else None)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._client = client

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception as e:  # noqa: BLE001
                self.log(f"{self.label}: disconnect: {e}")

    async def _turn(self, prompt: str) -> None:
        self.busy = True
        self.current_prompt = prompt
        self.turn_started = time.monotonic()
        self._streamed_chars = 0
        self._text_blocks.clear()
        self.sink.on_turn_start(self, prompt)
        try:
            await self._ensure_connected()
            assert self._client is not None
            await self._client.query(prompt)
            async for message in self._client.receive_response():
                self._handle(message)
        except CLINotFoundError as e:
            self.sink.on_error(self, "cli", str(e))
            await self._disconnect()
        except (CLIConnectionError, ProcessError) as e:
            self.sink.on_error(self, "cli", str(e))
            await self._disconnect()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.sink.on_error(self, "other", f"{type(e).__name__}: {e}")
            await self._disconnect()
        finally:
            self.busy = False
            self.current_prompt = ""

    def _handle(self, message: Any) -> None:
        if isinstance(message, StreamEvent):
            if message.parent_tool_use_id:
                return  # sub-agent chatter
            event = message.event
            etype = event.get("type")
            if etype == "content_block_start":
                if (event.get("content_block") or {}).get("type") == "text":
                    self._text_blocks.add(event.get("index", -1))
            elif etype == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    self._streamed_chars += len(delta["text"])
                    self.sink.on_text(self, delta["text"])
            elif etype == "content_block_stop" and event.get("index", -1) in self._text_blocks:
                self._text_blocks.discard(event.get("index", -1))
                self.sink.on_text_end(self)
            return

        if isinstance(message, AssistantMessage):
            if message.parent_tool_use_id:
                return
            if message.error:
                kind = _ERROR_KINDS.get(message.error, "other")
                text = " ".join(b.text for b in message.content if isinstance(b, TextBlock))
                self.sink.on_error(self, kind, text or message.error)
                self._streamed_chars = 0
                return
            texts = [b.text for b in message.content if isinstance(b, TextBlock) and b.text.strip()]
            if texts:
                if self._streamed_chars == 0:  # no partial messages arrived: speak the block now
                    for text in texts:
                        self.sink.on_text(self, text)
                        self.sink.on_text_end(self)
                self._streamed_chars = 0
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    self.sink.on_tool(self, block.name, block.input)
            return

        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                self._set_session_id(message.data.get("session_id"))
            return

        if isinstance(message, ResultMessage):
            self._set_session_id(message.session_id)
            interrupted = (message.terminal_reason or "").startswith("aborted")
            self.sink.on_result(self, TurnResult(
                text=message.result or "",
                is_error=bool(message.is_error) and not interrupted,
                subtype=message.subtype,
                seconds=time.monotonic() - self.turn_started,
                cost=message.total_cost_usd,
                session_id=message.session_id,
                interrupted=interrupted,
                errors=list(message.errors or []),
            ))

    def _set_session_id(self, session_id: str | None) -> None:
        if session_id and session_id != self.session_id:
            self.session_id = session_id
            if self.on_session_id is not None:
                self.on_session_id(session_id)

    # -- permissions by voice ---------------------------------------------------------

    async def _can_use_tool(
        self, tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        question, details = describe_permission(tool_name, tool_input, self.lang, context.title)
        answer = await self.sink.confirm(self, question, details)
        if answer == ALWAYS:
            # Like "Yes, and don't ask again" in Claude Code — for this session only.
            updates = [dataclasses.replace(s, destination="session") for s in context.suggestions]
            return PermissionResultAllow(updated_permissions=updates or None)
        if answer == YES:
            return PermissionResultAllow()
        if answer == NO:
            return PermissionResultDeny(message="The user declined this action by voice.")
        return PermissionResultDeny(
            message="The user did not answer the permission request by voice (they may be away). "
            "Don't retry it; briefly say what you wanted to do and why."
        )
