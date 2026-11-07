#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# README prerequisite: Python 3.12+. Fail clearly instead of half-working on an older Python.
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
  echo "Python 3.12 or newer is required; found $(python3 --version 2>&1)." >&2
  echo "Install a newer Python (e.g. sudo dnf install python3.12, or brew install python@3.12 on macOS) and run this again." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
