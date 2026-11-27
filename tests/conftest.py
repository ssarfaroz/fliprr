import asyncio

import numpy as np
import pytest

from fliprr.agents.chats import ChatStore
from fliprr.agents.echo import EchoAgent
from fliprr.assistant import Assistant
from fliprr.audio.player import NullPlayer
from fliprr.config import Config
from fliprr.tts.speaker import Speaker
from fliprr.wake import CHAT, CODE


class FakeEngine:
    name = "fake"

    def __init__(self, fail=False):
        self.fail = fail
        self.texts = []

    async def synthesize(self, text, lang):
        if self.fail:
            raise RuntimeError("boom")
        self.texts.append(text)
        return np.zeros(240, np.float32), 24000


class FakeUI:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.events.append((name, args))

        return record


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Transcriber:
    name = "fake"
    prompt = "Разговор с ассистентом Клод (Claude) и Клод Код (Claude Code)."

    def transcribe(self, audio, fast=False):  # pragma: no cover — tests call on_transcript directly
        raise AssertionError


class Harness:
    def __init__(self, tmp_path, cfg=None, delay=0.0):
        self.cfg = cfg or Config()
        self.cfg.data_dir = str(tmp_path)
        self.cfg.claude_code.cwd = str(tmp_path)
        self.engine = FakeEngine()
        self.player = NullPlayer()
        self.clock = Clock()
        self.speaker = Speaker([self.engine], self.player, earcons=False, clock=self.clock)
        self.ui = FakeUI()
        self.store = ChatStore(tmp_path / "chats.json")
        self.assistant = Assistant(self.cfg, transcriber=Transcriber(), speaker=self.speaker, ui=self.ui,
                                   chat_store=self.store, clock=self.clock)
        self.code = EchoAgent(CODE, "Claude Code", self.assistant, delay_s=delay)
        self.chat = EchoAgent(CHAT, "Claude", self.assistant, delay_s=delay)
        self.assistant.attach_agents(self.code, self.chat)
        self.speaker.start()

    @property
    def spoken(self):
        return self.engine.texts

    async def hear(self, text, **kw):
        self.clock.now += 2.0  # people take a breath between phrases
        await self.assistant.on_transcript(text, **kw)
        await self.settle()

    async def settle(self):
        for _ in range(300):
            await asyncio.sleep(0.005)
            if self.assistant.idle and not self.assistant._background:
                return

    async def close(self):
        await self.speaker.close()


@pytest.fixture
async def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    await harness.close()
