#!/usr/bin/env bash
set -euo pipefail

# Ensure Node/npm are on PATH (check NVM and standard macOS paths)
if ! command -v npm >/dev/null 2>&1; then
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
    # shellcheck source=/dev/null
    \. "$NVM_DIR/nvm.sh"
  fi
fi

if [ -d "/opt/homebrew/bin" ] && [[ ":$PATH:" != *":/opt/homebrew/bin:"* ]]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Auto-setup on first run if dependencies are missing
if [ ! -d ".venv" ] || [ ! -d "frontend/node_modules" ]; then
  echo ""
  echo "⚠️ Missing Python virtual environment or frontend dependencies."
  echo "📦 Running automatic setup (./scripts/setup.sh)..."
  ./scripts/setup.sh
  echo "✔ Setup completed!"
fi

echo ""
echo "🔭 ==========================================================="
echo "   SPHEREx Explorer — NASA Space Apps Challenge 2026"
echo "   Launching full stack from a single terminal..."
echo "=============================================================="
echo ""

# Helper to free stale port if an old zombie process is holding it
free_port_if_busy() {
  local port=$1
  local pids
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  → Releasing port $port from prior process ($pids)..."
    kill -9 $pids 2>/dev/null || true
    sleep 0.3
  fi
}

free_port_if_busy 8000
free_port_if_busy 5173

# 1. Start FastAPI backend in background
echo "  → [1/2] Starting FastAPI backend on http://127.0.0.1:8000 ..."
"$ROOT_DIR/.venv/bin/python" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

# Brief pause to let backend bind port
sleep 1.2

# 2. Start Vite frontend in background
echo "  → [2/2] Starting Vite frontend on http://127.0.0.1:5173 ..."
(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "⏹ Shutting down SPHEREx Explorer services..."
  trap - INT TERM EXIT

  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    pkill -P "$FRONTEND_PID" 2>/dev/null || true
    kill -TERM "$FRONTEND_PID" 2>/dev/null || true
  fi

  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    pkill -P "$BACKEND_PID" 2>/dev/null || true
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
  fi

  sleep 0.4
  free_port_if_busy 8000
  free_port_if_busy 5173

  echo "✔ All services stopped cleanly."
  exit 0
}

trap cleanup INT TERM EXIT

echo ""
echo "🚀 SPHEREx Explorer is running!"
echo "   • Frontend UI:   http://127.0.0.1:5173"
echo "   • Backend API:   http://127.0.0.1:8000"
echo "   • API Docs:      http://127.0.0.1:8000/docs"
echo ""
echo "💡 Press Ctrl+C in this terminal to stop both servers at once."
echo "──────────────────────────────────────────────────────────────"
echo ""

# Wait on background processes
wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
