import pytest

from fliprr import intents as it
from fliprr.wake import WakeMatcher

PROJECTS = ["блог", "фронтенд", "fliprr"]


def parse(text, target="code"):
    return it.parse_intent(text, target, project_names=PROJECTS)


@pytest.mark.parametrize("text", ["стоп", "Стоп!", "хватит", "отмена", "остановись", "stop", "Стоп, стоп."])
def test_stop(text):
    assert parse(text) == it.Intent(it.STOP)


def test_stop_then_request():
    assert parse("Стоп, сделай по-другому") == it.Intent(it.STOP, rest="сделай по-другому")
    assert parse("Подожди. Лучше используй pytest") == it.Intent(it.STOP, rest="Лучше используй pytest")


@pytest.mark.parametrize("text", ["отмени последний коммит", "останови сервер на порту 3000", "прекрати использовать var"])
def test_tasks_that_start_like_stop_go_to_claude(text):
    assert parse(text) is None


def test_mute_and_others():
    assert parse("замолчи").kind == it.MUTE
    assert parse("повтори").kind == it.REPEAT
    assert parse("спи").kind == it.PAUSE
    assert parse("проснись").kind == it.RESUME
    assert parse("что ты умеешь").kind == it.HELP
    assert parse("что ты делаешь?").kind == it.STATUS
    assert parse("статус гита") is None  # a task, not a status question


def test_new_session():
    assert parse("новая сессия").kind == it.NEW_SESSION
    assert parse("Начни заново.") == it.Intent(it.NEW_SESSION)
    assert parse("Новая сессия. Создай файл README") == it.Intent(it.NEW_SESSION, rest="Создай файл README")
    assert parse("новый чат", "chat").kind == it.NEW_SESSION
    assert parse("продолжи прошлую сессию").kind == it.CONTINUE_LAST


def test_projects():
    assert parse("переключись на проект блог") == it.Intent(it.SWITCH_PROJECT, arg="блог")
    assert parse("проект фронтенд") == it.Intent(it.SWITCH_PROJECT, arg="фронтенд")
    assert parse("открой проект флиппер") == it.Intent(it.SWITCH_PROJECT, arg="fliprr")  # sounds alike
    assert parse("Открой проект Fliprr.") == it.Intent(it.SWITCH_PROJECT, arg="fliprr")
    # unknown names and real tasks are left to Claude Code
    assert parse("открой проект на React и добавь кнопку") is None
    assert parse("создай новый проект на Django") is None
    assert parse("какие проекты").kind == it.LIST_PROJECTS
    assert it.parse_intent("проект блог", "code", project_names=[]) is None


def test_permission_modes():
    assert parse("разрешай правки").kind == it.ACCEPT_EDITS
    assert parse("спрашивай разрешение").kind == it.ASK_PERMISSIONS
    assert parse("разрешай правки", "chat") is None


def test_open_chat():
    assert parse("открой мне чат рецепты, напиши как приготовить борщ, потом озвучь мне это", "chat") == it.Intent(
        it.OPEN_CHAT, arg="рецепты", rest="напиши как приготовить борщ, потом озвучь мне это"
    )
    assert parse("открой чат про путешествия", "chat") == it.Intent(it.OPEN_CHAT, arg="путешествия")
    assert parse("создай чат английский язык. Как будет кошка?", "chat") == it.Intent(
        it.OPEN_CHAT, arg="английский язык", rest="Как будет кошка?"
    )
    assert parse("новый чат путешествия", "chat") == it.Intent(it.OPEN_CHAT, arg="путешествия")
    assert parse("открой чат рецепты как приготовить борщ", "chat") == it.Intent(
        it.OPEN_CHAT, arg="рецепты", rest="как приготовить борщ"
    )
    assert parse("чат GPT лучше тебя?", "chat") is None
    assert parse("какие у меня чаты", "chat").kind == it.LIST_CHATS


def test_match_name():
    assert it.match_name("Блог", PROJECTS) == "блог"
    assert it.match_name("фронт енд", PROJECTS) == "фронтенд"
    assert it.match_name("бэкенд", PROJECTS) is None
    assert it.match_name("", PROJECTS) is None


@pytest.mark.parametrize(
    "text, answer",
    [
        ("да", it.YES), ("Да, разрешаю.", it.YES), ("ну давай", it.YES), ("окей", it.YES),
        ("конечно", it.YES), ("yes", it.YES), ("go ahead", it.YES),
        ("нет", it.NO), ("не надо", it.NO), ("не разрешаю", it.NO), ("отмена", it.NO),
        ("нет, не надо", it.NO), ("don't", it.NO), ("да нет, не надо", it.NO), ("стоп", it.NO),
        ("всегда", it.ALWAYS), ("разрешай всегда", it.ALWAYS), ("больше не спрашивай", it.ALWAYS),
        ("Да, и больше не спрашивай", it.ALWAYS),
        ("что?", None), ("", None), ("подумаю", None),
    ],
)
def test_yes_no(text, answer):
    assert it.parse_yes_no(text) == answer


def test_barge_in():
    is_claude = WakeMatcher().claude_kind
    assert it.find_barge_in("и тогда функция вернёт Клод стоп список", is_claude) == it.STOP
    assert it.find_barge_in("Клод Код, стоп", is_claude) == it.STOP
    assert it.find_barge_in("ответ такой Клод замолчи", is_claude) == it.MUTE
    assert it.find_barge_in("и тогда функция вернёт список", is_claude) is None
    assert it.find_barge_in("стоп", is_claude) is None
