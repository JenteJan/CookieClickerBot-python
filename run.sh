#!/usr/bin/env bash
# One-shot launcher: ensures the venv exists with deps installed, then starts
# the bot. Any arguments are passed straight through, e.g.:
#   ./run.sh
#   ./run.sh --profile experiment --browser chrome
#   ./run.sh --no-menu --headless
#   ./run.sh --ab            # synchronized A/B test (two windows, same seed)
set -euo pipefail

# Resolve the directory this script lives in, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
PY="$VENV_DIR/bin/python"
STAMP="$VENV_DIR/.deps-installed"

# Create the venv on first run.
if [ ! -x "$PY" ]; then
    echo "Creating virtualenv in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# Install / update dependencies when requirements.txt changes (or first run).
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    echo "Installing dependencies ..."
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r requirements.txt
    touch "$STAMP"
fi

# `--ab` launches the synchronized A/B test instead of a single bot.
if [ "${1:-}" = "--ab" ]; then
    shift
    exec "$PY" ab_test.py "$@"
fi

exec "$PY" cookieBot.py "$@"
