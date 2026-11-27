"""Locate the Claude Code CLI the Agent SDK will use, and ask it about login."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from fliprr.config import Config


def find_cli(cfg: Config) -> str | None:
    """Same order as the SDK: explicit path, the bundled CLI, then PATH."""
    if cfg.claude_code.cli_path:
        return cfg.claude_code.cli_path
    try:
        import claude_agent_sdk

        base = Path(claude_agent_sdk.__file__).parent / "_bundled"
        for name in ("claude.exe", "claude"):
            if (base / name).is_file():
                return str(base / name)
    except ImportError:
        pass
    return shutil.which("claude")


def version(cli: str) -> str:
    out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
    return (out.stdout or out.stderr).strip()


def auth_status(cli: str) -> dict | None:
    """``claude auth status --json`` (doesn't use any tokens). None if unknown."""
    try:
        out = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def login(cli: str) -> int:
    """Interactive ``claude auth login`` in this terminal."""
    return subprocess.call([cli, "auth", "login"])
