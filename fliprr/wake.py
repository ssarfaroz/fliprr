"""Wake phrase detection on transcripts.

Every utterance is transcribed; an utterance is addressed to the assistant
when one of its first few words sounds like "Claude":

    «Клод Код, запусти тесты»      → target "code", command "запусти тесты"
    «Слушай, Клод, что такое DNS?» → target "chat", command "что такое DNS?"

Whisper spells the names inconsistently, so matching is phonetic and also
accepts the misrecognitions observed in practice («Код-код», «Клод-код»,
«Клод, Клод», «Claudecode», «Клауд код»…).
"""

from __future__ import annotations

from dataclasses import dataclass

from fliprr.text import normalize, phonetic_key, word_spans

CODE = "code"
CHAT = "chat"

_CLAUDE_KEY = "KLAT"
# Russian case endings / English possessive: Клода, Клоду, Клодом, Claude's.
_CLAUDE_SUFFIXES = {"", "A", "AM", "S"}
# Explicit spellings of "Code": a phonetic key would also match «куда», «кит», «got».
_CODE_WORDS = {
    "код", "кот", "коуд", "кода", "коду", "кодом", "коде", "коды", "кодд",
    "code", "cod", "codes", "kod", "coder",
}
_CODE_SUFFIX_KEYS = {"KAT", "KATA", "KATAM", "KATS"}
_PUNCT = " \t\r\n,.!?:;—–-…\"'«»()"
_FILLERS = {"давай", "слушай", "эй", "ну", "так", "а", "ок", "окей", "hey", "ok", "okay", "listen"}


@dataclass(frozen=True)
class WakeMatch:
    target: str  # CODE or CHAT
    command: str  # text after the wake phrase, original spelling
    wake_text: str  # the matched wake phrase as heard

    @property
    def wake_only(self) -> bool:
        """True when the user only called the assistant («Клод!») without a request."""
        rest = normalize(self.command).split()
        return all(w in _FILLERS for w in rest)


class WakeMatcher:
    def __init__(
        self,
        max_prefix_words: int = 3,
        default_target: str = CHAT,
        extra_claude_words: list[str] | tuple[str, ...] = (),
        extra_code_words: list[str] | tuple[str, ...] = (),
    ) -> None:
        if default_target not in (CODE, CHAT):
            raise ValueError(f"default_target must be {CODE!r} or {CHAT!r}")
        self.max_prefix_words = max(1, max_prefix_words)
        self.default_target = default_target
        self._extra_claude = {normalize(w) for w in extra_claude_words if normalize(w)}
        self._code_words = _CODE_WORDS | {normalize(w) for w in extra_code_words if normalize(w)}

    def claude_kind(self, word: str) -> str | None:
        """"claude" for a Claude-like word, "compound" for «клодкод», else None."""
        if word in self._extra_claude:
            return "claude"
        key = phonetic_key(word)
        if not key.startswith(_CLAUDE_KEY):
            return None
        rest = key[len(_CLAUDE_KEY):]
        if rest in _CLAUDE_SUFFIXES:
            return "claude"
        if rest in _CODE_SUFFIX_KEYS:
            return "compound"
        return None

    def is_code_word(self, word: str) -> bool:
        return word in self._code_words

    def match(self, text: str) -> WakeMatch | None:
        spans = word_spans(text)
        budget = self.max_prefix_words  # fillers («эй, слушай, ну…») don't count
        for i in range(len(spans)):
            if budget <= 0:
                break
            word = spans[i][0]
            if word not in _FILLERS:
                budget -= 1
            nxt = spans[i + 1][0] if i + 1 < len(spans) else None
            kind = self.claude_kind(word)
            if kind == "compound":
                return self._make(CODE, text, spans, i, i)
            if kind == "claude":
                # «Клод Код» — and «Клод, Клод», which is how Whisper often
                # garbles «Клод Код». When unsure, prefer Claude Code: it can
                # answer anything chat can.
                if nxt is not None and (self.is_code_word(nxt) or self.claude_kind(nxt) == "claude"):
                    return self._make(CODE, text, spans, i, i + 1)
                return self._make(self.default_target, text, spans, i, i)
            # «Код-код, …» is a frequent misrecognition of «Клод Код, …».
            if i == 0 and self.is_code_word(word) and nxt is not None and self.is_code_word(nxt):
                return self._make(CODE, text, spans, i, i + 1)
        return None

    def find_anywhere(self, text: str) -> list[int]:
        """Indexes of all Claude-like words (used for barge-in "…Клод, стоп…")."""
        return [i for i, (w, _, _) in enumerate(word_spans(text)) if self.claude_kind(w)]

    @staticmethod
    def _make(target: str, text: str, spans: list[tuple[str, int, int]], i: int, j: int) -> WakeMatch:
        start, end = spans[i][1], spans[j][2]
        command = text[end:].lstrip(_PUNCT).strip()
        return WakeMatch(target=target, command=command, wake_text=text[start:end])
