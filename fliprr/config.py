"""Configuration: defaults, TOML loading, standard locations."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@dataclass
class AudioConfig:
    input_device: str = ""  # name fragment or index; "" = system default
    output_device: str = ""
    vad: str = "silero"  # silero | energy
    vad_threshold: float = 0.5
    min_speech_ms: int = 300
    end_silence_ms: int = 900
    max_utterance_s: float = 30.0
    pre_roll_ms: int = 300
    input_gain: float = 1.0
    barge_in: bool = True  # keep listening while speaking, so «Клод, стоп» works
    earcons: bool = True
    earcon_volume: float = 0.25


@dataclass
class WakeConfig:
    max_prefix_words: int = 3  # wake word must be among the first N words
    default_target: str = "chat"  # what a plain «Клод» addresses: chat | code
    followup_s: float = 8.0  # after an answer, talk without the wake word this long
    listen_timeout_s: float = 8.0  # after a bare «Клод!», wait this long for the request
    extra_claude_words: list[str] = field(default_factory=list)
    extra_code_words: list[str] = field(default_factory=list)


@dataclass
class STTConfig:
    engine: str = "whisper"  # whisper (local, faster-whisper) | openai (OpenAI-compatible API)
    model: str = "small"  # tiny | base | small | medium | large-v3-turbo | path
    device: str = "auto"  # auto | cpu | cuda
    compute_type: str = "auto"
    cpu_threads: int = 0
    language: str = "ru"  # "" = autodetect
    beam_size: int = 5
    initial_prompt: str = ""  # "" = built-in hint with the assistant names
    download_root: str = ""
    api_base: str = "https://api.groq.com/openai/v1"
    api_key_env: str = "GROQ_API_KEY"
    api_model: str = "whisper-large-v3-turbo"


@dataclass
class TTSConfig:
    engine: str = "edge"  # edge (online, free) | piper (offline) | system | none
    fallback: str = "system"  # used if the main engine fails: piper | system | none
    voice: str = "ru-RU-SvetlanaNeural"  # edge-tts voice for Russian
    voice_en: str = "en-US-AvaNeural"  # edge-tts voice for English sentences
    rate: str = "+10%"
    volume: str = "+0%"
    piper_voice: str = "ru_RU-irina-medium"
    piper_voice_en: str = "en_US-lessac-medium"
    system_voice: str = ""


@dataclass
class ClaudeCodeConfig:
    cwd: str = ""  # project folder; "" = folder fliprr was started in
    projects: dict[str, str] = field(default_factory=dict)  # spoken name → folder
    model: str = ""  # "" = Claude Code default
    effort: str = ""  # low | medium | high | xhigh | max; "" = default
    permission_mode: str = "default"  # default | acceptEdits | plan | auto | bypassPermissions
    auto_allow: list[str] = field(default_factory=list)  # tools allowed without asking
    ask_timeout_s: float = 60.0
    speak: str = "all"  # all = progress + summary | final = summary only
    announce_tools: bool = False
    max_speech_chars: int = 900
    continue_last: bool = False  # resume the last session in the folder on start
    setting_sources: list[str] = field(default_factory=lambda: ["user", "project", "local"])
    cli_path: str = ""


@dataclass
class ChatConfig:
    model: str = ""
    effort: str = "low"  # quick spoken answers
    web: bool = True  # allow web search / fetch
    resume: bool = True  # continue the last chat after restart
    instructions: str = ""  # extra system prompt text
    max_speech_chars: int = 2500


@dataclass
class Config:
    language: str = "ru"  # language of fliprr's own phrases: ru | en
    data_dir: str = ""
    audio: AudioConfig = field(default_factory=AudioConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)

    # -- derived paths ---------------------------------------------------------

    @property
    def data_path(self) -> Path:
        return Path(os.path.expanduser(self.data_dir)) if self.data_dir else app_dir()

    def project_dir(self) -> Path:
        cwd = self.claude_code.cwd
        return Path(os.path.expanduser(cwd)).resolve() if cwd else Path.cwd()

    def projects(self) -> dict[str, Path]:
        return {
            name: Path(os.path.expanduser(path)).resolve()
            for name, path in self.claude_code.projects.items()
        }


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "fliprr"


def config_candidates() -> list[Path]:
    paths = []
    if os.environ.get("FLIPRR_CONFIG"):
        paths.append(Path(os.environ["FLIPRR_CONFIG"]))
    paths += [Path.cwd() / "fliprr.toml", app_dir() / "config.toml"]
    return paths


class ConfigError(ValueError):
    pass


def load_config(path: str | Path | None = None) -> tuple[Config, Path | None, list[str]]:
    """Load the first config file found. Returns (config, path used, warnings)."""
    candidates = [Path(path)] if path else config_candidates()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate.is_file():
            with candidate.open("rb") as fh:
                try:
                    raw = tomllib.load(fh)
                except tomllib.TOMLDecodeError as e:
                    raise ConfigError(f"{candidate}: {e}") from e
            warnings: list[str] = []
            cfg = _build(Config, raw, "", warnings)
            return cfg, candidate, warnings
        if path:
            raise ConfigError(f"config file not found: {candidate}")
    return Config(), None, []


def _build(cls: Any, raw: dict[str, Any], prefix: str, warnings: list[str]) -> Any:
    obj = cls()
    known = {f.name: f for f in fields(cls)}
    for key, value in raw.items():
        name = f"{prefix}{key}"
        if key not in known:
            warnings.append(f"unknown setting: {name}")
            continue
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"[{name}] must be a table")
            setattr(obj, key, _build(type(current), value, name + ".", warnings))
            continue
        setattr(obj, key, _coerce(name, current, value))
    return obj


def _coerce(name: str, current: Any, value: Any) -> Any:
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{name} must be true or false")
        return value
    if isinstance(current, float):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"{name} must be a number")
        return float(value)
    if isinstance(current, int):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{name} must be an integer")
        return value
    if isinstance(current, str):
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)  # e.g. input_device = 3
        if not isinstance(value, str):
            raise ConfigError(f"{name} must be a string")
        return value
    if isinstance(current, list):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{name} must be a list of strings")
        return list(value)
    if isinstance(current, dict):
        if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
            raise ConfigError(f"{name} must be a table of strings")
        return dict(value)
    return value


def as_dict(cfg: Config) -> dict[str, Any]:
    return asdict(cfg)
