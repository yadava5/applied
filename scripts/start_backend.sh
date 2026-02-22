#!/usr/bin/env bash
# =============================================================================
# JobTracker Backend Launcher (Development)
# =============================================================================
# - Reuses an already running backend if healthy.
# - Creates a local virtual environment on first run (if missing).
# - Installs backend dependencies when bootstrapping the venv.
# - Starts uvicorn in foreground.
#
# Usage:
#   ./scripts/start_backend.sh
#   ./scripts/start_backend.sh --reload
#   ./scripts/start_backend.sh --host 127.0.0.1 --port 8000
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

HOST="127.0.0.1"
PORT="8000"
RELOAD=false
AUTO_BOOTSTRAP="${JOBTRACKER_AUTO_BOOTSTRAP:-1}"

usage() {
    cat <<'EOF'
Usage: ./scripts/start_backend.sh [options]

Options:
  --host <host>         Backend host (default: 127.0.0.1)
  --port <port>         Backend port (default: 8000)
  --reload              Run uvicorn with auto-reload
  --no-bootstrap        Fail if venv is missing (do not auto-create/install)
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="${2:-}"
            shift 2
            ;;
        --port)
            PORT="${2:-}"
            shift 2
            ;;
        --reload)
            RELOAD=true
            shift
            ;;
        --no-bootstrap)
            AUTO_BOOTSTRAP="0"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "Backend directory not found: $BACKEND_DIR" >&2
    exit 1
fi

health_url="http://${HOST}:${PORT}/health"
if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 1 "$health_url" >/dev/null 2>&1; then
        echo "Backend already running at ${health_url}"
        exit 0
    fi
fi

if command -v lsof >/dev/null 2>&1; then
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Port $PORT is already in use by another process." >&2
        lsof -nP -iTCP:"$PORT" -sTCP:LISTEN || true
        exit 1
    fi
fi

PYTHON_BIN=""
if [[ -x "$BACKEND_DIR/.venv311/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv311/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    if [[ "$AUTO_BOOTSTRAP" != "1" ]]; then
        echo "No virtual environment found (.venv311 or .venv)." >&2
        echo "Run ./scripts/install.sh or rerun without --no-bootstrap." >&2
        exit 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 is required to bootstrap the backend environment." >&2
        exit 1
    fi

    echo "No virtual environment found. Bootstrapping backend/.venv311..."
    python3 -m venv "$BACKEND_DIR/.venv311"
    "$BACKEND_DIR/.venv311/bin/pip" install --quiet --upgrade pip
    "$BACKEND_DIR/.venv311/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"
    PYTHON_BIN="$BACKEND_DIR/.venv311/bin/python"
fi

cd "$BACKEND_DIR"
args=(-m uvicorn jobtracker.main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == true ]]; then
    args+=(--reload)
fi

exec "$PYTHON_BIN" "${args[@]}"
