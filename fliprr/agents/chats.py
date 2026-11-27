"""Named voice chats («открой чат рецепты»), each a resumable Claude session."""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_CHAT = "default"


class ChatStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.current = DEFAULT_CHAT
        self.chats: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.current = str(data.get("current") or DEFAULT_CHAT)
        chats = data.get("chats")
        if isinstance(chats, dict):
            self.chats = {str(k): v for k, v in chats.items() if isinstance(v, dict)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"current": self.current, "chats": self.chats}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    def names(self) -> list[str]:
        return list(self.chats)

    def session_of(self, name: str) -> str | None:
        return self.chats.get(name, {}).get("session_id")

    def remember(self, name: str, session_id: str) -> None:
        entry = self.chats.setdefault(name, {})
        entry["session_id"] = session_id
        entry["updated"] = int(time.time())
        self.save()

    def switch(self, name: str) -> bool:
        """Make ``name`` current. Returns True if the chat already existed."""
        existed = name in self.chats
        self.current = name
        self.chats.setdefault(name, {"updated": int(time.time())})
        self.save()
        return existed

    def reset_current(self) -> None:
        self.chats[self.current] = {"updated": int(time.time())}
        self.save()
