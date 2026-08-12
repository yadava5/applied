#!/usr/bin/env bash
# Measure the FULL three-layer cascade against rules-only on the committed v3
# set, and check it against the committed cascade baseline.
#
# Why this is a script and not two more steps in backend-ci.yml
# -------------------------------------------------------------
# CI's two classifier gates run `--mode rules` and `--mode hybrid
# --hybrid-profile deterministic`, and `deterministic` switches SetFit off and
# blanks the embedding store. That is correct for a fast, machine-stable gate --
# and it means neither gate has ever measured a learned layer. Both committed
# baselines read the same 0.9791 for exactly that reason.
#
# The cascade needs a SetFit checkpoint. Checkpoints are trained on disk, live
# under the app's data directory, are not in the repository (see .gitignore),
# and rotate after three. So this runs where the checkpoint is -- a developer
# machine, or any runner that has one -- and fails with the searched path when
# it is not there. It never degrades to a rules-only measurement and calls it a
# cascade; the harness's own layer guard forbids that.
#
# Reproducibility: the run is pointed at a scratch data directory holding
# nothing but a link to the checkpoint. The embedding store is therefore empty,
# which is deliberate twice over -- the real store is per-user mail, so a
# baseline recorded against it would be neither shareable nor reproducible, and
# an empty store makes the number a function of the checkpoint alone.
#
# Usage:
#   scripts/cascade_gate.sh [--checkpoint PATH] [--update-baseline]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

# $PYTHON wins when set, so a runner (or a git worktree without its own venv)
# can name the interpreter that has the ML dependencies installed.
if [ -n "${PYTHON:-}" ]; then
  :
elif [ -f "$BACKEND_DIR/.venv311/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv311/bin/python"
elif [ -f "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

CHECKPOINT="${JOBTRACKER_SETFIT_CHECKPOINT:-}"
UPDATE_BASELINE=false

while [ $# -gt 0 ]; do
  case "$1" in
    --checkpoint)
      CHECKPOINT="$2"
      shift 2
      ;;
    --update-baseline)
      UPDATE_BASELINE=true
      shift
      ;;
    --help|-h)
      cat <<USAGE
Usage: scripts/cascade_gate.sh [--checkpoint PATH] [--update-baseline]

Options:
  --checkpoint PATH   SetFit checkpoint directory to evaluate. Defaults to the
                      newest one under the app's models directory, or
                      \$JOBTRACKER_SETFIT_CHECKPOINT.
  --update-baseline   Rewrite backend/data/evaluation/baseline_cascade_v3.json
                      from this run. Promoting a new checkpoint is a decision;
                      see docs/ML_PROMOTION_POLICY.md before using it.
USAGE
      exit 0
      ;;
    *)
      echo "[cascade-gate] unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cd "$BACKEND_DIR"

# Where the app keeps checkpoints, asked of the app's own configuration rather
# than hardcoded, so this does not drift from get_models_dir().
MODELS_DIR="$("$PYTHON" -c 'from jobtracker.classifier.setfit_model import get_models_dir; print(get_models_dir())')"

if [ -z "$CHECKPOINT" ]; then
  # Newest by name, which is how get_latest_model_path() picks: the directory
  # names are timestamps.
  CHECKPOINT="$(/bin/ls -d "$MODELS_DIR"/*/ 2>/dev/null | /usr/bin/sort -r | /usr/bin/head -1 || true)"
  CHECKPOINT="${CHECKPOINT%/}"
fi

if [ -z "$CHECKPOINT" ] || [ ! -d "$CHECKPOINT" ]; then
  cat >&2 <<MISSING
[cascade-gate] FAIL: no SetFit checkpoint found.

Searched: $MODELS_DIR

The cascade cannot be measured without one, and measuring rules-only and
calling it the cascade is the failure this gate exists to prevent. On a
GitHub-hosted runner this is the expected outcome and is not a bug: no
checkpoint ships in the repository. Run this on a machine that has trained one,
or pass --checkpoint PATH.
MISSING
  exit 1
fi

SCRATCH_DIR="$(/usr/bin/mktemp -d)"
trap '/bin/rm -r "$SCRATCH_DIR"' EXIT
/bin/mkdir -p "$SCRATCH_DIR/models/setfit"
/bin/ln -s "$CHECKPOINT" "$SCRATCH_DIR/models/setfit/$(/usr/bin/basename "$CHECKPOINT")"

echo "[cascade-gate] Python: $PYTHON"
echo "[cascade-gate] checkpoint: $CHECKPOINT"
echo "[cascade-gate] scratch data dir: $SCRATCH_DIR"

EXTRA_ARGS=()
if [ "$UPDATE_BASELINE" = true ]; then
  EXTRA_ARGS+=(--update-baseline)
else
  EXTRA_ARGS+=(--tolerance 0.001)
fi

JOBTRACKER_DATABASE_DIR="$SCRATCH_DIR" \
JOBTRACKER_ENVIRONMENT=test \
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
TOKENIZERS_PARALLELISM=false \
  "$PYTHON" -m jobtracker.scripts.evaluate_classifier \
    --mode hybrid \
    --hybrid-profile full \
    --compare-rules \
    --dataset data/evaluation/classifier_eval_v3.jsonl \
    --baseline data/evaluation/baseline_cascade_v3.json \
    "${EXTRA_ARGS[@]}"
