#!/usr/bin/env bash
# AI Dubber Ultimate - Linux / macOS Launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "      AI Dubber Ultimate v1.2.9 Portable         "
echo "=================================================="

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "[!] Warning: ffmpeg not found in PATH. Please install ffmpeg for full audio/video capabilities."
fi

VENV_DIR="$SCRIPT_DIR/.venv"

# Prefer local virtual environment (.venv) where all AI engines are installed
if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
    echo "[*] Launching via local virtual environment (.venv)..."
    export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
    exec "$VENV_DIR/bin/python" src/main.py "$@"
fi

# If .venv does not exist, check if uv can create/run it or create standard venv
if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Creating virtual environment (.venv)..."
    if command -v uv &> /dev/null; then
        uv venv "$VENV_DIR" --python 3.11
        "$VENV_DIR/bin/pip" install -r requirements.txt
    elif command -v python3.11 &> /dev/null; then
        python3.11 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip
        "$VENV_DIR/bin/pip" install -r requirements.txt
    else
        python3 -m venv "$VENV_DIR"
        "$VENV_DIR/bin/pip" install --upgrade pip
        "$VENV_DIR/bin/pip" install -r requirements.txt
    fi
fi

export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
exec "$VENV_DIR/bin/python" src/main.py "$@"
