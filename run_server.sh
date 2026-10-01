#!/usr/bin/env bash

# Start an already installed local environment. Never download or install here.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

log() {
  echo "[illustrator-mcp] $1" >&2
}

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) PYTHON_BIN="$VENV_DIR/Scripts/python.exe" ;;
  Linux*)
    if [[ -r /proc/version ]] && grep -qi microsoft /proc/version; then
      PYTHON_BIN="$VENV_DIR/Scripts/python.exe"
    else
      PYTHON_BIN="$VENV_DIR/bin/python3"
    fi
    ;;
  *) PYTHON_BIN="$VENV_DIR/bin/python3" ;;
esac

installation_help() {
  log "Install or repair the environment explicitly; this launcher will not download packages."
  log "Windows: powershell -File ./install-windows.ps1 (use a new environment path if one exists)."
  log "macOS: python3.12 -m venv .venv, then .venv/bin/python3 -m pip install --require-hashes -r requirements.txt"
  log "Run installation commands from: $SCRIPT_DIR"
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  log "Missing Python environment: $PYTHON_BIN"
  installation_help
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
from importlib.metadata import version

if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required.")

expected = {"mcp": "1.30.0", "httpx": "0.28.1", "pillow": "12.3.0"}
if sys.platform == "win32":
    expected["pywin32"] = "312"
for package, pinned in expected.items():
    actual = version(package)
    if actual != pinned:
        raise SystemExit(f"Dependency mismatch: {package} {actual}; expected {pinned}.")

# Import the runtime without creating an Adobe backend or starting the server.
import mcp.server.stdio
from PIL import Image
if sys.platform == "win32":
    import win32com.client
PY
then
  log "Runtime dependency check failed. Nothing was installed or upgraded."
  installation_help
  exit 1
fi

SERVER_PATH="$SCRIPT_DIR/illustrator/server.py"
if [[ "$PYTHON_BIN" == */Scripts/python.exe ]]; then
  if command -v cygpath >/dev/null 2>&1; then
    SERVER_PATH="$(cygpath -w "$SERVER_PATH")"
  elif command -v wslpath >/dev/null 2>&1; then
    SERVER_PATH="$(wslpath -w "$SERVER_PATH")"
  fi
fi

log "Starting Illustrator MCP using the installed environment."
exec "$PYTHON_BIN" "$SERVER_PATH"
