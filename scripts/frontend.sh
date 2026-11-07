#!/usr/bin/env bash
set -euo pipefail
if ! command -v npm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  export NVM_DIR="$HOME/.nvm"
  # shellcheck source=/dev/null
  \. "$NVM_DIR/nvm.sh"
fi
cd "$(dirname "$0")/../frontend"
exec npm run dev
