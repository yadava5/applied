#!/usr/bin/env bash
# Weekly real-signal labeling cycle runner.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if [ -x "$BACKEND_DIR/.venv311/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv311/bin/python"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

cd "$BACKEND_DIR"
exec "$PYTHON" -m jobtracker.scripts.weekly_labeling_workflow "$@"
