"""Console output: what was heard, what Claude says and does."""

from __future__ import annotations

import os
import sys
import threading
import time

_COLORS = {
    "dim": "\033[2m", "bold": "\033[1m", "red": "\033[31m", "green": "\033[32m",
    "yellow": "\033[33m", "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
    "reset": "\033[0m",
}


def _enable_windows_ansi() -> bool:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001
        return False


class Console:
    def __init__(self, *, color: bool | None = None, verbose: bool = False, stream=None) -> None:  # noqa: ANN001
        self.stream = stream or sys.stdout
        if color is None:
            color = self.stream.isatty() and os.environ.get("NO_COLOR") is None
            if color and sys.platform == "win32":
                color = _enable_windows_ansi()
        self.color = color
        self.verbose = verbose
        self._lock = threading.Lock()
        try:  # Russian text on Windows consoles
            self.stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    def _c(self, name: str, text: str) -> str:
        return f"{_COLORS[name]}{text}{_COLORS['reset']}" if self.color else text

    def _print(self, line: str) -> None:
        with self._lock:
            print(f"{self._c('dim', time.strftime('%H:%M:%S'))} {line}", file=self.stream, flush=True)

    # -- events --------------------------------------------------------------------

    def info(self, text: str) -> None:
        self._print(text)

    def state(self, text: str) -> None:
        self._print(self._c("cyan", text))

    def warn(self, text: str) -> None:
        self._print(self._c("yellow", "! " + text))

    def error(self, text: str) -> None:
        self._print(self._c("red", "✖ " + text))

    def debug(self, text: str) -> None:
        if self.verbose:
            self._print(self._c("dim", text))

    def heard(self, text: str, note: str = "") -> None:
        suffix = f" ({note})" if note else ""
        self._print(self._c("dim", f"🎙  {text}{suffix}"))

    def command(self, label: str, text: str) -> None:
        self._print(self._c("bold", f"▶ {label}: ") + text)

    def agent(self, label: str, line: str) -> None:
        self._print(self._c("green", f"{label}: ") + line)

    def tool(self, label: str, name: str, detail: str) -> None:
        detail = f" {detail}" if detail else ""
        self._print(self._c("magenta", f"  ⚙ {name}") + self._c("dim", detail))

    def ask(self, question: str, details: str) -> None:
        self._print(self._c("yellow", f"❓ {question}") + (self._c("dim", f"  [{details}]") if details else ""))

    def answer(self, answer: str) -> None:
        self._print(self._c("yellow", f"   → {answer}"))

    def result(self, label: str, seconds: float, cost: float | None) -> None:
        cost_text = f", ${cost:.3f}" if cost else ""
        self._print(self._c("dim", f"✔ {label}: {seconds:.1f} s{cost_text}"))
