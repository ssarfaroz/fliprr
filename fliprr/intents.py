"""Local voice commands handled by fliprr itself (not sent to Claude).

Only short, unambiguous phrases count as commands. Anything else goes to
Claude as is, so «отмени последний коммит» is a task for Claude Code, while
«отмена» or «стоп, сделай по-другому» stops the current one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fliprr.text import normalize, phonetic_key, word_spans

STOP = "stop"
MUTE = "mute"
NEW_SESSION = "new_session"
CONTINUE_LAST = "continue_last"
REPEAT = "repeat"
SWITCH_PROJECT = "switch_project"
LIST_PROJECTS = "list_projects"
OPEN_CHAT = "open_chat"
LIST_CHATS = "list_chats"
PAUSE = "pause"
RESUME = "resume"
STATUS = "status"
HELP = "help"
ACCEPT_EDITS = "accept_edits"
ASK_PERMISSIONS = "ask_permissions"


@dataclass(frozen=True)
class Intent:
    kind: str
    arg: str = ""  # project / chat name
    rest: str = ""  # request to send to Claude after handling the command


def _phrases(*items: str) -> tuple[str, ...]:
    # Longest first, so «стоп стоп» wins over «стоп».
    return tuple(sorted({normalize(p) for p in items}, key=len, reverse=True))


# Whole-command phrases that may also be followed by ", <request>".
_STOP = _phrases(
    "стоп", "стоп стоп", "хватит", "отмена", "отмени", "отменить", "остановись",
    "останови", "прекрати", "прекращай", "перестань", "стой", "подожди", "погоди",
    "stop", "stop it", "cancel", "abort", "halt", "wait",
)
# Phrases whose rest is never a separate request (they are verbs).
_STOP_VERBS = {normalize(p) for p in ("отмени", "отменить", "останови", "прекрати", "прекращай", "перестань")}
_MUTE = _phrases(
    "замолчи", "молчи", "тихо", "тише", "помолчи", "заткнись", "не говори",
    "хватит говорить", "be quiet", "quiet", "shut up", "silence", "mute",
)
_NEW_SESSION = _phrases(
    "новая сессия", "новую сессию", "начни новую сессию", "новый диалог",
    "новый разговор", "начни заново", "начнем заново", "давай заново",
    "давай сначала", "начни сначала", "сбрось контекст", "очисти контекст",
    "забудь все", "new session", "start over", "reset", "clear context",
    "new conversation", "start a new session",
)
_NEW_CHAT = _phrases("новый чат", "создай новый чат", "открой новый чат", "new chat")
_CONTINUE_LAST = _phrases(
    "продолжи прошлую сессию", "продолжи предыдущую сессию", "продолжи последнюю сессию",
    "вернись к прошлой сессии", "продолжим прошлую сессию", "continue last session",
    "resume last session", "continue previous session",
)
_REPEAT = _phrases(
    "повтори", "повтори пожалуйста", "еще раз", "повтори еще раз", "что ты сказал",
    "что", "не расслышал", "не понял повтори", "repeat", "say again",
    "say that again", "pardon", "what did you say",
)
_LIST_PROJECTS = _phrases(
    "какие проекты", "какие есть проекты", "список проектов", "покажи проекты",
    "какие у меня проекты", "list projects", "what projects",
)
_LIST_CHATS = _phrases(
    "какие чаты", "какие есть чаты", "какие у меня чаты", "список чатов",
    "покажи чаты", "list chats", "what chats",
)
_PAUSE = _phrases(
    "спи", "спит", "спать", "иди спать", "усни", "засыпай", "не слушай", "перестань слушать",
    "режим сна", "пауза", "на паузу", "отдыхай", "sleep", "go to sleep", "stop listening", "pause",
)
_RESUME = _phrases(
    "проснись", "просыпайся", "вставай", "слушай", "начни слушать", "я тут",
    "wake up", "start listening", "resume",
)
_STATUS = _phrases(
    "статус", "твой статус", "что делаешь", "что ты делаешь", "ты тут", "ты здесь",
    "ты работаешь", "чем занят", "ты занят", "status", "what are you doing",
    "are you there", "are you busy",
)
_HELP = _phrases(
    "помощь", "что ты умеешь", "какие команды", "команды", "справка", "help",
    "what can you do",
)
_ACCEPT_EDITS = _phrases(
    "разрешай правки", "разрешаю правки", "разрешай все правки", "разрешай редактировать",
    "редактируй без вопросов", "правь без вопросов", "не спрашивай про правки",
    "принимай правки", "accept edits", "auto accept edits",
)
_ASK_PERMISSIONS = _phrases(
    "спрашивай разрешение", "спрашивай разрешения", "спрашивай перед правками",
    "спрашивай перед изменениями", "ask permission", "ask for permission",
    "ask before edits",
)

_BREAK = re.compile(r"\s*[,.!?:;—–…-]+\s*")
_PROJECT_RE = re.compile(
    r"^(?:(?:переключись|переключи|перейди|открой|смени|выбери|возьми|switch|go|open|use)\s+)?"
    r"(?:(?:на|в|to)\s+)?(?:проект|папку|репозиторий|project|repo|folder)\s+(?P<name>.+)$"
)
# A verb (or «новый») is required so that «чат GPT лучше?» stays a question.
_CHAT_RE = re.compile(
    r"^(?:(?:открой|создай|начни|запусти|переключись\s+на|перейди\s+в|вернись\s+в|open|start|switch\s+to|go\s+to)"
    r"\s+(?:мне\s+)?(?:новый\s+)?|(?:новый|new)\s+)(?:чат|chat)\b"
)
_CHAT_NAME_PREFIX = {"про", "о", "об", "по", "на", "тему", "под", "с", "названием", "называется", "about", "named", "called", "on"}


def _match(command: str, phrases: tuple[str, ...], *, allow_rest: bool = True) -> tuple[bool, str]:
    """Match ``command`` against ``phrases`` as a whole, or as "<phrase>, <rest>"."""
    norm = normalize(command)
    for phrase in phrases:
        if norm == phrase:
            return True, ""
        if allow_rest and norm.startswith(phrase + " "):
            spans = word_spans(command)
            n = len(phrase.split())
            after = command[spans[n - 1][2]:]
            m = _BREAK.match(after)
            if m and m.group(0).strip():
                return True, after[m.end():].strip()
    return False, ""


def parse_intent(command: str, target: str, *, project_names: list[str] | None = None) -> Intent | None:
    """Return the local command in ``command`` (already stripped of the wake phrase)."""
    norm = normalize(command)
    if not norm:
        return None

    ok, rest = _match(command, _STOP)
    if ok:
        first = next((p for p in _STOP if norm == p or norm.startswith(p + " ")), "")
        if rest and first in _STOP_VERBS:
            return None  # «отмени, последний коммит» is ambiguous enough — let Claude decide
        return Intent(STOP, rest=rest)
    for phrases, kind in ((_MUTE, MUTE), (_PAUSE, PAUSE), (_RESUME, RESUME), (_REPEAT, REPEAT),
                          (_STATUS, STATUS), (_HELP, HELP)):
        if _match(command, phrases, allow_rest=False)[0]:
            return Intent(kind)

    ok, rest = _match(command, _NEW_SESSION)
    if ok:
        return Intent(NEW_SESSION, rest=rest)

    if target == "code":
        for phrases, kind in ((_CONTINUE_LAST, CONTINUE_LAST), (_ACCEPT_EDITS, ACCEPT_EDITS),
                              (_ASK_PERMISSIONS, ASK_PERMISSIONS), (_LIST_PROJECTS, LIST_PROJECTS)):
            if _match(command, phrases, allow_rest=False)[0]:
                return Intent(kind)
        m = _PROJECT_RE.match(norm)
        if m and project_names:
            name = match_name(m.group("name"), project_names)
            if name is not None:
                return Intent(SWITCH_PROJECT, arg=name)
        return None

    # chat
    ok, rest = _match(command, _NEW_CHAT)
    if ok:
        return Intent(NEW_SESSION, rest=rest)
    if _match(command, _LIST_CHATS, allow_rest=False)[0]:
        return Intent(LIST_CHATS)
    return _parse_open_chat(command)


def _parse_open_chat(command: str) -> Intent | None:
    """«открой чат рецепты, напиши как сварить борщ» → name "рецепты" + rest."""
    norm = normalize(command)
    m = _CHAT_RE.match(norm)
    if not m:
        return None
    spans = word_spans(command)
    n_words = len(m.group(0).split())
    idx = n_words
    while idx < len(spans) and spans[idx][0] in _CHAT_NAME_PREFIX:
        idx += 1
    if idx >= len(spans):
        return None
    # The name runs up to a punctuation mark within 4 words («чат английский
    # язык, …»), or is the whole rest if that is 1–2 words; otherwise it is
    # the first word and the rest is a message («чат рецепты как сварить борщ»).
    end = idx
    for k in range(idx, min(idx + 4, len(spans) - 1)):
        if _BREAK.fullmatch(command[spans[k][2]:spans[k + 1][1]]):
            end = k
            break
    else:
        if len(spans) - idx <= 2:
            end = len(spans) - 1
    name = command[spans[idx][1]:spans[end][2]]
    rest = command[spans[end][2]:].lstrip(" \t,.!?:;—–-…").strip()
    return Intent(OPEN_CHAT, arg=name.strip(), rest=rest)


def match_name(spoken: str, names: list[str]) -> str | None:
    """Fuzzy-match a spoken name against known project/chat names."""
    spoken_n = normalize(spoken)
    if not spoken_n or len(spoken_n.split()) > 4:
        return None
    by_norm = {normalize(n): n for n in names}
    if spoken_n in by_norm:
        return by_norm[spoken_n]
    spoken_key = "".join(phonetic_key(w) for w in spoken_n.split())
    best, best_score = None, 0.0
    for norm_name, original in by_norm.items():
        key = "".join(phonetic_key(w) for w in norm_name.split())
        score = _similarity(spoken_key, key)
        if score > best_score:
            best, best_score = original, score
    return best if best_score >= 0.75 else None


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # Levenshtein distance → similarity in [0, 1]
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


# --- barge-in: «…Клод, стоп…» anywhere in an utterance -------------------------

_BARGE_STOP = {"стоп", "хватит", "отмена", "остановись", "стой", "stop", "cancel"}
_BARGE_MUTE = {"замолчи", "молчи", "тихо", "тише", "помолчи", "quiet", "silence"}


def find_barge_in(text: str, is_claude_word) -> str | None:  # noqa: ANN001
    """While the assistant talks, the microphone also hears it, so the user's
    «Клод, стоп» can end up in the middle of a transcript."""
    spans = word_spans(text)
    for i, (word, _, _) in enumerate(spans):
        if is_claude_word(word):
            for nxt, _, _ in spans[i + 1:i + 3]:  # «Клод Код, стоп»
                if nxt in _BARGE_STOP:
                    return STOP
                if nxt in _BARGE_MUTE:
                    return MUTE
    return None


# --- yes / no answers to permission questions ---------------------------------

YES = "yes"
NO = "no"
ALWAYS = "always"

_NO_WORDS = {
    "нет", "не", "неа", "нельзя", "отмена", "отмени", "стоп", "запрещаю", "отклонить",
    "отклони", "никогда", "no", "nope", "nah", "don", "dont", "cancel", "deny", "stop", "never",
}
_YES_WORDS = {
    "да", "давай", "конечно", "разрешаю", "разреши", "можно", "ок", "окей", "ага", "угу",
    "выполняй", "делай", "делаем", "поехали", "подтверждаю", "согласен", "согласна", "верно",
    "разрешить", "одобряю", "запускай", "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
    "allow", "approve", "go", "do", "proceed", "fine",
}
_ALWAYS_PHRASES = ("всегда", "always", "больше не спрашивай", "не спрашивай больше", "dont ask again", "don t ask again")


def parse_yes_no(text: str) -> str | None:
    norm = normalize(text)
    ws = norm.split()
    if not ws:
        return None
    if ws[0] in _NO_WORDS or "нет" in ws or "не надо" in norm or "не нужно" in norm or "no" in ws[:2]:
        if not any(p in norm for p in ("не спрашивай", "dont ask", "don t ask")):
            return NO
    if any(p in norm for p in _ALWAYS_PHRASES):
        return ALWAYS
    if any(w in _YES_WORDS for w in ws[:3]):
        return YES
    return None
