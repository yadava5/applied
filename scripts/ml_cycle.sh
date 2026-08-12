#!/usr/bin/env bash
# Standard ML cycle runner: optional import + optional retrain + evaluations + reports

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if [ -f "$BACKEND_DIR/.venv311/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv311/bin/python"
elif [ -f "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

IMPORT_MOCK=false
TRIGGER_RETRAIN=false

for arg in "$@"; do
  case "$arg" in
    --import-mock) IMPORT_MOCK=true ;;
    --retrain) TRIGGER_RETRAIN=true ;;
    --help|-h)
      cat <<USAGE
Usage: scripts/ml_cycle.sh [--import-mock] [--retrain]

Options:
  --import-mock   Import mock JSONL as source=mock_seed
  --retrain       Trigger SetFit retraining before evaluation
USAGE
      exit 0
      ;;
  esac
done

echo "[ML] Python: $PYTHON"
cd "$BACKEND_DIR"

if [ "$IMPORT_MOCK" = true ]; then
  echo "[ML] Importing mock seed dataset..."
  "$PYTHON" -m jobtracker.scripts.import_jsonl_training_data \
    --input data/external/mock_training_data.jsonl \
    --source mock_seed
fi

if [ "$TRIGGER_RETRAIN" = true ]; then
  echo "[ML] Triggering SetFit retrain..."
  "$PYTHON" - <<'PY'
import asyncio

from jobtracker.classifier import get_classifier
from jobtracker.classifier.setfit_model import resolve_training_user_id
from jobtracker.database import init_db


async def main() -> None:
    await init_db()
    classifier = get_classifier()
    # SCOPE: training reads training_data for ONE user. Applied reads mail
    # under Gmail's restricted gmail.readonly scope, whose user-data policy
    # permits training only a model personalized to a single end user, with
    # no co-mingling across users. This script has no authenticated identity,
    # so it resolves to the LOCAL_USER_ID sentinel every desktop row carries.
    # That is deliberate: run against a production DATABASE_URL it matches no
    # rows and trains on nothing, instead of pooling every tenant's mail.
    # See setfit_model.CrossUserTrainingError.
    await classifier.retrain_setfit(user_id=resolve_training_user_id())


asyncio.run(main())
PY
fi

echo "[ML] Evaluating rules v1..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset data/evaluation/classifier_eval_v1.jsonl \
  --baseline data/evaluation/baseline_rules_v1.json \
  --tolerance 0.001

echo "[ML] Evaluating hybrid v1..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v1.jsonl \
  --baseline data/evaluation/baseline_hybrid_v1.json \
  --hybrid-profile deterministic \
  --tolerance 0.001

echo "[ML] Evaluating rules v2..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset data/evaluation/classifier_eval_v2.jsonl \
  --baseline data/evaluation/baseline_rules_v2.json \
  --tolerance 0.001

echo "[ML] Evaluating hybrid v2..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v2.jsonl \
  --baseline data/evaluation/baseline_hybrid_v2.json \
  --hybrid-profile deterministic \
  --tolerance 0.001

echo "[ML] Evaluating rules v3..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode rules \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_rules_v3.json \
  --tolerance 0.001

echo "[ML] Evaluating hybrid v3..."
"$PYTHON" -m jobtracker.scripts.evaluate_classifier \
  --mode hybrid \
  --dataset data/evaluation/classifier_eval_v3.jsonl \
  --baseline data/evaluation/baseline_hybrid_v3.json \
  --hybrid-profile deterministic \
  --tolerance 0.001

echo "[ML] Rebuilding benchmark history..."
"$PYTHON" -m jobtracker.scripts.build_benchmark_history

echo "[ML] Rebuilding label-balance report..."
"$PYTHON" -m jobtracker.scripts.report_label_balance \
  --target-per-label 25 \
  --real-sources user_correction \
  --output data/evaluation/label_balance_report.md

echo "[ML] Rebuilding monitoring report..."
"$PYTHON" -m jobtracker.scripts.generate_ml_monitoring_report \
  --days 7 \
  --output data/evaluation/ml_monitoring_report.md

echo "[ML] Cycle complete."
