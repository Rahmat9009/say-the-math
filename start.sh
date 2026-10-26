#!/usr/bin/env sh
# Say the Math launcher for macOS and Linux. Safe for folders with spaces in their path.
#   ./start.sh          start (running setup first if needed)
#   ./start.sh setup    run or repair setup, then start
set -eu
cd "$(dirname "$0")"

needs_setup=0
[ "${1:-}" = "setup" ] && needs_setup=1
[ -x ".venv/bin/python" ] || needs_setup=1
[ -f "models/setup-record.json" ] || needs_setup=1
[ -f "node_modules/speech-rule-engine/package.json" ] || needs_setup=1

if [ "$needs_setup" = "1" ]; then
  echo "Setting up Say the Math. This downloads about 1 GB of packages and a 120 MB model, once."
  PY=""
  for cand in python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.12 or 3.11 was not found. Install it and Node.js 22+, then run ./start.sh again." >&2
    exit 1
  fi
  "$PY" "setup_app.py"
fi

echo "Starting Say the Math. Press Ctrl+C to stop."
exec ".venv/bin/python" "app.py" --open
