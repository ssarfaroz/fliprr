"""Turn a Claude Code permission request into a short spoken question."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from fliprr.i18n import t
from fliprr.text import shorten


def _base(path: str) -> str:
    return os.path.basename(path.rstrip("/\\")) or path


def describe_permission(tool: str, data: dict[str, Any], lang: str, title: str | None = None) -> tuple[str, str]:
    """Return (spoken question, details for the screen)."""
    if tool == "Bash":
        command = str(data.get("command", ""))
        what = str(data.get("description") or "") or shorten(command, 80)
        return t(lang, "perm_bash", what=what.rstrip(".")), command
    if tool in ("Edit", "MultiEdit", "NotebookEdit"):
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        return t(lang, "perm_edit", file=_base(path)), path
    if tool == "Write":
        path = str(data.get("file_path", ""))
        exists = bool(path) and os.path.exists(path)
        return t(lang, "perm_overwrite" if exists else "perm_create", file=_base(path)), path
    if tool == "WebFetch":
        url = str(data.get("url", ""))
        return t(lang, "perm_fetch", host=urlparse(url).netloc or url), url
    if tool == "WebSearch":
        query = str(data.get("query", ""))
        return t(lang, "perm_search", query=shorten(query, 80)), query
    if tool == "ExitPlanMode":
        return t(lang, "perm_plan"), str(data.get("plan", ""))[:2000]
    if tool in ("Task", "Agent"):
        what = str(data.get("description") or data.get("prompt") or "")
        return t(lang, "perm_agent", what=shorten(what, 80)), str(data.get("prompt", ""))[:2000]
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        name = parts[-1].replace("_", " ")
        server = parts[1] if len(parts) > 2 else ""
        return t(lang, "perm_mcp", tool=name, server=server), _compact(data)
    if title:
        return title.rstrip(".") + "?", _compact(data)
    return t(lang, "perm_generic", tool=tool), _compact(data)


def _compact(data: dict[str, Any]) -> str:
    parts = [f"{k}={shorten(str(v), 120)}" for k, v in data.items()]
    return ", ".join(parts)[:600]
