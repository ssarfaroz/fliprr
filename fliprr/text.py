"""Text helpers shared by wake-word matching, intent parsing and echo detection.

Speech recognition spells the same spoken word in many ways ("Клод", "Клот",
"Claude", "Клауд"…), so matching is done on a coarse *phonetic key* that maps
Cyrillic and Latin spellings of similar sounds to the same string.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Sound classes: all vowels collapse to "A"; voiced/voiceless pairs that
# Russian word-final devoicing confuses (д/т, г/к) share a class.
_CYR = {
    "а": "A", "е": "A", "ё": "A", "и": "A", "о": "A", "у": "A", "ы": "A",
    "э": "A", "ю": "A", "я": "A", "й": "A",
    "к": "K", "г": "K", "х": "H", "л": "L", "д": "T", "т": "T", "б": "B",
    "п": "P", "в": "V", "ф": "F", "з": "Z", "с": "S", "ж": "Z", "ш": "S",
    "щ": "S", "ч": "C", "ц": "S", "м": "M", "н": "N", "р": "R",
    "ь": "", "ъ": "",
}
_LAT = {
    "a": "A", "e": "A", "i": "A", "o": "A", "u": "A", "y": "A", "w": "A",
    "c": "K", "k": "K", "q": "K", "g": "K", "x": "KS", "h": "", "l": "L",
    "d": "T", "t": "T", "b": "B", "p": "P", "v": "V", "f": "F", "z": "Z",
    "s": "S", "j": "Z", "m": "M", "n": "N", "r": "R",
}


def normalize(text: str) -> str:
    """Lowercase, ё→е, drop punctuation, collapse whitespace."""
    return " ".join(_WORD_RE.findall(text.lower().replace("ё", "е")))


def words(text: str) -> list[str]:
    return normalize(text).split()


def word_spans(text: str) -> list[tuple[str, int, int]]:
    """Words of ``text`` (normalized) with their character spans in ``text``."""
    return [
        (m.group(0).lower().replace("ё", "е"), m.start(), m.end())
        for m in _WORD_RE.finditer(text)
    ]


def phonetic_key(word: str) -> str:
    """Coarse sound-alike key: "Клод", "клот", "Claude", "cloud" → "KLAT"."""
    w = word.lower().replace("ё", "е")
    if len(w) > 3 and w.endswith("e") and w.isascii():
        w = w[:-1]  # silent final e: claude → claud, code → cod
    out: list[str] = []
    for ch in w:
        code = _CYR.get(ch)
        if code is None:
            code = _LAT.get(ch)
        if code is None:
            code = ch if ch.isdigit() else ""
        for c in code:
            if not out or out[-1] != c:
                out.append(c)
    return "".join(out)


def keys(text: str) -> list[str]:
    return [k for k in (phonetic_key(w) for w in words(text)) if k]


def overlap_ratio(text: str, reference_keys: set[str]) -> float:
    """Share of ``text``'s words whose phonetic key occurs in ``reference_keys``."""
    ks = keys(text)
    if not ks:
        return 0.0
    return sum(1 for k in ks if k in reference_keys) / len(ks)


def script_of(text: str) -> str:
    """Return "ru" if Cyrillic letters dominate, else "en"."""
    cyr = sum(1 for ch in text if "а" <= ch.lower() <= "я" or ch in "ёЁ")
    lat = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    return "ru" if cyr >= lat else "en"


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]) + "…"
