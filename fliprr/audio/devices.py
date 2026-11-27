"""sounddevice access with friendly errors and device lookup by name."""

from __future__ import annotations

import sys
from typing import Any


class AudioUnavailable(RuntimeError):
    pass


def import_sounddevice() -> Any:
    try:
        import sounddevice as sd
    except OSError as e:  # PortAudio shared library missing
        hint = (
            "sudo apt install libportaudio2" if sys.platform.startswith("linux")
            else "reinstall the 'sounddevice' package"
        )
        raise AudioUnavailable(f"PortAudio is not available ({e}). Fix: {hint}") from e
    except ImportError as e:
        raise AudioUnavailable("the 'sounddevice' package is not installed") from e
    return sd


def resolve_device(sd: Any, spec: str, kind: str) -> int | None:
    """"" → default device; "3" → index 3; "USB" → first device whose name contains it."""
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.isdigit():
        return int(spec)
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    needle = spec.lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev[key] > 0 and needle in dev["name"].lower():
            return idx
    raise AudioUnavailable(f"no {kind} device matching {spec!r} (see `fliprr devices`)")


def list_devices() -> list[dict[str, Any]]:
    sd = import_sounddevice()
    try:
        default_in, default_out = sd.default.device
    except Exception:  # noqa: BLE001
        default_in = default_out = -1
    out = []
    hostapis = sd.query_hostapis()
    for idx, dev in enumerate(sd.query_devices()):
        out.append({
            "index": idx,
            "name": dev["name"],
            "hostapi": hostapis[dev["hostapi"]]["name"],
            "inputs": dev["max_input_channels"],
            "outputs": dev["max_output_channels"],
            "rate": int(dev["default_samplerate"]),
            "default_input": idx == default_in,
            "default_output": idx == default_out,
        })
    return out
