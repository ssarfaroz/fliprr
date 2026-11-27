"""`fliprr setup`: everything that has to be done once, in one go.

Project folder → speech model download → Claude login → microphone and
speakers → a test phrase → autostart → start now.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from fliprr import autostart, claude_cli, instance
from fliprr.config import ConfigError, app_dir, load_config
from fliprr.config_template import TEMPLATE
from fliprr.ui import Console


def config_path() -> Path:
    return Path(os.environ["FLIPRR_CONFIG"]) if os.environ.get("FLIPRR_CONFIG") else app_dir() / "config.toml"


def lock_path(data_dir: Path) -> Path:
    return data_dir / "fliprr.lock"


def toml_path(folder: Path) -> str:
    """A folder as a TOML string body (forward slashes work on Windows too)."""
    return str(folder).replace("\\", "/").replace('"', '\\"')


def write_project(path: Path, folder: Path) -> None:
    """Create the config from the template, or change only `cwd` in an existing one."""
    value = toml_path(folder)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.replace("{cwd}", value), encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    line = f'cwd = "{value}"'
    new, count = re.subn(r'(?m)^[ \t]*cwd[ \t]*=.*$', lambda _m: line, text, count=1)
    if count == 0:
        if re.search(r"(?m)^\[claude_code\][ \t]*$", text):
            new = re.sub(r"(?m)^\[claude_code\][ \t]*$", lambda _m: "[claude_code]\n" + line, text, count=1)
        else:
            new = text.rstrip() + f"\n\n[claude_code]\n{line}\n"
    path.write_text(new, encoding="utf-8")


def run_setup(
    ui: Console,
    *,
    project: str | None = None,
    assume_yes: bool = False,
    ask: Callable[[str], str] = input,
    interactive: bool | None = None,
    speak: Callable | None = None,
) -> int:
    if interactive is None:
        interactive = not assume_yes and sys.stdin.isatty()
    problems = 0

    def confirm(question: str, default: bool = True) -> bool:
        if not interactive:
            return default
        hint = "[Д/н]" if default else "[д/Н]"
        answer = ask(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        return answer[0] in "дyаоo"  # да / yes / ага / ок / ok

    def ok(msg: str) -> None:
        ui.info(f"✔ {msg}")

    def bad(msg: str) -> None:
        nonlocal problems
        problems += 1
        ui.error(msg)

    ui.state("Настройка fliprr")
    path = config_path()

    # 1. The project folder Claude Code works in
    current = None
    if path.exists():
        try:
            current = load_config(path)[0].project_dir()
        except ConfigError as e:
            ui.warn(f"в файле настроек ошибка: {e}")
    default = Path(project).expanduser() if project else (current or Path.home())
    folder = None
    for _ in range(3):
        answer = str(default)
        if interactive and not project:
            answer = ask(f"Папка проекта, в которой будет работать Claude Code\n(Enter — {default}): ").strip() or answer
        candidate = Path(os.path.expandvars(os.path.expanduser(answer.strip().strip('"').strip("'")))).resolve()
        if candidate.is_dir():
            folder = candidate
            break
        ui.error(f"Нет такой папки: {candidate}")
        if not interactive or project:
            break
    if folder is None:
        return 1
    write_project(path, folder)
    try:
        cfg = load_config(path)[0]
    except ConfigError as e:
        ui.error(f"файл настроек {path}: {e}")
        return 1
    ok(f"Папка проекта: {folder}")
    ui.info(f"  настройки: {path}")

    # 2. Speech recognition model (downloads once)
    ui.info("Скачиваю и проверяю модель распознавания речи (только в первый раз, ~500 МБ)…")
    try:
        from fliprr.stt import make_transcriber

        make_transcriber(cfg.stt, ui.warn)
        ok("Распознавание речи готово")
    except Exception as e:  # noqa: BLE001
        bad(f"Распознавание речи не загрузилось: {e}")

    # 3. Claude login (the same as Claude Code's)
    cli = claude_cli.find_cli(cfg)
    if cli is None:
        bad("Claude Code не найден (переустанови: pip install claude-agent-sdk)")
    else:
        status = claude_cli.auth_status(cli)
        if status and status.get("loggedIn"):
            ok("Вход в Claude выполнен")
        elif interactive and confirm("Нужно войти в аккаунт Claude. Войти сейчас (откроется браузер)?"):
            claude_cli.login(cli)
            status = claude_cli.auth_status(cli)
            if status and status.get("loggedIn"):
                ok("Вход в Claude выполнен")
            else:
                bad("Вход не выполнен — потом: fliprr login")
        else:
            bad("Не выполнен вход в Claude — выполни: fliprr login")

    # 4. Microphone and speakers
    try:
        from fliprr.audio.devices import import_sounddevice

        sd = import_sounddevice()
        for kind, label in (("input", "Микрофон"), ("output", "Колонки")):
            try:
                ok(f"{label}: {sd.query_devices(kind=kind)['name']}")
            except Exception:  # noqa: BLE001
                bad(f"{label}: не найдены — подключи и выбери их в настройках звука системы")
    except Exception as e:  # noqa: BLE001
        bad(f"Звук: {e}")

    # 5. Say something, so it's clear the voice works
    try:
        (speak or speak_once)(cfg, ui, "Привет! Я настроен. Зови меня: Клод или Клод Код.")
        ok("Голос работает (если ты ничего не услышал — проверь колонки)")
    except Exception as e:  # noqa: BLE001
        bad(f"Голос: {e}")

    # 6. Start at login, and 7. start now
    already_running = instance.is_running(lock_path(cfg.data_path))
    enabled = False
    if confirm("Запускать fliprr автоматически при входе в систему?"):
        try:
            ui.info(autostart.enable())
            enabled = True
        except Exception as e:  # noqa: BLE001
            bad(f"Автозапуск: {e}")
    if already_running:
        ui.info("fliprr уже работает. Новые настройки он подхватит после перезапуска: "
                "закрой его окно и перезайди в систему (или запусти fliprr вручную).")
    elif enabled and confirm("Запустить сейчас?"):
        if autostart.start_now():
            ok("fliprr запущен в отдельном окне")

    ui.state("Готово." if not problems else f"Готово, но есть проблемы: {problems} (см. выше).")
    if enabled:
        ui.info("Больше ничего запускать не нужно: fliprr стартует сам при входе в систему.")
        ui.info("Выключить автозапуск: fliprr autostart off")
    else:
        ui.info("Запуск вручную: fliprr")
    return 0 if not problems else 1


def speak_once(cfg, ui: Console, text: str) -> None:  # noqa: ANN001
    from fliprr.audio.player import AudioPlayer
    from fliprr.speakable import to_speakable
    from fliprr.tts import Speaker, make_engines

    async def go() -> None:
        engines = make_engines(cfg.tts, cfg.data_path, ui.warn)
        if not engines:
            raise RuntimeError("нет ни одного голоса (см. [tts] в настройках)")
        speaker = Speaker(engines, AudioPlayer(cfg.audio.output_device), log=ui.warn)
        speaker.start()
        try:
            await speaker.say_and_wait(to_speakable(text))
        finally:
            await speaker.close()
        if not speaker.recent:  # every engine failed (the reasons were logged)
            raise RuntimeError("не удалось озвучить фразу")

    asyncio.run(go())
