#!/usr/bin/env bash
# ==============================================================================
# Training Pipeline — End-to-End
# ==============================================================================
# Runs the full external dataset ingestion pipeline:
#   Step 1: Parse & auto-label     → candidates.jsonl
#   Step 2: Manual review           → (interactive terminal)
#   Step 3: Import to DB & retrain  → training_data + SetFit
#
# Prerequisites:
#   bash scripts/download_datasets.sh   (one-time download)
#
# Usage:
#   bash scripts/train_pipeline.sh              # full pipeline
#   bash scripts/train_pipeline.sh --skip-review # skip manual review
#   bash scripts/train_pipeline.sh --import-only # just import + retrain
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { printf "${GREEN}[STEP]${NC}  %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
header() { printf "\n${CYAN}%s${NC}\n" "$1"; }

# --------------------------------------------------------------------------
# Parse arguments
# --------------------------------------------------------------------------
SKIP_REVIEW=false
IMPORT_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --skip-review) SKIP_REVIEW=true ;;
        --import-only) IMPORT_ONLY=true ;;
        --help|-h)
            echo "Usage: bash scripts/train_pipeline.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-review   Skip the manual review step"
            echo "  --import-only   Only run import + retrain (skip parse & review)"
            echo "  --help, -h      Show this help"
            exit 0
            ;;
    esac
done

# --------------------------------------------------------------------------
# Find Python (prefer venv)
# --------------------------------------------------------------------------
if [ -f "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
elif [ -f "$BACKEND_DIR/.venv311/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv311/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "Error: Python not found. Please activate your venv or install Python 3.11+"
    exit 1
fi

echo ""
header "=========================================="
header "  JobTracker Training Pipeline"
header "=========================================="
echo ""
echo "  Python: $PYTHON"
echo "  Backend: $BACKEND_DIR"
echo ""

# --------------------------------------------------------------------------
# Step 1: Parse & Auto-label
# --------------------------------------------------------------------------
if [ "$IMPORT_ONLY" = false ]; then
    info "Step 1/3 — Parsing external datasets & auto-labeling..."
    echo ""
    cd "$BACKEND_DIR"
    $PYTHON -m jobtracker.scripts.ingest_datasets
    echo ""
fi

# --------------------------------------------------------------------------
# Step 2: Manual Review (interactive)
# --------------------------------------------------------------------------
if [ "$IMPORT_ONLY" = false ] && [ "$SKIP_REVIEW" = false ]; then
    CANDIDATES="$BACKEND_DIR/data/processed/candidates.jsonl"
    if [ -f "$CANDIDATES" ]; then
        REVIEW_COUNT=$(grep -c '"needs_review": true' "$CANDIDATES" 2>/dev/null || echo "0")
        if [ "$REVIEW_COUNT" -gt 0 ]; then
            info "Step 2/3 — Manual review ($REVIEW_COUNT candidates need review)..."
            echo ""
            echo "  You'll be shown ambiguous emails one at a time."
            echo "  Press Enter to accept the auto-label, or 1-8 to change it."
            echo "  Press 'q' to quit early and import what's done so far."
            echo ""
            read -p "  Press Enter to start review (or 's' to skip)... " START_REVIEW
            if [ "$START_REVIEW" != "s" ]; then
                cd "$BACKEND_DIR"
                $PYTHON -m jobtracker.scripts.review_candidates
            else
                warn "Skipping review — only auto-verified candidates will be imported."
            fi
        else
            info "Step 2/3 — No candidates need manual review. All auto-verified!"
        fi
    else
        warn "No candidates.jsonl found — skipping review."
    fi
elif [ "$SKIP_REVIEW" = true ]; then
    info "Step 2/3 — Skipping manual review (--skip-review)"
fi

# --------------------------------------------------------------------------
# Step 3: Import to Database + Retrain
# --------------------------------------------------------------------------
info "Step 3/3 — Importing verified candidates into database..."
echo ""
cd "$BACKEND_DIR"
$PYTHON -m jobtracker.scripts.import_to_db
echo ""

# --------------------------------------------------------------------------
# Done
# --------------------------------------------------------------------------
header "=========================================="
header "  Pipeline Complete!"
header "=========================================="
echo ""
echo "  Your classifier should now have more training data."
echo "  If SetFit was retrained, new classifications will use the improved model."
echo ""
echo "  Verification commands:"
echo "    # Check training data in DB:"
echo "    sqlite3 ~/Library/Application\\ Support/JobTracker/jobtracker.db \\"
echo "      \"SELECT label, COUNT(*) FROM training_data GROUP BY label ORDER BY COUNT(*) DESC;\""
echo ""
echo "    # Check classifier status (if backend running):"
echo "    curl -s http://127.0.0.1:8000/classify/status | python3 -m json.tool"
echo ""
echo "    # Manually trigger retrain (if backend running):"
echo "    curl -s -X POST http://127.0.0.1:8000/classify/retrain"
echo ""
