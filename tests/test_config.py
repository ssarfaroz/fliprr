import pytest

from fliprr.config import Config, ConfigError, load_config, tomllib
from fliprr.config_template import TEMPLATE


def write(tmp_path, text):
    path = tmp_path / "c.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLIPRR_CONFIG", str(tmp_path / "nope.toml"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg, path, warnings = load_config()
    assert path is None and warnings == []
    assert cfg.stt.model == "small" and cfg.wake.default_target == "chat"


def test_load_and_merge(tmp_path):
    path = write(tmp_path, """
language = "en"
[stt]
model = "medium"
beam_size = 3
[audio]
input_device = 2
input_gain = 2
[claude_code]
auto_allow = ["Bash(npm test:*)"]
[claude_code.projects]
blog = "~/blog"
[bogus]
x = 1
""")
    cfg, used, warnings = load_config(path)
    assert used == path
    assert cfg.language == "en"
    assert cfg.stt.model == "medium" and cfg.stt.beam_size == 3 and cfg.stt.engine == "whisper"
    assert cfg.audio.input_device == "2" and cfg.audio.input_gain == 2.0
    assert cfg.claude_code.auto_allow == ["Bash(npm test:*)"]
    assert cfg.projects()["blog"].name == "blog"
    assert warnings == ["unknown setting: bogus"]


def test_type_errors(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[stt]\nbeam_size = 'five'\n"))
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[audio]\nbarge_in = 1\n"))
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "stt = 3\n"))
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[stt\n"))
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")


def test_template_is_valid_and_matches_defaults(tmp_path):
    text = TEMPLATE.replace("{cwd}", str(tmp_path).replace("\\", "/"))
    tomllib.loads(text)
    cfg, _, warnings = load_config(write(tmp_path, text))
    assert warnings == []
    defaults = Config()
    assert cfg.stt.model == defaults.stt.model
    assert cfg.tts.voice == defaults.tts.voice
    assert cfg.project_dir() == tmp_path.resolve()
