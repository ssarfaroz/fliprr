import asyncio

from conftest import Harness

from fliprr import intents as it


async def test_routes_code_and_chat(h):
    await h.hear("Клод Код, запусти тесты.")
    await h.hear("Слушай, Клод, расскажи анекдот.")
    assert h.code.prompts == ["запусти тесты."]
    assert h.chat.prompts == ["расскажи анекдот."]
    assert "Ты сказал: запусти тесты." in h.spoken
    assert "Ты сказал: расскажи анекдот." in h.spoken


async def test_ignores_speech_not_addressed_and_noise(h):
    await h.hear("Я вчера смотрел кино про кота.")
    await h.hear("Продолжение следует...")
    await h.hear("Субтитры сделал DimaTorzok")
    assert h.code.prompts == [] and h.chat.prompts == []
    assert h.spoken == []


async def test_wake_word_alone_then_request(h):
    await h.hear("Клод Код!")
    await h.hear("покажи статус гита")
    assert h.code.prompts == ["покажи статус гита"]


async def test_listen_window_expires(h):
    await h.hear("Клод Код!")
    h.clock.now += 30
    await h.hear("покажи статус гита")
    assert h.code.prompts == []


async def test_follow_up_without_wake_word(h):
    await h.hear("Клод, придумай имя для кота")
    await h.hear("а ещё одно")  # inside the follow-up window → same agent
    assert h.chat.prompts == ["придумай имя для кота", "а ещё одно"]
    h.clock.now += 60
    await h.hear("и ещё")  # window closed
    assert h.chat.prompts == ["придумай имя для кота", "а ещё одно"]


async def test_follow_up_goes_to_last_agent(h):
    await h.hear("Клод Код, создай файл")
    await h.hear("назови его readme")
    assert h.code.prompts == ["создай файл", "назови его readme"]
    assert h.chat.prompts == []


async def test_typed_input_defaults_to_chat(h):
    await h.hear("сколько будет два плюс два", typed=True)
    assert h.chat.prompts == ["сколько будет два плюс два"]


async def test_repeat(h):
    await h.hear("Клод, скажи привет")
    h.engine.texts.clear()
    h.clock.now += 60
    await h.hear("Клод, повтори")
    assert h.spoken == ["Ты сказал: скажи привет"]
    assert h.chat.prompts == ["скажи привет"]


async def test_new_session_and_rest(h):
    await h.hear("Клод Код, новая сессия. Создай README")
    assert h.code.restarts == [{"resume": None, "continue_conversation": False}]
    assert h.code.prompts == ["Создай README"]


async def test_open_chat_with_message(h):
    await h.hear("Клод, открой мне чат рецепты, напиши как приготовить борщ, потом озвучь мне это")
    assert h.store.current == "рецепты"
    assert h.chat.restarts == [{"resume": None}]
    assert h.chat.prompts == ["напиши как приготовить борщ, потом озвучь мне это"]
    assert "Создал чат «рецепты»." in h.spoken
    # existing chat is resumed with its session id
    h.store.remember("рецепты", "sess-123")
    h.clock.now += 60
    await h.hear("Клод, открой чат рецепты")
    assert h.chat.restarts[-1] == {"resume": "sess-123"}
    assert "Открыл чат «рецепты»." in h.spoken


async def test_switch_project(tmp_path):
    from fliprr.config import Config

    cfg = Config()
    blog = tmp_path / "blog"
    blog.mkdir()
    cfg.claude_code.projects = {"блог": str(blog)}
    h = Harness(tmp_path, cfg)
    await h.hear("Клод Код, переключись на проект блог")
    assert h.code.restarts == [{"cwd": blog.resolve(), "resume": None, "continue_conversation": False}]
    assert h.assistant.current_project == "блог"
    await h.hear("Клод Код, открой проект на React и добавь кнопку")  # a task, not a switch
    assert h.code.prompts == ["открой проект на React и добавь кнопку"]
    await h.close()


async def test_pause_and_resume(h):
    await h.hear("Клод, спи")
    assert h.assistant.paused
    await h.hear("Клод Код, удали всё")
    assert h.code.prompts == []
    await h.hear("Клод, проснись")
    assert not h.assistant.paused
    h.clock.now += 60
    await h.hear("Клод Код, покажи статус")
    assert h.code.prompts == ["покажи статус"]


async def test_accept_edits_command(h):
    await h.hear("Клод Код, разрешай правки")
    assert h.code.permission_modes == ["acceptEdits"]
    await h.hear("Клод Код, спрашивай разрешение")
    assert h.code.permission_modes == ["acceptEdits", "default"]


async def test_status_and_help(h):
    await h.hear("Клод, статус")
    assert any(s.startswith("Свободен") for s in h.spoken)
    await h.hear("Клод, что ты умеешь")
    assert any("Клод Код" in s for s in h.spoken)


async def confirm_with(h, *answers, timeout=2.0):
    h.cfg.claude_code.ask_timeout_s = timeout
    task = asyncio.create_task(h.assistant.confirm(h.code, "Выполнить команду: тесты?", "npm test"))
    await asyncio.sleep(0.05)
    for answer in answers:
        h.clock.now += 2.0  # the answer comes after the question
        await h.assistant.on_transcript(answer)
    return await asyncio.wait_for(task, timeout + 2)


async def test_confirm_yes_no_always(h):
    assert await confirm_with(h, "да") == it.YES
    assert await confirm_with(h, "нет, не надо") == it.NO
    assert await confirm_with(h, "Да, и больше не спрашивай") == it.ALWAYS
    assert "Выполнить команду: тесты?" in h.spoken


async def test_confirm_hint_then_answer(h):
    assert await confirm_with(h, "э-э, подожди-ка", "да") == it.YES
    assert "Скажи «да» или «нет»." in h.spoken


async def test_confirm_timeout(h):
    assert await confirm_with(h, timeout=0.2) is None
    assert "Не услышал ответа, отменяю это действие." in h.spoken


async def test_confirm_with_wake_word_answer_and_stop(h):
    assert await confirm_with(h, "Клод, да") == it.YES
    assert await confirm_with(h, "Клод Код, стоп") == it.NO


async def test_confirm_does_not_send_answer_to_claude(h):
    await confirm_with(h, "да")
    assert h.code.prompts == [] and h.chat.prompts == []


async def test_stop_interrupts_busy_agent(tmp_path):
    h = Harness(tmp_path, delay=1.0)
    await h.assistant.on_transcript("Клод Код, сделай большую задачу")
    await asyncio.sleep(0.05)
    assert h.code.busy
    await h.assistant.on_transcript("Клод, стоп")  # chat is idle → stops the busy Claude Code
    assert h.code.interrupted == 1
    await h.close()


async def test_new_request_while_busy_is_queued(tmp_path):
    h = Harness(tmp_path, delay=0.3)
    await h.assistant.on_transcript("Клод Код, первая задача")
    await asyncio.sleep(0.05)
    await h.assistant.on_transcript("Клод Код, вторая задача")
    await asyncio.sleep(0.05)
    assert "Добавил в очередь, сделаю после текущей задачи." in h.engine.texts
    await h.settle()
    await asyncio.sleep(0.4)
    await h.settle()
    assert h.code.prompts == ["первая задача", "вторая задача"]
    await h.close()


async def test_echo_of_own_speech_is_ignored(h):
    h.speaker.say("Привет, это длинный тестовый ответ ассистента.")
    await h.assistant.on_transcript("привет это длинный тестовый ответ ассистента")
    await h.settle()
    assert h.code.prompts == [] and h.chat.prompts == []


async def test_barge_in_inside_echo(h):
    h.player.realtime = True
    for _ in range(5):
        h.speaker.say("Это очень длинный ответ, который никто не хочет слушать до конца.")
    await asyncio.sleep(0.05)
    assert h.speaker.speaking
    await h.assistant.on_transcript("который никто не хочет Клод стоп слушать")
    assert not h.speaker.speaking or h.speaker._items.empty()
    await h.settle()
    assert not h.speaker.speaking


async def test_barge_in_probe_while_speaking(tmp_path):
    import numpy as np

    h = Harness(tmp_path)

    class ProbeTranscriber:
        prompt = ""
        calls = 0

        def transcribe(self, audio, fast=False):
            from fliprr.stt.base import Transcript

            ProbeTranscriber.calls += 1
            assert fast  # probes use the quick decoding settings
            return Transcript(text="и вот эта функция Клод стоп возвращает список")

    h.assistant.transcriber = ProbeTranscriber()
    h.assistant.probe_audio = lambda seconds: np.zeros(int(seconds * 16000), np.float32)
    h.player.realtime = True
    for _ in range(3):
        h.speaker.say("Это очень длинный ответ, который никто не хочет слушать до конца.")
    await asyncio.sleep(0.05)
    assert h.speaker.speaking
    await h.assistant._maybe_probe()
    assert ProbeTranscriber.calls == 1
    await h.settle()
    assert not h.speaker.speaking
    await h.assistant._maybe_probe()  # nothing is being said: no probe
    assert ProbeTranscriber.calls == 1
    await h.close()


async def test_while_speaking_only_a_direct_call_counts(tmp_path):
    h = Harness(tmp_path)
    await h.hear("Клод, придумай имя для кота")  # opens a follow-up window afterwards
    h.player.realtime = True
    h.speaker.say("Например, Барсик. А ещё можно назвать его Пушок или Мурзик, это классика.")
    await asyncio.sleep(0.05)
    assert h.speaker.speaking
    # garbled echo of our own answer: no follow-up, no request
    await h.assistant.on_transcript("например барсук а ещё мурзилка")
    # «Я Клод, …» from our own speech: the name is not at the start → ignored
    await h.assistant.on_transcript("Я Клод, ассистент от Антропик")
    assert h.chat.prompts == ["придумай имя для кота"]
    # a direct call interrupts us
    await h.assistant.on_transcript("Клод Код, запусти сборку")
    await h.settle()
    assert h.code.prompts == ["запусти сборку"]
    await h.close()


async def test_echo_cannot_answer_a_permission_question(tmp_path):
    h = Harness(tmp_path)
    h.player.realtime = True
    h.cfg.claude_code.ask_timeout_s = 0.5
    task = asyncio.create_task(h.assistant.confirm(h.code, "Удалить?", "rm -rf build"))
    await asyncio.sleep(0.02)
    hint = "Скажи «да» или «нет»."
    h.speaker.say(hint)
    while h.speaker.last_spoken != hint:  # wait until the hint is actually playing
        await asyncio.sleep(0.01)
    # the microphone hears our own hint: neither the whole phrase nor its last word answers
    await h.assistant.on_transcript("скажи да или нет")
    await h.assistant.on_transcript("нет")
    assert await task is None  # nothing was accepted; the question timed out
    await h.close()


async def test_user_can_answer_over_the_question(tmp_path):
    h = Harness(tmp_path)
    h.player.realtime = True
    task = asyncio.create_task(h.assistant.confirm(h.code, "Выполнить команду: удалить сборку?", "rm -rf build"))
    await asyncio.sleep(0.05)
    await h.assistant.on_transcript("нет")  # said while the question is still being read
    assert await asyncio.wait_for(task, 3) == it.NO
    await h.close()


async def test_quick_yes_right_after_the_question(tmp_path):
    h = Harness(tmp_path)
    h.player.realtime = True
    task = asyncio.create_task(h.assistant.confirm(h.code, "Создать файл привет.txt?", "привет.txt"))
    await asyncio.sleep(0.05)
    # the user answers while the question's echo tail is still "in the air"
    await h.assistant.on_transcript("Да, разрешаю.", started=h.clock())
    assert await asyncio.wait_for(task, 3) == it.YES
    await h.close()
