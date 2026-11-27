"""One-time setup, autostart, the single-instance lock and the restart loop."""

import subprocess
import sys
import textwrap
import types

import pytest

from fliprr import autostart, cli, instance, setup_wizard
from fliprr.config import load_config
from fliprr.ui import Console


# -- config writing ------------------------------------------------------------------------


def test_write_project_creates_and_updates(tmp_path):
    path = tmp_path / "config.toml"
    project = tmp_path / "Мой проект"
    project.mkdir()
    setup_wizard.write_project(path, project)
    cfg = load_config(path)[0]
    assert cfg.project_dir() == project.resolve()
    assert cfg.stt.model == "small"  # the rest comes from the template

    # a user edit elsewhere in the file survives a folder change
    text = path.read_text(encoding="utf-8").replace('model = "small"', 'model = "medium"')
    path.write_text(text, encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    setup_wizard.write_project(path, other)
    cfg = load_config(path)[0]
    assert cfg.project_dir() == other.resolve()
    assert cfg.stt.model == "medium"


def test_write_project_adds_missing_cwd(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[stt]\nmodel = "base"\n', encoding="utf-8")
    setup_wizard.write_project(path, tmp_path)
    assert load_config(path)[0].project_dir() == tmp_path.resolve()
    path.write_text('[claude_code]\nspeak = "final"\n', encoding="utf-8")
    setup_wizard.write_project(path, tmp_path)
    cfg = load_config(path)[0]
    assert cfg.project_dir() == tmp_path.resolve() and cfg.claude_code.speak == "final"


def test_toml_path_on_windows_style_paths():
    assert setup_wizard.toml_path(r"C:\Users\Иван\code") == "C:/Users/Иван/code"
    assert setup_wizard.toml_path('/tmp/a"b') == '/tmp/a\\"b'


# -- the wizard ----------------------------------------------------------------------------


@pytest.fixture
def wizard_env(tmp_path, monkeypatch):
    """Everything the wizard touches, faked."""
    calls = {"transcriber": 0, "spoken": [], "enabled": 0, "started": 0, "login": 0}
    monkeypatch.setenv("FLIPRR_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    monkeypatch.setattr("fliprr.stt.make_transcriber", lambda cfg, log=None: calls.__setitem__("transcriber", 1))
    logged_in = {"value": False}
    monkeypatch.setattr(setup_wizard.claude_cli, "find_cli", lambda cfg: "/fake/claude")
    monkeypatch.setattr(setup_wizard.claude_cli, "auth_status", lambda cli: {"loggedIn": logged_in["value"]})

    def fake_login(cli):
        calls["login"] += 1
        logged_in["value"] = True
        return 0

    monkeypatch.setattr(setup_wizard.claude_cli, "login", fake_login)
    sd = types.SimpleNamespace(query_devices=lambda kind=None: {"name": f"fake {kind}"})
    monkeypatch.setattr("fliprr.audio.devices.import_sounddevice", lambda: sd)
    monkeypatch.setattr(autostart, "enable", lambda: calls.__setitem__("enabled", calls["enabled"] + 1) or "enabled")
    monkeypatch.setattr(autostart, "start_now", lambda: calls.__setitem__("started", calls["started"] + 1) or True)
    calls["speak"] = lambda cfg, ui, text: calls["spoken"].append(text)
    calls["logged_in"] = logged_in
    return calls


def test_setup_non_interactive(tmp_path, wizard_env, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    wizard_env["logged_in"]["value"] = True
    code = setup_wizard.run_setup(Console(color=False), project=str(project), interactive=False,
                                  speak=wizard_env["speak"])
    assert code == 0
    cfg = load_config(tmp_path / "cfg" / "config.toml")[0]
    assert cfg.project_dir() == project.resolve()
    assert wizard_env["transcriber"] == 1
    assert wizard_env["spoken"] and wizard_env["enabled"] == 1 and wizard_env["started"] == 1
    assert "Больше ничего запускать не нужно" in capsys.readouterr().out


def test_setup_interactive_retries_folder_and_logs_in(tmp_path, wizard_env):
    project = tmp_path / "proj"
    project.mkdir()
    answers = iter([str(tmp_path / "nope"), f'"{project}"', "да", "", "н"])  # bad folder, good, login, autostart, start
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return next(answers)

    code = setup_wizard.run_setup(Console(color=False), interactive=True, ask=ask, speak=wizard_env["speak"])
    assert code == 0
    assert load_config(tmp_path / "cfg" / "config.toml")[0].project_dir() == project.resolve()
    assert wizard_env["login"] == 1
    assert wizard_env["enabled"] == 1 and wizard_env["started"] == 0  # said «н» to starting now
    assert len(asked) == 5


def test_setup_reports_problems_but_finishes(tmp_path, wizard_env, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("no internet")

    monkeypatch.setattr("fliprr.stt.make_transcriber", broken)
    code = setup_wizard.run_setup(Console(color=False), project=str(tmp_path), interactive=False,
                                  speak=wizard_env["speak"])
    assert code == 1  # model failed + not logged in
    assert wizard_env["enabled"] == 1  # still set up the rest


def test_setup_rejects_missing_project(tmp_path, wizard_env):
    assert setup_wizard.run_setup(Console(color=False), project=str(tmp_path / "missing"), interactive=False,
                                  speak=wizard_env["speak"]) == 1


# -- autostart -----------------------------------------------------------------------------


def test_autostart_linux_systemd(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/systemctl")
    ran = []
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    autostart.enable()
    unit = (tmp_path / "systemd" / "user" / "fliprr.service").read_text()
    assert f"ExecStart={sys.executable} -m fliprr run --no-color\n" in unit
    assert "Restart=on-failure" in unit
    assert ["systemctl", "--user", "enable", "--now", "fliprr.service"] in ran
    assert autostart.is_enabled()
    assert autostart.start_now() is False  # systemd already started it
    autostart.disable()
    assert not autostart.is_enabled()
    assert ["systemctl", "--user", "disable", "--now", "fliprr.service"] in ran


def test_autostart_linux_reports_systemctl_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Failed to connect to bus"))
    with pytest.raises(autostart.AutostartError, match="Failed to connect to bus"):
        autostart.enable()


class FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        super().__init__("winreg")
        self.values = {}

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def CreateKey(self, root, path):  # noqa: N802
        return self._Key(self, path)

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802
        return self._Key(self, path)

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.values[(key.path, name)] = value

    def QueryValueEx(self, key, name):  # noqa: N802
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        return self.values[(key.path, name)], self.REG_SZ

    def DeleteValue(self, key, name):  # noqa: N802
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        del self.values[(key.path, name)]


def test_autostart_windows_registry(monkeypatch):
    reg = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\Users\Иван Петров\fliprr\.venv\Scripts\python.exe")
    assert not autostart.is_enabled()
    autostart.enable()
    command = reg.values[(autostart.RUN_KEY, "fliprr")]
    # quoted because of the space; Unicode path kept as is
    assert command == '"C:\\Users\\Иван Петров\\fliprr\\.venv\\Scripts\\python.exe" -m fliprr service'
    assert autostart.is_enabled()
    started = []
    monkeypatch.setattr(autostart.subprocess, "Popen", lambda *a, **kw: started.append((a, kw)))
    assert autostart.start_now() is True
    assert started[0][0][0][-1] == "service"
    autostart.disable()
    autostart.disable()  # twice is fine
    assert not autostart.is_enabled()


def test_autostart_macos_login_item(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(autostart.Path, "home", classmethod(lambda cls: tmp_path))
    scripts = []
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda cmd, **kw: scripts.append(cmd[-1]) or subprocess.CompletedProcess(cmd, 0, "", ""))
    autostart.enable()
    command = tmp_path / "Applications" / "fliprr.command"
    assert command.read_text().startswith("#!/bin/bash")
    assert "-m fliprr service" in command.read_text()
    assert command.stat().st_mode & 0o100
    assert "make login item" in scripts[0] and str(command) in scripts[0]
    autostart.disable()
    assert not command.exists() and "delete login item" in scripts[-1]


# -- one instance only ---------------------------------------------------------------------


def test_instance_lock(tmp_path):
    path = tmp_path / "fliprr.lock"
    first = instance.acquire(path)
    assert first is not None
    assert instance.is_running(path)
    # another process can't take it either
    code = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from fliprr import instance
        sys.exit(0 if instance.acquire(Path({str(path)!r})) is None else 1)
    """)
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
    first.close()
    assert not instance.is_running(path)


def test_run_exits_quietly_when_already_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FLIPRR_CONFIG", str(tmp_path / "c.toml"))
    (tmp_path / "c.toml").write_text(f'data_dir = "{tmp_path.as_posix()}"\n', encoding="utf-8")
    held = instance.acquire(tmp_path / "fliprr.lock")
    assert cli.main(["--no-color", "run"]) == 0
    assert "уже запущен" in capsys.readouterr().out
    held.close()


# -- the restart loop ----------------------------------------------------------------------


def test_service_restarts_after_a_crash(monkeypatch, tmp_path):
    codes = iter([1, 0])
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda cmd: calls.append(cmd) or next(codes))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--no-color", "service"]) == 0
    assert len(calls) == 2 and calls[0][-1] == "run"
