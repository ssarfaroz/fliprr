"""Make Claude's Markdown-ish output pleasant to listen to.

``SpeechChunker`` takes the text as it streams in and hands out complete
sentences as soon as they are ready, so speech can start before the answer
is finished. Code blocks and tables are not read out; a short placeholder
("код на экране") is spoken instead — the full text is on the console.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PLACEHOLDERS = {
    "ru": {"code": "Код показан на экране.", "table": "Таблица показана на экране."},
    "en": {"code": "The code is on the screen.", "table": "The table is on the screen."},
}

_FENCE = re.compile(r"^\s*(```|~~~)")
_SENTENCE_END = re.compile(r"[.!?…]+[\"»)\]]*(?=\s)")
_URL = re.compile(r"https?://[^\s)>\]]+")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC = re.compile(r"(?<![\w*])[*_](?!\s)([^*_\n]+?)(?<!\s)[*_](?![\w*])")
_LINE_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+•]\s+|\[[ xX]\]\s+)")
_PATH = re.compile(r"(?<![\w/])(?:[A-Za-z]:)?(?:[\w.~-]*[/\\])+([\w.-]+\.[A-Za-z0-9]{1,8})\b")
_HEX = re.compile(r"\b([0-9a-f]{7})[0-9a-f]{5,}\b")
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D\U00002B00-\U00002BFF]"
)
_ARROWS = re.compile(r"\s*(?:->|=>|→|⟶|⇒)\s*")
_HAS_WORD = re.compile(r"[^\W_]", re.UNICODE)


def to_speakable(text: str) -> str:
    """Strip Markdown and other things that sound bad when read aloud."""
    s = _LINE_PREFIX.sub("", text)
    s = _MD_IMAGE.sub(r"\1", s)
    s = _MD_LINK.sub(r"\1", s)
    s = _URL.sub(lambda m: urlparse(m.group(0)).netloc or "", s)
    s = _INLINE_CODE.sub(r"\1", s)
    s = _BOLD.sub(r"\2", s)
    s = _ITALIC.sub(r"\1", s)
    s = _PATH.sub(r"\1", s)
    s = _HEX.sub(r"\1", s)
    s = _EMOJI.sub("", s)
    s = _ARROWS.sub(" — ", s)
    s = s.replace("**", "").replace("`", "").replace("|", " ")
    s = " ".join(s.split())
    return s if _HAS_WORD.search(s) else ""


class SpeechChunker:
    """Split streamed text into speakable sentences."""

    def __init__(self, lang: str = "ru", max_len: int = 300) -> None:
        self.placeholders = PLACEHOLDERS.get(lang, PLACEHOLDERS["en"])
        self.max_len = max_len
        self._buf = ""
        self._in_code = False
        self._in_table = False

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            piece = self._next_piece()
            if piece is None:
                break
            if piece:
                out.append(piece)
        return out

    def flush(self) -> list[str]:
        out = self.feed("\n")
        rest, self._buf = self._buf, ""
        if self._in_code:
            out.append(self.placeholders["code"])
        elif rest.strip():
            spoken = to_speakable(rest)
            if spoken:
                out.append(spoken)
        self._in_code = False
        self._in_table = False
        return out

    # -- internals -------------------------------------------------------------

    def _next_piece(self) -> str | None:
        """Consume one piece from the buffer; None means "need more text"."""
        buf = self._buf
        if self._in_code:
            # Drop complete lines of code until the closing fence.
            nl = buf.find("\n")
            while nl != -1:
                line, buf = buf[:nl], buf[nl + 1:]
                if _FENCE.match(line):
                    self._buf, self._in_code = buf, False
                    return self.placeholders["code"]
                nl = buf.find("\n")
            self._buf = buf
            return None

        nl = buf.find("\n")
        line = buf if nl == -1 else buf[:nl]
        stripped = line.lstrip()

        # Fences and tables are line-level: wait for the whole line.
        if stripped.startswith(("```", "~~~")):
            if nl == -1:
                return None
            self._buf, self._in_code = buf[nl + 1:], True
            return ""
        if stripped.startswith("|"):
            if nl == -1:
                return None
            self._buf = buf[nl + 1:]
            if not self._in_table:
                self._in_table = True
                return self.placeholders["table"]
            return ""
        if nl != -1:
            self._in_table = False

        m = _SENTENCE_END.search(line)
        if m:
            end = m.end()
            self._buf = buf[end:]
            return to_speakable(line[:end])
        if nl != -1:
            self._buf = buf[nl + 1:]
            return to_speakable(line)
        if len(line) > self.max_len:
            cut = max(line.rfind(", ", 0, self.max_len), line.rfind(" ", 0, self.max_len))
            if cut <= 0:
                cut = self.max_len
            self._buf = buf[cut + 1:]
            return to_speakable(line[: cut + 1])
        return None
