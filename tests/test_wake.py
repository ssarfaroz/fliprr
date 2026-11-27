import pytest

from fliprr.text import phonetic_key, script_of
from fliprr.wake import CHAT, CODE, WakeMatcher

m = WakeMatcher()


@pytest.mark.parametrize(
    "text, target, command",
    [
        # clean transcripts
        ("Клод Код, запусти тесты.", CODE, "запусти тесты."),
        ("Клод, какая столица Франции?", CHAT, "какая столица Франции?"),
        ("Claude Code, run the tests", CODE, "run the tests"),
        ("Claude, what's the weather?", CHAT, "what's the weather?"),
        ("Слушай, Клод, расскажи анекдот.", CHAT, "расскажи анекдот."),
        ("Эй, слушай, ну Клод, привет", CHAT, "привет"),
        # misrecognitions actually produced by Whisper on «Клод Код, …»
        ("Код-код, покажи статус в оппозиторе.", CODE, "покажи статус в оппозиторе."),
        ("Клод-код запустить тесто.", CODE, "запустить тесто."),
        ("Клод, Клод, покажи статус репозитория.", CODE, "покажи статус репозитория."),
        ("К Claude Code покажи статус", CODE, "покажи статус"),
        ("Клодкод, сделай коммит", CODE, "сделай коммит"),
        ("Клауд код, открой файл", CODE, "открой файл"),
        ("Клот, сколько времени?", CHAT, "сколько времени?"),
        ("Клад, сколько будет 2 плюс 2?", CHAT, "сколько будет 2 плюс 2?"),
        ("Клоду скажи привет", CHAT, "скажи привет"),
        ("Клод кот, запусти сборку", CODE, "запусти сборку"),  # final devoicing: код → [кот]
    ],
)
def test_wake_matches(text, target, command):
    match = m.match(text)
    assert match is not None, text
    assert match.target == target
    assert match.command == command


@pytest.mark.parametrize(
    "text",
    [
        "Я вчера смотрел кино про кота.",
        "Код не работает",
        "Глоток воды",
        "Клон репозитория готов",
        "Мы обсуждали, что Клод умеет",  # name too far into the sentence
        "",
        "...",
    ],
)
def test_not_addressed(text):
    assert m.match(text) is None


def test_wake_only():
    assert m.match("Клод!").wake_only
    assert m.match("Клод Код.").wake_only
    assert m.match("Клод, слушай").wake_only
    assert not m.match("Клод, привет").wake_only


def test_question_word_after_name_is_not_code():
    # «куда» has the same sound key as «кода»; it must stay a chat question
    match = m.match("Клод, куда пропали файлы?")
    assert match.target == CHAT
    assert match.command == "куда пропали файлы?"


def test_default_target_and_extra_words():
    matcher = WakeMatcher(default_target=CODE, extra_claude_words=["клоди"])
    assert matcher.match("Клод, почини сборку").target == CODE
    assert matcher.match("Клоди, привет").target == CODE
    with pytest.raises(ValueError):
        WakeMatcher(default_target="nope")


def test_phonetic_key():
    for word in ("клод", "Клот", "claude", "Cloud", "клауд", "клоуд", "clawed"):
        assert phonetic_key(word) == "KLAT", word
    assert phonetic_key("код") == phonetic_key("code") == phonetic_key("кот") == "KAT"


def test_script_of():
    assert script_of("Привет, мир") == "ru"
    assert script_of("Hello world") == "en"
    assert script_of("Запусти npm test") == "ru"
