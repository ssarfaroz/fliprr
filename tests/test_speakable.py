from fliprr.speakable import SpeechChunker, to_speakable


def stream(text, step=5, lang="ru"):
    chunker = SpeechChunker(lang)
    out = []
    for i in range(0, len(text), step):
        out += chunker.feed(text[i:i + step])
    return out + chunker.flush()


def test_to_speakable_markdown():
    assert to_speakable("**Готово!** Исправил `main.py`.") == "Готово! Исправил main.py."
    assert to_speakable("## Итог") == "Итог"
    assert to_speakable("- пункт") == "пункт"
    assert to_speakable("См. [документацию](https://docs.example.com/a/b)") == "См. документацию"
    assert to_speakable("Ссылка https://github.com/foo/bar") == "Ссылка github.com"
    assert to_speakable("Файл src/app/components/Button.tsx обновлён") == "Файл Button.tsx обновлён"
    assert to_speakable("Коммит 3f9a2b1c4d5e6f708192") == "Коммит 3f9a2b1"
    assert to_speakable("✅ Тесты прошли 🎉") == "Тесты прошли"
    assert to_speakable("a -> b") == "a — b"
    assert to_speakable("```") == ""
    assert to_speakable("snake_case_name stays") == "snake_case_name stays"


def test_chunker_sentences_and_code():
    text = (
        "Готово! Я исправил файл `src/app/main.py`. Вот код:\n```python\nprint('hi')\n# a. b. c.\n```\n"
        "Теперь **всё** работает. Таблица:\n| a | b |\n|---|---|\n| 1 | 2 |\nИтого 3.14 процента.\n- один\n- два"
    )
    assert stream(text) == [
        "Готово!",
        "Я исправил файл main.py.",
        "Вот код:",
        "Код показан на экране.",
        "Теперь всё работает.",
        "Таблица:",
        "Таблица показана на экране.",
        "Итого 3.14 процента.",
        "один",
        "два",
    ]


def test_chunker_same_result_for_any_chunking():
    text = "Первое предложение. Второе! Третье?\nЧетвёртое без точки"
    expected = ["Первое предложение.", "Второе!", "Третье?", "Четвёртое без точки"]
    for step in (1, 2, 3, 7, 100):
        assert stream(text, step) == expected, step


def test_unterminated_code_block():
    assert stream("Смотри:\n```\nx = 1\n") == ["Смотри:", "Код показан на экране."]


def test_long_text_without_punctuation_is_split():
    text = "слово " * 120
    parts = stream(text)
    assert len(parts) > 1
    assert all(len(p) <= 310 for p in parts)


def test_english_placeholder():
    assert stream("Look:\n```\nx\n```\n", lang="en") == ["Look:", "The code is on the screen."]
