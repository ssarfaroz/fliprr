#!/usr/bin/env bash
# One-time setup on macOS / Linux. Run from the fliprr folder: ./scripts/install.sh
# Installs fliprr into ./.venv, links `fliprr` into ~/.local/bin, then `fliprr setup`
# asks for your project folder, downloads the speech model, checks the Claude login,
# turns on autostart and starts it.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required")'

if [ "$(uname)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
  echo "! Нет PortAudio. Сначала установи: sudo apt install libportaudio2"
  exit 1
fi

"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/fliprr" "$HOME/.local/bin/fliprr"

# setup asks questions: give it the terminal even if this script was piped
if [ -t 0 ]; then
  .venv/bin/python -m fliprr setup
else
  .venv/bin/python -m fliprr setup < /dev/tty
fi
