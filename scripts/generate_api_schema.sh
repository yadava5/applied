#!/usr/bin/env bash
# =============================================================================
# Regenerate the web app's typed API bindings from the CLOUD FastAPI app
# =============================================================================
# Writes apps/web/lib/api/schema.d.ts from `jobtracker.main_cloud`'s OpenAPI
# document. That app — not `jobtracker.main` — is what Vercel serves
# (`api/index.py` forces JOBTRACKER_DEPLOYMENT=cloud), so it is the only
# contract the browser ever talks to.
#
# ONE implementation, run from two places, so the gate can never disagree with
# the developer command:
#
#   pnpm -C apps/web api:gen          # developers
#   .github/workflows/e2e-ci.yml      # the drift gate (regenerate + git diff)
#
# WHY IT IMPORTS THE APP INSTEAD OF CURLING /openapi.json
# ------------------------------------------------------
# The old scripts fetched `$BACKEND_API_URL/openapi.json` or
# `localhost:8000/openapi.json`. Under this repo's e2e setup :8000 is the
# DESKTOP app (`jobtracker.main`), which serves a different contract, and a
# deployed URL serves whatever was last deployed rather than what is in this
# checkout. Importing the app needs no server and describes THIS working tree.
#
# WHY THE SPEC IS WRITTEN FROM PYTHON RATHER THAN PIPED FROM STDOUT
# -----------------------------------------------------------------
# `jobtracker.logging.setup_logging()` runs at import time and installs a
# stdout handler, so `python -c '...print(json.dumps(app.openapi()))' > spec`
# produces a file whose first line is a TIMESTAMPED log line. That is invalid
# JSON, and differently invalid on every run — it could never have been a
# stable gate. Python writes the file itself; the log line stays on the
# terminal where it belongs.
#
# Usage:
#   ./scripts/generate_api_schema.sh
#   PYTHON=/path/to/python ./scripts/generate_api_schema.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
WEB_DIR="$PROJECT_ROOT/apps/web"
OUTPUT="lib/api/schema.d.ts"

# An explicit $PYTHON wins; otherwise prefer a local 3.11 venv (what CI pins),
# then whatever `python3` is on PATH — which is the case in CI, where
# actions/setup-python has already put 3.11 there.
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    if [[ -x "$BACKEND_DIR/.venv311/bin/python" ]]; then
        PYTHON_BIN="$BACKEND_DIR/.venv311/bin/python"
    elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
        PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
SPEC="$TMP_DIR/openapi-cloud.json"

echo "==> Building the cloud OpenAPI document ($PYTHON_BIN)"
cd "$BACKEND_DIR"
JOBTRACKER_DEPLOYMENT=cloud \
JOBTRACKER_ENVIRONMENT=test \
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
    "$PYTHON_BIN" - "$SPEC" <<'PY'
import json
import pathlib
import sys

from jobtracker.main_cloud import app

pathlib.Path(sys.argv[1]).write_text(json.dumps(app.openapi()))
PY

echo "==> Writing apps/web/$OUTPUT"
cd "$WEB_DIR"
if command -v pnpm >/dev/null 2>&1; then
    pnpm exec openapi-typescript "$SPEC" -o "$OUTPUT"
else
    npx --no-install openapi-typescript "$SPEC" -o "$OUTPUT"
fi
