"""Start fliprr automatically when you log in, and keep it running.

* Windows — a value in HKCU\\…\\Run (no admin rights needed). It starts
  ``python -m fliprr service`` in its own console window, which minimizes
  itself; close that window to stop fliprr until the next login.
* Linux — a systemd user service (``systemctl --user``).
* macOS — a login item that opens ``~/Applications/fliprr.command`` in
  Terminal (Terminal already has, or will ask for, microphone access).

``fliprr service`` restarts ``fliprr run`` if it crashes or the microphone
is missing at login (e.g. a Bluetooth headset not connected yet).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "fliprr"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartError(RuntimeError):
    pass


def service_argv() -> list[str]:
    return [sys.executable, "-m", "fliprr", "service"]


# -- Windows ---------------------------------------------------------------------------


def _win_command() -> str:
    return subprocess.list2cmdline(service_argv())


def _win_enable() -> str:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _win_command())
    return "fliprr будет запускаться при входе в Windows (свёрнутое окно «fliprr»)."


def _win_disable() -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
    except FileNotFoundError:
        pass
    return "Автозапуск выключен."


def _win_status() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
        return True
    except FileNotFoundError:
        return False


def _win_start() -> None:
    subprocess.Popen(service_argv(), cwd=str(Path.home()),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


# -- Linux -----------------------------------------------------------------------------

_UNIT = """\
[Unit]
Description=fliprr — voice control for Claude Code
After=pipewire.service pulseaudio.service

[Service]
ExecStart={command}
WorkingDirectory=%h
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / f"{NAME}.service"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)


def _linux_enable() -> str:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    command = shlex.join([sys.executable, "-m", "fliprr", "run", "--no-color"])
    path.write_text(_UNIT.format(command=command), encoding="utf-8")
    if not shutil.which("systemctl"):
        raise AutostartError(f"systemd не найден; файл службы записан в {path}, запусти его своим способом")
    _systemctl("daemon-reload")
    result = _systemctl("enable", "--now", f"{NAME}.service")
    if result.returncode != 0:
        raise AutostartError(f"systemctl: {result.stderr.strip() or result.stdout.strip()}")
    return "fliprr запущен и будет стартовать при входе (журнал: journalctl --user -u fliprr -f)."


def _linux_disable() -> str:
    if shutil.which("systemctl"):
        _systemctl("disable", "--now", f"{NAME}.service")
    unit_path().unlink(missing_ok=True)
    return "Автозапуск выключен."


def _linux_status() -> bool:
    return unit_path().is_file()


# -- macOS -----------------------------------------------------------------------------


def command_file() -> Path:
    return Path.home() / "Applications" / f"{NAME}.command"


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)


def _mac_enable() -> str:
    path = command_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/bash\ncd ~\nexec {shlex.join(service_argv())}\n", encoding="utf-8")
    path.chmod(0o755)
    result = _osascript(
        'tell application "System Events" to make login item at end with properties '
        f'{{path:"{path}", hidden:false}}'
    )
    if result.returncode != 0:
        raise AutostartError(
            f"не удалось добавить объект входа ({result.stderr.strip()}). Добавь вручную: "
            f"Системные настройки → Основные → Объекты входа → «+» → {path}"
        )
    return "fliprr будет запускаться при входе (окно Терминала)."


def _mac_disable() -> str:
    _osascript(f'tell application "System Events" to delete login item "{NAME}.command"')
    command_file().unlink(missing_ok=True)
    return "Автозапуск выключен."


def _mac_status() -> bool:
    return command_file().is_file()


def _mac_start() -> None:
    subprocess.Popen(["open", str(command_file())])


# -- public ----------------------------------------------------------------------------


def enable() -> str:
    if sys.platform == "win32":
        return _win_enable()
    if sys.platform == "darwin":
        return _mac_enable()
    return _linux_enable()


def disable() -> str:
    if sys.platform == "win32":
        return _win_disable()
    if sys.platform == "darwin":
        return _mac_disable()
    return _linux_disable()


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_status()
    if sys.platform == "darwin":
        return _mac_status()
    return _linux_status()


def start_now() -> bool:
    """Start the background instance now. False if enabling already started it."""
    if sys.platform == "win32":
        _win_start()
        return True
    if sys.platform == "darwin":
        _mac_start()
        return True
    return False  # systemctl enable --now already started it


def prepare_console() -> None:
    """Windows: title the service window and tuck it into the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW("fliprr")
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    except Exception:  # noqa: BLE001 — purely cosmetic
        pass
