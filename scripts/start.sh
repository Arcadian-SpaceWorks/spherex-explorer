#!/usr/bin/env bash
# Start the backend (port 8000) and frontend (port 5173) from one terminal. Ctrl+C stops both.
# Other ports: SKYTRACKER_BACKEND_PORT=8010 SKYTRACKER_FRONTEND_PORT=5180 ./scripts/start.sh
# Never kills anything it did not start: if a port is already busy, it says so and exits.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# npm installed through nvm is not always on PATH in a fresh terminal.
if ! command -v npm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
fi

if [ ! -x .venv/bin/python ] || [ ! -d frontend/node_modules ]; then
  echo "First run: installing dependencies with scripts/setup.sh ..."
  ./scripts/setup.sh
fi

BACKEND_PORT="${SKYTRACKER_BACKEND_PORT:-8000}"
FRONTEND_PORT="${SKYTRACKER_FRONTEND_PORT:-5173}"
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if port_busy "$port"; then
    echo "Port $port is already in use, perhaps by an earlier run of the app."
    echo "Stop that process first (find it with: lsof -i :$port), then run this again."
    exit 1
  fi
done

pids=()
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping backend and frontend ..."
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true  # The whole group: uvicorn reloader + worker, npx + vite.
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT
set -m  # Each server gets its own process group, so stopping it also stops its child processes.

.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload & pids+=("$!")
(cd frontend && SKYTRACKER_API_TARGET="http://127.0.0.1:$BACKEND_PORT" exec npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort) & pids+=("$!")
echo "Backend:  http://127.0.0.1:$BACKEND_PORT/api/health"
echo "App:      http://127.0.0.1:$FRONTEND_PORT   (Ctrl+C stops both)"
# If either one stops on its own, stop the other too.
wait -n "${pids[@]}" || true
