"""ClaudeSession against a fake SDK client (no Claude Code process)."""

import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
)

from fliprr import intents as it
from fliprr.agents import session as session_mod
from fliprr.agents.session import ClaudeSession, SessionSpec


def ev(event, parent=None):
    return StreamEvent(uuid="u", session_id="s1", event=event, parent_tool_use_id=parent)


def text_turn(*chunks):
    msgs = [ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})]
    msgs += [ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": c}}) for c in chunks]
    msgs.append(AssistantMessage(content=[TextBlock("".join(chunks))], model="m"))
    msgs.append(ev({"type": "content_block_stop", "index": 0}))
    return msgs


def result(**kw):
    base = dict(subtype="success", duration_ms=10, duration_api_ms=5, is_error=False, num_turns=1,
                session_id="s1", result="готово", total_cost_usd=0.01)
    base.update(kw)
    return ResultMessage(**base)


class Sink:
    def __init__(self, answer=it.YES):
        self.events = []
        self.answer = answer

    def on_turn_start(self, agent, prompt):
        self.events.append(("start", prompt))

    def on_text(self, agent, delta):
        self.events.append(("text", delta))

    def on_text_end(self, agent):
        self.events.append(("end",))

    def on_tool(self, agent, name, data):
        self.events.append(("tool", name))

    def on_result(self, agent, res):
        self.events.append(("result", res.text, res.interrupted, res.is_error))

    def on_error(self, agent, kind, detail):
        self.events.append(("error", kind))

    async def confirm(self, agent, question, details):
        self.events.append(("confirm", question))
        return self.answer


class FakeClient:
    instances = []
    script = []

    def __init__(self, options):
        self.options = options
        self.queries = []
        self.interrupted = False
        FakeClient.instances.append(self)

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, prompt):
        self.queries.append(prompt)

    async def receive_response(self):
        for message in FakeClient.script:
            if isinstance(message, Exception):
                raise message
            yield message
            await asyncio.sleep(0)

    async def interrupt(self):
        self.interrupted = True

    async def set_permission_mode(self, mode):
        self.mode = mode


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.instances = []
    FakeClient.script = []
    monkeypatch.setattr(session_mod, "ClaudeSDKClient", FakeClient)
    return FakeClient


def make_session(sink, tmp_path=Path("."), ids=None):
    def options(spec, can_use_tool):
        return {"cwd": spec.cwd, "resume": spec.resume, "continue": spec.continue_conversation,
                "can_use_tool": can_use_tool}

    return ClaudeSession("code", "Claude Code", SessionSpec(cwd=tmp_path), options, sink,
                         on_session_id=(ids.append if ids is not None else None))


def test_streamed_text_is_reported_once():
    sink = Sink()
    s = make_session(sink)
    for message in text_turn("Привет. ", "Как дела?"):
        s._handle(message)
    assert sink.events == [("text", "Привет. "), ("text", "Как дела?"), ("end",)]


def test_text_without_stream_events_is_reported_from_message():
    sink = Sink()
    s = make_session(sink)
    s._handle(AssistantMessage(content=[TextBlock("Готово."), ToolUseBlock("t1", "Bash", {"command": "ls"})], model="m"))
    assert sink.events == [("text", "Готово."), ("end",), ("tool", "Bash")]


def test_subagent_output_and_errors():
    sink = Sink()
    s = make_session(sink)
    s._handle(ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "x"}}, parent="t9"))
    s._handle(AssistantMessage(content=[TextBlock("sub")], model="m", parent_tool_use_id="t9"))
    assert sink.events == []
    s._handle(AssistantMessage(content=[TextBlock("Invalid API key · Please run /login")], model="m",
                               error="authentication_failed"))
    assert sink.events == [("error", "auth")]


def test_result_and_session_id(tmp_path):
    sink, ids = Sink(), []
    s = make_session(sink, tmp_path, ids)
    s._handle(SystemMessage(subtype="init", data={"session_id": "abc"}))
    s._handle(result(session_id="abc", terminal_reason="aborted_tools", is_error=True))
    assert ids == ["abc"] and s.session_id == "abc"
    assert sink.events == [("result", "готово", True, False)]  # interrupted, not an error


async def test_worker_runs_turns_in_order_and_restarts(fake_client, tmp_path):
    sink = Sink()
    s = make_session(sink, tmp_path)
    fake_client.script = text_turn("Ок.") + [result()]
    s.start()
    s.submit("первая")
    s.submit("вторая")
    s.restart(cwd=tmp_path / "other", resume=None)
    s.submit("третья")
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not s.busy and s.queued == 0 and len(fake_client.instances) == 2 and fake_client.instances[1].queries:
            break
    first, second = fake_client.instances
    assert first.queries == ["первая", "вторая"]
    assert second.queries == ["третья"]
    assert second.options["cwd"] == tmp_path / "other"
    assert second.options["resume"] is None
    assert [e for e in sink.events if e[0] == "start"] == [("start", "первая"), ("start", "вторая"), ("start", "третья")]
    await s.close()


async def test_reconnect_after_error_keeps_conversation(fake_client, tmp_path):
    sink = Sink()
    s = make_session(sink, tmp_path)
    s.start()
    fake_client.script = [SystemMessage(subtype="init", data={"session_id": "keep-me"}), RuntimeError("pipe broke")]
    s.submit("раз")
    await asyncio.sleep(0.1)
    assert ("error", "other") in sink.events
    fake_client.script = [result(session_id="keep-me")]
    s.submit("два")
    await asyncio.sleep(0.1)
    assert fake_client.instances[1].options["resume"] == "keep-me"
    await s.close()


async def test_permission_answers():
    ctx = ToolPermissionContext(suggestions=[PermissionUpdate(type="setMode", mode="acceptEdits", destination="localSettings")])
    for answer, expected in ((it.YES, PermissionResultAllow), (it.ALWAYS, PermissionResultAllow),
                             (it.NO, PermissionResultDeny), (None, PermissionResultDeny)):
        sink = Sink(answer)
        s = make_session(sink)
        out = await s._can_use_tool("Bash", {"command": "rm -rf build", "description": "Удалить сборку"}, ctx)
        assert isinstance(out, expected)
        assert sink.events == [("confirm", "Выполнить команду: Удалить сборку?")]
        if answer == it.ALWAYS:
            assert out.updated_permissions[0].destination == "session"  # never persisted to disk
        if answer is None:
            assert "did not answer" in out.message
