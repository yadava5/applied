#!/usr/bin/env bash
# ==============================================================================
# Download External Training Datasets
# ==============================================================================
# One-time script to fetch free, commercially-safe datasets for training
# the JobTracker email classifier.
#
# Datasets:
#   1. Berkeley Enron subset (public domain FERC release + academic annotations)
#   2. SpamAssassin Public Corpus (Apache 2.0)
#   3. Charlie9 Enron Intent Dataset (MIT)
#
# Usage:
#   bash scripts/download_datasets.sh
#
# Files land in backend/data/external/ (gitignored).
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/backend/data/external"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { printf "${GREEN}[INFO]${NC}  %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

# --------------------------------------------------------------------------
# Check dependencies
# --------------------------------------------------------------------------
for cmd in curl tar; do
    if ! command -v "$cmd" &>/dev/null; then
        error "Required command '$cmd' not found. Please install it."
        exit 1
    fi
done

mkdir -p "$DATA_DIR"

# ==========================================================================
# 1. Berkeley Enron (labeled subset ~25 MB compressed)
# ==========================================================================
ENRON_DIR="$DATA_DIR/enron_berkeley"
ENRON_URL="https://bebop.berkeley.edu/enron/enron_with_categories.tar.gz"
ENRON_CATS_URL="https://bebop.berkeley.edu/enron/enron_categories.txt"
ENRON_ARCHIVE="$DATA_DIR/enron_with_categories.tar.gz"

if [ -d "$ENRON_DIR" ] && [ "$(ls -A "$ENRON_DIR" 2>/dev/null)" ]; then
    info "Berkeley Enron already downloaded — skipping"
else
    info "Downloading Berkeley Enron labeled subset..."
    mkdir -p "$ENRON_DIR"

    curl -L --progress-bar -o "$ENRON_ARCHIVE" "$ENRON_URL"
    info "Extracting Berkeley Enron..."
    tar -xzf "$ENRON_ARCHIVE" -C "$ENRON_DIR" --strip-components=0
    rm -f "$ENRON_ARCHIVE"

    # Also grab the category definitions file
    curl -L -s -o "$ENRON_DIR/enron_categories.txt" "$ENRON_CATS_URL" 2>/dev/null || true

    info "Berkeley Enron ready  → $ENRON_DIR"
fi

# ==========================================================================
# 2. SpamAssassin Public Corpus (Apache 2.0, ~5 MB)
# ==========================================================================
SA_DIR="$DATA_DIR/spamassassin"
SA_SPAM_URL="https://spamassassin.apache.org/old/publiccorpus/20030228_spam_2.tar.bz2"
SA_HAM_URL="https://spamassassin.apache.org/old/publiccorpus/20030228_easy_ham_2.tar.bz2"

if [ -d "$SA_DIR/spam" ] && [ -d "$SA_DIR/ham" ]; then
    info "SpamAssassin corpus already downloaded — skipping"
else
    info "Downloading SpamAssassin spam corpus..."
    mkdir -p "$SA_DIR/spam" "$SA_DIR/ham"

    curl -L --progress-bar -o "$DATA_DIR/spam_2.tar.bz2" "$SA_SPAM_URL"
    info "Extracting spam..."
    tar -xjf "$DATA_DIR/spam_2.tar.bz2" -C "$SA_DIR/spam" --strip-components=1
    rm -f "$DATA_DIR/spam_2.tar.bz2"

    info "Downloading SpamAssassin ham corpus..."
    curl -L --progress-bar -o "$DATA_DIR/easy_ham_2.tar.bz2" "$SA_HAM_URL"
    info "Extracting ham..."
    tar -xjf "$DATA_DIR/easy_ham_2.tar.bz2" -C "$SA_DIR/ham" --strip-components=1
    rm -f "$DATA_DIR/easy_ham_2.tar.bz2"

    info "SpamAssassin ready    → $SA_DIR"
fi

# ==========================================================================
# 3. Charlie9 Enron Intent Dataset (MIT)
# ==========================================================================
C9_DIR="$DATA_DIR/charlie9_intent"
C9_POS_URL="https://raw.githubusercontent.com/Charlie9/enron_intent_dataset_verified/master/intent_pos"
C9_NEG_URL="https://raw.githubusercontent.com/Charlie9/enron_intent_dataset_verified/master/intent_neg"

if [ -f "$C9_DIR/intent_pos" ] && [ -f "$C9_DIR/intent_neg" ]; then
    info "Charlie9 Intent dataset already downloaded — skipping"
else
    info "Downloading Charlie9 Enron Intent dataset..."
    mkdir -p "$C9_DIR"
    curl -L --progress-bar -o "$C9_DIR/intent_pos" "$C9_POS_URL"
    curl -L --progress-bar -o "$C9_DIR/intent_neg" "$C9_NEG_URL"
    info "Charlie9 Intent ready → $C9_DIR"
fi

# ==========================================================================
# Summary
# ==========================================================================
echo ""
echo "=========================================="
echo "  Download Summary"
echo "=========================================="

count_files() {
    local dir="$1"
    if [ -d "$dir" ]; then
        find "$dir" -type f | wc -l | tr -d ' '
    else
        echo "0"
    fi
}

printf "  %-25s %6s files\n" "Berkeley Enron:" "$(count_files "$ENRON_DIR")"
printf "  %-25s %6s files\n" "SpamAssassin spam:" "$(count_files "$SA_DIR/spam")"
printf "  %-25s %6s files\n" "SpamAssassin ham:" "$(count_files "$SA_DIR/ham")"
printf "  %-25s %6s files\n" "Charlie9 Intent:" "$(count_files "$C9_DIR")"

echo ""
echo "All datasets saved to: $DATA_DIR"
echo ""
echo "Next step:"
echo "  bash scripts/train_pipeline.sh"
echo ""
