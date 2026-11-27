import asyncio
import time

from conftest import FakeEngine

from fliprr.audio.player import NullPlayer
from fliprr.tts.speaker import Speaker


async def test_speaks_in_order_and_goes_idle():
    engine, player = FakeEngine(), NullPlayer()
    speaker = Speaker([engine], player, earcons=False)
    speaker.start()
    for text in ("один", "два", "три"):
        speaker.say(text)
    assert speaker.speaking
    await asyncio.wait_for(speaker.wait_idle(), 2)
    assert engine.texts == ["один", "два", "три"]
    assert len(player.clips) == 3
    assert not speaker.speaking
    await speaker.close()


async def test_stop_drops_queue():
    engine, player = FakeEngine(), NullPlayer(realtime=True)
    speaker = Speaker([engine], player, earcons=False)
    speaker.start()
    for i in range(10):
        speaker.say(f"фраза {i}")
    await asyncio.sleep(0.02)
    speaker.stop()
    await asyncio.wait_for(speaker.wait_idle(), 2)
    assert len(player.clips) < 10
    await speaker.close()


async def test_falls_back_to_next_engine_and_skips_broken_one():
    broken, good = FakeEngine(fail=True), FakeEngine()
    logs = []
    speaker = Speaker([broken, good], NullPlayer(), earcons=False, log=logs.append)
    speaker.start()
    speaker.say("привет")
    speaker.say("ещё раз")
    await asyncio.wait_for(speaker.wait_idle(), 2)
    assert good.texts == ["привет", "ещё раз"]
    assert len(logs) == 1  # the broken engine was tried once, then skipped
    await speaker.close()


async def test_earcons_and_empty_text():
    player = NullPlayer()
    speaker = Speaker([FakeEngine()], player, earcons=True)
    speaker.start()
    speaker.say("   ")
    speaker.earcon("wake")
    await asyncio.wait_for(speaker.wait_idle(), 2)
    assert len(player.clips) == 1 and player.clips[0][1] == 24000
    await speaker.close()


async def test_echo_detection():
    speaker = Speaker([FakeEngine()], NullPlayer(), earcons=False)
    speaker.start()
    speaker.say("Я Claude, ассистент от Anthropic.")
    await asyncio.wait_for(speaker.wait_idle(), 2)
    now = time.monotonic()
    assert speaker.is_echo("Я Клод, ассистент от Антропик.", now)  # what the mic heard
    assert not speaker.is_echo("Клод Код, запусти тесты", now)
    assert not speaker.is_echo("Я Клод, ассистент от Антропик.", now + 10)  # long after speaking
    await speaker.close()
