#!/usr/bin/env bash
set -euo pipefail

if ! command -v npm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  \. "$NVM_DIR/nvm.sh"
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "✳ Starting Arcadian SkyTracker (Backend + Frontend)..."
echo "  → Starting FastAPI backend on http://127.0.0.1:8000"

"$ROOT_DIR/.venv/bin/python" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "Stopping Arcadian SkyTracker..."
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM EXIT

sleep 1.5
echo "  → Starting Vite frontend on http://127.0.0.1:5173"
cd "$ROOT_DIR/frontend"
exec npm run dev
