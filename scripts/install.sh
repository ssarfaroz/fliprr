#!/usr/bin/env bash
# Install fliprr into ./.venv and link the `fliprr` command into ~/.local/bin.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required")'

if [ "$(uname)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
  echo "! PortAudio is missing. Install it first, e.g.: sudo apt install libportaudio2"
fi

"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/fliprr" "$HOME/.local/bin/fliprr"

echo
echo "Готово. Дальше:"
echo "  fliprr init     # файл настроек — впиши папку проекта"
echo "  fliprr doctor   # проверка"
echo "  fliprr test-mic # проверка микрофона издалека"
echo "  fliprr          # запуск"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "(~/.local/bin нет в PATH — запускай $PWD/.venv/bin/fliprr)";;
esac
