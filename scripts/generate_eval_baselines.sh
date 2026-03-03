#!/usr/bin/env bash
# Generate and update evaluation baselines for a versioned dataset.
#
# Examples:
#   scripts/generate_eval_baselines.sh --version 3
#   scripts/generate_eval_baselines.sh --version 3 --skip-hybrid
#   scripts/generate_eval_baselines.sh --version 2 --dataset data/evaluation/classifier_eval_v2.jsonl
#   scripts/generate_eval_baselines.sh --version 3 --hybrid-profile full

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if [[ -x "$BACKEND_DIR/.venv311/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv311/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

VERSION="3"
DATASET=""
SKIP_HYBRID=false
SKIP_HISTORY=false
HYBRID_PROFILE="deterministic"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --dataset)
      DATASET="${2:-}"
      shift 2
      ;;
    --skip-hybrid)
      SKIP_HYBRID=true
      shift
      ;;
    --skip-history)
      SKIP_HISTORY=true
      shift
      ;;
    --hybrid-profile)
      HYBRID_PROFILE="${2:-}"
      shift 2
      ;;
    --help|-h)
      cat <<'USAGE'
Usage: scripts/generate_eval_baselines.sh [options]

Options:
  --version <n>        Dataset/baseline version number (default: 3)
  --dataset <path>     Dataset path relative to backend/ (default: data/evaluation/classifier_eval_v<version>.jsonl)
  --skip-hybrid        Skip hybrid baseline generation
  --skip-history       Skip benchmark history rebuild
  --hybrid-profile     Hybrid profile for evaluator (default: deterministic)
  -h, --help           Show this help
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$DATASET" ]]; then
  DATASET="data/evaluation/classifier_eval_v${VERSION}.jsonl"
fi

if [[ "$HYBRID_PROFILE" != "full" && "$HYBRID_PROFILE" != "deterministic" ]]; then
  echo "Invalid --hybrid-profile: $HYBRID_PROFILE (expected: full|deterministic)" >&2
  exit 1
fi

RULES_BASELINE="data/evaluation/baseline_rules_v${VERSION}.json"
HYBRID_BASELINE="data/evaluation/baseline_hybrid_v${VERSION}.json"

cd "$BACKEND_DIR"

echo "[baselines] dataset=$DATASET version=v$VERSION"
echo "[baselines] updating rules baseline -> $RULES_BASELINE"
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset "$DATASET" \
  --baseline "$RULES_BASELINE" \
  --update-baseline

if [[ "$SKIP_HYBRID" != true ]]; then
  echo "[baselines] updating hybrid baseline -> $HYBRID_BASELINE (profile=$HYBRID_PROFILE)"
  "$PYTHON" -m jobtracker.scripts.evaluate_classifier \
    --mode hybrid \
    --dataset "$DATASET" \
    --baseline "$HYBRID_BASELINE" \
    --hybrid-profile "$HYBRID_PROFILE" \
    --update-baseline
fi

if [[ "$SKIP_HISTORY" != true ]]; then
  echo "[baselines] rebuilding benchmark history artifacts"
  "$PYTHON" -m jobtracker.scripts.build_benchmark_history
fi

echo "[baselines] done"
