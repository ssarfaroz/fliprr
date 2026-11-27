"""Claude Code and Claude chat sessions, configured for voice."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fliprr import __version__
from fliprr.agents.prompts import CODE_APPEND, chat_system_prompt
from fliprr.agents.session import AgentSink, ClaudeSession, SessionSpec, TurnResult
from fliprr.config import Config

__all__ = [
    "AgentSink", "ClaudeSession", "SessionSpec", "TurnResult",
    "make_chat_options", "make_code_options",
]

WEB_TOOLS = ["WebSearch", "WebFetch"]


def _stderr_logger(log: Callable[[str], None], label: str) -> Callable[[str], None]:
    def write(line: str) -> None:
        line = line.rstrip()
        if line:
            log(f"[{label} stderr] {line}")

    return write


def make_code_options(cfg: Config, log: Callable[[str], None]) -> Callable[[SessionSpec, Any], Any]:
    from claude_agent_sdk import ClaudeAgentOptions

    cc = cfg.claude_code

    def build(spec: SessionSpec, can_use_tool: Any) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(spec.cwd),
            system_prompt={"type": "preset", "preset": "claude_code", "append": CODE_APPEND},
            setting_sources=list(cc.setting_sources),  # type: ignore[arg-type]
            permission_mode=(spec.permission_mode or cc.permission_mode or None),  # type: ignore[arg-type]
            allowed_tools=list(cc.auto_allow),
            # A voice user can't click through a multiple-choice form; Claude asks in text instead.
            disallowed_tools=["AskUserQuestion"],
            can_use_tool=can_use_tool,
            include_partial_messages=True,
            model=cc.model or None,
            effort=(cc.effort or None),  # type: ignore[arg-type]
            resume=spec.resume,
            continue_conversation=bool(spec.continue_conversation and not spec.resume),
            cli_path=cc.cli_path or None,
            stderr=_stderr_logger(log, "claude-code"),
            client_app=f"fliprr/{__version__}",
        )

    return build


def make_chat_options(cfg: Config, log: Callable[[str], None]) -> Callable[[SessionSpec, Any], Any]:
    from claude_agent_sdk import ClaudeAgentOptions

    chat = cfg.chat
    tools = WEB_TOOLS if chat.web else []

    def build(spec: SessionSpec, _can_use_tool: Any) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(spec.cwd),
            system_prompt=chat_system_prompt(web=chat.web, extra=chat.instructions),
            tools=list(tools),
            allowed_tools=list(tools),
            permission_mode="dontAsk",
            setting_sources=["user"],  # login helpers / env from ~/.claude/settings.json
            include_partial_messages=True,
            model=chat.model or None,
            effort=(chat.effort or None),  # type: ignore[arg-type]
            resume=spec.resume,
            cli_path=cfg.claude_code.cli_path or None,
            stderr=_stderr_logger(log, "claude"),
            client_app=f"fliprr/{__version__}",
        )

    return build
