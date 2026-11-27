"""fliprr's own spoken phrases."""

from __future__ import annotations

_PHRASES: dict[str, dict[str, str]] = {
    "ru": {
        "ready": "Я слушаю. Скажи «Клод» — для разговора, или «Клод Код» — для задач в проекте.",
        "queued": "Добавил в очередь, сделаю после текущей задачи.",
        "stopped": "Остановил.",
        "nothing_to_stop": "",
        "new_session": "Хорошо, начинаю новую сессию.",
        "new_chat": "Хорошо, новый чат.",
        "continue_last": "Продолжаю прошлую сессию.",
        "chat_opened": "Открыл чат «{name}».",
        "chat_created": "Создал чат «{name}».",
        "chats_list": "Твои чаты: {names}. Сейчас открыт «{current}».",
        "no_chats": "Пока есть только текущий чат.",
        "project_switched": "Переключился на проект «{name}».",
        "projects_list": "Проекты: {names}. Сейчас открыт «{current}».",
        "no_projects": "Проекты не настроены. Работаю в папке {cwd}.",
        "paused": "Хорошо, не слушаю. Скажи «Клод, проснись», когда понадоблюсь.",
        "resumed": "Снова слушаю.",
        "nothing_to_repeat": "Мне пока нечего повторить.",
        "status_idle": "Свободен. Проект «{project}».",
        "status_busy": "Работаю над задачей: {task}.",
        "status_queue": "В очереди ещё {count}.",
        "confirm_hint": "Скажи «да» или «нет».",
        "confirm_timeout": "Не услышал ответа, отменяю это действие.",
        "denied": "Хорошо, не буду.",
        "error": "Ошибка: {error}",
        "auth_error": "Claude Code не авторизован. Выполни в терминале команду fliprr login.",
        "cli_error": "Не получилось запустить Claude Code. Подробности на экране.",
        "rate_limit": "Достигнут лимит использования Claude. Попробуй позже.",
        "billing_error": "Проблема с оплатой аккаунта Claude.",
        "turn_failed": "Что-то пошло не так. Подробности на экране.",
        "max_turns": "Задача остановлена: слишком много шагов.",
        "truncated": "Остальное на экране.",
        "accept_edits_on": "Хорошо, правки файлов применяю без вопросов.",
        "accept_edits_off": "Хорошо, буду спрашивать разрешение.",
        "help": (
            "Чтобы дать задачу в проекте, скажи «Клод Код» и задачу. "
            "Чтобы просто поговорить, скажи «Клод» и вопрос. "
            "После ответа можно продолжать без имени несколько секунд. "
            "Команды: стоп, замолчи, повтори, новая сессия, проект и название, "
            "открой чат и название, разрешай правки, спи и проснись."
        ),
        "perm_bash": "Выполнить команду: {what}?",
        "perm_edit": "Изменить файл {file}?",
        "perm_create": "Создать файл {file}?",
        "perm_overwrite": "Перезаписать файл {file}?",
        "perm_fetch": "Открыть страницу {host}?",
        "perm_search": "Поискать в интернете: {query}?",
        "perm_plan": "План готов. Начать выполнение?",
        "perm_agent": "Запустить помощника: {what}?",
        "perm_mcp": "Использовать инструмент «{tool}» из {server}?",
        "perm_generic": "Разрешить инструмент {tool}?",
        "tool_bash": "Выполняю команду.",
        "tool_edit": "Правлю {file}.",
        "tool_write": "Пишу {file}.",
        "tool_search": "Ищу в интернете.",
        "tool_agent": "Запускаю помощника.",
        "label_code": "Claude Code",
        "label_chat": "Claude",
    },
    "en": {
        "ready": "I'm listening. Say “Claude” to talk, or “Claude Code” for a task in your project.",
        "queued": "Queued. I'll do it after the current task.",
        "stopped": "Stopped.",
        "nothing_to_stop": "",
        "new_session": "OK, starting a new session.",
        "new_chat": "OK, new chat.",
        "continue_last": "Continuing the last session.",
        "chat_opened": "Opened the chat “{name}”.",
        "chat_created": "Created the chat “{name}”.",
        "chats_list": "Your chats: {names}. The current one is “{current}”.",
        "no_chats": "There is only the current chat so far.",
        "project_switched": "Switched to the project “{name}”.",
        "projects_list": "Projects: {names}. The current one is “{current}”.",
        "no_projects": "No projects configured. Working in {cwd}.",
        "paused": "OK, not listening. Say “Claude, wake up” when you need me.",
        "resumed": "Listening again.",
        "nothing_to_repeat": "Nothing to repeat yet.",
        "status_idle": "Idle. Project “{project}”.",
        "status_busy": "Working on: {task}.",
        "status_queue": "{count} more queued.",
        "confirm_hint": "Say yes or no.",
        "confirm_timeout": "No answer, so I'm skipping that action.",
        "denied": "OK, I won't.",
        "error": "Error: {error}",
        "auth_error": "Claude Code is not logged in. Run fliprr login in a terminal.",
        "cli_error": "Couldn't start Claude Code. Details are on the screen.",
        "rate_limit": "Claude usage limit reached. Try again later.",
        "billing_error": "There is a billing problem with the Claude account.",
        "turn_failed": "Something went wrong. Details are on the screen.",
        "max_turns": "Stopped: the task took too many steps.",
        "truncated": "The rest is on the screen.",
        "accept_edits_on": "OK, I'll apply file edits without asking.",
        "accept_edits_off": "OK, I'll ask for permission.",
        "help": (
            "For a task in your project, say “Claude Code” and the task. "
            "To just talk, say “Claude” and your question. "
            "After an answer you can go on without the name for a few seconds. "
            "Commands: stop, be quiet, repeat, new session, project and a name, "
            "open chat and a name, accept edits, sleep and wake up."
        ),
        "perm_bash": "Run the command: {what}?",
        "perm_edit": "Edit {file}?",
        "perm_create": "Create {file}?",
        "perm_overwrite": "Overwrite {file}?",
        "perm_fetch": "Open {host}?",
        "perm_search": "Search the web for {query}?",
        "perm_plan": "The plan is ready. Start working?",
        "perm_agent": "Start a helper agent: {what}?",
        "perm_mcp": "Use the tool “{tool}” from {server}?",
        "perm_generic": "Allow the tool {tool}?",
        "tool_bash": "Running a command.",
        "tool_edit": "Editing {file}.",
        "tool_write": "Writing {file}.",
        "tool_search": "Searching the web.",
        "tool_agent": "Starting a helper.",
        "label_code": "Claude Code",
        "label_chat": "Claude",
    },
}


def t(lang: str, key: str, **kwargs: object) -> str:
    table = _PHRASES.get(lang, _PHRASES["en"])
    text = table.get(key, _PHRASES["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text
